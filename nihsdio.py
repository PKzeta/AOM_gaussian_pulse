import nihsdio

# --- Open session to the SOURCE PXI-6541 (the one generating the trigger) ---
resource_name = "Dev1"  # replace with your actual device resource name (check MAX)
session = nihsdio.Session(resource_name)

# --- Configure sample clock (adjust to match your actual generation setup) ---
session.configure_sample_clock(
    clock_source=nihsdio.SampleClockSource.ON_BOARD_CLOCK,
    clock_rate=50e6
)

# --- Set PFI 0 direction to OUTPUT ---
# PFI channels have per-channel direction control; must be explicit
session.exported_start_trigger_output_terminal = "PFI0"

# --- Explicitly export the Start Trigger event to PFI 0 ---
session.export_signal(
    signal=nihsdio.SignalSource.START_TRIGGER,
    output_terminal="PFI0"
)

# --- (Optional) If you want to trigger on a Marker/event mid-waveform instead ---
# session.export_signal(
#     signal=nihsdio.SignalSource.MARKER_EVENT0,
#     output_terminal="PFI0"
# )

# --- Configure and write your waveform data here ---
# session.write_waveform(...)

# --- Arm and start the session ---
session.initiate()

# At this point, the moment the Start Trigger condition is met
# (software trigger call, or whatever you've configured to start the session),
# a pulse will be driven out on PFI 0.

# If starting via software trigger explicitly:
session.send_software_edge_trigger(trigger=nihsdio.TriggerType.START)

# --- Wait for generation to complete ---
session.wait_until_done(timeout=10.0)

# --- Clean up ---
session.close()