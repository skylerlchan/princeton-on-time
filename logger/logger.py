#!/usr/bin/env python3
"""Log TripShot GTFS-Realtime (TigerTransit + Princeton Loop) every POLL seconds.

Writes, per UTC day, in data/:
  vp_YYYY-MM-DD.jsonl   one line per vehicle per poll (position, next stop, status)
  tu_YYYY-MM-DD.jsonl   one line per trip per TU poll (predicted arrival per stop), every TU_EVERY s
  gtfs/gtfs_YYYY-MM-DD.zip  the static schedule, once per day
Nothing here identifies a person. Only bus positions and predicted times.
"""
from zoneinfo import ZoneInfo
import json, os, sys, time, datetime, urllib.request, urllib.error, pathlib
from concurrent.futures import ThreadPoolExecutor
from google.transit import gtfs_realtime_pb2 as gtfs

BASE = "https://princeton.tripshot.com/v1/gtfs/realtime/feed/tigertransit?types="
GTFS = "https://princeton.tripshot.com/v1/gtfs.zip"
DATA = pathlib.Path(__file__).resolve().parent / "data"
POLL = int(os.environ.get("POLL", "30"))
TU_EVERY = int(os.environ.get("TU_EVERY", "300"))
DV_EVERY = int(os.environ.get("DV_EVERY", "30"))
DV_STATIONS = ["Princeton Junction", "Princeton"]
DV_URL = "https://www.njtransit.com/api/graphql/graphql"
DV_QUERY = "query TrainDepartureScreens($station: String!) { getTrainDepartureScreens(station: $station) { items { departureDate destination line lineAbbreviation status track trainID inlineMessage } bannerMsg } }"
AMTRAK_URL = "https://api-v3.amtraker.com/v3/stations/PJC"
EV_EVERY = int(os.environ.get("EV_EVERY", "300"))
MYBUS_STOPS = {"22503": "Nassau St at Palmer Square (to Hamilton)", "22512": "Harrison St N at Nassau St (to Princeton)", "22550": "Princeton Shopping Center",
               "33087": "Nassau St at S Tulane St (to Princeton)", "22498": "Nassau St at Harrison St North (to Hamilton)", "22931": "Princeton Junction on Vaughn Drive (600)", "30251": "Princeton MarketFair (600)"}
USGS_EVERY = int(os.environ.get("USGS_EVERY", "900"))
# Stony Brook (Princeton), Millstone (Blackwells Mills, Griggstown), Pike Run, D&R Canal (Port Mercer, Kingston), Princessville rain gauge.
# One site per request: the 7-site query returns 503 about half the time, single sites almost never (tested 2026-10-05).
USGS_SITES = ["01401000", "01402000", "01401750", "01401650", "01460440", "01460500", "401731074422301"]
USGS_URL = "https://waterservices.usgs.gov/nwis/iv/?format=json&sites={}&parameterCd=00060,00065,00045,63160,00010&period={}"
NWPS_EVERY = int(os.environ.get("NWPS_EVERY", "3600"))
NWPS_GAUGES = {"PCTN4": "Stony Brook at Princeton", "BKWN4": "Millstone River at Blackwells Mills"}
CAM_EVERY = int(os.environ.get("CAM_EVERY", "60"))
LOOP_EVERY = int(os.environ.get("LOOP_EVERY", "30"))
LOOP_ROUTES = {"TPL": "BB733FC7-4B53-481F-9616-28D61CCA131C", "TPLEXP": "D03AD4F8-19B1-482A-A028-1BD79BFFD7EF"}
MYBUS_QUERY = "query BusArrivalsByStopID($stopID: ID!) { getBusArrivalsByStopID(stopID: $stopID) { publicRoute header departuretime departurestatus schedDepTime internalTripNumber vehicleId passload } }"  # NJ Transit changed this schema on 2026-10-01
NJT_RSS = ["https://www.njtransit.com/rss/RailAdvisories_feed.xml", "https://www.njtransit.com/rss/BusAdvisories_feed.xml"]
NJT_STATUS_QUERY = "query Index { getSystemStatus { abbreviation message service advisoryAlert } }"
NWS_OBS = "https://api.weather.gov/stations/KTTN/observations/latest"
NWS_ALERTS = "https://api.weather.gov/alerts/active?zone=NJZ015"

def fetch(url, timeout=20, tries=3):
    """GET with retries: NJ Transit and USGS return 502/503 or time out a few times per hour."""
    last = None
    for i in range(tries):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "cee420-on-time/0.1 (student project)"})
            with urllib.request.urlopen(req, timeout=timeout) as r:
                return r.read()
        except Exception as ex:
            last = ex; time.sleep(3 * (i + 1))
    raise last

