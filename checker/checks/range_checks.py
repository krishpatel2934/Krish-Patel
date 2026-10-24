"""
Physical-range validation for every weather channel.

Catches values that are impossible given the sensor specs or basic physics
(e.g. temperature = 85 °C, negative wind speed, RH > 100 %).
"""

import numpy as np

# ── thresholds ──────────────────────────────────────────────────────────────
# Conservative limits — anything outside these is almost certainly wrong.
LIMITS = {
    "temp_c":       (-45.0, 55.0),
    "rh_pct":       (0.0, 105.0),     # allow slight over-read before flagging
    "pressure_hpa": (500.0, 1100.0),  # covers all terrestrial elevations
    "wind_kmh":     (0.0, 200.0),
    "wind_dir_deg": (0.0, 360.0),
    "rain_mm":      (0.0, 100.0),     # >100 mm in 10 min is extraordinary
    "ghi_wm2":      (-5, 1500),       # small negative from sensor offset OK
}


def check_ranges(pack):
    """Flag individual readings outside physically plausible limits."""
    flags = []

    for sid, df in pack["data"].items():
        for col, (lo, hi) in LIMITS.items():
            if col not in df.columns:
                continue

            mask = (df[col] < lo) | (df[col] > hi)
            bad = df.loc[mask]
            if bad.empty:
                continue

            # Group consecutive bad rows into spans
            for start_idx, end_idx, sample in _consecutive_spans(bad, df, col):
                start_ts = df.loc[start_idx, "timestamp_utc"]
                end_ts = df.loc[end_idx, "timestamp_utc"]
                flags.append({
                    "station_id": sid,
                    "channel": col,
                    "start_utc": _fmt(start_ts),
                    "end_utc": _fmt(end_ts),
                    "issue": f"out of range ({sample})",
                    "action": "exclude",
                    "note": (
                        f"Value {sample} outside plausible range "
                        f"[{lo}, {hi}]; likely sensor error"
                    ),
                })

    return flags


# ── helpers ─────────────────────────────────────────────────────────────────

def _fmt(ts):
    """Format a Timestamp to YYYY-MM-DD HH:MM."""
    return ts.strftime("%Y-%m-%d %H:%M")


def _consecutive_spans(bad_df, full_df, col_name):
    """
    Yield (start_index, end_index, sample_value) for each block of
    consecutive rows that appear in *bad_df* (a subset of *full_df*).
    """
    indices = bad_df.index.tolist()
    if not indices:
        return

    start = indices[0]
    prev = indices[0]
    for idx in indices[1:]:
        if idx != prev + 1:
            yield start, prev, full_df.loc[start, col_name]
            start = idx
        prev = idx
    yield start, prev, full_df.loc[start, col_name]
