"""
Gaussian-pulse + CW generator for the Spectrum M4x.6631-x4 AWG (sn 18230).

Channel 0: Gaussian-enveloped sine burst (the "pulse" -- envelope(t) * sin(t))
Channel 1: continuous sine wave at the same frequency, full amplitude

Both channels are replayed continuously from the same loop buffer. X0
(front-panel multi-purpose I/O) outputs a marker pulse at the start of
every replay loop -- use that as your oscilloscope's external trigger.

Card: M4x.6631-x4, 2 channels used, 1.25 GS/s, 16-bit, 400 MHz analog BW.

Requires pyspcm.py, regs.py, spcerr.py, spcm_tools.py from the Spectrum
driver install, in the same folder as this script (or on PYTHONPATH).

IMPORTANT: when more than one channel is enabled on these cards, the
card does NOT accept two separate single-channel DMA transfers. All
enabled channels share one on-board memory and the samples must be
interleaved sample-by-sample in ascending channel order:
    ch0[0], ch1[0], ch0[1], ch1[1], ...
This script builds one interleaved int16 buffer and does a single
DMA transfer, which is the fix for the original version (which wrote
two separate buffers to board offset 0, so the second transfer just
clobbered the first).
"""

import time
import sys
import numpy as np

from pyspcm import *
from spcm_tools import *
from regs import *

