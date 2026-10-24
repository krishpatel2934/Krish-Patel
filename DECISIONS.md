# DECISIONS.md

> **Note to reviewer:** This document is written in my own words.
> I used AI to write and debug the checker code. The reasoning below is mine.

---

## 01 — The Visit

**Station: S06 — South Hills Fire Station**

The technician should spend their hour at S06.

When the battery went flat on 24 March and the logger rebooted, the clock
reset to local Mountain time instead of UTC. Every timestamp from that point
is six hours behind the true time — meaning all six measurement channels
(temperature, humidity, pressure, wind, rain, irradiance) carry the wrong
time for the last 18 days of the six-week record. I confirmed this with the GPS
data: the `$GPRMC` sentences show UTC 17:00 at the same moment the logger
says 11:00 — a consistent 6-hour deficit that persists to the end of the file.

In one hour the technician should:
1. Read the logger clock display *before touching anything* — this records
   the current offset state.
2. Force a GPS re-sync, or set the clock manually to UTC if GPS is not locking.
3. Check the battery voltage and solar charge controller — a flat battery was
   the root cause; it may go flat again.
4. Confirm the GPS indicator light is active (shows ongoing clock discipline).
5. Note the exact moment they correct the clock, so the data correction can
   be anchored precisely.

**Why not S03?**

S03 has a broken temperature sensor (85 °C spikes are the DS18B20 reset code;
the 80-hour freeze at exactly 6.5 °C is a stuck register). But only the
temperature channel is broken — humidity, pressure, wind, rain, and GHI from
S03 are all usable. Fixing S03 needs a replacement probe and takes longer than
an hour. S06's problem corrupts *everything* and can be solved in one visit
with no parts. That is a better use of one technician-hour.

---

## 02 — My Least Certain Call

**Flag: S04 rain gauge blockage (29–30 March)**

I am confident there was a blockage — the maintenance log says the funnel was
full of leaves and a bird nest, and the 33.8 mm dump on 2 April (clean-out day)
against a network max of 1.4 mm is hard to explain any other way. The evidence
that points the other direction: only two consecutive dry days are flagged
(March 29–30), while March 31 and April 1 also show zero rain at S04 while a
few other stations show 1–2 mm. Two days is not a long run; it could in
principle be a localised dry spell.

The single piece of information that would settle it: the actual date the
funnel became fully blocked. The maintenance note says it was cleaned "around
10" on 2 April, but does not say when the blockage started. A photo taken at
clean-out showing the depth of debris would let me estimate whether the funnel
had been blocked for two days or two weeks.

---

## 03 — Where the AI Was Wrong

**Example 1 — spike threshold**

I asked the AI to write a spike detector for the temperature channel. It
suggested a multiplier of 8× the rolling MAD. Running that on the data produced
632 spike flags — it was flagging normal GHI variability from clouds and natural
wind gusts as spikes. The threshold of 8 is reasonable for truly stationary
signals but weather data is inherently variable. I had to raise the multiplier
to 20 and restrict spike detection to temperature, humidity, and pressure only,
which brought the count to the two genuine 85 °C and −40 °C events I could
verify by eye.

**Example 2 — pressure comparison**

The AI suggested comparing each station's pressure to the network mean to
detect the S02 sensor-swap offset. That produced four false-positive "offset"
flags on S01, S04, S05, and S06 because S02's +6 hPa error contaminated the
network mean enough to make all the others look shifted. I noticed this because
the alleged onset dates on S01, S04, and S05 were all the same day (19 March)
and none of them have maintenance events on that date. The fix — reduce
all pressures to sea-level equivalent first, then compare residuals against
the network median — eliminated all four false flags while keeping the real S02 flag.

---

## 04 — Next Year (500 Stations, Unattended)

**What I would keep:**
- Range checks — fast, zero false positives, catches the obvious.
- Temporal checks (gaps, backward jumps) — mechanical and reliable.
- GPS clock-offset detection — the only way to catch a logger that silently
  resets its clock; a human reviewer would not spot a 6-hour offset across
  18 days of timestamps.
- Rain-dump detection — a single-day total that is 5× the network max is
  almost never weather.

**What I would change:**
- The stuck-sensor detector should track a *rolling* window (not full-file
  runs) so it catches partial-day freezes and resets cleanly at midnight.
- Pressure comparison needs elevation normalisation from the start (as I
  eventually implemented) — the naive mean comparison does not scale.
- All thresholds should be calibrated on a hold-out set of known-good data
  before deployment; the numbers I chose were reasoned but not validated.

**What I would refuse to automate:**
- The final *action* decision. The checker can recommend `exclude` or `correct`,
  but whether to actually exclude a channel from a published climate summary
  should require a human sign-off. At 500 stations, the stakes of silently
  discarding real data are high — a cold snap, a record rainfall, a drought —
  and no automated system should make that call unilaterally.
- Anything involving the maintenance log. Matching free-text notes to time
  series events is fragile; I used it as a cross-check but not as an input
  to any automated flag.

---

## 05 — By Hand: Solar Noon at S04 on 20 March 2025

**Station S04:** lat = 39.754 °N, lon = −105.146 °E (i.e. 105.146 °W)

**Step 1 — Local solar noon in local apparent solar time (LAST)**

Solar noon in LAST is always 12:00:00 by definition.

**Step 2 — Convert LAST to UTC**

UTC = LAST − (longitude / 15) − Equation of Time correction

Longitude offset: 105.146 °W / 15 = **7.010 hours west**

Equation of Time on 20 March: approximately **−7.5 minutes** (the sun runs
about 7.5 minutes *slow* relative to mean time near the March equinox).

UTC of solar noon ≈ 12:00 + 7:01 − (−0:07.5) ≈ **19:08 UTC**

(i.e. roughly 19:08 UTC = 12:08 MDT local, which is consistent with the
Colorado mid-March solar angle.)

**What this is useful for here:**

The GHI channel peaks close to solar noon. If a logger's clock is wrong, the
GHI peak will appear at the wrong UTC time. For S06, after the 24 March clock
reset, the GHI peak shifted 6 hours earlier in UTC — from ~19:00 UTC to
~13:00 UTC. Comparing the observed GHI peak time against the expected solar
noon (computed from lat/lon) is an independent, physics-based way to confirm
the clock offset that I found using the GPS. It also works for stations whose
GPS files are sparse or corrupted.
