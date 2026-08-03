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

from pyspcm import *
from spcm_tools import *
from regs import *

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

        # ---- Enable CH0 and CH1 ----
        spcm_dwSetParam_i32(
            self.hCard,
            SPC_CHENABLE,
            CHANNEL0 | CHANNEL1
        )

        # Store amplitude registers
        self._amp_regs = [SPC_AMP0, SPC_AMP1]

        # Enable outputs
        spcm_dwSetParam_i32(self.hCard, SPC_ENABLEOUT0, 1)
        spcm_dwSetParam_i32(self.hCard, SPC_ENABLEOUT1, 1)

        # ---- Card mode: continuous replay ----
        spcm_dwSetParam_i32(self.hCard, SPC_CARDMODE, SPC_REP_STD_SINGLE)
        spcm_dwSetParam_i32(self.hCard, SPC_TRIG_ORMASK, SPC_TMASK_SOFTWARE)
        spcm_dwSetParam_i64(self.hCard, SPC_LOOPS, 0)

        # ---- X0 marker pulse ----
        spcm_dwSetParam_i32(
            self.hCard,
            SPCM_X0_MODE,
            SPCM_XMODE_CONTOUTMARK
        )

        self.pnBuffer = None
        self.running = False

    # ------------------------------------------------------------------
    def _check_error(self):
        szErrorText = create_string_buffer(ERRORTEXTLEN)
        if spcm_dwGetErrorInfo_i32(self.hCard, None, None, szErrorText) != ERR_OK:
            print(szErrorText.value.decode())

    def _num_samples_for(self, frequency_hz, min_samples=4096):
        """
        Choose a memory length that holds a whole number of sine periods,
        so the waveform loops without a phase jump. Also round up to a
        multiple the card's memory granularity typically requires (32 here;
        check SPC_MIINST_MEMORY_ALIGNMENT for your exact card).
        """
        periods = max(1, round(min_samples * frequency_hz / self.samplerate))
        n = int(round(periods * self.samplerate / frequency_hz))
        n = ((n + 31) // 32) * 32  # round up to multiple of 32
        return max(n, 32)
    # ------------------------------------------------------------------
    def update_pulse(self, width_us, amplitude_mV, rep_period_us=None,frequency_hz=200_000_000, n_sigma=4):
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

        n_sin = self._num_samples_for(frequency_hz)
        t = np.arange(n_sin)
        wave = np.sin(2 * np.pi * frequency_hz * t / self.samplerate)

        sigma_us = width_us / 2.3548  # FWHM -> sigma
        if rep_period_us is None:
           rep_period_us = 1

        n = int(round(rep_period_us * 1e-6 * self.samplerate))
        print(f"n: {n}")
        n = ((n + 31) // 32) * 32  # round up to multiple of 32 (memory granularity)
        n = max(n, 32)

        t_us = (np.arange(n) - n / 2) / self.samplerate * 1e6  # center pulse in buffer
        envelope = np.exp(-0.5 * (t_us / sigma_us) ** 2)

        full_scale = 32767
        shaped_envelope = np.zeros(len(wave))
        shaped_envelope[:len(envelope)] = envelope

        data = (shaped_envelope * full_scale * wave).astype(np.int16)

        spcm_dwSetParam_i64(self.hCard, SPC_MEMSIZE, int64(n))
        spcm_dwSetParam_i32(self.hCard, SPC_AMP0, pulse_amplitude=1000)
        spcm_dwSetParam_i32(self.hCard, SPC_AMP1, sine_amplitude=1000)

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

    # ------------------------------------------------------------------
    def _num_samples_for(self, frequency_hz, min_samples=4096):
        """
        Choose a memory length that holds a whole number of sine periods,
        so the waveform loops without a phase jump. Also round up to a
        multiple the card's memory granularity typically requires (32 here;
        check SPC_MIINST_MEMORY_ALIGNMENT for your exact card).
        """
        periods = max(1, round(min_samples * frequency_hz / self.samplerate))
        n = int(round(periods * self.samplerate / frequency_hz))
        n = ((n + 31) // 32) * 32  # round up to multiple of 32
        return max(n, 32)

    # ------------------------------------------------------------------
    def update_waveform(self, frequency_hz, amplitude_mV, phase_deg=0.0, offset_mV=0.0):
        """
        frequency_hz:  sine frequency in Hz
        amplitude_mV:  peak amplitude into 50 Ohm, in mV (card limits apply,
                       e.g. 80 - 2500 mV on many 66xx models)
        phase_deg:     starting phase in degrees
        offset_mV:     currently only used to shift within full scale via
                       the digital samples (card has no separate analog
                       offset register on most 66xx models)
        """
        was_running = self.running
        if was_running:
            self.stop()

        n = self._num_samples_for(frequency_hz)
        t = np.arange(n)
        phase = np.deg2rad(phase_deg)
        wave = np.sin(2 * np.pi * frequency_hz * t / self.samplerate + phase)

        full_scale = 32767  # int16 full scale, corresponds to SPC_AMPx (peak)
        # amplitude_mV is expressed relative to the SPC_AMP0 setting below,
        # so the digital data is always full-scale sine and the *voltage*
        # is controlled by the SPC_AMP0 register (cleaner + higher resolution)
        data = (wave * full_scale).astype(np.int16)

        spcm_dwSetParam_i64(self.hCard, SPC_MEMSIZE, int64(n))
        spcm_dwSetParam_i32(self.hCard, self._amp_reg, int(amplitude_mV))

        self.pnBuffer = create_string_buffer(data.tobytes())
        spcm_dwDefTransfer_i64(
            self.hCard,
            SPCM_BUF_DATA,
            SPCM_DIR_PCTOCARD,
            1,
            self.pnBuffer,
            uint64(0),
            uint64(n * 2),  # 2 bytes per int16 sample
        )
        spcm_dwSetParam_i32(self.hCard, SPC_M2CMD, M2CMD_DATA_STARTDMA | M2CMD_DATA_WAITDMA)
        self._check_error()

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
    awg = AWGPulse_and_sin(device="/dev/spcm0", channel=0, samplerate=1_250_000_000)

    awg.update_pulse(width_us=1.0, amplitude_mV=1000, frequency_hz=1_000_000,)
    awg.start()

    print("Press Enter to change width/amplitude, or 'q' + Enter to quit.")

    try:
        while True:
            cmd = input("> ")
            if cmd.strip().lower() == "q":
                break
            try:
                width = float(input("pulse width / FWHM (us): "))
                freq = float(input("frequency (Hz): "))
            except ValueError:
                print("invalid input, try again")
                continue
            awg.update_pulse(width_us=width, frequency_hz=freq, amplitude_mV=1000)
            awg.update_waveform(frequency_hz=freq, amplitude_mV=1000)
            
    finally:
        awg.close()
