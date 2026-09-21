"""
Gaussian pulse generator for the Spectrum M4x.6631-x4 AWG (sn 18230).

Generates a single Gaussian-envelope pulse of a given width (FWHM) and
peak amplitude, and replays it repetitively so you can see it on a
scope. X0 (front-panel multi-purpose I/O) is programmed to output a
marker pulse at the start of every replay loop -- use that as your
oscilloscope's external trigger so the trace is stable.

Card: M4x.6631-x4, 1 channel used, 1.25 GS/s, 16-bit, 400 MHz analog BW.
This pulse is meant to be fed into a mixer IF port together with an RF
LO, so its baseband bandwidth (~1/pulse_width ~ 1 MHz) is well within
the card's 400 MHz output bandwidth.

Requires pyspcm.py, regs.py, spcerr.py, spcm_tools.py from the Spectrum
driver install, in the same folder as this script (or on PYTHONPATH).
"""

import sys
import numpy as np

from claude_sin_gen import AWGSineGenerator
from pyspcm import *
from spcm_tools import *
from regs import *


class AWGGaussianPulse:
    def __init__(self, device="/dev/spcm0", channel=0, samplerate=1_250_000_000):
        self.channel = channel
        self.samplerate = samplerate

        self.hCard = spcm_hOpen(create_string_buffer(device.encode()))
        if not self.hCard:
            sys.exit(f"could not open card at {device}")

        # ---- clock ----
        spcm_dwSetParam_i32(self.hCard, SPC_CLOCKMODE, SPC_CM_INTPLL)
        spcm_dwSetParam_i64(self.hCard, SPC_SAMPLERATE, int64(self.samplerate))

        lSampleRate = int64(0)
        spcm_dwGetParam_i64(self.hCard, SPC_SAMPLERATE, byref(lSampleRate))
        self.samplerate = lSampleRate.value

        # ---- channel setup ----
        channel_masks = [CHANNEL0, CHANNEL1, CHANNEL2, CHANNEL3]
        spcm_dwSetParam_i32(self.hCard, SPC_CHENABLE, channel_masks[channel])

        amp_regs = [SPC_AMP0, SPC_AMP1, SPC_AMP2, SPC_AMP3]
        self._amp_reg = amp_regs[channel]

        enable_regs = [SPC_ENABLEOUT0, SPC_ENABLEOUT1, SPC_ENABLEOUT2, SPC_ENABLEOUT3]
        spcm_dwSetParam_i32(self.hCard, enable_regs[channel], 1)

        # ---- card mode: continuous replay of one buffer (loops = 0 -> forever) ----
        spcm_dwSetParam_i32(self.hCard, SPC_CARDMODE, SPC_REP_STD_SINGLE)
        spcm_dwSetParam_i32(self.hCard, SPC_TRIG_ORMASK, SPC_TMASK_SOFTWARE)
        spcm_dwSetParam_i64(self.hCard, SPC_LOOPS, 0)

        # ---- X0 outputs a marker pulse at the start of every loop ----
        # use this as the external trigger input on your oscilloscope
        spcm_dwSetParam_i32(self.hCard, SPCM_X0_MODE, SPCM_XMODE_CONTOUTMARK)

        self.pnBuffer = None
        self.running = False

    # ------------------------------------------------------------------
    def _check_error(self):
        szErrorText = create_string_buffer(ERRORTEXTLEN)
        if spcm_dwGetErrorInfo_i32(self.hCard, None, None, szErrorText) != ERR_OK:
            print(szErrorText.value.decode())

    # ------------------------------------------------------------------
    def update_pulse(self, width_us, amplitude_mV, rep_period_us=None, n_sigma=4):
        """
        width_us:      Gaussian FWHM in microseconds (e.g. 1.0 for a 1 us pulse)
        amplitude_mV:  peak output amplitude in mV (into 50 Ohm)
        rep_period_us: total length of one replay loop, in microseconds.
                       Must be long enough to contain the full pulse plus
                       some flat baseline before/after (dead time for the
                       mixer/scope). Defaults to 5x the FWHM on each side.
        n_sigma:       how many standard deviations the buffer extends
                       out to before/after the pulse center (controls how
                       cleanly the Gaussian goes to ~0 at the edges)
        """
        was_running = self.running
        if was_running:
            self.stop()

        sigma_us = width_us / 2.3548  # FWHM -> sigma
        if rep_period_us is None:
           rep_period_us = 1e6/1_000_000

        n = int(round(rep_period_us * 1e-6 * self.samplerate))
        print(f"n: {n}")
        n = ((n + 31) // 32) * 32  # round up to multiple of 32 (memory granularity)
        n = max(n, 32)

        t_us = (np.arange(n) - n / 2) / self.samplerate * 1e6  # center pulse in buffer
        envelope = np.exp(-0.5 * (t_us / sigma_us) ** 2)

        full_scale = 32767
        # first waveform: 1 MHz, 1000 mV peak, 0 deg phase  
        data = (envelope * full_scale).astype(np.int16)

        spcm_dwSetParam_i64(self.hCard, SPC_MEMSIZE, int64(n))
        spcm_dwSetParam_i32(self.hCard, self._amp_reg, int(amplitude_mV))

        self.pnBuffer = create_string_buffer(data.tobytes())
        spcm_dwDefTransfer_i64(
            self.hCard,
            SPCM_BUF_DATA,
            SPCM_DIR_PCTOCARD,
            0,
            self.pnBuffer,
            uint64(0),
            uint64(n * 2),
        )
        spcm_dwSetParam_i32(self.hCard, SPC_M2CMD, M2CMD_DATA_STARTDMA | M2CMD_DATA_WAITDMA)
        self._check_error()

        self.actual_period_us = n / self.samplerate * 1e6
        print(f"buffer length: {n} samples, replay period: {self.actual_period_us:.3f} us "
              f"({1 / (self.actual_period_us * 1e-6) / 1000:.1f} kHz rep rate)")

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
    awg = AWGGaussianPulse(device="/dev/spcm0", channel=0, samplerate=1_250_000_000)

    # 1 us FWHM Gaussian pulse, 500 mV peak, repeated every ~15 us
    awg.update_pulse(width_us=1.0, amplitude_mV=500)
    awg.start()

    print("Gaussian pulse running. Trigger your scope from the X0 MMCX "
          "connector on the front panel.")
    print("Press Enter to change width/amplitude, or 'q' + Enter to quit.")

    try:
        while True:
            cmd = input("> ")
            if cmd.strip().lower() == "q":
                break
            try:
                width = float(input("pulse width / FWHM (us): "))
                amp = float(input("amplitude (mV peak): "))
            except ValueError:
                print("invalid input, try again")
                continue
            awg.update_pulse(width_us=width, amplitude_mV=amp)
    finally:
        awg.close()
