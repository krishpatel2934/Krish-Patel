"""
Orchestrator: imports every check module and runs them all against the pack.
"""

from .range_checks import check_ranges
from .temporal_checks import check_temporal
from .gps_checks import check_gps
from .sensor_checks import check_sensors
from .cross_station import check_cross_station
from .solar_checks import check_solar


def run_all_checks(pack):
    """Run every category of check and return the combined flag list."""
    flags = []

    print("  [1/6] Range checks ...")
    flags.extend(check_ranges(pack))

    print("  [2/6] Temporal checks ...")
    flags.extend(check_temporal(pack))

    print("  [3/6] GPS checks ...")
    gps_flags = check_gps(pack)
    flags.extend(gps_flags)
    # Track which stations have confirmed clock offsets so solar checks
    # can suppress redundant per-day "GHI at night" noise for those stations.
    clock_offset_stations = {
        f["station_id"]
        for f in gps_flags
        if "clock offset" in f.get("issue", "")
    }

    print("  [4/6] Sensor checks ...")
    flags.extend(check_sensors(pack))

    print("  [5/6] Cross-station checks ...")
    flags.extend(check_cross_station(pack))

    print("  [6/6] Solar / GHI checks ...")
    solar_flags = check_solar(pack)
    # For stations with a confirmed clock offset, collapse all "GHI > 0 at
    # night" entries into a single summary flag instead of one per day.
    flags.extend(_collapse_solar_noise(solar_flags, clock_offset_stations))

    return flags


def _collapse_solar_noise(solar_flags, clock_offset_stations):
    """
    For clock-offset stations, replace many daily "GHI at night" entries
    with a single summary flag. Keep all other solar flags as-is.
    """
    out = []
    by_station = {}
    for f in solar_flags:
        sid = f["station_id"]
        if sid in clock_offset_stations and f["issue"] == "GHI > 0 during expected night":
            by_station.setdefault(sid, []).append(f)
        else:
            out.append(f)

    for sid, grp in by_station.items():
        out.append({
            "station_id": sid,
            "channel": "ghi_wm2",
            "start_utc": grp[0]["start_utc"],
            "end_utc": grp[-1]["end_utc"],
            "issue": f"GHI > 0 during expected night ({len(grp)} days)",
            "action": "correct",
            "note": (
                f"GHI appears during expected nighttime for {len(grp)} days; "
                f"consistent with the confirmed 6-hour clock offset — "
                f"correct timestamps before using GHI data"
            ),
        })
    return out
