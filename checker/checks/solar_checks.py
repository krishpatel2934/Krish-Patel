"""
Solar / GHI plausibility checks.

Uses a simple astronomical model (no external dependencies) to compute
approximate sunrise and sunset for each station on each day, then
flags GHI readings that are inconsistent with expected daylight:
  • GHI well above zero during the expected night  → possible clock issue
  • GHI stuck at zero during a bright midday window → possible obstruction
"""

import math
from datetime import timedelta

import numpy as np
import pandas as pd


# A small buffer so we don't flag twilight readings (minutes).
TWILIGHT_BUFFER_MIN = 40

# GHI above this during expected nighttime triggers a flag.
NIGHT_GHI_THRESHOLD = 20  # W/m²

# Minimum consecutive midday intervals of GHI=0 to flag obstruction.
MIDDAY_ZERO_MIN_INTERVALS = 12  # 2 hours of zero at midday is suspicious


def check_solar(pack):
    """Flag GHI readings inconsistent with expected daylight."""
    flags = []
    stations = pack["stations"]

    for sid, df in pack["data"].items():
        row = stations.loc[stations["station_id"] == sid]
        if row.empty:
            continue
        lat = float(row.iloc[0]["lat"])
        lon = float(row.iloc[0]["lon"])

        flags.extend(_check_nighttime_ghi(sid, df, lat, lon))
        flags.extend(_check_midday_zero(sid, df, lat, lon))

    return flags


# ── nighttime GHI ──────────────────────────────────────────────────────────

def _check_nighttime_ghi(sid, df, lat, lon):
    """Flag intervals where GHI > threshold during expected night."""
    flags = []
    ts = df["timestamp_utc"]
    ghi = df["ghi_wm2"]

    night_violations = []
    for i in range(len(df)):
        t = ts.iloc[i]
        g = ghi.iloc[i]
        if g <= NIGHT_GHI_THRESHOLD:
            continue

        doy = t.timetuple().tm_yday
        sunrise_utc, sunset_utc = _sunrise_sunset_utc(doy, lat, lon)
        hour_frac = t.hour + t.minute / 60.0

        # Sunset may wrap past midnight UTC, so handle both sides
        is_night = False
        buf = TWILIGHT_BUFFER_MIN / 60.0
        if sunset_utc < 24:
            if hour_frac < (sunrise_utc - buf) or hour_frac > (sunset_utc + buf):
                is_night = True
        else:
            # Sunset wraps past midnight — e.g. sunset at 25.5 → 01:30 UTC
            sunset_wrapped = sunset_utc - 24
            if (sunset_wrapped + buf) < hour_frac < (sunrise_utc - buf):
                is_night = True

        if is_night:
            night_violations.append(i)

    # Group consecutive violations into spans
    if night_violations:
        spans = _group_consecutive(night_violations)
        for start_i, end_i in spans:
            flags.append({
                "station_id": sid,
                "channel": "ghi_wm2",
                "start_utc": _fmt(ts.iloc[start_i]),
                "end_utc": _fmt(ts.iloc[end_i]),
                "issue": "GHI > 0 during expected night",
                "action": "keep",
                "note": (
                    f"GHI readings during expected nighttime; may indicate "
                    f"clock error or unusual atmospheric conditions"
                ),
            })

    return flags


# ── midday zero GHI ─────────────────────────────────────────────────────────

def _check_midday_zero(sid, df, lat, lon):
    """Flag sustained GHI=0 during the brightest part of the day."""
    flags = []
    ts = df["timestamp_utc"]
    ghi = df["ghi_wm2"]

    midday_zeros = []
    for i in range(len(df)):
        t = ts.iloc[i]
        g = ghi.iloc[i]

        doy = t.timetuple().tm_yday
        sunrise_utc, sunset_utc = _sunrise_sunset_utc(doy, lat, lon)
        solar_noon = (sunrise_utc + sunset_utc) / 2

        hour_frac = t.hour + t.minute / 60.0
        # "Midday window" = solar noon ± 2 hours
        if abs(hour_frac - solar_noon) < 2.0 and g == 0:
            midday_zeros.append(i)

    # Group and filter short spans (clouds can cause brief zero readings)
    if midday_zeros:
        spans = _group_consecutive(midday_zeros)
        for start_i, end_i in spans:
            span_len = end_i - start_i + 1
            if span_len >= MIDDAY_ZERO_MIN_INTERVALS:
                flags.append({
                    "station_id": sid,
                    "channel": "ghi_wm2",
                    "start_utc": _fmt(ts.iloc[start_i]),
                    "end_utc": _fmt(ts.iloc[end_i]),
                    "issue": f"GHI=0 for {span_len} intervals at midday",
                    "action": "keep",
                    "note": (
                        f"Sensor reads zero for {span_len * 10} min around "
                        f"solar noon; possible obstruction or heavy overcast"
                    ),
                })

    return flags


# ── solar position model (no external deps) ────────────────────────────────

def _sunrise_sunset_utc(day_of_year, lat_deg, lon_deg):
    """
    Return (sunrise_utc, sunset_utc) in fractional hours.

    Uses the standard simplified solar-position equations:
      - solar declination from day of year
      - hour angle from latitude and declination
      - equation of time for UTC conversion
    """
    # Solar declination (degrees)
    decl = 23.45 * math.sin(math.radians(360.0 / 365.0 * (day_of_year - 81)))
    decl_rad = math.radians(decl)
    lat_rad = math.radians(lat_deg)

    # Hour angle at sunrise/sunset
    cos_ha = -math.tan(lat_rad) * math.tan(decl_rad)
    cos_ha = max(-1.0, min(1.0, cos_ha))  # clamp for polar regions
    ha_deg = math.degrees(math.acos(cos_ha))
    half_day_h = ha_deg / 15.0

    # Equation of time (minutes) — Spencer formula approximation
    B = math.radians(360.0 / 365.0 * (day_of_year - 81))
    eot = (9.87 * math.sin(2 * B)
           - 7.53 * math.cos(B)
           - 1.5 * math.sin(B))

    # Solar noon in UTC (hours)
    solar_noon_utc = 12.0 - eot / 60.0 - lon_deg / 15.0

    sunrise = solar_noon_utc - half_day_h
    sunset = solar_noon_utc + half_day_h
    return sunrise, sunset


# ── helpers ─────────────────────────────────────────────────────────────────

def _fmt(ts):
    return ts.strftime("%Y-%m-%d %H:%M")


def _group_consecutive(indices, max_gap=2):
    """Group a sorted list of integer indices into (start, end) spans."""
    spans = []
    start = indices[0]
    prev = indices[0]
    for idx in indices[1:]:
        if idx - prev > max_gap:
            spans.append((start, prev))
            start = idx
        prev = idx
    spans.append((start, prev))
    return spans