def post_json(url, payload, timeout=15, tries=2):
    last = None
    for i in range(tries):
        try:
            req = urllib.request.Request(url, data=json.dumps(payload).encode(), headers={"User-Agent": "Mozilla/5.0 (cee420-on-time student project)", "content-type": "application/json"})
            with urllib.request.urlopen(req, timeout=timeout) as r:
                return json.load(r)
        except Exception as ex:
            last = ex; time.sleep(3 * (i + 1))
    raise last

def day():
    return datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%d")

def log_vp(now):
    f = gtfs.FeedMessage(); f.ParseFromString(fetch(BASE + "VehiclePosition"))
    rows = []
    for e in f.entity:
        v = e.vehicle
        rows.append({"poll": now, "feed_ts": f.header.timestamp, "ts": v.timestamp,
                     "trip_id": v.trip.trip_id, "veh": v.vehicle.label or v.vehicle.id,
                     "lat": round(v.position.latitude, 6), "lon": round(v.position.longitude, 6),
                     "bearing": round(v.position.bearing, 1), "speed": round(v.position.speed, 2),
                     "status": gtfs.VehiclePosition.VehicleStopStatus.Name(v.current_status),
                     "stop_id": v.stop_id, "occ": gtfs.VehiclePosition.OccupancyStatus.Name(v.occupancy_status) if v.HasField("occupancy_status") else ""})
    with open(DATA / f"vp_{day()}.jsonl", "a") as fh:
        for r in rows: fh.write(json.dumps(r) + "\n")
    return len(rows)

def log_tu(now):
    f = gtfs.FeedMessage(); f.ParseFromString(fetch(BASE + "TripUpdate"))
    n = 0
    with open(DATA / f"tu_{day()}.jsonl", "a") as fh:
        for e in f.entity:
            t = e.trip_update
            stus = [{"seq": s.stop_sequence, "stop_id": s.stop_id,
                     "arr": s.arrival.time if s.HasField("arrival") else None,
                     "dep": s.departure.time if s.HasField("departure") else None} for s in t.stop_time_update]
            fh.write(json.dumps({"poll": now, "feed_ts": f.header.timestamp, "trip_id": t.trip.trip_id,
                                 "veh": t.vehicle.label or t.vehicle.id, "delay": t.delay if t.HasField("delay") else None,
                                 "stops": stus}) + "\n"); n += 1
    return n

def log_dv(now):
    """NJ Transit DepartureVision board (public GraphQL, no key): Dinky + Northeast Corridor at both Princeton stations."""
    n = 0
    with open(DATA / f"dv_{day()}.jsonl", "a") as fh:
        for st in DV_STATIONS:
            try:
                d = post_json(DV_URL, {"operationName": "TrainDepartureScreens", "variables": {"station": st}, "query": DV_QUERY})["data"]["getTrainDepartureScreens"]
            except Exception as ex:
                print(f"DV ERROR {st} {ex!r}", flush=True); continue
            for it in d["items"]:
                fh.write(json.dumps({"poll": now, "station": st, "sched": it["departureDate"], "train": it["trainID"], "line": it["lineAbbreviation"],
                                     "dest": it["destination"], "status": it["status"], "track": it["track"], "msg": it["inlineMessage"]}) + "\n"); n += 1
    return n

def log_mybus(now):
    """NJ Transit MyBus (public GraphQL): live 605/606 arrivals at Princeton stops."""
    n = 0
    with open(DATA / f"mybus_{day()}.jsonl", "a") as fh:
        for sid, name in MYBUS_STOPS.items():
            try:
                items = post_json(DV_URL, {"operationName": "BusArrivalsByStopID", "variables": {"stopID": sid}, "query": MYBUS_QUERY})["data"]["getBusArrivalsByStopID"] or []
            except urllib.error.HTTPError as ex:
                items = []
                if ex.code != 400: print(f"MYBUS ERROR {sid} {ex!r}", flush=True)
            except Exception as ex:
                items = []; print(f"MYBUS ERROR {sid} {ex!r}", flush=True)
            for it in items:
                fh.write(json.dumps({"poll": now, "stop_id": sid, "stop": name, "route": it["publicRoute"], "veh": it["vehicleId"], "sched": it["schedDepTime"],
                                     "predicted": it["departuretime"], "status": it["departurestatus"], "trip": it["internalTripNumber"], "dest": it["header"], "capacity": it["passload"]}) + "\n"); n += 1
    return n

_usgs_seen = set()