phase_arr = np.array([
    0.005,
    0.01,
    0.02,
    0.05,
    0.1,
    0.2,
    0.5,
    1.0,
    2.0,
    5.0
])
class AWGPulse_and_sin:
    def __init__(self, device="/dev/spcm0", samplerate=1_250_000_000):
        self.samplerate = samplerate

        self.hCard = spcm_hOpen(create_string_buffer(device.encode()))
        if not self.hCard:
            sys.exit(f"Could not open card at {device}")

        # ---- Clock ----
        spcm_dwSetParam_i32(self.hCard, SPC_CLOCKMODE, SPC_CM_INTPLL)
        spcm_dwSetParam_i64(self.hCard, SPC_SAMPLERATE, int64(self.samplerate))

        lSampleRate = int64(0)
        spcm_dwGetParam_i64(self.hCard, SPC_SAMPLERATE, byref(lSampleRate))
        self.samplerate = lSampleRate.value

        # ---- Enable CH0 (pulse) and CH1 (sine) ----
        spcm_dwSetParam_i32(self.hCard, SPC_CHENABLE, CHANNEL0 | CHANNEL1)

        # Enable outputs
        spcm_dwSetParam_i32(self.hCard, SPC_ENABLEOUT0, 1)
        spcm_dwSetParam_i32(self.hCard, SPC_ENABLEOUT1, 1)

        # ---- Card mode: continuous replay ----
        spcm_dwSetParam_i32(self.hCard, SPC_CARDMODE, SPC_REP_STD_SINGLE)
        spcm_dwSetParam_i32(self.hCard, SPC_TRIG_ORMASK, SPC_TMASK_SOFTWARE)
        spcm_dwSetParam_i64(self.hCard, SPC_LOOPS, 0)  # 0 = loop forever

        # ---- X0 marker pulse ----
        spcm_dwSetParam_i32(self.hCard, SPCM_X0_MODE, SPCM_XMODE_CONTOUTMARK)

        self.pnBuffer = None
        self.running = False
        self.actual_period_us = None

    # ------------------------------------------------------------------
    def _check_error(self):
        szErrorText = create_string_buffer(ERRORTEXTLEN)
        if spcm_dwGetErrorInfo_i32(self.hCard, None, None, szErrorText) != ERR_OK:
            print(szErrorText.value.decode())

    # ------------------------------------------------------------------
    def _periodic_length(self, frequency_hz, min_samples=4096):
        """
        Number of samples that (a) holds a whole number of sine periods,
        so the waveform loops without a phase jump, and (b) is at least
        min_samples long. Rounded up to a multiple of 32 (typical memory
        granularity -- check SPC_MIINST_MEMORY_ALIGNMENT for your card).
        """
        if frequency_hz <= 0:
            n = min_samples
        else:
            periods = max(1, round(min_samples * frequency_hz / self.samplerate))
            n = int(round(periods * self.samplerate / frequency_hz))
        n = ((n + 31) // 32) * 32
        return max(n, 32)

    # ------------------------------------------------------------------
    def update_waveforms(
        self,
        width_us,
        pulse_amplitude_mV,
        sine_amplitude_mV,
        frequency_hz=1_000_000,
        rep_period_us=None,
        n_sigma=4, phase = np.pi/2
    ):
        """
        Programs both channels from ONE shared, interleaved buffer:

          Channel 0: Gaussian(width_us FWHM) * sin(frequency_hz)
          Channel 1: sin(frequency_hz), full envelope (no gating)

        width_us:            Gaussian FWHM in microseconds
        pulse_amplitude_mV:  peak amplitude (into 50 Ohm) for channel 0
        sine_amplitude_mV:   peak amplitude (into 50 Ohm) for channel 1
        frequency_hz:        sine frequency for both channels
        rep_period_us:       minimum length of one replay loop, in
                              microseconds. The actual length used is
                              rounded up to the nearest whole number of
                              sine periods (so channel 1 has no phase
                              jump at the loop boundary). If None, a
                              default long enough to hold the pulse
                              cleanly is chosen automatically.
        n_sigma:              how many standard deviations the buffer
                              extends before/after the pulse center
        """
        was_running = self.running
        if was_running:
            self.stop()

        sigma_us = width_us / 2.3548  # FWHM -> sigma

        # minimum samples needed so the Gaussian settles to ~0 at the edges
        min_len_for_pulse = int(np.ceil(2 * n_sigma * sigma_us * 1e-6 * self.samplerate))
        n = self._periodic_length(frequency_hz, min_samples=max(4096, min_len_for_pulse))

        if rep_period_us is not None:
            n_req = int(round(rep_period_us * 1e-6 * self.samplerate))
            if n_req > n:
                period_len = (
                    self.samplerate / frequency_hz if frequency_hz > 0 else n_req
                )
                periods = int(np.ceil(n_req / period_len))
                n = int(round(periods * period_len))
                n = ((n + 31) // 32) * 32
                n = max(n, 32)

        t = np.arange(n)

        sine = np.sin(2 * np.pi * frequency_hz * t / self.samplerate)
        sine_two = np.sin(2 * np.pi * frequency_hz * t / self.samplerate + phase)
        t_us = (t - n / 2) / self.samplerate * 1e6  # center pulse in buffer
        envelope = np.exp(-0.5 * (t_us / sigma_us) ** 2)

        full_scale = 32767
        ch0 = np.clip(envelope * sine * full_scale, -full_scale, full_scale).astype(np.int16)
        ch1 = np.clip(sine_two * full_scale, -full_scale, full_scale).astype(np.int16)

        # Interleave: ch0 sample, ch1 sample, ch0, ch1, ... (ascending channel order)
        data = np.empty(2 * n, dtype=np.int16)
        data[0::2] = ch0
        data[1::2] = ch1

        spcm_dwSetParam_i64(self.hCard, SPC_MEMSIZE, int64(n))
        spcm_dwSetParam_i32(self.hCard, SPC_AMP0, int(pulse_amplitude_mV))
        spcm_dwSetParam_i32(self.hCard, SPC_AMP1, int(sine_amplitude_mV))

        self.pnBuffer = create_string_buffer(data.tobytes())
        spcm_dwDefTransfer_i64(
            self.hCard,
            SPCM_BUF_DATA,
            SPCM_DIR_PCTOCARD,
            0,  # notify size: 0 = notify only once the whole transfer is done
            self.pnBuffer,
            uint64(0),
            uint64(data.nbytes),
        )
        spcm_dwSetParam_i32(self.hCard, SPC_M2CMD, M2CMD_DATA_STARTDMA | M2CMD_DATA_WAITDMA)
        self._check_error()

        self.actual_period_us = n / self.samplerate * 1e6
        print(
            f"buffer length: {n} samples/channel, replay period: "
            f"{self.actual_period_us:.3f} us "
            f"({1 / (self.actual_period_us * 1e-6) / 1000:.1f} kHz rep rate)"
        )

        if was_running:
            self.start()

    # ------------------------------------------------------------------
    def start(self):
        spcm_dwSetParam_i32(
            self.hCard, SPC_M2CMD, M2CMD_CARD_START | M2CMD_CARD_ENABLETRIGGER
        )
        self._check_error()
        self.running = True

    def stop(self):
        spcm_dwSetParam_i32(self.hCard, SPC_M2CMD, M2CMD_CARD_STOP)
        self.running = False

    def close(self):
        if self.hCard is not None:
            self.stop()
            spcm_vClose(self.hCard)
            self.hCard = None


# ----------------------------------------------------------------------
if __name__ == "__main__":
    awg = AWGPulse_and_sin(device="/dev/spcm0", samplerate=1_250_000_000)

    awg.update_waveforms(
        width_us=1.0,
        pulse_amplitude_mV=1000,
        sine_amplitude_mV=1000,
        frequency_hz=1_000_000,
    )
    awg.start()

    print("Press Enter to change width/frequency, or 'q' + Enter to quit.")
    try:
        width = 1
        freq = 2e8
        for phase in phase_arr:
            awg.update_waveforms(
                width_us=width,
                pulse_amplitude_mV=1000,
                sine_amplitude_mV=1000,
                frequency_hz=freq,
                phase=phase*np.pi
            )
            print(f'Phase: {phase} pi')
            
            input('Press Enter to continue to next phase')
            
            
            
    finally:
        awg.close()