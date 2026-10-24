"""
Timestamp-quality checks: gaps, backward jumps, and duplicate blocks.

These are independent of the weather values — they only look at the
timestamp_utc column to make sure the 10-minute time series is complete
and monotonically increasing.
"""

import pandas as pd


# How long a gap must be before we flag it (in minutes).
GAP_THRESHOLD_MIN = 15  # anything > 1 interval (10 min)


def check_temporal(pack):
    """Flag timestamp gaps, backward jumps, and duplicate blocks."""
    flags = []

    for sid, df in pack["data"].items():
        ts = df["timestamp_utc"]

        # ── 1. backward jumps / duplicate blocks ────────────────────────
        diffs = ts.diff()
        backward = diffs < pd.Timedelta(0)
        for idx in df.index[backward]:
            prev_ts = ts.iloc[idx - 1] if idx > 0 else None
            cur_ts = ts.iloc[idx]
            if prev_ts is not None:
                # Find how far the duplicated block extends
                dup_end = _find_duplicate_end(ts, idx)
                flags.append({
                    "station_id": sid,
                    "channel": "all",
                    "start_utc": _fmt(cur_ts),
                    "end_utc": _fmt(ts.iloc[dup_end]),
                    "issue": "duplicate / out-of-order block",
                    "action": "exclude",
                    "note": (
                        f"Timestamps jump backward from "
                        f"{_fmt(prev_ts)} to {_fmt(cur_ts)}; "
                        f"rows {idx}–{dup_end} appear to be duplicates"
                    ),
                })

        # ── 2. gaps (missing intervals) ─────────────────────────────────
        expected = pd.Timedelta(minutes=10)
        gap_mask = diffs > pd.Timedelta(minutes=GAP_THRESHOLD_MIN)
        for idx in df.index[gap_mask]:
            if idx == 0:
                continue
            gap_start = ts.iloc[idx - 1]
            gap_end = ts.iloc[idx]
            gap_len = gap_end - gap_start
            missing_n = int(gap_len / expected) - 1
            flags.append({
                "station_id": sid,
                "channel": "all",
                "start_utc": _fmt(gap_start),
                "end_utc": _fmt(gap_end),
                "issue": f"data gap ({_human_duration(gap_len)})",
                "action": "exclude",
                "note": (
                    f"No data for {_human_duration(gap_len)} "
                    f"({missing_n} missing interval(s))"
                ),
            })

    return flags


# ── helpers ─────────────────────────────────────────────────────────────────

def _fmt(ts):
    return ts.strftime("%Y-%m-%d %H:%M")


def _find_duplicate_end(ts_series, start_idx):
    """Return the last index of the duplicate/out-of-order block."""
    # The block ends when timestamps catch up to the point before the jump
    ceiling = ts_series.iloc[start_idx - 1]
    for i in range(start_idx, len(ts_series)):
        if ts_series.iloc[i] > ceiling:
            return i - 1
    return len(ts_series) - 1


def _human_duration(td):
    """Format a timedelta as a readable string like '1d 11h 50m'."""
    total_min = int(td.total_seconds() // 60)
    days, remainder = divmod(total_min, 1440)
    hours, mins = divmod(remainder, 60)
    parts = []
    if days:
        parts.append(f"{days}d")
    if hours:
        parts.append(f"{hours}h")
    if mins:
        parts.append(f"{mins}m")
    return " ".join(parts) or "0m"
