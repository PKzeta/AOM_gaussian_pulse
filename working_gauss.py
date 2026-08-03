"""
Gaussian-sided flat-top RF burst generator for the Spectrum M4x.6631-x4 AWG
(sn 18230), single channel output.
 
Envelope shape
--------------
    ______________
   /              \\
  /                \\
 /                  \\
 
Flat top for `flat_top_us` (the pulse "duration"), with the rising and
falling edges following a Gaussian roll-off of standard deviation
`sigma_us` on each side. This is multiplied by a `frequency_hz` carrier
sine wave to give the actual RF burst that gets sent to the mixer.
 
Controls exposed to the user:
    - flat_top_us   : length of the flat-top portion of the envelope
    - sigma_us      : sigma of the Gaussian sides (rise/fall shape)
    - period_us     : distance between the start of consecutive pulses
                       (i.e. the total buffer/replay length)
    - frequency_hz  : carrier frequency synthesized directly by the AWG
    - amplitude_mV  : peak output amplitude into 50 Ohm
 
Fixes applied (previously identified but not yet folded into the
production script):
    - SPC_FILTER0 = 0   -> bypass the card's fixed 65 MHz output filter,
                           required to pass a 200 MHz-class carrier
    - hard envelope clamp (< 1e-4 -> 0) at the loop boundary, to kill
      the residual step/ringing from the Gaussian never quite reaching
      zero within a finite buffer
 
Card: M4x.6631-x4, 1 channel used, 1.25 GS/s, 16-bit, 400 MHz analog BW.
 
Requires pyspcm.py, regs.py, spcerr.py, spcm_tools.py from the Spectrum
driver install, in the same folder as this script (or on PYTHONPATH).
"""
 
import sys
import math
import numpy as np
 
