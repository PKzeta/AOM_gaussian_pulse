#!/usr/bin/env python3
"""
gaussian_expected_vs_actual.py

Hybrid control:
- AWG: Spectrum M4x.6631-x4 via pyspcm (/dev/spcm0)
- Scope: Rohde & Schwarz RTO2004 via PyVISA

Generates Gaussian on AWG, acquires from scope, plots expected vs actual.
"""

import sys
import time
import numpy as np
import matplotlib.pyplot as plt
import pyvisa

from ctypes import byref, create_string_buffer, c_int16, cast, POINTER
from pyspcm import *
from spcm_tools import *
from regs import *

# -----------------------------
# USER SETTINGS
# -----------------------------
SCOPE_RESOURCE = "TCPIP0::10.59.238.90::inst0::INSTR"
SCOPE_CHANNEL = 1
SCOPE_TIMEOUT_MS = 10000

# Pulse settings
WIDTH_US = 1e-2
AMPLITUDE_MV = 1000
REP_PERIOD_US = None    # None = auto
N_SIGMA = 4

# Acquisition settings
SCOPE_TIME_RANGE_S = 40e-6
SCOPE_TRIGGER_LEVEL_V = 0.05

# FIX 8: Minimum sample count required by Spectrum SDK (card-dependent, 1024 is safe)
MIN_SAMPLES = 1024


