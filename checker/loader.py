"""
Load all components of a data pack: station metadata, weather CSVs,
GPS NMEA files, and the volunteer maintenance log.
"""

import os
import glob
import re
from datetime import datetime

import pandas as pd


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def load_data_pack(data_dir):
    """
    Load every file in a Ridgeline-format data pack.

    Returns a dict with keys:
        'stations'    – DataFrame from stations.csv
        'data'        – dict {station_id: DataFrame} from data/Sxx.csv
        'gps'         – dict {station_id: list[dict]} from gps/Sxx.nmea
        'maintenance' – list[dict] from maintenance_log.md
    """
    pack = {}

    # ---- station metadata ----
    stations_path = os.path.join(data_dir, "stations.csv")
    pack["stations"] = pd.read_csv(stations_path)

    # ---- weather data ----
    data_subdir = os.path.join(data_dir, "data")
    pack["data"] = {}
    for fpath in sorted(glob.glob(os.path.join(data_subdir, "S*.csv"))):
        sid = os.path.splitext(os.path.basename(fpath))[0]
        df = pd.read_csv(fpath)
        df["timestamp_utc"] = pd.to_datetime(df["timestamp_utc"],
                                              format="%Y-%m-%d %H:%M")
        pack["data"][sid] = df

    # ---- GPS NMEA ----
    gps_subdir = os.path.join(data_dir, "gps")
    pack["gps"] = {}
    for fpath in sorted(glob.glob(os.path.join(gps_subdir, "S*.nmea"))):
        sid = os.path.splitext(os.path.basename(fpath))[0]
        pack["gps"][sid] = _parse_nmea_file(fpath)

    # ---- maintenance log ----
    log_path = os.path.join(data_dir, "maintenance_log.md")
    if os.path.exists(log_path):
        pack["maintenance"] = _parse_maintenance_log(log_path)
    else:
        pack["maintenance"] = []

    return pack


# ---------------------------------------------------------------------------
# NMEA parser
# ---------------------------------------------------------------------------

def _nmea_coord_to_decimal(coord_str, direction):
    """Convert NMEA lat (DDMM.MMMM) or lon (DDDMM.MMMM) to decimal degrees."""
    if direction in ("N", "S"):
        degrees = int(coord_str[:2])
        minutes = float(coord_str[2:])
    else:  # E / W
        degrees = int(coord_str[:3])
        minutes = float(coord_str[3:])
    decimal = degrees + minutes / 60.0
    if direction in ("S", "W"):
        decimal = -decimal
    return decimal


def _parse_nmea_file(filepath):
    """
    Parse a logger-timestamped NMEA file.

    Each line: ``logger_timestamp,$GPxxx,field,field,...*checksum``

    Returns a list of dicts, one per sentence, with parsed fields.
    """
    records = []
    with open(filepath, "r", encoding="utf-8", errors="replace") as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            parts = line.split(",")
            if len(parts) < 3:
                continue

            logger_ts_str = parts[0]
            sentence_type = parts[1]

            try:
                logger_ts = datetime.strptime(logger_ts_str,
                                              "%Y-%m-%d %H:%M:%S")
            except ValueError:
                continue

            rec = {
                "logger_ts": logger_ts,
                "type": sentence_type.replace("$", ""),
            }

            # --- $GPRMC ---
            if sentence_type == "$GPRMC" and len(parts) >= 11:
                rec["status"] = parts[3]
                try:
                    gps_time = parts[2]
                    date_field = parts[10]
                    if gps_time and date_field and rec["status"] == "A":
                        hh = int(gps_time[:2])
                        mm = int(gps_time[2:4])
                        ss = int(float(gps_time[4:]))
                        dd = int(date_field[:2])
                        mo = int(date_field[2:4])
                        yr = 2000 + int(date_field[4:6])
                        rec["gps_datetime"] = datetime(yr, mo, dd, hh, mm, ss)
                    if parts[4] and parts[6]:
                        rec["lat"] = _nmea_coord_to_decimal(parts[4], parts[5])
                        rec["lon"] = _nmea_coord_to_decimal(parts[6], parts[7])
                except (ValueError, IndexError):
                    pass

            # --- $GPGGA ---
            elif sentence_type == "$GPGGA" and len(parts) >= 11:
                try:
                    if parts[3] and parts[5]:
                        rec["lat"] = _nmea_coord_to_decimal(parts[3], parts[4])
                        rec["lon"] = _nmea_coord_to_decimal(parts[5], parts[6])
                    if parts[10]:
                        rec["altitude"] = float(parts[10])
                    if parts[8]:
                        rec["num_sats"] = int(parts[8])
                except (ValueError, IndexError):
                    pass

            records.append(rec)
    return records


# ---------------------------------------------------------------------------
# Maintenance-log parser
# ---------------------------------------------------------------------------

_LOG_RE = re.compile(
    r"^(\d{4}-\d{2}-\d{2})\s+(S\d+)\s+(.+)$"
)


def _parse_maintenance_log(filepath):
    """
    Parse the volunteer maintenance log (markdown list of notes).

    Returns a list of dicts with keys: date, station_id, note.
    """
    entries = []
    with open(filepath, "r", encoding="utf-8") as fh:
        for line in fh:
            m = _LOG_RE.match(line.strip())
            if m:
                entries.append({
                    "date": m.group(1),
                    "station_id": m.group(2),
                    "note": m.group(3),
                })
    return entries
