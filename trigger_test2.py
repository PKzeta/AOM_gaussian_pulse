import ctypes
from ctypes import byref

# ==============================
# Load NI-HSDIO driver
# ==============================
hsdio = ctypes.cdll.LoadLibrary(
    r"C:\Program Files\IVI Foundation\IVI\Bin\niHSDIO_64.dll"
)

ViSession = ctypes.c_uint32
ViStatus = ctypes.c_int32
ViBoolean = ctypes.c_uint16
ViUInt32 = ctypes.c_uint32

# ==============================
# Function definitions
# ==============================
hsdio.niHSDIO_InitGenerationSession.argtypes = [
    ctypes.c_char_p, ViBoolean, ViBoolean, ctypes.c_char_p, ctypes.POINTER(ViSession)
]
hsdio.niHSDIO_InitGenerationSession.restype = ViStatus

hsdio.niHSDIO_AssignDynamicChannels.argtypes = [ViSession, ctypes.c_char_p]
hsdio.niHSDIO_AssignDynamicChannels.restype = ViStatus

hsdio.niHSDIO_ConfigureSampleClock.argtypes = [ViSession, ctypes.c_char_p, ctypes.c_double]
hsdio.niHSDIO_ConfigureSampleClock.restype = ViStatus

hsdio.niHSDIO_WriteNamedWaveformU32.argtypes = [
    ViSession, ctypes.c_char_p, ctypes.c_int32, ctypes.POINTER(ViUInt32)
]
hsdio.niHSDIO_WriteNamedWaveformU32.restype = ViStatus

hsdio.niHSDIO_WriteScript.argtypes = [ViSession, ctypes.c_char_p]
hsdio.niHSDIO_WriteScript.restype = ViStatus

hsdio.niHSDIO_ExportSignal.argtypes = [ViSession, ctypes.c_int32, ctypes.c_char_p, ctypes.c_char_p]
hsdio.niHSDIO_ExportSignal.restype = ViStatus

hsdio.niHSDIO_Initiate.argtypes = [ViSession]
hsdio.niHSDIO_Initiate.restype = ViStatus

# Needed to cleanly stop a "repeat forever" generation before closing
hsdio.niHSDIO_Abort.argtypes = [ViSession]
hsdio.niHSDIO_Abort.restype = ViStatus

hsdio.niHSDIO_close.argtypes = [ViSession]
hsdio.niHSDIO_close.restype = ViStatus

# ==============================
# Driver Constants
# ==============================
NIHSDIO_VAL_ON_BOARD_CLOCK_STR = b"OnboardClock"   # verify against your niHSDIO.h
NIHSDIO_VAL_SCRIPT_TRIGGER = 58
NIHSDIO_VAL_SCRIPT0 = b"scriptTrigger0"

SAMPLE_CLOCK_RATE = 50_000_000.0     # 50 MHz -> 20 ns/sample
PERIOD_US = 20                  # desired trigger period
WAVEFORM_SIZE = int(round(PERIOD_US * 1e-6 * SAMPLE_CLOCK_RATE))  # 500 samples
WAVEFORM_SIZE = ((WAVEFORM_SIZE + 31) // 32) * 32
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

status = hsdio.niHSDIO_ConfigureSampleClock(session, NIHSDIO_VAL_ON_BOARD_CLOCK_STR, SAMPLE_CLOCK_RATE)
print("Clock configuration status:", status)

# ==============================
# 3. Waveform: WAVEFORM_SIZE samples = exactly one 10us period.
#    Content doesn't matter for the trigger itself; kept at zero.
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

# Loop forever, firing scriptTrigger0 at the start of every 10us waveform
generation_script = (
    b"script myScript\n"
    b"  repeat forever\n"
    b"    generate wfm1 marker0(0)\n"
    b"  end repeat\n"
    b"end script"
)
status = hsdio.niHSDIO_WriteScript(session, generation_script)
print("Script compilation status:", status)

# ==============================
# 4. Route Trigger to Front Panel
# ==============================
status = hsdio.niHSDIO_ExportSignal(session, NIHSDIO_VAL_SCRIPT_TRIGGER, NIHSDIO_VAL_SCRIPT0, b"PFI0")
print("Export status:", status)
if status != 0:
    raise RuntimeError("Could not export trigger to PFI0")

# ==============================
# 5. Launch Hardware Generation
# ==============================

# Configure Generation Mode (Waveform vs Script)
hsdio.niHSDIO_ConfigureGenerationMode.argtypes = [ViSession, ctypes.c_int32]
hsdio.niHSDIO_ConfigureGenerationMode.restype = ViStatus
NIHSDIO_VAL_WAVEFORM = 14
NIHSDIO_VAL_SCRIPT = 15
status = hsdio.niHSDIO_WriteScript(session, generation_script)
print("Script compilation status:", status)
# Without this, Initiate() ignores the script and just plays wfm1 once
status = hsdio.niHSDIO_ConfigureGenerationMode(session, NIHSDIO_VAL_SCRIPT)
print("Generation mode status:", status)
if status != 0:
    raise RuntimeError("Could not set scripted generation mode")



status = hsdio.niHSDIO_Initiate(session)
print("Initiate status:", status)
if status != 0:
    raise RuntimeError(f"Could not initiate generation. Code: {status}")

print(f"\nRunning. PFI0 should show a repeating trigger pulse every {PERIOD_US} us.")

input("\nPress ENTER to stop generation and close session...")
hsdio.niHSDIO_Abort(session)   # stop the "repeat forever" loop cleanly
hsdio.niHSDIO_close(session)
print("Closed")