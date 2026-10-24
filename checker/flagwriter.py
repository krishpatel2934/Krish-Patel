"""
Write the final flags.csv in the format required by the assignment.

Columns:
    station_id, channel, start_utc, end_utc, issue, action, note
"""

import csv


COLUMNS = [
    "station_id",
    "channel",
    "start_utc",
    "end_utc",
    "issue",
    "action",
    "note",
]


def write_flags(flags, output_path):
    """
    Sort the flags by station then start time, deduplicate exact
    duplicates and same-interval overlapping issue types, and write to CSV.
    """
    # Sort: station first, then chronologically
    flags.sort(key=lambda f: (f["station_id"], f["start_utc"], f["channel"]))

    # Deduplicate: drop a "spike" flag if an "out of range" flag for the same
    # station / channel / timestamp already exists (range check is more specific).
    seen_range = set()
    for f in flags:
        if f["issue"].startswith("out of range"):
            seen_range.add((f["station_id"], f["channel"], f["start_utc"]))

    unique = []
    seen_key = set()
    for f in flags:
        # Drop spike if range check already covers this point
        if (f["issue"].startswith("spike")
                and (f["station_id"], f["channel"], f["start_utc"]) in seen_range):
            continue
        key = (f["station_id"], f["channel"],
               f["start_utc"], f["end_utc"], f["issue"])
        if key not in seen_key:
            seen_key.add(key)
            unique.append(f)

    with open(output_path, "w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=COLUMNS, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(unique)