def log_usgs(now, period="PT3H"):
    """Every 15-min value from 7 USGS sites (flow, height, canal level, water temp, rain). Asks for the last 3 hours
    and keeps only readings not yet written, so a missed poll (USGS 503s) is filled by the next one."""
    if not _usgs_seen:
        for f in sorted(DATA.glob("usgs_*.jsonl"))[-2:]:
            for ln in f.read_text().splitlines():
                r = json.loads(ln)
                if "code" in r: _usgs_seen.add((r["code"], r["param"], r["t"]))
    series, failed = [], []
    for site in USGS_SITES:
        try: series += json.loads(fetch(USGS_URL.format(site, period), timeout=30))["value"]["timeSeries"]
        except Exception: failed.append(site)
    if len(failed) == len(USGS_SITES): raise RuntimeError("all USGS sites failed")
    rows = []
    for ts in series:
        code, param = ts["sourceInfo"]["siteCode"][0]["value"], ts["variable"]["variableCode"][0]["value"]
        for v in ts["values"][0]["value"]:
            key = (code, param, v["dateTime"])
            if key in _usgs_seen: continue
            _usgs_seen.add(key)
            rows.append({"poll": now, "code": code, "param": param, "site": ts["sourceInfo"]["siteName"], "var": ts["variable"]["variableName"],
                         "t": v["dateTime"], "value": v["value"], "q": v.get("qualifiers", [])})
    with open(DATA / f"usgs_{day()}.jsonl", "a") as fh:
        for r in rows: fh.write(json.dumps(r) + "\n")
    return len(rows) if not failed else f"{len(rows)}(missed {','.join(failed)})"

def log_nwps(now):
    """NOAA flood status and the river forecast (stage, flow) for the two gauges NWS forecasts near Princeton."""
    n = 0
    with open(DATA / f"nwps_{day()}.jsonl", "a") as fh:
        for lid in NWPS_GAUGES:
            g = json.loads(fetch(f"https://api.water.noaa.gov/nwps/v1/gauges/{lid}", timeout=30))
            sf = json.loads(fetch(f"https://api.water.noaa.gov/nwps/v1/gauges/{lid}/stageflow/forecast", timeout=30))
            fh.write(json.dumps({"poll": now, "lid": lid, "name": g["name"], "status": g["status"], "flood": g["flood"]["categories"],
                                 "forecast_issued": sf.get("issuedTime"), "forecast": sf.get("data", [])}) + "\n"); n += 1
    return n

_PERSONAL = {"driverId", "acceptingDeviceId", "shiftId", "principalId", "deviceId", "fullRideHistory", "rideHistory", "userNavigationId"}


def _scrub(x):
    """Drop fields that identify drivers or their devices."""
    if isinstance(x, dict): return {k: _scrub(v) for k, v in x.items() if k not in _PERSONAL}
    if isinstance(x, list): return [_scrub(v) for v in x]
    return x


def log_loop(now):
    """TripShot per-route live data for the Princeton Loop (the GTFS-RT feed showed no Loop vehicles). Keeps live trips and any recorded stop visits."""
    n = 0
    today = datetime.datetime.now(ZoneInfo("America/New_York")).strftime("%Y-%m-%d")  # service day in Princeton (EDT or EST)
    with open(DATA / f"loop_{day()}.jsonl", "a") as fh:
        for name, rid in LOOP_ROUTES.items():
            d = json.loads(fetch(f"https://princeton.tripshot.com/v2/p/shared/route/{rid}/live?day={today}&includePreviousDayRidesSpanningMidnight=true", timeout=60))["InternalRouteLiveData"]
            for ex in d["exactLiveData"]:
                visits = [v for trip in ex["liveTimetable"] for v in trip if v.get("liveVisitDetails") and v["liveVisitDetails"].get("state") != "Awaiting"]
                rides = _scrub(ex.get("liveRides"))  # driver, device and shift ids are never stored
                fh.write(json.dumps({"poll": now, "route": name, "liveTrips": ex["liveTrips"], "liveRides": rides, "visits": visits}) + "\n"); n += len(ex["liveTrips"])
    return n

def log_amtrak(now):
    d = json.loads(fetch(AMTRAK_URL, timeout=30))
    trains = d.get("PJC", {}).get("trains", [])
    with open(DATA / f"amtrak_{day()}.jsonl", "a") as fh:
        fh.write(json.dumps({"poll": now, "trains": trains}) + "\n")
    return len(trains)

