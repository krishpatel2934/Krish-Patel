# Krish Patel
# Email : krishpatel2934@gmail.com
# Video: [YouTube/Drive link — add before submission]
# Run: python -m checker <data_pack_folder>

## Ridgeline Schools Weather Network — Data Quality Checker

Automated checker for the Aeron AI Research Engineer Intern assignment.
Reads a weather station data pack and writes `flags.csv` listing every
data-quality issue found, with evidence and recommended actions.

---

## How to Run

```bash
# 1. Create and activate a virtual environment
python -m venv venv
venv\Scripts\activate          # Windows
# source venv/bin/activate     # macOS / Linux

# 2. Install dependencies
pip install -r requirements.txt

# 3. Run the checker (from the project root)
python -m checker <path-to-data-pack>

# Example (data pack is the current directory):
python -m checker .
```

Output: `flags.csv` written to the directory you ran the command from.

---

## What Each Check Does

| Module | What it detects |
|---|---|
| `range_checks.py` | Values outside physically plausible limits (e.g. 85 °C, negative wind) |
| `temporal_checks.py` | Gaps in the 10-minute sequence; backward/duplicate timestamp blocks |
| `gps_checks.py` | Logger clock offset vs GPS UTC; station position vs install sheet |
| `sensor_checks.py` | Stuck-value runs; near-saturated sensors; isolated spikes |
| `cross_station.py` | Pressure offset after uncalibrated swap; blocked rain gauge; anemometer calibration loss |
| `solar_checks.py` | GHI > 0 during expected night; GHI = 0 during midday |

---

## Key Findings (this data pack)

| Station | Issue | Action |
|---|---|---|
| S02 | Pressure +7.8 hPa bias from 20 Mar (uncalibrated board swap 21 Mar) | correct |
| S03 | Temp sensor: 85 C spikes, -40 C spikes, 80-hour freeze at 6.5 C | exclude affected intervals |
| S04 | Rain gauge blocked; missed ~30 mm on 29-30 Mar; 33.8 mm dump on 2 Apr | exclude rain channel |
| S05 | Humidity pegged 99-105% for 77 hours (7-11 Mar) | exclude that period |
| S06 | Logger clock 6 h behind UTC from 24 Mar (battery reset to local time) | correct (+6 h to timestamps) |
| S07 | Wind reads ~74% too low from 26 Mar (new anemometer, wrong calibration) | exclude wind channel |
| S08 | 35-hour data gap 16-18 Mar (SIM ran out); duplicate April-5 data block | exclude |

Full details with start/end timestamps and evidence in `flags.csv`.

---

## What I Did Not Get To

- Automated output of a corrected data pack with offsets applied
- Wind-direction stuck-value check
- Cross-station temperature comparison (radiation-shield contamination from S04 fence repaint)

---

## Project Structure

```
checker/
  __main__.py         Entry point (CLI)
  loader.py           Data-pack loader (CSV, NMEA, maintenance log)
  flagwriter.py       Writes flags.csv
  checks/
    __init__.py       Orchestrator
    range_checks.py
    temporal_checks.py
    gps_checks.py
    sensor_checks.py
    cross_station.py
    solar_checks.py
report.html           Network health report (A4 printable)
DECISIONS.md          Written reasoning
flags.csv             Output for this data pack
requirements.txt      pandas, numpy only
```
