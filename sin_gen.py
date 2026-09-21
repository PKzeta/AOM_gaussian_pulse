"""
Sine wave generator for Spectrum Instrumentation M4i/M4x 66xx series AWG cards.

Uses the standard replay mode (SPC_REP_STD_SINGLE) with continuous looping
(SPC_LOOPS = 0). The sine wave is precomputed as int16 samples and pushed
into on-board memory. Frequency, amplitude (voltage) and phase can all be
changed at run time via update_waveform().

Requires the driver files that ship with the card / on the Spectrum USB
stick: pyspcm.py, regs.py, spcerr.py, spcm_tools.py
Put this script in the same folder as those files (or on the PYTHONPATH).
"""

import sys
import numpy as np

from pyspcm import *
from spcm_tools import *
from regs import *


class AWGSineGenerator:
    def __init__(self, device="/dev/spcm0", channel=0, samplerate=1_250_000_000):
        """
        device:     '/dev/spcm0' on Linux, 'spcm0' on Windows,
                    or 'TCPIP::<ip>::INST0::INSTR' for a NETBOX / remote card
        channel:    0..3 depending on card model
        samplerate: sample rate in Hz (check SPC_MIINST_MAXADCLOCK for your card's max)
        """
        self.channel = channel
        self.samplerate = samplerate

        self.hCard = spcm_hOpen(create_string_buffer(device.encode()))
        if self.hCard is None:
            sys.exit(f"could not open card at {device}")

        self._check_error()

        # ---- clock ----
        spcm_dwSetParam_i32(self.hCard, SPC_CLOCKMODE, SPC_CM_INTPLL)
        spcm_dwSetParam_i64(self.hCard, SPC_SAMPLERATE, int64(self.samplerate))

        # read back the actually-set sample rate (it gets rounded to a valid value)
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

        # ---- card / trigger mode ----
        spcm_dwSetParam_i32(self.hCard, SPC_CARDMODE, SPC_REP_STD_SINGLE)
        spcm_dwSetParam_i32(self.hCard, SPC_TRIG_ORMASK, SPC_TMASK_SOFTWARE)
        spcm_dwSetParam_i64(self.hCard, SPC_LOOPS, 0)  # 0 = replay continuously

        self.pnBuffer = None
        self.running = False

    # ------------------------------------------------------------------
    def _check_error(self):
        szErrorText = create_string_buffer(ERRORTEXTLEN)
        if spcm_dwGetErrorInfo_i32(self.hCard, None, None, szErrorText) != ERR_OK:
            print(szErrorText.value.decode())

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
    def update_waveform(self, frequency_hz, amplitude_mV = 100, phase_deg=0.0, offset_mV=0.0):
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
            0,
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
    awg = AWGSineGenerator(device="/dev/spcm0", channel=0, samplerate=1_250_000_000)

    # first waveform: 1 MHz, 1000 mV peak, 0 deg phase
    awg.update_waveform(frequency_hz=1_000_000, amplitude_mV=100, phase_deg=0)
    awg.start()

    print("Sine wave running. Press Enter to change frequency/amplitude, "
          "or type 'q' + Enter to quit.")

    try:
        while True:
            cmd = input("> ")
            if cmd.strip().lower() == "q":
                break
            try:
                freq = float(input("frequency (Hz): "))
                amp = float(input("amplitude (mV peak): "))
                phase = float(input("phase (deg) [0]: ") or 0)
            except ValueError:
                print("invalid input, try again")
                continue
            awg.update_waveform(frequency_hz
                                =freq, amplitude_mV=amp, phase_deg=phase)
    finally:
        awg.close()
