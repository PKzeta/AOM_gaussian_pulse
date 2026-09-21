import ctypes
from ctypes import byref

# ==============================
# Load NI-HSDIO driver
# ==============================
hsdio = ctypes.cdll.LoadLibrary(
    r"C:\Program Files\IVI Foundation\IVI\Bin\niHSDIO_64.dll"
)

# NI types
ViSession = ctypes.c_uint32
ViStatus = ctypes.c_int32
ViBoolean = ctypes.c_uint16
ViUInt32 = ctypes.c_uint32

# ==============================
# Function definitions
# ==============================

# Init Generation Session
hsdio.niHSDIO_InitGenerationSession.argtypes = [
    ctypes.c_char_p,                 # resource name
    ViBoolean,                       # idQuery
    ViBoolean,                       # reset
    ctypes.c_char_p,                 # options
    ctypes.POINTER(ViSession)
]
hsdio.niHSDIO_InitGenerationSession.restype = ViStatus

# Assign Dynamic Channels -- this is the real replacement for the
# nonexistent "ConfigureNamedChannelU32" call. It just takes a
# channel-list string, e.g. "0-31".
hsdio.niHSDIO_AssignDynamicChannels.argtypes = [
    ViSession,
    ctypes.c_char_p                  # channelList (e.g., "0-31")
]
hsdio.niHSDIO_AssignDynamicChannels.restype = ViStatus

# Configure Sample Clock
# NOTE: clockSource is a *string* (ViConstString), not an int32 --
# e.g. NIHSDIO_VAL_ON_BOARD_CLOCK_STR = b"OnboardClock"
hsdio.niHSDIO_ConfigureSampleClock.argtypes = [
    ViSession,
    ctypes.c_char_p,                 # clockSource (string constant)
    ctypes.c_double                  # clockRate (Hz)
]
hsdio.niHSDIO_ConfigureSampleClock.restype = ViStatus

# Write Named Waveform (U32 data)
hsdio.niHSDIO_WriteNamedWaveformU32.argtypes = [
    ViSession,
    ctypes.c_char_p,                 # waveformName
    ctypes.c_int32,                  # numSamples
    ctypes.POINTER(ViUInt32)         # data array
]
hsdio.niHSDIO_WriteNamedWaveformU32.restype = ViStatus   # <-- fixed typo

# Write Script
hsdio.niHSDIO_WriteScript.argtypes = [
    ViSession,
    ctypes.c_char_p                  # script string
]
hsdio.niHSDIO_WriteScript.restype = ViStatus

# Export Signal
hsdio.niHSDIO_ExportSignal.argtypes = [
    ViSession,                       # vi
    ctypes.c_int32,                  # signal
    ctypes.c_char_p,                 # signalIdentifier
    ctypes.c_char_p                  # outputTerminal
]
hsdio.niHSDIO_ExportSignal.restype = ViStatus

# Initiate
hsdio.niHSDIO_Initiate.argtypes = [ViSession]
hsdio.niHSDIO_Initiate.restype = ViStatus

# Close
hsdio.niHSDIO_close.argtypes = [ViSession]
hsdio.niHSDIO_close.restype = ViStatus


# ==============================
# Driver Constants
# ==============================
NIHSDIO_VAL_ON_BOARD_CLOCK_STR = b"OnboardClock"   # verify exact spelling against niHSDIO.h
NIHSDIO_VAL_SCRIPT_TRIGGER = 58
NIHSDIO_VAL_SCRIPT0 = b"scriptTrigger0"

SAMPLE_CLOCK_RATE = 50_000_000.0     # 50 MHz -> 20 ns/sample
PERIOD_US = 10                   # desired trigger period
WAVEFORM_SIZE = int(round(PERIOD_US * 1e-6 * SAMPLE_CLOCK_RATE))  # 500 samples

# ==============================
# 1. Open PXI-6541
# ==============================
session = ViSession(0)
status = hsdio.niHSDIO_InitGenerationSession(b"Dev1", 0, 1, b"", byref(session))
print("Init status:", status)
if status != 0:
    raise RuntimeError("Could not open PXI-6541")

# ==============================
# 2. Assign channels + configure clock
# ==============================
status = hsdio.niHSDIO_AssignDynamicChannels(session, b"0-31")
print("Assign channels status:", status)
if status != 0:
    raise RuntimeError("Could not assign dynamic channels")

status = hsdio.niHSDIO_ConfigureSampleClock(
    session, NIHSDIO_VAL_ON_BOARD_CLOCK_STR, 50000000.0
)
print("Clock configuration status:", status)

# ==============================
# 3. Create & Load Waveform Data
# ==============================
pattern = []

for i in range(WAVEFORM_SIZE):
    if i < 1:
        pattern.append(0x00000001)   # DIO0 HIGH
    else:
        pattern.append(0x00000000)   # DIO0 LOW

dummy_pattern = (ViUInt32 * WAVEFORM_SIZE)(*pattern)
status = hsdio.niHSDIO_WriteNamedWaveformU32(session, b"wfm1", WAVEFORM_SIZE, dummy_pattern)
print("Waveform load status:", status)

generation_script = (
    b"script myScript\n"
    b"  generate wfm1 marker0(0)\n"
    b"end script"
)
status = hsdio.niHSDIO_WriteScript(session, generation_script)
print("Script compilation status:", status)

# ==============================
# 4. Route Trigger to Front Panel
# ==============================
status = hsdio.niHSDIO_ExportSignal(
    session, NIHSDIO_VAL_SCRIPT_TRIGGER, NIHSDIO_VAL_SCRIPT0, b"PFI0"
)
print("Export status:", status)
if status != 0:
    raise RuntimeError("Could not export trigger to PFI0")

# ==============================
# 5. Launch Hardware Generation
# ==============================
status = hsdio.niHSDIO_Initiate(session)
print("Initiate status:", status)
if status != 0:
    raise RuntimeError(f"Could not initiate generation. Code: {status}")

print("\nSuccess! PXI-6541 generation initiated. Checking PFI0 for the trigger pulse...")

# ==============================
# Clean up
# ==============================
input("\nPress ENTER to stop generation and close session...")
hsdio.niHSDIO_close(session)
print("Closed")
