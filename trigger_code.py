from pyspcm import *
from spcm_tools import *
import sys
import numpy as np

#
# **************************************************************************
# main
# **************************************************************************
#

# open card
# uncomment the second line and replace the IP address to use remote
# cards like in a generatorNETBOX
# page 50
hCard = spcm_hOpen(create_string_buffer(b'/dev/spcm0'))
# hCard = spcm_hOpen(create_string_buffer(b'TCPIP::192.168.1.10::inst0::INSTR'))
if not hCard:
    sys.stdout.write("no card found...\n")
    exit(1)

# get card type name from driver
qwValueBufferLen = 20
pValueBuffer = pvAllocMemPageAligned(qwValueBufferLen)
spcm_dwGetParam_ptr(hCard, SPC_PCITYP, pValueBuffer, qwValueBufferLen)
sCardName = pValueBuffer.value.decode('UTF-8')

# read type, function and sn and check for D/A card
# page 52
lCardType = int32(0)
spcm_dwGetParam_i32(hCard, SPC_PCITYP, byref(lCardType))
lSerialNumber = int32(0)
spcm_dwGetParam_i32(hCard, SPC_PCISERIALNO, byref(lSerialNumber))
lFncType = int32(0)
spcm_dwGetParam_i32(hCard, SPC_FNCTYPE, byref(lFncType))

if lFncType.value == SPCM_TYPE_AO or lFncType.value == SPCM_TYPE_DO or lFncType.value == SPCM_TYPE_DIO:
    sys.stdout.write("Found: {0} sn {1:05d}\n".format(
        sCardName, lSerialNumber.value))
else:
    sys.stdout.write(
        "This is an example for analog output, digital output and digital I/O cards.\nCard: {0} sn {1:05d} not supported by example\n".format(sCardName, lSerialNumber.value))
    spcm_vClose(hCard)
    exit(1)


# set samplerate to 1 MHz (M2i) or 50 MHz, no clock output
# page 97
if ((lCardType.value & TYP_SERIESMASK) == TYP_M4IEXPSERIES) or ((lCardType.value & TYP_SERIESMASK) == TYP_M4XEXPSERIES):
    spcm_dwSetParam_i64(hCard, SPC_SAMPLERATE, MEGA(1250))
else:
    #
    spcm_dwSetParam_i64(hCard, SPC_SAMPLERATE, MEGA(1))
# last number is the clock output of the card 0 disabbles the output and 1 enables it
spcm_dwSetParam_i32(hCard, SPC_CLOCKOUT,   0)