from pyspcm import *
from spcm_tools import *
from regs import *
 
 
class AWGGaussianFlatTopPulse:
    def __init__(self, device="/dev/spcm0", channel=0, samplerate=1_250_000_000):
        self.channel = channel
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
 
        # ---- Channel setup (single channel only) ----
        channel_masks = [CHANNEL0, CHANNEL1, CHANNEL2, CHANNEL3]
        amp_regs = [SPC_AMP0, SPC_AMP1, SPC_AMP2, SPC_AMP3]
        enable_regs = [SPC_ENABLEOUT0, SPC_ENABLEOUT1, SPC_ENABLEOUT2, SPC_ENABLEOUT3]
        filter_regs = [SPC_FILTER0, SPC_FILTER1, SPC_FILTER2, SPC_FILTER3]
 
        spcm_dwSetParam_i32(self.hCard, SPC_CHENABLE, channel_masks[channel])
        self._amp_reg = amp_regs[channel]
        spcm_dwSetParam_i32(self.hCard, enable_regs[channel], 1)
 
        # Fix #1: bypass the 65 MHz output filter so the carrier passes
        spcm_dwSetParam_i32(self.hCard, filter_regs[channel], 0)
 
        # ---- Card mode: continuous replay of one buffer (loops = 0 -> forever) ----
        spcm_dwSetParam_i32(self.hCard, SPC_CARDMODE, SPC_REP_STD_SINGLE)
        spcm_dwSetParam_i32(self.hCard, SPC_TRIG_ORMASK, SPC_TMASK_SOFTWARE)
        spcm_dwSetParam_i64(self.hCard, SPC_LOOPS, 0)
 
        # ---- X0 outputs a marker pulse at the start of every loop ----
        # use this as the external trigger input on your oscilloscope
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
    def _periodic_length(self, frequency_hz, min_samples):
        """
        Number of samples that (a) holds an exact whole number of carrier
        periods -- so the carrier phase is exactly continuous across the
        loop boundary, with no phase jump -- and (b) is at least
        min_samples long, (c) is a multiple of 32 (memory granularity).
 
        Exactness uses integer arithmetic rather than rounding a float
        sample count: the smallest buffer length that repeats the carrier
        exactly is samplerate / gcd(samplerate, frequency_hz) samples.
        Any multiple of that length also repeats exactly, so the length
        actually used is the smallest common multiple of that exact unit
        and the 32-sample memory granularity that is >= min_samples.
        """
        if frequency_hz <= 0:
            n = ((min_samples + 31) // 32) * 32
            return max(n, 32)
 
        fs = int(round(self.samplerate))
        f = int(round(frequency_hz))
        g = math.gcd(fs, f)
        exact_unit = fs // g  # smallest n with an exact integer number of periods
        step = exact_unit * 32 // math.gcd(exact_unit, 32)  # LCM(exact_unit, 32)
 
        # For "nice" frequencies (simple fraction of the sample rate, e.g.
        # 200 MHz at 1.25 GS/s) this is small. For an arbitrary frequency
        # it can blow up to an impractically large buffer, so fall back to
        # the nearest whole number of periods (a tiny residual phase slip
        # at the loop point, effectively invisible) if it would exceed a
        # sane cap.
        max_exact_samples = 8_000_000
        if step > max_exact_samples:
            periods = max(1, round(min_samples * f / fs))
            n = int(round(periods * fs / f))
            n = ((n + 31) // 32) * 32
            return max(n, 32)
 
        n = int(math.ceil(min_samples / step)) * step
        return max(n, step)
 
    # ------------------------------------------------------------------
    def update_pulse(
        self,
        flat_top_us,
        sigma_us,
        period_us,
        frequency_hz,
        amplitude_mV,
        n_sigma=4,
        clamp_threshold=1e-4,
    ):
        """
        flat_top_us:   length of the flat-top ("plateau") portion of the
                       pulse envelope, in microseconds. Set to 0 for a
                       pure Gaussian pulse (no flat top).
        sigma_us:      standard deviation of the Gaussian rise/fall
                       edges, in microseconds.
        period_us:     distance between the start of consecutive pulses,
                       i.e. the requested total replay-loop length, in
                       microseconds. The actual buffer length used may be
                       rounded up slightly to keep the carrier phase
                       continuous and to satisfy memory granularity.
        frequency_hz:  carrier frequency synthesized by the AWG, in Hz.
        amplitude_mV:  peak output amplitude in mV (into 50 Ohm).
        n_sigma:       how many standard deviations of headroom are
                       required after the flat top before the buffer
                       loops back around (controls how cleanly the
                       envelope has decayed by the edge of the buffer).
        clamp_threshold: envelope values below this (relative to a peak
                       of 1.0) are hard-clamped to zero, eliminating the
                       loop-boundary step/ringing from the Gaussian tails
                       never fully reaching zero in a finite buffer.
        """
        was_running = self.running
        if was_running:
            self.stop()
 
        # Minimum length needed for the envelope itself to have decayed
        # to ~0 by the edges of the buffer.
        min_len_for_pulse_us = flat_top_us + 2 * n_sigma * sigma_us
        min_len_us = max(period_us, min_len_for_pulse_us)
        min_samples = int(np.ceil(min_len_us * 1e-6 * self.samplerate))
 
        n = self._periodic_length(frequency_hz, min_samples=min_samples)
 
        t_us = (np.arange(n) - n / 2) / self.samplerate * 1e6  # center pulse in buffer
 
        # Gaussian-sided flat-top envelope:
        #   |t| <= flat_top/2         -> 1.0 (flat top)
        #   |t|  > flat_top/2         -> Gaussian decay based on the
        #                                distance past the flat-top edge
        half_flat_us = flat_top_us / 2.0
        dist_us = np.clip(np.abs(t_us) - half_flat_us, 0, None)
        if sigma_us > 0:
            envelope = np.exp(-0.5 * (dist_us / sigma_us) ** 2)
        else:
            envelope = (dist_us <= 0).astype(float)
 
        # Fix #2: hard-clamp small envelope values to kill loop-boundary
        # ringing from the Gaussian tails never quite reaching zero.
        envelope[envelope < clamp_threshold] = 0.0
 
        carrier = np.sin(2 * np.pi * frequency_hz * t_us * 1e-6)
 
        full_scale = 32767
        data = np.clip(envelope * carrier * full_scale, -full_scale, full_scale).astype(np.int16)
 
        spcm_dwSetParam_i64(self.hCard, SPC_MEMSIZE, int64(n))
        spcm_dwSetParam_i32(self.hCard, self._amp_reg, int(amplitude_mV))
 
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
            f"buffer length: {n} samples, replay period: "
            f"{self.actual_period_us:.3f} us "
            f"({1 / (self.actual_period_us * 1e-6) / 1000:.3f} kHz rep rate)"
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
    awg = AWGGaussianFlatTopPulse(device="/dev/spcm0", channel=0, samplerate=1_250_000_000)
 
    # 1 us flat top, 0.2 us Gaussian sides, 10 us between pulses, 200 MHz carrier
    awg.update_pulse(
        flat_top_us=1.0,
        sigma_us=0.2,
        period_us=10.0,
        frequency_hz=200_000_000,
        amplitude_mV=500,
    )
    awg.start()
 
    print("Gaussian flat-top burst running. Trigger your scope from the X0 "
          "MMCX connector on the front panel.")
    print("Press Enter to change parameters, or 'q' + Enter to quit.")
 
    try:
        while True:
            cmd = input("> ")
            if cmd.strip().lower() == "q":
                break
            try:
                flat_top = float(input("flat-top duration (us): "))
                sigma = float(input("Gaussian sigma (us): "))
                period = float(input("distance between pulses / period (us): "))
                freq = float(input("carrier frequency (Hz): "))
                amp = float(input("amplitude (mV peak): "))
            except ValueError:
                print("invalid input, try again")
                continue
            awg.update_pulse(
                flat_top_us=flat_top,
                sigma_us=sigma,
                period_us=period,
                frequency_hz=freq,
                amplitude_mV=amp,
            )
    finally:
        awg.close()