def log_events(now):
    """Exceptions: TripShot service alerts, NJ Transit system status + RSS advisories, NWS weather and alerts."""
    out = {"poll": now}
    f = gtfs.FeedMessage(); f.ParseFromString(fetch(BASE + "Alert"))
    out["tripshot_alerts"] = [{"id": e.id, "text": (e.alert.header_text.translation[0].text if e.alert.header_text.translation else ""),
                               "desc": (e.alert.description_text.translation[0].text if e.alert.description_text.translation else ""),
                               "routes": [ie.route_id for ie in e.alert.informed_entity], "trips": [ie.trip.trip_id for ie in e.alert.informed_entity if ie.trip.trip_id]} for e in f.entity]
    try: out["njt_status"] = post_json(DV_URL, {"operationName": "Index", "variables": {}, "query": NJT_STATUS_QUERY})["data"]["getSystemStatus"]
    except Exception as ex: out["njt_status"] = []; out["njt_status_err"] = repr(ex)
    out["njt_rss"] = {}
    for u in NJT_RSS:
        try: out["njt_rss"][u.rsplit("/", 1)[1]] = fetch(u, timeout=30).decode("utf-8", "ignore")[:20000]
        except Exception as ex: out["njt_rss"][u] = f"ERR {ex!r}"
    try:
        o = json.loads(fetch(NWS_OBS, timeout=30))["properties"]
        out["weather"] = {k: (o.get(k) or {}).get("value") for k in ["temperature", "windSpeed", "precipitationLastHour", "visibility"]} | {"text": o.get("textDescription"), "ts": o.get("timestamp")}
        out["nws_alerts"] = [{"event": a["properties"]["event"], "headline": a["properties"].get("headline")} for a in json.loads(fetch(NWS_ALERTS, timeout=30))["features"]]
    except Exception as ex: out["weather_err"] = repr(ex)
    with open(DATA / f"events_{day()}.jsonl", "a") as fh: fh.write(json.dumps(out) + "\n")
    return len(out["tripshot_alerts"]) + len(out["njt_status"])

def fetch_gtfs():
    p = DATA / "gtfs" / f"gtfs_{day()}.zip"
    if p.exists(): return
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_bytes(fetch(GTFS, timeout=60))

def main():
    DATA.mkdir(exist_ok=True)
    last = {"tu": 0, "dv": 0, "ev": 0, "usgs": 0, "nwps": 0, "cam": 0, "loop": 0}
    pool = ThreadPoolExecutor(max_workers=6)
    def guarded(name, fn, *a):
        try: return fn(*a)
        except Exception as ex:
            print(f"{name.upper()} ERROR {ex!r}", flush=True)
            with open(DATA / "errors.log", "a") as fh: fh.write(f"{int(time.time())} {name} {ex!r}\n")
            return 0
    while True:
        now = int(time.time())
        jobs = {"vp": pool.submit(guarded, "vp", log_vp, now)}
        try: fetch_gtfs()
        except Exception as ex: print(f"GTFS ERROR {ex!r}", flush=True)
        if now - last["loop"] >= LOOP_EVERY: jobs["loop"] = pool.submit(guarded, "loop", log_loop, now); last["loop"] = now
        if now - last["dv"] >= DV_EVERY:
            jobs["dv"] = pool.submit(guarded, "dv", log_dv, now); jobs["mybus"] = pool.submit(guarded, "mybus", log_mybus, now); jobs["amtrak"] = pool.submit(guarded, "amtrak", log_amtrak, now); last["dv"] = now
        if now - last["tu"] >= TU_EVERY: jobs["tu"] = pool.submit(guarded, "tu", log_tu, now); last["tu"] = now
        if now - last["usgs"] >= USGS_EVERY: jobs["usgs"] = pool.submit(guarded, "usgs", log_usgs, now); last["usgs"] = now
        if now - last["nwps"] >= NWPS_EVERY: jobs["nwps"] = pool.submit(guarded, "nwps", log_nwps, now); last["nwps"] = now
        if now - last["ev"] >= EV_EVERY: jobs["ev"] = pool.submit(guarded, "ev", log_events, now); last["ev"] = now
        res = {}
        for k, f in jobs.items():
            if k in ("usgs", "nwps") and not f.done(): res[k] = "bg"; continue  # slow, 15-min/hourly: let it finish in the background
            try: res[k] = f.result(timeout=max(5, POLL - (time.time() - now) + 25))
            except Exception as ex: res[k] = "slow"; print(f"{k.upper()} SLOW {ex!r}", flush=True)
        print(f"{datetime.datetime.now():%H:%M:%S} " + " ".join(f"{k}={v}" for k, v in res.items()), flush=True)
        time.sleep(max(1, POLL - (time.time() - now)))

if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] == "once":
        now = int(time.time()); fetch_gtfs(); print("vp", log_vp(now), "tu", log_tu(now), "dv", log_dv(now), "amtrak", log_amtrak(now), "mybus", log_mybus(now), "usgs", log_usgs(now), "nwps", log_nwps(now), "loop", log_loop(now), "events", log_events(now))
    else:
        main()
