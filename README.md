# AOM Pulse Generator

Program for generating, shaping, and controlling RF waveforms for AOM-based Rydberg excitation experiments using a Spectrum Instrumentation M4x.6631-x4 AWG.

# Hardware

The code was developed for the:

- Spectrum Instrumentation M4i/M4x 66xx series AWG cards
- Serial number: 18230
- Sampling rate: 1.25 GS/s
- Resolution: 16-bit
- Analog bandwidth: 400 MHz
- 3100-1125 AOM

# Contains
Gaussian Generator with tuneable pulse width and amplitude (gaussian_pulse.py)
Sine Generator with tuneable sinusoid parameters (sin_gen.py)
Multi-channel waveform generation (multi_channel_code.py)
Gaussian baseband pulse envelope for mixing with an RF local oscillator to produce a Gaussian-shaped RF pulse for AOM control (convol_CH1_sin_CH2.py)
AWG waveform/array generation and control (AWG_array.py)
Live AWG waveform/array generation and control, allowing pulse parameters to be changed in real time while the waveform is being continuously output (live_gauss_loop.py)
trigger_test2.py	Tests the AWG trigger/marker output by sending in an external trigger from the .
