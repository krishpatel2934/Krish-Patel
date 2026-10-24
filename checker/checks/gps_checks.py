"""
GPS-based checks: clock-offset detection and coordinate validation.

Compares the logger's own timestamp against the GPS-derived UTC time
(from $GPRMC sentences) to find clock drift or jumps.  Also compares
GPS-derived lat/lon against the install-sheet values in stations.csv.
"""

import math
from datetime import timedelta


# If logger-vs-GPS offset exceeds this, we flag it.
CLOCK_OFFSET_THRESHOLD_SEC = 300  # 5 minutes

# If GPS position is more than this far from install sheet, flag it.
POSITION_THRESHOLD_M = 1000  # 1 km


def check_gps(pack):
    """Flag clock offsets and position mismatches."""
    flags = []
    flags.extend(_check_clock_offset(pack))
    flags.extend(_check_position(pack))
    return flags


# ── clock offset ────────────────────────────────────────────────────────────

def _check_clock_offset(pack):
    flags = []

    for sid, records in pack["gps"].items():
        # Collect (logger_ts, gps_datetime, offset_seconds) for GPRMC fixes
        offsets = []
        for rec in records:
            if rec["type"] != "GPRMC":
                continue
            if rec.get("status") != "A":
                continue
            gps_dt = rec.get("gps_datetime")
            if gps_dt is None:
                continue

            diff = (rec["logger_ts"] - gps_dt).total_seconds()
            offsets.append((rec["logger_ts"], gps_dt, diff))

        if not offsets:
            continue

        # Walk through and find transitions where offset jumps
        baseline = offsets[0][2]  # initial offset (should be ~0)
        onset = None
        offset_value = None

        for logger_ts, gps_dt, diff in offsets:
            deviation = abs(diff - baseline)
            if deviation > CLOCK_OFFSET_THRESHOLD_SEC and onset is None:
                onset = logger_ts
                offset_value = diff
            elif deviation <= CLOCK_OFFSET_THRESHOLD_SEC and onset is not None:
                # Offset returned to normal — close this span
                flags.append(_make_clock_flag(
                    sid, onset, logger_ts, offset_value
                ))
                onset = None
                offset_value = None

        # If offset persists to the end of the file
        if onset is not None:
            last_logger_ts = offsets[-1][0]
            flags.append(_make_clock_flag(
                sid, onset, last_logger_ts, offset_value
            ))

    return flags


def _make_clock_flag(sid, onset, end, offset_sec):
    offset_h = offset_sec / 3600
    direction = "behind" if offset_sec < 0 else "ahead of"
    correction = f"{'add' if offset_sec < 0 else 'subtract'} {abs(offset_h):.0f}h"
    return {
        "station_id": sid,
        "channel": "all",
        "start_utc": _fmt(onset),
        "end_utc": _fmt(end),
        "issue": f"clock offset {offset_h:+.0f}h vs GPS",
        "action": "correct",
        "note": (
            f"Logger clock is {abs(offset_h):.0f}h {direction} GPS UTC "
            f"from {_fmt(onset)} onward; {correction} to all timestamps "
            f"in this range"
        ),
    }


# ── position validation ────────────────────────────────────────────────────

def _check_position(pack):
    flags = []
    stations_df = pack["stations"]

    for sid, records in pack["gps"].items():
        # Collect GPS-derived positions
        lats, lons = [], []
        for rec in records:
            if "lat" in rec and "lon" in rec:
                lats.append(rec["lat"])
                lons.append(rec["lon"])

        if not lats:
            continue

        gps_lat = _median(lats)
        gps_lon = _median(lons)

        # Look up install-sheet position
        row = stations_df.loc[stations_df["station_id"] == sid]
        if row.empty:
            continue
        sheet_lat = float(row.iloc[0]["lat"])
        sheet_lon = float(row.iloc[0]["lon"])

        dist_m = _haversine(gps_lat, gps_lon, sheet_lat, sheet_lon)

        if dist_m > POSITION_THRESHOLD_M:
            flags.append({
                "station_id": sid,
                "channel": "metadata",
                "start_utc": _fmt(records[0]["logger_ts"]),
                "end_utc": _fmt(records[-1]["logger_ts"]),
                "issue": f"GPS position {dist_m:.0f}m from install sheet",
                "action": "keep",
                "note": (
                    f"Median GPS position ({gps_lat:.4f}, {gps_lon:.4f}) "
                    f"is {dist_m:.0f}m from stations.csv "
                    f"({sheet_lat:.4f}, {sheet_lon:.4f}); "
                    f"verify install-sheet coordinates"
                ),
            })

    return flags


# ── helpers ─────────────────────────────────────────────────────────────────

def _fmt(ts):
    return ts.strftime("%Y-%m-%d %H:%M")


def _median(values):
    s = sorted(values)
    n = len(s)
    if n % 2 == 1:
        return s[n // 2]
    return (s[n // 2 - 1] + s[n // 2]) / 2


def _haversine(lat1, lon1, lat2, lon2):
    """Distance in metres between two points (decimal degrees)."""
    R = 6_371_000  # Earth radius in metres
    rlat1, rlat2 = math.radians(lat1), math.radians(lat2)
    dlat = math.radians(lat2 - lat1)
    dlon = math.radians(lon2 - lon1)
    a = (math.sin(dlat / 2) ** 2
         + math.cos(rlat1) * math.cos(rlat2) * math.sin(dlon / 2) ** 2)
    return R * 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))
