"""Shared paths, readers, the on-time rule and per-day GTFS timetables."""
from __future__ import annotations
import datetime as dt, glob, gzip, io, json, math, os, pathlib, zipfile
from functools import lru_cache
import pandas as pd
from zoneinfo import ZoneInfo

ROOT = pathlib.Path(__file__).resolve().parent.parent
DATA = pathlib.Path(os.environ.get("POT_DATA", ROOT / "data" / "sample"))
_SAMPLE = DATA.resolve() == (ROOT / "data" / "sample").resolve()
# A sample run never overwrites the full-data results behind the report: it writes to results_sample/ and figures_sample/.
OUT = pathlib.Path(os.environ.get("POT_OUT", ROOT / ("results_sample" if _SAMPLE else "results")))
FIG = pathlib.Path(os.environ.get("POT_FIG", ROOT / ("figures_sample" if _SAMPLE else "figures")))
TZ = ZoneInfo("America/New_York")  # follows EDT and EST

# On time = from 1 minute early to 5 minutes late (inclusive), the convention used by most US agencies.
EARLY_MIN, LATE_MIN = -1.0, 5.0
# Matches outside this window are treated as a bus running a different trip than the one it reports.
VALID_MIN, VALID_MAX = -5.0, 60.0
STOP_RADIUS_M = 40.0


def on_time(delay_min) -> bool:
    return EARLY_MIN <= delay_min <= LATE_MIN


def openany(path):
    return gzip.open(path, "rt") if str(path).endswith(".gz") else open(path)


def files(prefix: str) -> list[str]:
    """Daily log files for one feed, plain or gzipped, de-duplicated by day (gz wins)."""
    by_day = {}
    for f in sorted(glob.glob(str(DATA / f"{prefix}_*.jsonl"))) + sorted(glob.glob(str(DATA / f"{prefix}_*.jsonl.gz"))):
        by_day[pathlib.Path(f).name.split(".")[0]] = f
    since = os.environ.get("POT_SINCE", "")   # optional YYYY-MM-DD: read only files from that day on (the weekly run)
    return [by_day[k] for k in sorted(by_day) if not since or k.split("_")[-1] >= since]


def records(prefix: str):
    """Yield every JSON record of one feed; a corrupt archive is skipped with a warning, never silently."""
    for f in files(prefix):
        try:
            with openany(f) as fh:
                for line in fh:
                    try:
                        yield json.loads(line)
                    except json.JSONDecodeError:
                        continue
        except (OSError, EOFError) as e:
            print(f"  warning: skipped unreadable file {pathlib.Path(f).name}: {e}")


def local(ts: float) -> dt.datetime:
    return dt.datetime.fromtimestamp(ts, TZ)


def haversine(lat1, lon1, lat2, lon2) -> float:
    r = 6371000.0
    p1, p2 = math.radians(lat1), math.radians(lat2)
    a = math.sin((p2 - p1) / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(math.radians(lon2 - lon1) / 2) ** 2
    return 2 * r * math.asin(math.sqrt(a))


def hms(s: str) -> int:
    h, m, sec = s.split(":")
    return int(h) * 3600 + int(m) * 60 + int(sec)


def gtfs_snapshots() -> list[tuple[str, str]]:
    snaps = sorted(glob.glob(str(DATA / "gtfs" / "gtfs_*.zip")))
    return [(pathlib.Path(p).stem.split("_")[1], p) for p in snaps]


@lru_cache(maxsize=64)
def gtfs(path: str) -> dict:
    z = zipfile.ZipFile(path)
    rd = lambda n: pd.read_csv(io.BytesIO(z.read(n)), dtype=str)
    stops, st, trips, routes = rd("stops.txt"), rd("stop_times.txt"), rd("trips.txt"), rd("routes.txt")
    st["sched_s"] = st.arrival_time.map(hms)
    st["seq"] = st.stop_sequence.astype(int)
    rname = dict(zip(routes.route_id.str.lower(), routes.route_short_name))
    troute = {t: rname.get(r.lower(), "?") for t, r in zip(trips.trip_id, trips.route_id)}
    visits = {}
    for t, s, q, v in sorted(zip(st.trip_id, st.stop_id, st.seq, st.sched_s), key=lambda x: (x[0], x[2])):
        visits.setdefault((t, s), []).append((q, v))   # a trip can serve the same stop more than once
    return dict(
        visits=visits, trip_len=st.groupby("trip_id").seq.max().to_dict(),
        late_trips=set(st.trip_id[st.sched_s >= 86400]),   # trips that run past midnight (times of 24:00 or later)
        sched={(t, s): v for t, s, v in zip(st.trip_id, st.stop_id, st.sched_s)},
        seq={(t, s): v for t, s, v in zip(st.trip_id, st.stop_id, st.seq)},
        trip_route=troute,
        stop_name=dict(zip(stops.stop_id, stops.stop_name)),
        stop_xy={s: (float(a), float(b)) for s, a, b in zip(stops.stop_id, stops.stop_lat, stops.stop_lon)},
        st=st[["trip_id", "stop_id", "seq", "sched_s"]],
    )


def gtfs_for(day: str) -> dict:
    """Timetable in force on a service day: the newest daily snapshot taken on or before that day."""
    snaps = gtfs_snapshots()
    if not snaps:
        raise FileNotFoundError(f"no GTFS snapshots in {DATA / 'gtfs'}")
    chosen = snaps[0][1]
    for d, p in snaps:
        if d <= day:
            chosen = p
    return gtfs(chosen)


def save_json(obj, name: str):
    OUT.mkdir(parents=True, exist_ok=True)
    with open(OUT / name, "w") as fh:
        json.dump(obj, fh, indent=1, default=str)


def split_day(dates, default: str) -> str:
    """Train/test boundary: env POT_SPLIT, else the default, else (on a short sample) the median service day."""
    days = sorted(set(dates)); want = os.environ.get("POT_SPLIT", default)
    if days and days[0] < want <= days[-1]:
        return want
    return days[len(days) // 2]
