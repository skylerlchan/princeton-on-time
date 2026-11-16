# Princeton On Time

Does Princeton's transit keep its own timetable? This repository logs every bus and train in Princeton, NJ every 30 seconds
from public feeds, scores each departure against the timetable in force that day, predicts lateness 30 minutes ahead, and
replays timetable fixes on held-out weeks before anyone is asked to adopt them.

CEE 420 Urban AI, Princeton University, Fall 2026. Skyler Chan and Victoria Spradlin.
Repository: https://github.com/skylerlchan/princeton-on-time
Report to the Municipality of Princeton: [report/Princeton On Time - Final Report.pdf](report/Princeton%20On%20Time%20-%20Final%20Report.pdf).
Poster (48 x 36 in): [poster/Princeton On Time - poster.pdf](poster/Princeton%20On%20Time%20-%20poster.pdf). Every field: [DATA.md](DATA.md).
Sample weekly reliability page: [results/weekly.html](results/weekly.html).

## Findings, Sep 30 to Nov 15, 2026

- TigerTransit left 88.5% of stops on time (1 min early to 5 min late); the Loop Express 87.2%; the Loop Local 70.0%.
- The Loop Local skipped 7.1% of scheduled visits; one stop stands out, the Senior Resource Center at 30.5%.
- Replayed on held-out weeks, having early Loop Local buses wait on every trip lifts it from 72% to 77%, and to 82% with a
  re-timed schedule. A 30-minute forecast beats a table of past lateness by 2%; using the route network does not help.

## Run it

```bash
python3.12 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt                 # core; add requirements-optional.txt for the map and the logger
python run_all.py                               # (or: make sample) three-day sample, about 1 minute, into results_sample/ and figures_sample/
python -m pytest -q                             # 14 tests, about 1 to 2 minutes (one runs the whole pipeline on the sample)
POT_DATA=/path/to/full/data python run_all.py   # the 47-day log behind the report, about 6 to 8 minutes, into results/ and figures/
```

Check the sample run: `results_sample/summary.json` should show TigerTransit `n` 6,895 at 88.1% on time and the Loop Local
576 departures at 73.6% with 66 skipped visits (the test suite asserts these). Every headline number in the report is checked
against `results/*.json` by `tests/test_report_numbers.py`.

The poster needs Node.js 18 or later (built with Node 22) and `npm install` in `poster/` (pptxgenjs 4.0.1, pinned in the lockfile).

