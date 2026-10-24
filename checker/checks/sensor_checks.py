"""
Within-station sensor-health checks: stuck values and isolated spikes.

These look only at a single station's own time series to find patterns
that indicate sensor malfunction (not weather).
"""

import numpy as np
import pandas as pd


# ── configuration ───────────────────────────────────────────────────────────

# Minimum consecutive identical readings (at 10-min intervals) to flag.
STUCK_THRESHOLDS = {
    "rh_pct":       36,   # 6 hours — RH should fluctuate
    "temp_c":       36,   # 6 hours
    "pressure_hpa": 36,   # 6 hours — pressure always drifts
    "wind_kmh":     72,   # 12 hours — prolonged calm *can* happen
    "wind_dir_deg": 72,   # 12 hours
    "ghi_wm2":      None, # skip — long stretches of 0 at night are normal
    "rain_mm":      None, # skip — long dry spells are normal
}

# Spike detection: an isolated single-interval jump that returns to normal.
# Only applied to channels that have well-defined "normal" ranges and where
# a spike is unambiguous (e.g. 85 °C temp). GHI and wind are naturally
# spiky (gusts, clouds) so we skip them here.
SPIKE_MULT = 20.0  # flag only extreme outliers (e.g. 85 C vs 7 C, -40 vs 5)
SPIKE_WINDOW = 11  # rolling window size (must be odd)

# Channels to run spike detection on (omit ghi_wm2 and wind_kmh — too noisy)
SPIKE_CHANNELS = ["temp_c", "rh_pct", "pressure_hpa"]


def check_sensors(pack):
    """Flag stuck sensors and isolated spikes."""
    flags = []

    for sid, df in pack["data"].items():
        flags.extend(_check_stuck(sid, df))
        flags.extend(_check_near_stuck(sid, df))
        flags.extend(_check_spikes(sid, df))

    return flags


# ── stuck-sensor detection (exact value repeats) ───────────────────────────

def _check_stuck(sid, df):
    flags = []

    for col, min_run in STUCK_THRESHOLDS.items():
        if min_run is None or col not in df.columns:
            continue

        values = df[col].values
        timestamps = df["timestamp_utc"]
        n = len(values)

        run_start = 0
        for i in range(1, n + 1):
            # End of a run?
            if i == n or values[i] != values[run_start]:
                run_len = i - run_start
                if run_len >= min_run:
                    stuck_val = values[run_start]
                    flags.append({
                        "station_id": sid,
                        "channel": col,
                        "start_utc": _fmt(timestamps.iloc[run_start]),
                        "end_utc": _fmt(timestamps.iloc[i - 1]),
                        "issue": f"stuck at {stuck_val}",
                        "action": "exclude",
                        "note": (
                            f"{col} reads exactly {stuck_val} for "
                            f"{run_len} consecutive intervals "
                            f"({run_len * 10 / 60:.0f}h); "
                            f"likely sensor malfunction"
                        ),
                    })
                if i < n:
                    run_start = i

    return flags


# ── near-stuck / saturated sensor detection ─────────────────────────────────

# A sensor pegged at its physical ceiling or floor: values hover within
# a narrow band around a boundary for a long time.  Catches e.g. a humidity
# sensor stuck reading 100-105 % while actual conditions vary.
NEAR_STUCK_DEFS = {
    # channel: (boundary_lo, boundary_hi, min_intervals)
    "rh_pct": (98.0, 110.0, 36),  # RH stuck near/above 100% for 6+ hours
}


def _check_near_stuck(sid, df):
    flags = []

    for col, (bnd_lo, bnd_hi, min_run) in NEAR_STUCK_DEFS.items():
        if col not in df.columns:
            continue

        values = df[col].values
        timestamps = df["timestamp_utc"]
        n = len(values)

        run_start = None
        run_len = 0

        for i in range(n):
            if bnd_lo <= values[i] <= bnd_hi:
                if run_start is None:
                    run_start = i
                run_len += 1
            else:
                if run_len >= min_run:
                    sample_min = min(values[run_start:i])
                    sample_max = max(values[run_start:i])
                    flags.append({
                        "station_id": sid,
                        "channel": col,
                        "start_utc": _fmt(timestamps.iloc[run_start]),
                        "end_utc": _fmt(timestamps.iloc[i - 1]),
                        "issue": (
                            f"saturated sensor ({sample_min}-{sample_max})"
                        ),
                        "action": "exclude",
                        "note": (
                            f"{col} stuck in [{sample_min}, {sample_max}] "
                            f"for {run_len} intervals ({run_len * 10 / 60:.0f}h); "
                            f"sensor appears saturated"
                        ),
                    })
                run_start = None
                run_len = 0

        # Close any trailing run
        if run_len >= min_run and run_start is not None:
            sample_min = min(values[run_start:n])
            sample_max = max(values[run_start:n])
            flags.append({
                "station_id": sid,
                "channel": col,
                "start_utc": _fmt(timestamps.iloc[run_start]),
                "end_utc": _fmt(timestamps.iloc[n - 1]),
                "issue": f"saturated sensor ({sample_min}-{sample_max})",
                "action": "exclude",
                "note": (
                    f"{col} stuck in [{sample_min}, {sample_max}] "
                    f"for {run_len} intervals ({run_len * 10 / 60:.0f}h); "
                    f"sensor appears saturated"
                ),
            })

    return flags


# ── spike detection ─────────────────────────────────────────────────────────

def _check_spikes(sid, df):
    flags = []
    ts = df["timestamp_utc"]

    for col in SPIKE_CHANNELS:
        if col not in df.columns:
            continue

        values = df[col].astype(float)

        # Rolling median and MAD (Median Absolute Deviation)
        rolling_med = values.rolling(
            SPIKE_WINDOW, center=True, min_periods=3
        ).median()
        rolling_mad = (values - rolling_med).abs().rolling(
            SPIKE_WINDOW, center=True, min_periods=3
        ).median()
        # Avoid division by zero — set floor on MAD
        rolling_mad = rolling_mad.clip(lower=0.5)

        deviation = (values - rolling_med).abs() / rolling_mad

        for idx in deviation.index:
            if deviation.loc[idx] < SPIKE_MULT:
                continue
            # Confirm it is *isolated* (neighbours are normal)
            pos = df.index.get_loc(idx)
            if pos < 1 or pos >= len(df) - 1:
                continue
            prev_dev = deviation.iloc[pos - 1]
            next_dev = deviation.iloc[pos + 1]
            if prev_dev < SPIKE_MULT / 2 and next_dev < SPIKE_MULT / 2:
                val = values.iloc[pos]
                med = rolling_med.iloc[pos]
                flags.append({
                    "station_id": sid,
                    "channel": col,
                    "start_utc": _fmt(ts.iloc[pos]),
                    "end_utc": _fmt(ts.iloc[pos]),
                    "issue": f"spike ({val})",
                    "action": "exclude",
                    "note": (
                        f"Isolated spike: {col}={val} vs rolling median "
                        f"{med:.1f}; neighbours are normal"
                    ),
                })

    return flags


# ── helper ──────────────────────────────────────────────────────────────────

def _fmt(ts):
    return ts.strftime("%Y-%m-%d %H:%M")