samplerate = 1_250_000_000
sigma_s = 1 / 10_000_250_000_000
n_sigma = 5
amplitude_mV = 1000
n = int(round(2 * n_sigma * sigma_s * samplerate))
n = ((n + 31) // 32) * 32
n = max(n, 32)

# set up the mode
# standard single replay modes for awg
if lFncType.value == SPCM_TYPE_AO:
    qwChEnable = uint64(1)
else:
    qwChEnable = 0xFFFFFFFF  # enable 32 channels
llMemSamples = int64(n)
llLoops = int64(0)  # loop continuously (use 0 instead)
# changed SPC_REP_STD_CONTINUOUS to SPC_REP_STD_SINGLE because its just supposed to be 1 gaussian being replayed i believe
spcm_dwSetParam_i32(hCard, SPC_CARDMODE,    SPC_REP_STD_SINGLE)
spcm_dwSetParam_i64(hCard, SPC_CHENABLE,    qwChEnable)
spcm_dwSetParam_i64(hCard, SPC_MEMSIZE,     llMemSamples)
spcm_dwSetParam_i64(hCard, SPC_LOOPS,       llLoops)

lSetChannels = int32(0)
spcm_dwGetParam_i32(hCard, SPC_CHCOUNT,     byref(lSetChannels))
lBytesPerSample = int32(0)
spcm_dwGetParam_i32(hCard, SPC_MIINST_BYTESPERSAMPLE,  byref(lBytesPerSample))

# setup the trigger mode
# page 102
# (SW trigger, no output)
# sets up default software trigger
# spcm_dwSetParam_i32(hCard, SPC_TRIG_EXT0_LEVEL0, 1800)
# spcm_dwSetParam_i32(hCard, SPC_TRIG_EXT0_LEVEL1, 2500)
# spcm_dwSetParam_i32(hCard, SPC_TRIG_EXT0_MODE, SPC_TM_WINENTER)
# spcm_dwSetParam_i32(hCard, SPC_TRIG_EXT1_MODE, SPC_TM_POS)

spcm_dwSetParam_i32(hCard, SPC_TRIG_ORMASK, SPC_TMASK_EXT0)
spcm_dwSetParam_i32(hCard, SPC_TRIG_ANDMASK, SPC_TMASK_NONE)

spcm_dwSetParam_i32(hCard, SPC_TRIG_EXT0_LEVEL0, 1800)
spcm_dwSetParam_i32(hCard, SPC_TRIG_EXT0_LEVEL1, 2500)
spcm_dwSetParam_i32(hCard, SPC_TRIG_EXT0_MODE, SPC_TM_WINENTER)
# spcm_dwSetParam_i32 (hDrv, SPC_TRIG_ORMASK, SPC_TMASK_NONE);
# spcm_dwSetParam_i32 (hDrv, SPC_TRIG_CH_ORMASK0, SPC_TMASK_CH0);
# spcm_dwSetParam_i32 (hDrv, SPC_TRIG_CH0_LEVEL0, 0);
# spcm_dwSetParam_i32 (hDrv, SPC_TRIG_CH0_MODE, SPC_TM_POS);
# set up the analog output channels
# page 74
# if lFncType.value == SPCM_TYPE_AO:
#     lChannel = int32(0)
#     # spcm_dwSetParam_i32 (hDrv, SPC_CHENABLE, CHANNEL0 | CHANNEL1);
#     spcm_dwSetParam_i32(hCard, SPC_AMP0 + lChannel.value *
#                         (SPC_AMP1 - SPC_AMP0), int32(1000))
#     # spcm_dwSetParam_i64 (hDrv, SPC_CHENABLE, CHANNEL0 | CHANNEL1 | CHANNEL2 | CHANNEL3);
#     spcm_dwSetParam_i64(hCard, SPC_ENABLEOUT0 + lChannel.value *
#                         (SPC_ENABLEOUT1 - SPC_ENABLEOUT0), int32(1), int)

# setup software buffer
if lFncType.value == SPCM_TYPE_AO:
    qwBufferSize = uint64(llMemSamples.value *
                          lBytesPerSample.value * lSetChannels.value)
else:
    # eight channels per byte for DO and DIO cards
    qwBufferSize = uint64(llMemSamples.value * lSetChannels.value // 8)
# we try to use continuous memory if available and big enough
# page 173
pvBuffer = c_void_p()
qwContBufLen = uint64(0)
spcm_dwGetContBuf_i64(hCard, SPCM_BUF_DATA, byref(
    pvBuffer), byref(qwContBufLen))
sys.stdout.write("ContBuf length: {0:d}\n".format(qwContBufLen.value))
if qwContBufLen.value >= qwBufferSize.value:
    sys.stdout.write("Using continuous buffer\n")
else:
    pvBuffer = pvAllocMemPageAligned(qwBufferSize.value)
    sys.stdout.write("Using buffer allocated by user program\n")

# calculate the data
if lFncType.value == SPCM_TYPE_AO:
    # simple ramp for analog output cards
    # we replace the simple ramp with the gaussian here
    t = np.arange(n)
    t0 = n / 2
    sigma_samples = sigma_s * samplerate
    envelope = np.exp(-((t - t0) ** 2) / (2 * sigma_samples ** 2))
    gaussian_data = (envelope * 32767).astype(np.int16)

    pnBuffer = cast(pvBuffer, ptr16)
    for i in range(0, llMemSamples.value, 1):
        pnBuffer[i] = int(gaussian_data[i])
else:
    # a tree for digital output cards
    pdwBuffer = cast(pvBuffer, uptr32)
    for i in range(0, llMemSamples.value, 1):
        pdwBuffer[i] = 0x1 << (i % 32)

# we define the buffer for transfer and start the DMA transfer
sys.stdout.write(
    "Starting the DMA transfer and waiting until data is in board memory\n")
spcm_dwDefTransfer_i64(hCard, SPCM_BUF_DATA, SPCM_DIR_PCTOCARD, int32(
    0), pvBuffer, uint64(0), qwBufferSize)
spcm_dwSetParam_i32(hCard, SPC_M2CMD, M2CMD_DATA_STARTDMA | M2CMD_DATA_WAITDMA)
sys.stdout.write("... data has been transferred to board memory\n")

# We'll start the card and wait specifically for the trigger event first
sys.stdout.write("\nStarting the card and waiting for trigger\n")
spcm_dwSetParam_i32(hCard, SPC_M2CMD, M2CMD_CARD_START | M2CMD_CARD_ENABLETRIGGER)

dwErr = spcm_dwSetParam_i32(hCard, SPC_M2CMD, M2CMD_CARD_WAITTRIGGER)

if dwErr == ERR_OK:
    sys.stdout.write(">>> Trigger detected! <<<\n")
elif dwErr == ERR_TIMEOUT:
    sys.stdout.write("Timed out waiting for trigger.\n")
else:
    sys.stdout.write("Error while waiting for trigger: {0}\n".format(dwErr))

# Now wait until the card has finished or until a timeout occurs
spcm_dwSetParam_i32(hCard, SPC_TIMEOUT, 10000)
sys.stdout.write(
    "Waiting for ready interrupt\n(continuous and single restart will have timeout)\n")
dwError = spcm_dwSetParam_i32(hCard, SPC_M2CMD, M2CMD_CARD_WAITREADY)
if dwError == ERR_TIMEOUT:
    spcm_dwSetParam_i32(hCard, SPC_M2CMD, M2CMD_CARD_STOP)

# close the card
spcm_vClose(hCard)