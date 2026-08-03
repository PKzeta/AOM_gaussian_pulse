"""
Arbitrary-envelope RF burst generator for the Spectrum M4x.6631-x4 AWG
(sn 18230), single channel output, externally triggered on Ext0/Trig0
by the PXI-6541's PFI0 output.
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

        # Bypass the 65 MHz output filter so the 100 MHz carrier passes
        spcm_dwSetParam_i32(self.hCard, filter_regs[channel], 0)

        # ---- Card mode: replay the whole buffer once per external trigger,
        #      then re-arm and wait for the next one (SPC_LOOPS=0 -> forever) ----
        spcm_dwSetParam_i32(self.hCard, SPC_CARDMODE, SPC_REP_STD_SINGLERESTART)
        spcm_dwSetParam_i64(self.hCard, SPC_LOOPS, 0)

        # ---- External trigger setup: Ext0/Trig0, fed from the 6541's PFI0 ----
        # reset the trigger from the previous runs

        spcm_dwSetParam_i32(self.hCard, SPC_TRIG_TERM, 1)          # high-Z input; set to 1 for 50 Ohm if needed
        spcm_dwSetParam_i32(self.hCard, SPC_TRIG_EXT0_ACDC, COUPLING_DC)
        spcm_dwSetParam_i32(self.hCard, SPC_TRIG_EXT0_MODE, SPC_TM_POS)   # rising edge
        spcm_dwSetParam_i32(self.hCard, SPC_TRIG_EXT0_LEVEL0, 500)       # mV threshold -- verify against PFI0's actual logic swing
        spcm_dwSetParam_i32(self.hCard, SPC_TRIG_ORMASK, SPC_TMASK_EXT0)

        # ---- X0 still marks the start of each replay, useful for scope debugging ----
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
        if frequency_hz <= 0:
            n = ((min_samples + 31) // 32) * 32
            return max(n, 32)

        fs = int(round(self.samplerate))
        f = int(round(frequency_hz))
        g = math.gcd(fs, f)
        exact_unit = fs // g
        step = exact_unit * 32 // math.gcd(exact_unit, 32)

        max_exact_samples = 8_000_000
        if step > max_exact_samples:
            periods = max(1, round(min_samples * f / fs))
            n = int(round(periods * fs / f))
            n = ((n + 31) // 32) * 32
            return max(n, 32)

        n = int(math.ceil(min_samples / step)) * step
        return max(n, step)

    def _envelope(self, shape, t_us, flat_top_us, sigma_us, n_sigma,
              clamp_threshold):
        half = flat_top_us / 2.0
        left = t_us < -half
        right = t_us > half

        if shape == 'gaussian':
            env = np.ones_like(t_us)
            env[left] = np.exp(-0.5 * ((t_us[left] + half) / sigma_us) ** 2)
            env[right] = np.exp(-0.5 * ((t_us[right] - half) / sigma_us) ** 2)

        elif shape == 'sine':
            if sigma_us <= 0:
                raise ValueError("sine shape requires sigma_us (period, us) > 0")
            half_width = sigma_us / 2.0
            env = np.zeros_like(t_us)
            within = np.abs(t_us) <= half_width
            env[within] = np.cos(np.pi * t_us[within] / sigma_us)

        elif shape == 'square':
            if flat_top_us <= 0:
                raise ValueError("square shape requires flat_top_us > 0")
            env = (np.abs(t_us) <= half).astype(float)

        elif shape in ('sawtooth', 'ramp'):
            edge = abs(n_sigma) * sigma_us
            if edge <= 0:
                raise ValueError("sawtooth/ramp shape requires a positive ramp width")
            env = np.zeros_like(t_us)
            env[left] = np.clip((t_us[left] + half + edge) / edge, 0.0, 1.0)
            # env[right] = np.clip((half + edge - t_us[right]) / edge, 0.0, 1.0)

        else:
            raise ValueError(
                f"unknown envelope shape {shape!r}: "
                "use 'gaussian', 'square', 'sawtooth'/'ramp', or 'sine'")

        env[env < clamp_threshold] = 0.0
        return env

        # ------------------------------------------------------------------
    def update_pulse(
        self,
        flat_top_us,
        sigma_us,
        period_us,
        amplitude_mV,
        shape='gaussian',
        n_sigma=-3,
        clamp_threshold=1e-4,
        ):
        was_running = self.running
        if was_running:
            self.stop()

        # Single source of truth for edge_us / pre_roll_us, used both for
        # buffer-length sizing below and for centering the pulse later.
        if shape == 'square':
            edge_us = 0.0
        elif shape == 'sine':
            edge_us = -sigma_us / 2.0   # half-period tail before the peak
        else:
            edge_us = n_sigma * sigma_us

        pre_roll_us = -edge_us

        min_len_for_pulse_us = flat_top_us + 2 * abs(edge_us)
        min_len_us = max(period_us, min_len_for_pulse_us)
        min_samples = int(np.ceil(min_len_us * 1e-6 * self.samplerate))

        n = self._periodic_length(central_freq, min_samples=min_samples)
        print(f"periodic length: {n} samples")

        t_us = np.arange(n) / self.samplerate * 1e6 - pre_roll_us

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
            f"buffer length: {n} samples ({self.actual_period_us:.3f} us) "
            f"-- must be shorter than your 6541 trigger period, or the "
            f"pulse will get cut off before the next trigger arrives."
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

    awg.update_pulse(
        flat_top_us=1.0,
        sigma_us=0.2,
        period_us=10.0,
        amplitude_mV=300,
        shape='gaussian',
    )
    awg.start()

    print("Card armed and waiting for external trigger on Ext0/Trig0 "
          "(from the 6541's PFI0). Nothing plays until a trigger arrives.")
    print("Press Enter to change parameters, or 'q' + Enter to quit.")

    try:
        while True:
            cmd = input("> ")
            if cmd.strip().lower() == "q":
                break
            try:
                shape = input(
                    "shape [gaussian/square/sawtooth/sine] (blank=gaussian): "
                ).strip().lower() or 'gaussian'
                # amp = float(input("amplitude (mV): "))
                if shape == "gaussian":
                    # sigma = 1
                    sigma = float(input("edge sigma/ramp unit (us): "))
                elif shape == "sine":
                    sigma = float(input("sin time period: "))
                elif shape == "sawtooth":
                    sigma = float(input("ramp time (us): "))
                
                else:
                    sigma = 0

                if shape == "square":
                    flat_top = float(input("flat top duration: "))
                else:
                    flat_top = 0

                if shape == "sawtooth":
                    amplitude = float(input("amplitude (mV): "))
                else:
                    amplitude = 250

            except ValueError:
                print("invalid input, try again")
                continue
            try:
                awg.update_pulse(
                    flat_top_us=flat_top,
                    sigma_us=sigma,
                    period_us=5,
                    amplitude_mV=amplitude,
                    shape=shape,
                )
            except ValueError as e:
                print(e)
    finally:
        awg.close()