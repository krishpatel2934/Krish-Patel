"""
Cross-station comparisons to detect problems invisible within a single
station's time series.

1. Pressure-offset detection  – a sensor swap can introduce a constant bias
   that is only visible when compared to neighbours.
2. Rain-gauge blockage        – a clogged funnel reads zero while the network
   sees rain; cleaning may dump accumulated water.
3. Wind-sensor calibration    – a replacement anemometer with a different
   calibration factor shifts the mean permanently.
"""

import numpy as np
import pandas as pd


# ── thresholds ──────────────────────────────────────────────────────────────

PRESSURE_SHIFT_HPA = 5.0   # minimum step to flag (conservative: only clear offsets)
RAIN_DRY_DAYS = 2           # consecutive dry days while network is wet
RAIN_NETWORK_MIN_MM = 5.0   # network median must exceed this to count as wet
RAIN_DUMP_FACTOR = 5.0      # single-day total > factor × network max → dump
WIND_RATIO_DROP = 0.45      # flag if station/network ratio drops below this
WIND_SUSTAINED_DAYS = 7     # ratio must stay low for this many days


def check_cross_station(pack):
    """Run all cross-station comparisons."""
    flags = []
    if len(pack["data"]) < 3:
        return flags  # need enough stations for a meaningful comparison

    flags.extend(_check_pressure_offset(pack))
    flags.extend(_check_rain_blockage(pack))
    flags.extend(_check_wind_calibration(pack))
    return flags


# ── 1. pressure offset ─────────────────────────────────────────────────────

def _check_pressure_offset(pack):
    flags = []
    stations_df = pack["stations"]

    # Reduce each station's pressure to sea-level equivalent using the
    # international barometric formula, so all stations can be compared on
    # the same scale regardless of elevation.
    def to_sl(p_series, elevation_m):
        """P_sl = P_station / (1 - 2.25577e-5 * elev)^5.25588"""
        factor = (1.0 - 2.25577e-5 * elevation_m) ** 5.25588
        return p_series / factor

    daily_sl = {}
    for sid, df in pack["data"].items():
        row = stations_df.loc[stations_df["station_id"] == sid]
        if row.empty:
            continue
        elev = float(row.iloc[0]["elevation_m"])
        s = df.set_index("timestamp_utc")["pressure_hpa"].resample("D").mean()
        daily_sl[sid] = to_sl(s, elev)

    p_df = pd.DataFrame(daily_sl).dropna(how="all")

    for sid in p_df.columns:
        others = [c for c in p_df.columns if c != sid]
        if len(others) < 2:
            continue
        # Use median of other stations to be robust against one bad actor
        ref = p_df[others].median(axis=1)
        residual = (p_df[sid] - ref).dropna()
        if len(residual) < 14:
            continue

        # Sliding-window step detection
        w = 7
        best_jump = 0.0
        best_idx = None
        for i in range(w, len(residual) - w):
            before = residual.iloc[i - w : i].median()
            after  = residual.iloc[i : i + w].median()
            jump   = after - before
            if abs(jump) > abs(best_jump):
                best_jump = jump
                best_idx  = i

        if abs(best_jump) < PRESSURE_SHIFT_HPA or best_idx is None:
            continue

        # Extra sanity check: the shift must persist in the majority of
        # the remaining data (not just one week).  This filters out natural
        # synoptic pressure excursions.
        onset_pos = best_idx
        n_after   = len(residual) - onset_pos
        if n_after < 7:
            continue
        before_med = residual.iloc[:onset_pos].median()
        after_med  = residual.iloc[onset_pos:].median()
        persistent_jump = after_med - before_med
        if abs(persistent_jump) < PRESSURE_SHIFT_HPA:
            continue

        onset = residual.index[onset_pos]
        end   = residual.index[-1]
        flags.append({
            "station_id": sid,
            "channel": "pressure_hpa",
            "start_utc": _fmt_date(onset),
            "end_utc":   _fmt_date(end),
            "issue":     f"pressure offset {persistent_jump:+.1f} hPa",
            "action":    "correct",
            "note": (
                f"Sea-level-normalised pressure residual (station minus "
                f"network median) shifts by {persistent_jump:+.1f} hPa "
                f"around {onset.strftime('%Y-%m-%d')} and remains shifted; "
                f"apply {-persistent_jump:+.1f} hPa correction from this date"
            ),
        })

    return flags


# ── 2. rain-gauge blockage ──────────────────────────────────────────────────

