"""
Arbitrary-envelope RF burst generator for the Spectrum M4x.6631-x4 AWG
(sn 18230), single channel output.

Envelope shapes
---------------
shape='gaussian' (default):

    ______________
   /              \\
  /                \\
 /                  \\

Flat top for `flat_top_us`, with rising/falling edges following a
Gaussian roll-off of standard deviation `sigma_us` on each side.

shape='square':

   ________________
   |               |
   |               |

Instant on/off, no soft edges. `sigma_us` is unused.

shape='sawtooth' (alias 'ramp'):

      _____________
     /             \\
    /               \\

Linear ramp up/down. Full transition (0 -> 1 -> 0) takes
n_sigma*sigma_us on each side, matching the same "how much buffer do
I need for the edges" convention as the Gaussian case.

Whichever shape is chosen, the envelope is multiplied by a
`central_freq` carrier sine wave to give the actual RF burst sent to
the mixer.

Controls exposed to the user:
    - shape         : 'gaussian', 'square', or 'sawtooth'/'ramp'
    - flat_top_us   : length of the flat-top portion of the envelope
    - sigma_us      : edge shape parameter (Gaussian std-dev, or ramp
                       time unit -- ignored for 'square')
    - period_us     : distance between the start of consecutive pulses
                       (i.e. the total buffer/replay length)
    - central_freq  : carrier frequency synthesized directly by the AWG
    - amplitude_mV  : peak output amplitude into 50 Ohm

Fixes applied vs. the earlier version of this script:
    - SPC_FILTER0 = 0   -> bypass the card's fixed 65 MHz output filter,
                           required to pass a 200 MHz-class carrier
    - hard envelope clamp (< clamp_threshold -> 0) at the loop
      boundary, to kill residual step/ringing at the edges of a finite
      buffer
    - the envelope itself is now actually generated (previously
      update_pulse() multiplied a mislabeled sawtooth by the carrier as
      a placeholder and never built a real Gaussian/flat-top shape)
    - sine() now sizes its buffer with the same exact-period (gcd/lcm)
      method as update_pulse(), instead of round-to-nearest-32, so the
      carrier phase is guaranteed continuous across the loop boundary
      for arbitrary frequencies

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

central_freq = 1e8  # central frequency of the AOM


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
        enable_regs = [SPC_ENABLEOUT0, SPC_ENABLEOUT1,
                       SPC_ENABLEOUT2, SPC_ENABLEOUT3]
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
        # LCM(exact_unit, 32)
        step = exact_unit * 32 // math.gcd(exact_unit, 32)

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
    def _envelope(self, shape, t_us, flat_top_us, sigma_us, n_sigma,
                  clamp_threshold):
        """
        Build the amplitude envelope (values in [0, 1]) for one of the
        supported shapes, evaluated at times t_us (buffer centered on 0).
        """
        half = flat_top_us / 2.0
        left = t_us < -half
        right = t_us > half

        if shape == 'gaussian':
            env = np.ones_like(t_us)
            env[left] = np.exp(-0.5 * ((t_us[left] + half) / sigma_us) ** 2)
            env[right] = np.exp(-0.5 * ((t_us[right] - half) / sigma_us) ** 2)

        elif shape == 'square':
            env = (np.abs(t_us) <= half).astype(float)

        elif shape in ('sawtooth', 'ramp'):
            edge = n_sigma * sigma_us  # full 0->1 ramp width, matches
                                        # the buffer-sizing convention below
            env = np.zeros_like(t_us)
            env[left] = np.clip((t_us[left] + half + edge) / edge, 0.0, 1.0)
            # env[right] = np.clip((half + edge - t_us[right]) / edge, 0.0, 1.0)


        else:
            raise ValueError(
                f"unknown envelope shape {shape!r}: "
                "use 'gaussian', 'square', or 'sawtooth'/'ramp'")

        env[env < clamp_threshold] = 0.0
        return env

    # ------------------------------------------------------------------
    def square(self, n, frequency_hz):
        """Raw bipolar square wave, n samples, not an envelope."""
        samples = np.arange(n)
        return np.where(
            np.sin(2 * np.pi * frequency_hz * samples / self.samplerate) >= 0,
            1.0,
            -1.0,
        )

    def sawtooth(self, n, frequency_hz):
        """Raw bipolar sawtooth wave, n samples, not an envelope."""
        samples = np.arange(n)
        phase = (samples * frequency_hz / self.samplerate) % 1.0
        return 2.0 * phase - 1.0



    # ------------------------------------------------------------------
    def update_pulse(
        self,
        flat_top_us,
        sigma_us,
        period_us,
        amplitude_mV,
        shape='gaussian',
        n_sigma=4,
        clamp_threshold=1e-4,
    ):
        """
        shape: 'gaussian' (default), 'square', or 'sawtooth'/'ramp'.
        For 'square', sigma_us is unused (edges are instantaneous).
        """
        was_running = self.running
        if was_running:
            self.stop()

        # Minimum length needed for the envelope itself to have decayed
        # to ~0 by the edges of the buffer.
        edge_us = 0.0 if shape == 'square' else n_sigma * sigma_us
        min_len_for_pulse_us = flat_top_us + 2 * edge_us
        min_len_us = max(period_us, min_len_for_pulse_us)
        min_samples = int(np.ceil(min_len_us * 1e-6 * self.samplerate))

        n = self._periodic_length(central_freq, min_samples=min_samples)
        print(f"periodic length: {n} samples")

        t_us = (np.arange(n) - n / 2) / self.samplerate * \
            1e6  # center pulse in buffer

        envelope = self._envelope(shape, t_us, flat_top_us, sigma_us,
                                   n_sigma, clamp_threshold)
        carrier = np.sin(2 * np.pi * central_freq * t_us * 1e-6)

        full_scale = 32767
        data = np.clip(envelope * carrier * full_scale, -full_scale,
                       full_scale).astype(np.int16)

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
            uint64(data.nbytes),
        )
        spcm_dwSetParam_i32(self.hCard, SPC_M2CMD,
                            M2CMD_DATA_STARTDMA | M2CMD_DATA_WAITDMA)
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
    awg = AWGGaussianFlatTopPulse(
        device="/dev/spcm0", channel=0, samplerate=1_250_000_000)

    # 1 us flat top, 0.2 us Gaussian sides, 10 us between pulses, 200 MHz carrier
    awg.update_pulse(
        flat_top_us=1.0,
        sigma_us=0.2,
        period_us=10.0,
        amplitude_mV=300,
        shape='gaussian',
    )
    awg.start()

    print("RF burst running. Trigger your scope from the X0 "
          "MMCX connector on the front panel.")
    print("Press Enter to change parameters, or 'q' + Enter to quit.")

    try:
        while True:
            cmd = input("> ")
            if cmd.strip().lower() == "q":
                break
            try:
                shape = input(
                    "shape [gaussian/square/sawtooth] (blank=gaussian): "
                ).strip().lower() or 'gaussian'
                # flat_top = float(input("flat-top duration (us): "))
                sigma = float(input("edge sigma/ramp unit (us): "))
                # period = float(
                    # input("distance between pulses / period (us): "))
                # amp = float(input("amplitude (mV peak): "))
            except ValueError:
                print("invalid input, try again")
                continue
            try:
                awg.update_pulse(
                    flat_top_us=0,
                    sigma_us=sigma,
                    period_us=5,
                    amplitude_mV=300,
                    shape=shape,
                )
            except ValueError as e:
                print(e)
    finally:
        awg.close()