class AWGGaussianPulse:
    def __init__(self, device="/dev/spcm0", channel=0, samplerate=1_250_000_000):
        self.channel = channel
        self.samplerate = samplerate
        self.last_wave_i16 = None
        self.last_t_s = None

        self.hCard = spcm_hOpen(create_string_buffer(device.encode()))
        if not self.hCard:
            sys.exit(f"could not open card at {device}")

        spcm_dwSetParam_i32(self.hCard, SPC_CLOCKMODE, SPC_CM_INTPLL)
        spcm_dwSetParam_i64(self.hCard, SPC_SAMPLERATE, int64(self.samplerate))

        lSampleRate = int64(0)
        spcm_dwGetParam_i64(self.hCard, SPC_SAMPLERATE, byref(lSampleRate))
        self.samplerate = lSampleRate.value

        channel_masks = [CHANNEL0, CHANNEL1, CHANNEL2, CHANNEL3]
        spcm_dwSetParam_i32(self.hCard, SPC_CHENABLE, channel_masks[channel])

        amp_regs = [SPC_AMP0, SPC_AMP1, SPC_AMP2, SPC_AMP3]
        self._amp_reg = amp_regs[channel]

        enable_regs = [SPC_ENABLEOUT0, SPC_ENABLEOUT1, SPC_ENABLEOUT2, SPC_ENABLEOUT3]
        spcm_dwSetParam_i32(self.hCard, enable_regs[channel], 1)

        # FIX 1: Use CONTINUOUS mode so the buffer loops indefinitely.
        # SPC_REP_STD_SINGLE fires once and stops — wrong for a repeating pulse.
        spcm_dwSetParam_i32(self.hCard, SPC_CARDMODE, SPC_REP_STD_CONTINUOUS)
        spcm_dwSetParam_i32(self.hCard, SPC_TRIG_ORMASK, SPC_TMASK_SOFTWARE)

        # FIX 1 cont.: SPC_LOOPS = 0 means "loop forever", valid in CONTINUOUS mode.
        spcm_dwSetParam_i64(self.hCard, SPC_LOOPS, int64(0))

        # FIX 2: Use TRIGOUT marker (fires once per buffer replay) instead of
        # CONTOUTMARK which is only meaningful in true continuous streaming mode.
        spcm_dwSetParam_i32(self.hCard, SPCM_X0_MODE, SPCM_XMODE_TRIGOUT)

        self.pnBuffer = None
        self.running = False
        self.actual_period_us = None

    def _check_error(self):
        szErrorText = create_string_buffer(ERRORTEXTLEN)
        dwErr = spcm_dwGetErrorInfo_i32(self.hCard, None, None, szErrorText)
        if dwErr != ERR_OK:
            # Raise so callers know something went wrong instead of silently continuing
            raise RuntimeError(f"Spectrum card error: {szErrorText.value.decode()}")

    def update_pulse(self, width_us, amplitude_mV, rep_period_us=None, n_sigma=4):
        was_running = self.running
        if was_running:
            self.stop()

        sigma_us = width_us / 2.3548
        if rep_period_us is None:
            rep_period_us = 2 * n_sigma * sigma_us + 4 * width_us

        n = int(round(rep_period_us * 1e-6 * self.samplerate))
        # Align to 32-sample boundary (Spectrum requirement)
        n = ((n + 31) // 32) * 32
        # FIX 8: Enforce minimum sample count (1024) required by Spectrum SDK
        n = max(n, MIN_SAMPLES)

        t_s = (np.arange(n) - n / 2) / self.samplerate
        t_us = t_s * 1e6
        envelope = np.exp(-0.5 * (t_us / sigma_us) ** 2)

        full_scale = 32767
        data = (envelope * full_scale).astype(np.int16)

        spcm_dwSetParam_i64(self.hCard, SPC_MEMSIZE, int64(n))
        spcm_dwSetParam_i32(self.hCard, self._amp_reg, int(amplitude_mV))

        # FIX 3: Use pvAllocMemPageAligned for a properly page-aligned DMA buffer.
        # create_string_buffer() is NOT page-aligned and can cause DMA corruption.
        byte_count = n * 2  # int16 = 2 bytes per sample
        self.pnBuffer = pvAllocMemPageAligned(byte_count)

        # Copy numpy int16 data into the aligned buffer via ctypes pointer cast
        ptr = cast(self.pnBuffer, POINTER(c_int16))
        for i, val in enumerate(data):
            ptr[i] = int(val)

        spcm_dwDefTransfer_i64(
            self.hCard,
            SPCM_BUF_DATA,
            SPCM_DIR_PCTOCARD,
            0,
            self.pnBuffer,
            uint64(0),
            uint64(byte_count),
        )
        spcm_dwSetParam_i32(
            self.hCard,
            SPC_M2CMD,
            M2CMD_DATA_STARTDMA | M2CMD_DATA_WAITDMA,
        )
        self._check_error()

        self.actual_period_us = n / self.samplerate * 1e6
        self.last_wave_i16 = data.copy()
        self.last_t_s = t_s.copy()

        print(f"buffer length: {n} samples, replay period: {self.actual_period_us:.3f} us")

        if was_running:
            self.start()

    def start(self):
        spcm_dwSetParam_i32(
            self.hCard,
            SPC_M2CMD,
            M2CMD_CARD_START | M2CMD_CARD_ENABLETRIGGER,
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


# FIX 6: Use correct RTO2004 SCPI command tree.
# RTO uses TRIGger1: namespace, not TRIGger:A: (that's Tektronix syntax).
def setup_scope(scope, ch=1):
    scope.timeout = 20000
    scope.read_termination = "\n"
    scope.write_termination = "\n"
    scope.chunk_size = 1024 * 1024

    scope.write("*CLS")
    scope.write("STOP")
    scope.write(f"CHANnel{ch}:STATe ON")
    scope.write(f"TIMebase:RANGe {SCOPE_TIME_RANGE_S}")

    # RTO2004 correct trigger syntax
    scope.write("TRIGger1:MODE NORMal")
    scope.write(f"TRIGger1:SOURce CHANnel{ch}")
    scope.write(f"TRIGger1:LEVel{ch} {SCOPE_TRIGGER_LEVEL_V}")


def acquire_scope(scope, ch=1):
    scope.write("SINGle")

    # FIX 7: Raise a proper TimeoutError if acquisition never completes
    # instead of silently falling through and reading stale data.
    max_polls = 200
    for i in range(max_polls):
        if scope.query("*OPC?").strip() == "1":
            break
        time.sleep(0.05)
    else:
        raise TimeoutError(
            f"Scope acquisition did not complete after {max_polls * 0.05:.1f} s"
        )

    # FIX 5: Robust header parsing that correctly extracts t_start and dt.
    # RTO2004 CHANnel:DATA:HEADer? returns:
    #   <XStart>,<XStop>,<RecordLength>,<ValuesPerSample>
    hdr = scope.query(f"CHANnel{ch}:DATA:HEADer?").strip()
    dat = scope.query(f"CHANnel{ch}:DATA?").strip()

    y = np.array(
        [float(v) for v in dat.split(",") if v.strip() != ""],
        dtype=float,
    )

    # Parse header fields explicitly by position (RTO2004 documented format)
    t0 = 0.0
    dt = SCOPE_TIME_RANGE_S / max(len(y), 1)  # safe fallback

    parts = [p.strip() for p in hdr.split(",")]
    if len(parts) >= 3:
        try:
            x_start = float(parts[0])   # XStart (seconds)
            x_stop  = float(parts[1])   # XStop  (seconds)
            n_pts   = int(float(parts[2]))  # RecordLength

            t0 = x_start
            if n_pts > 1:
                dt = (x_stop - x_start) / (n_pts - 1)
        except (ValueError, ZeroDivisionError):
            # Header format unexpected — fall back to time-range estimate
            print("Warning: could not parse scope header, using fallback dt.")

    t = t0 + np.arange(len(y)) * dt
    return t, y


# FIX 4: Use cross-correlation to find the true time lag between expected
# and measured signals before comparing. np.interp on misaligned axes
# produces a meaningless RMSE/correlation.
def align_and_compare(t_exp, y_exp, t_meas, y_meas):
    """
    1. Interpolate measured signal onto the expected time grid.
    2. Use cross-correlation to find and correct the sample lag.
    3. Compute gain, RMSE, and Pearson correlation on aligned signals.
    """
    # Step 1: interpolate measured onto expected time grid
    y_meas_i = np.interp(t_exp, t_meas, y_meas,
                         left=y_meas[0], right=y_meas[-1])

    # Step 2: zero-mean both signals
    e = y_exp  - np.mean(y_exp)
    m = y_meas_i - np.mean(y_meas_i)

    # Step 3: cross-correlate to find lag
    corr_full = np.correlate(e, m, mode="full")
    lag = corr_full.argmax() - (len(e) - 1)   # samples

    # Step 4: shift measured signal to align with expected
    if lag > 0:
        m_aligned = np.concatenate([np.zeros(lag), m[:-lag]]) if lag < len(m) else m
    elif lag < 0:
        m_aligned = np.concatenate([m[-lag:], np.zeros(-lag)])
    else:
        m_aligned = m

    # Step 5: least-squares amplitude scale
    denom = np.dot(m_aligned, m_aligned)
    gain = np.dot(e, m_aligned) / denom if denom > 1e-15 else 1.0
    m_scaled = gain * m_aligned

    rmse = np.sqrt(np.mean((e - m_scaled) ** 2))
    corr = np.corrcoef(e, m_scaled)[0, 1]

    lag_us = lag / (t_exp[1] - t_exp[0]) * 1e6 if len(t_exp) > 1 else 0.0
    print(f"Cross-correlation lag: {lag} samples ({lag_us:.3f} us)")

    return e, m_scaled, gain, rmse, corr


def main():
    awg = None
    rm = None
    scope = None
    try:
        # AWG
        awg = AWGGaussianPulse(
            device="/dev/spcm0", channel=0, samplerate=1_250_000_000
        )
        awg.update_pulse(
            width_us=WIDTH_US,
            amplitude_mV=AMPLITUDE_MV,
            rep_period_us=REP_PERIOD_US,
            n_sigma=N_SIGMA,
        )
        awg.start()

        # Expected waveform (normalized shape)
        y_expected = awg.last_wave_i16.astype(np.float64)
        y_expected = y_expected / np.max(np.abs(y_expected))
        t_expected = awg.last_t_s

        # Scope
        rm = pyvisa.ResourceManager()
        scope = rm.open_resource(SCOPE_RESOURCE)
        scope.timeout = SCOPE_TIMEOUT_MS
        print("Scope ID:", scope.query("*IDN?").strip())

        setup_scope(scope, ch=SCOPE_CHANNEL)
        t_meas, y_meas = acquire_scope(scope, ch=SCOPE_CHANNEL)

        # Align & compare
        e, m, gain, rmse, corr = align_and_compare(
            t_expected, y_expected, t_meas, y_meas
        )
        print(f"gain={gain:.6f}, rmse={rmse:.6e}, corr={corr:.6f}")

        # Plot
        fig, axes = plt.subplots(2, 1, figsize=(10, 8))

        axes[0].plot(t_expected * 1e6, e, label="Expected Gaussian (norm)")
        axes[0].plot(t_expected * 1e6, m, label="Actual from scope (aligned)", alpha=0.9)
        axes[0].set_xlabel("Time (µs)")
        axes[0].set_ylabel("Amplitude (a.u.)")
        axes[0].set_title("Expected vs Actual Gaussian Pulse")
        axes[0].grid(True, alpha=0.3)
        axes[0].legend()

        # Residual subplot — makes deviations immediately visible
        axes[1].plot(t_expected * 1e6, e - m, color="red", label="Residual (expected − actual)")
        axes[1].axhline(0, color="black", linewidth=0.8, linestyle="--")
        axes[1].set_xlabel("Time (µs)")
        axes[1].set_ylabel("Residual (a.u.)")
        axes[1].set_title(f"Residual  |  RMSE={rmse:.4e}  corr={corr:.6f}  gain={gain:.4f}")
        axes[1].grid(True, alpha=0.3)
        axes[1].legend()

        plt.tight_layout()
        plt.show()

        input("Press Enter to stop output and exit...")

    finally:
        if scope is not None:
            try:
                scope.close()
            except Exception:
                pass
        if rm is not None:
            try:
                rm.close()
            except Exception:
                pass
        if awg is not None:
            awg.close()


if __name__ == "__main__":
    main()