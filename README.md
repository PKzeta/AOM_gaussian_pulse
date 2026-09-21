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
Convoluted signal 
live_gauss_loop.py	Generates and continuously replays a Gaussian pulse.
convol_CH1_sin_CH2.py	Generates a waveform using a convolution/envelope approach with sine-wave output on multiple channels.
multi_channel_code.py	Example code for operating multiple AWG channels.
AWG_array.py	AWG waveform/array generation and control.
trigger_test2.py	Tests the AWG trigger/marker output.
quick_plot.py	Quick plotting and inspection of generated waveforms.
plan.txt	Development notes and plans for the project.
