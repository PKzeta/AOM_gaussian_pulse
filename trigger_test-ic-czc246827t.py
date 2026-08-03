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

# Configure Sample Clock
hsdio.niHSDIO_ConfigureSampleClock.argtypes = [
    ViSession,
    ctypes.c_int32,                  # clockSource
    ctypes.c_double                  # clockRate (Hz)
]
hsdio.niHSDIO_ConfigureSampleClock.restype = ViStatus

# Assign Channels to Session
hsdio.niHSDIO_ConfigureNamedChannelU32.argtypes = [
    ViSession,
    ctypes.c_char_p,                 # channelList (e.g., "0-31")
    ctypes.c_char_p,                 # attribute name
    ViUInt32                         # value
]
hsdio.niHSDIO_ConfigureNamedChannelU32.restype = ViStatus

# Write Named Waveform (U32 data)
hsdio.niHSDIO_WriteNamedWaveformU32.argtypes = [
    ViSession,
    ctypes.c_char_p,                 # waveformName
    ctypes.c_int32,                  # numSamples
    ctypes.POINTER(ViUInt32)         # data array
]
hsdio.niHSDIO_WriteNamedWaveformU64.restype = ViStatus

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
hsdio.niHSDIO_Initiate.argtypes = [
    ViSession
]
hsdio.niHSDIO_Initiate.restype = ViStatus

# Close
hsdio.niHSDIO_close.argtypes = [
    ViSession
]
hsdio.niHSDIO_close.restype = ViStatus


# ==============================
# Driver Constants
# ==============================
NIHSDIO_VAL_CLOCK_INTERNAL = 1             # Use internal onboard clock
NIHSDIO_VAL_SCRIPT_TRIGGER = 58            # C-API constant for Script Trigger
NIHSDIO_VAL_SCRIPT0 = b"scriptTrigger0"    # ID matching the script command below

# ==============================
# 1. Open PXI-6541
# ==============================
session = ViSession(0)
status = hsdio.niHSDIO_InitGenerationSession(b"Dev1", 0, 1, b"", byref(session))
print("Init status:", status)
if status != 0: raise RuntimeError("Could not open PXI-6541")

# ==============================
# 2. Configure Hardware Timing & Channels
# ==============================
# Set Sample Clock to 50 MHz
status = hsdio.niHSDIO_ConfigureSampleClock(session, NIHSDIO_VAL_CLOCK_INTERNAL, 50000000.0)
print("Clock configuration status:", status)

# ==============================
# 3. Create & Load Waveform Data
# ==============================
# Create a dummy waveform array of 32-bit values (representing channel output patterns)
dummy_pattern = (ViUInt32 * 16)(*[0x00000000, 0xFFFFFFFF] * 8) 
status = hsdio.niHSDIO_WriteNamedWaveformU32(session, b"wfm1", 16, dummy_pattern)
print("Waveform load status:", status)

# Write a basic generation script that fires your scriptTrigger0
generation_script = (
    b"script myScript\n"
    b"  generate wfm1 marker0(0)\n"  # fires scriptTrigger0 on the first sample
    b"end script"
)
status = hsdio.niHSDIO_WriteScript(session, generation_script)
print("Script compilation status:", status)

# ==============================
# 4. Route Trigger to Front Panel
# ==============================
status = hsdio.niHSDIO_ExportSignal(session, NIHSDIO_VAL_SCRIPT_TRIGGER, NIHSDIO_VAL_SCRIPT0, b"PFI0")
print("Export status:", status)
if status != 0: raise RuntimeError("Could not export trigger to PFI0")

# ==============================
# 5. Launch Hardware Generation
# ==============================
status = hsdio.niHSDIO_Initiate(session)
print("Initiate status:", status)
if status != 0: raise RuntimeError(f"Could not initiate generation. Code: {status}")

print("\nSuccess! PXI-6541 generation initiated. Checking PFI 0 line for physical trigger pulse...")

# ==============================
# Clean up
# ==============================
input("\nPress ENTER to stop generation and close session...")
hsdio.niHSDIO_close(session)
print("Closed")