| Variable | Default | Meaning |
|---|---|---|
| `POT_DATA` | `data/sample` | folder of raw feed logs and `gtfs/` snapshots |
| `POT_OUT` | `results/` (`results_sample/` for the sample) | where tables and JSON go |
| `POT_FIG` | `figures/` (`figures_sample/` for the sample) | where charts go |
| `POT_SPLIT` | `2026-11-01` | first test day for the forecast and the timetable replay |
| `POT_SINCE` | none | read only log files from this date on, e.g. the last 5 weeks for the weekly page |
| `POT_BASEMAP` | none | optional GeoPackage with `roads` and `boundary` layers for the map (we built ours from the Municipality of Princeton's open GIS data; without it the map draws routes and stops only) |

On the three-day sample the split falls back to the middle day, so forecast and replay numbers there are a smoke test only,
and they go to separate folders so they never overwrite the full-data run in `results/` and `figures/` (log: `results/run_all_full.log`).

## Rebuilding the report and poster

- **Report:** `python report/build_doc.py report/report.md -o "report/Princeton On Time - Final Report.docx"` (needs
  `python-docx` 1.2.0). The PDF is that file opened in Google Docs (File > Save as Google Docs) and exported as PDF.
- **Poster:** `python poster/aspect.py && (cd poster && npm install) && node poster/poster.js` writes the .pptx; the PDF is
  its Google Slides export. Google's export sets the page breaks and compresses images to about 150 to 190 dpi.
- The submitted version is the commit tagged `final-report`. `results/MANIFEST.sha256` lists SHA-256 hashes of the committed
  full-data outputs; after a full rerun, `cd results && shasum -a 256 -c MANIFEST.sha256` checks they match.

## What each step does

| Step | Module | Writes |
|---|---|---|
| 1 measure | `pot/measure.py` | `tt_arrivals.csv` (TigerTransit departures), `tt_dropped.json`, `loop_visits.csv`, `loop_skips.csv`, `loop_trips.csv`, `rail.csv`, `njt_bus.csv`, `weather.csv`, `coverage.json` |
| 2 summarize | `pot/summarize.py` | `summary.json` (every number in the report), `tt_stops.csv` |
| 2b validate | `pot/validate.py` | `validation.json`: two records of the same Loop stop, how often they agree |
| 3 forecast | `pot/forecast.py` | `forecast.json`, `forecast_test_predictions.csv` |
| 3b graph network | `pot/gnn.py` (needs torch) | `gnn.json`: the same network with and without stop links |
| 4 timetable | `pot/timetable.py` | `timetable_test.csv`, `timetable_segments.csv` (proposed minutes from the first stop), `timetable.json` |
| 5 figures | `pot/figures.py` | `figures/fig1` to `fig7`, `fig6b` (poster) |
| 6 map | `pot/map.py` | `figures/fig2_map.png` (needs geopandas) |
| 7 weekly page | `pot/weekly.py` | `weekly.html`: last 7 days by route and stop, skipped stops |
| poster | `poster/poster.js` | `python poster/aspect.py && (cd poster && npm install) && node poster/poster.js`; the PDF is the Google Slides export of that file |

Per-departure tables (`tt_arrivals.csv`, `loop_*.csv`, `forecast_test_predictions.csv`) are written by the run but not
committed: each Loop route runs one bus, so departure times by route can reveal a driver's shift.

## Definitions

- **Lateness** = actual departure minus timetable departure, minutes. **On time** = between 1 minute early and 5 minutes late.
- **TigerTransit departure**: a stop visit is the run of GPS fixes in which a bus names that stop as its next stop; departure is
  the last fix within 40 m, or the moment it names the following stop. Repeat visits to a stop on one trip are matched in order.
- **Loop departure**: the time the operator's device logged (TripShot ride records). **Skipped** is the operator's own state.
- **Trains and NJ Transit buses**: the last countdown or prediction before departure. Trains cannot leave early, so negative
  estimates count as on time. NJ Transit predictions with no live bus behind them are dropped.
- A trip's last stop is drop-off only and is not scored.
- Each service day is scored against the GTFS snapshot published that day. TigerTransit departures more than 5 min early or
  60 min late are treated as a different trip and dropped (385 matches, under 0.5%); counts by reason are in `results/tt_dropped.json`.
- 95% intervals resample whole service days (1,000 draws). Forecast features use only data before the issue time
  (scheduled time minus 30 min); the time-window helper is unit-tested.

## Handover runbook (one page for town staff)

| Item | Plan |
|---|---|
| Owner | Proposed: the municipal transit contract manager, with Municipal IT as backup. To be agreed by the town; nothing here assumes it |
| Who runs it until then | The student team, on its own cloud account, through June 30, 2027. Contacts: Skyler Chan (sc8742@princeton.edu) and Victoria Spradlin; backup: the CEE 420 course staff |
| Skills needed | Basic Linux and Python. Without them, hire a contractor for the weekly run and upkeep: about 5 hours a month, roughly $400 to $700 a month at local IT rates |
| Moving it over | Municipal IT creates a small Linux server (any provider, 2 GB RAM). The team copies the code, the timetable snapshots (`gtfs/`, about 50 MB) and scrubbed feed files, then hands over the server login. The town holds all keys; the logger needs none |
| Monthly cost | Server under $30; storage about 18 GB a year, gzipped (a few dollars) |
| Weekly task (about 1 hour) | `POT_OUT=weekly POT_SINCE=$(date -d '6 weeks ago' +%F) POT_DATA=logger/data python run_all.py --weekly` (a few minutes; writes to `weekly/` by default, never touching the report's `results/`; needs at least 6 weeks of logs, or the comparison column shows n/a). Then follow the checklist below and post `weekly/weekly.html`. Once the University agrees to TigerTransit figures, add `POT_UNIVERSITY_AGREED=1` |
| When a feed breaks | A cron check emails within an hour (step 3), for the GPS, Loop and arrival-prediction feeds, during service hours only. TripShot page changes are the likeliest cause. Keep the other feeds running and contact the team; affected weeks show as partial on the page. The Loop figures come from TripShot's public live pages, which are undocumented: if TripShot changes them, Loop figures stop until the code is updated or a direct feed is agreed |
| Before publishing | Agree the page with WeDriveU and a labour review: each Loop route runs one bus, so even a weekly route total can describe one driver's week. TigerTransit figures stay off the page until the University agrees (`POT_UNIVERSITY_AGREED=1`). Confirm the town website can host a plain HTML page |
| Data terms | Feeds belong to TripShot and NJ Transit; seek a data agreement with TripShot, ideally a direct feed, before republishing |
| Sunset | If nobody owns it by June 30, 2027, the team stops the logger and deletes its raw files |

### Setting it up, in order

1. **Install.** On the server: `git clone` the repository, then
   `python3.12 -m venv .venv && .venv/bin/pip install -r requirements.txt -r requirements-optional.txt`.
2. **Run the logger as a service** (replace `USER`), then `sudo systemctl enable --now on-time`:

```ini
# /etc/systemd/system/on-time.service
[Unit]
Description=Princeton On Time logger
After=network-online.target

[Service]
User=USER
WorkingDirectory=/home/USER/princeton-on-time
ExecStart=/home/USER/princeton-on-time/.venv/bin/python logger/logger.py
Restart=always
RestartSec=10

[Install]
WantedBy=multi-user.target
```

   The logger writes one file per feed per day to `logger/data/` and saves each day's timetable as
   `logger/data/gtfs/gtfs_YYYY-MM-DD.zip`; the analysis needs those snapshots, so never delete them.
3. **Add the cron jobs** (`crontab -e` as the logger's user). Email needs a mail agent on the server (for example `msmtp`
   configured with a town mailbox); without one, the alerts go nowhere.

```cron
CRON_TZ=America/New_York   # run times below are Eastern; feed file names are UTC dates, which the checks handle
MAILTO=transit-staff@example.org   # placeholder: replace with a real town mailbox
# 02:30 daily: gzip feed files older than two days (never the gtfs/ snapshots)
30 2 * * * find /home/USER/princeton-on-time/logger/data -maxdepth 1 -name '*.jsonl' -mtime +2 -exec gzip {} \;
# daily 07:00: email if the disk is over 80% full
0 7 * * * df --output=pcent / | tail -1 | tr -dc 0-9 | awk '$1 > 80 {print "Princeton On Time: disk " $1 "% full"}'
# hourly 8 am to 10 pm: email if a feed file has not grown in the last hour. Files are named by UTC date, so the check accepts
# today's or yesterday's UTC file (the name changes at 7 or 8 pm Eastern). The Loop feed is skipped on Sundays (no service).
0 8-22 * * * cd /home/USER/princeton-on-time/logger/data && for f in vp loop tu; do [ "$f" = loop ] && [ "$(date +\%u)" = 7 ] && continue; test -n "$(find . -maxdepth 1 \( -name "${f}_$(date -u +\%F).jsonl" -o -name "${f}_$(date -u -d yesterday +\%F).jsonl" \) -mmin -60)" || echo "Princeton On Time: $f feed stalled"; done
# during University breaks TigerTransit runs less; expect occasional alerts then, or comment out "vp tu" for the break
```

4. **Each week**, run the weekly task in the table above, then check before posting:
   - every route row is present (routes under 50 departures are dropped by design; a missing Loop route means a feed problem);
   - no partial day is flagged, or if one is, add a note or hold the page for a week;
   - the "Data through" date is the last service day.
   Hold the page if a feed was down for more than a day of the week.
5. **Is it working?** Each morning the newest files in `logger/data/` should have grown overnight, `logger/data/errors.log`
   should not be growing fast, and no alert email should have arrived. **Restoring:** on a new server, repeat steps 1 to 3, copy
   back `logger/data/gtfs/` and any gzipped feed files from the off-server copy, and start the service; gaps show as partial days.
6. **Housekeeping.** Copy `logger/data/gtfs/` and the gzipped feed files off the server monthly (to the town's file share or
   cloud storage; the timetable snapshots cannot be re-downloaded), apply OS updates monthly (Municipal IT), and
   watch disk space (about 18 GB a year).

## Data and privacy

The shipped three-day sample has driver and device identifiers removed. It keeps bus numbers, which are painted on each bus and
visible to anyone at a stop, and per-departure Loop timing, which the pipeline
needs to run. We judged three days of route-level timing an acceptable trade for a runnable package; the 47-day per-departure
tables are not shipped. This public repository is a fresh copy of the team's working repository, without the earlier commits that held those tables.

The full log (2.3 GB, Sep 30 to Nov 15, 2026) is not in the repository: its early operator files carry driver and device
identifiers. `data/sample/` holds Nov 11 to 13 with those removed. The logger code now drops them before saving (`_scrub` in
`logger/logger.py`, tested in `tests/test_logger.py`); it was changed on Nov 15, after the study period.

## Limits

No field timing (departures are checked against other public records only); trains and NJ Transit buses are operator estimates; the timetable fixes are a replay that depends on
driver compliance, not a trial. See section 6 of the report.

## AI note

Code, analysis and drafts were written with Claude Code (Anthropic). The team chose the questions, rules and splits. Appendix B
of the report lists the errors independent reviews found and how each was fixed.

## Licence and contact

Code under the MIT licence (`LICENSE`). Feed data belong to TripShot, NJ Transit, Amtrak, NWS and USGS under their own terms.
Questions: Skyler Chan (sc8742@princeton.edu) and Victoria Spradlin, Princeton University.