def _check_rain_blockage(pack):
    flags = []

    # Daily rain totals
    daily = {}
    for sid, df in pack["data"].items():
        s = df.set_index("timestamp_utc")["rain_mm"].resample("D").sum()
        daily[sid] = s
    r_df = pd.DataFrame(daily).dropna(how="all").fillna(0)

    for sid in r_df.columns:
        others = [c for c in r_df.columns if c != sid]
        if not others:
            continue
        network_med = r_df[others].median(axis=1)

        # Count consecutive "dry while network wet" days
        dry_while_wet = (r_df[sid] == 0) & (network_med >= RAIN_NETWORK_MIN_MM)
        run_start = None
        run_len = 0

        for i, (date, is_bad) in enumerate(dry_while_wet.items()):
            if is_bad:
                if run_start is None:
                    run_start = date
                run_len += 1
            else:
                if run_len >= RAIN_DRY_DAYS:
                    flags.append({
                        "station_id": sid,
                        "channel": "rain_mm",
                        "start_utc": _fmt_date(run_start),
                        "end_utc": _fmt_date(date - pd.Timedelta(days=1)),
                        "issue": f"rain gauge reads 0 for {run_len}d while network wet",
                        "action": "exclude",
                        "note": (
                            f"Station reports zero rain for {run_len} "
                            f"consecutive day(s) while network median "
                            f">{RAIN_NETWORK_MIN_MM} mm; likely blocked funnel"
                        ),
                    })
                run_start = None
                run_len = 0

        # Close any remaining run
        if run_len >= RAIN_DRY_DAYS and run_start is not None:
            flags.append({
                "station_id": sid,
                "channel": "rain_mm",
                "start_utc": _fmt_date(run_start),
                "end_utc": _fmt_date(dry_while_wet.index[-1]),
                "issue": f"rain gauge reads 0 for {run_len}d while network wet",
                "action": "exclude",
                "note": (
                    f"Station reports zero rain for {run_len} consecutive "
                    f"day(s) while network median >{RAIN_NETWORK_MIN_MM} mm; "
                    f"likely blocked funnel"
                ),
            })

        # Rain dump detection: single day much higher than everyone else
        for date in r_df.index:
            station_rain = r_df.loc[date, sid]
            net_max = r_df.loc[date, others].max()
            if (station_rain > 10
                    and net_max > 0
                    and station_rain > RAIN_DUMP_FACTOR * net_max):
                flags.append({
                    "station_id": sid,
                    "channel": "rain_mm",
                    "start_utc": _fmt_date(date),
                    "end_utc": _fmt_date(date),
                    "issue": f"rain dump ({station_rain:.1f} mm in 1 day)",
                    "action": "exclude",
                    "note": (
                        f"Daily total {station_rain:.1f} mm is "
                        f"{station_rain / net_max:.0f}× the network max "
                        f"({net_max:.1f} mm); likely accumulated water "
                        f"released when gauge was cleaned"
                    ),
                })

    return flags


# ── 3. wind-sensor calibration ──────────────────────────────────────────────

def _check_wind_calibration(pack):
    flags = []

    # Daily mean wind
    daily = {}
    for sid, df in pack["data"].items():
        s = df.set_index("timestamp_utc")["wind_kmh"].resample("D").mean()
        daily[sid] = s
    w_df = pd.DataFrame(daily).dropna(how="all")

    for sid in w_df.columns:
        others = [c for c in w_df.columns if c != sid]
        if len(others) < 2:
            continue
        network_med = w_df[others].median(axis=1)
        # Avoid division by zero on calm days
        safe_net = network_med.clip(lower=0.5)
        ratio = w_df[sid] / safe_net

        # Look for a sustained drop in ratio
        ratio_smooth = ratio.rolling(5, min_periods=3, center=True).median()

        # Compute baseline ratio from the first third of the record
        n = len(ratio_smooth.dropna())
        if n < 14:
            continue
        clean = ratio_smooth.dropna()
        baseline = clean.iloc[: n // 3].median()

        if baseline < 0.3:
            continue  # station is naturally much calmer; skip

        # Find onset of ratio collapse
        onset = None
        sustained = 0
        for date, r in clean.items():
            if r < baseline * WIND_RATIO_DROP:
                if onset is None:
                    onset = date
                sustained += 1
            else:
                if sustained >= WIND_SUSTAINED_DAYS:
                    break  # keep onset; the drop is confirmed
                onset = None
                sustained = 0

        if sustained >= WIND_SUSTAINED_DAYS and onset is not None:
            end_date = clean.index[-1]
            drop_pct = (1 - clean.iloc[-7:].median() / baseline) * 100
            flags.append({
                "station_id": sid,
                "channel": "wind_kmh",
                "start_utc": _fmt_date(onset),
                "end_utc": _fmt_date(end_date),
                "issue": f"wind speed drop ~{drop_pct:.0f}%",
                "action": "exclude",
                "note": (
                    f"Daily mean wind / network median ratio drops from "
                    f"{baseline:.2f} to {clean.iloc[-7:].median():.2f} "
                    f"around {onset.strftime('%Y-%m-%d')} and stays low; "
                    f"likely anemometer calibration issue after replacement"
                ),
            })

    return flags


# ── helper ──────────────────────────────────────────────────────────────────

def _fmt_date(dt):
    """Format a date or Timestamp as 'YYYY-MM-DD HH:MM'."""
    try:
        return dt.strftime("%Y-%m-%d %H:%M")
    except AttributeError:
        # It's a date, not a datetime
        return f"{dt} 00:00"
