"""Step 1. Turn raw feed logs into one row per scheduled stop event, scored against the timetable in force that day.
`delay` is departure lateness in minutes (+ late); `arr_delay` is arrival lateness.

Outputs (in results/):
  tt_arrivals.csv    TigerTransit stop arrivals from GPS (routes 1 to 6B, WS)
  loop_visits.csv    Princeton Loop stop visits from the operator's live page, incl. skipped stops
  rail.csv           NJ Transit departures at Princeton Junction (NEC) and the Dinky
  njt_bus.csv        NJ Transit 600/605/606 at seven Princeton stops
  weather.csv        hourly weather, NWS alerts and rain flags
"""
from __future__ import annotations
import collections, datetime as dt, json, re
import numpy as np, pandas as pd
from .common import (DATA, OUT, TZ, STOP_RADIUS_M, VALID_MAX, VALID_MIN, files, gtfs_for, haversine, local, openany, records)


def _service_seconds(t: dt.datetime, day: str | None = None) -> int:
    """Seconds after midnight of the service day (a trip past midnight belongs to the day it started: 00:30 -> 24:30)."""
    extra = (t.date() - dt.date.fromisoformat(day)).days * 86400 if day else 0
    return extra + t.hour * 3600 + t.minute * 60 + t.second


def _service_day(t: dt.datetime, trip) -> str:
    """Service day of a GPS poll: the calendar day, unless it is before 4 am on a trip that started the evening before."""
    day = t.date().isoformat()
    if t.hour < 4:
        prev = (t.date() - dt.timedelta(days=1)).isoformat()
        if trip in gtfs_for(prev)["late_trips"]: return prev
    return day


def _close(eps, cur, ts_next, veh):
    """Store a finished stop visit: radius times if the bus was seen within 40 m, else the moment it moved on."""
    if cur is None: return
    key, fi, la = cur[:3]
    if fi is not None: eps.setdefault(key, []).append([fi, la, "radius", veh])
    elif ts_next is not None: eps.setdefault(key, []).append([ts_next, ts_next, "passed", veh])


def tigertransit() -> pd.DataFrame:
    """Each run of consecutive GPS polls in which a vehicle declares the same next stop on the same trip is one stop visit.
    Arrival = first poll in that run within 40 m of the stop; departure = last poll within 40 m. If the bus never reported
    a fix within 40 m, both are the poll at which the next-stop field moved on. When a trip serves a stop twice, its
    visits are matched to the timetable in order. Departure is the headline: a bus that arrives early and waits strands
    nobody. Each day is scored against that day's GTFS timetable."""
    eps = {}   # (day, trip, stop) -> list of [arrival_ts, departure_ts, how, veh]
    state = {}
    for f in files("vp"):
        rows = []
        with openany(f) as fh:
            for line in fh:
                try:
                    r = json.loads(line)
                except json.JSONDecodeError:
                    continue
                rows.append((r["veh"], r["poll"], r.get("ts") or r["poll"], r.get("trip_id"), r.get("stop_id"), r.get("lat"), r.get("lon")))
        if not rows:
            continue
        vp = pd.DataFrame(rows, columns=["veh", "poll", "ts", "trip", "stop", "lat", "lon"]).sort_values(["veh", "poll"])
        for veh, g in vp.groupby("veh", sort=False):
            cur = state.get(veh)   # a visit still open at the end of the previous (UTC-day) file carries over
            for _, poll, ts, trip, stop, lat, lon in g.itertuples(index=False):
                day = _service_day(local(ts), trip); G = gtfs_for(day)
                if cur is None or (cur[0][1], cur[0][2]) != (trip, stop) or ts - cur[3] > 1800:   # new visit (or a 30-min silence)
                    _close(eps, cur, ts if cur is None or ts - cur[3] <= 1800 else None, veh); cur = [(day, trip, stop), None, None, ts]
                cur[3] = ts
                if stop in G["stop_xy"] and lat is not None:
                    sl, so = G["stop_xy"][stop]
                    if haversine(lat, lon, sl, so) <= STOP_RADIUS_M:
                        if cur[1] is None: cur[1] = ts
                        cur[2] = ts
            state[veh] = cur
    for veh, cur in state.items():   # end of the log: keep visits that were seen at the stop
        if cur is not None and cur[1] is not None: _close(eps, cur, None, veh)
    rows, drop = [], collections.Counter()
    for (day, trip, stop), visits in eps.items():
        G = gtfs_for(day); plan = G["visits"].get((trip, stop))
        if not plan:
            drop["not in timetable"] += 1; continue
        visits = sorted(v for v in visits if v[0] is not None)
        if len(visits) > len(plan):   # flapping next-stop field: keep the first visit and the last ones, one per timetable visit
            visits = visits[:len(plan)] if len(plan) == 1 else [visits[0]] + visits[1:][-(len(plan) - 1):]
        for (seq, sched), (ta_ts, td_ts, how, veh) in zip(plan, visits):
            if seq == G["trip_len"].get(trip):   # the trip's last stop is drop-off only (GTFS pickup_type 1): nobody boards, so it is not scored
                drop["last stop of the trip (drop-off only)"] += 1; continue
            ta, td = local(ta_ts), local(td_ts)
            arr = (_service_seconds(ta, day) - sched) / 60; dep = (_service_seconds(td, day) - sched) / 60
            if dep < VALID_MIN: drop["departed > 5 min early (likely a different trip)"] += 1; continue
            if dep > VALID_MAX: drop["departed > 60 min late (likely a different trip)"] += 1; continue
            rows.append(dict(date=day, route=G["trip_route"].get(trip, "?"), trip_id=trip, stop_id=stop, stop=G["stop_name"].get(stop, stop),
                             seq=seq, trip_len=G["trip_len"].get(trip), sched_s=sched, actual_s=_service_seconds(td, day), epoch=int(td_ts),
                             delay=round(dep, 2), arr_delay=round(arr, 2), veh=veh, how=how))
    df = pd.DataFrame(rows).sort_values(["date", "epoch", "trip_id", "seq"])
    df.to_csv(OUT / "tt_arrivals.csv", index=False)
    json.dump(dict(drop), open(OUT / "tt_dropped.json", "w"), indent=1)
    print(f"  TigerTransit: {len(df):,} stop departures scored; dropped: {dict(drop)}")
    return df


def _wall(t: dt.datetime, d0: dt.date) -> float:
    """Seconds after local midnight on wall-clock time (correct across the Nov 1 clock change), days counted from d0."""
    return (t.date() - d0).days * 86400 + t.hour * 3600 + t.minute * 60 + t.second


def _iso(t: str) -> dt.datetime:
    return dt.datetime.fromisoformat(t.replace("Z", "+00:00")).astimezone(TZ)


def loop() -> tuple[pd.DataFrame, pd.DataFrame]:
    """Loop arrivals come from the operator's own ride records (TripShot liveRides): for every stop of every trip the
    record carries the scheduled time, the state (Departed, Present, Skipped, Awaiting) and the arrival time the
    driver's device logged. The last record seen for each ride is final. Driver ids in the feed are never written out.
    Also kept: the vehicle (for the timetable simulation) and the highest rider count the ride reported."""
    final, riders, veh, route = {}, {}, {}, {}
    for r in records("loop"):
        for lr in r.get("liveRides") or []:
            ride = lr.get("ride") or {}; rid = ride.get("rideId")
            if not rid or not ride.get("stopStatus"):
                continue
            final[rid] = ride["stopStatus"]; route[rid] = r["route"]
            veh[rid] = ride.get("vehicleName") or (lr.get("vehicle") or {}).get("name")
            try:
                riders[rid] = max(riders.get(rid, 0), int(ride.get("riderCount") or 0))
            except (TypeError, ValueError):
                pass
    rows, sk, trips, unserved = [], [], [], []
    for rid, stops in final.items():
        trip, day = rid.rsplit(":", 1); G = gtfs_for(day)
        d0 = dt.date.fromisoformat(day)
        states = [list(x)[0] for x in stops]
        ran = any(st in ("Departed", "Present", "Skipped") for st in states)
        for j, x in enumerate(stops[:-1]):   # the final stop is drop-off only and is often never marked
            (st, v), = x.items()
            if st == "Awaiting":
                unserved.append(dict(date=day, route=route[rid], trip_id=trip, stop_id=v.get("stopId"), stop=G["stop_name"].get(v.get("stopId"), v.get("stopId")),
                                     trip_ran=ran))
        for x in stops:
            (state, v), = x.items()
            stop = v.get("stopId"); sat = v.get("scheduledAt")
            if not stop or not sat:
                continue
            h, m, s_ = map(int, sat.split(":")); sched = h * 3600 + m * 60 + s_
            name = G["stop_name"].get(stop, stop)
            if state == "Skipped":
                sk.append(dict(date=day, route=route[rid], trip_id=trip, stop_id=stop, stop=name, sched_s=sched, hour=h)); continue
            if state not in ("Departed", "Present") or not v.get("arrivalTime"):
                continue
            t = _iso(v["arrivalTime"])
            actual = _wall(t, d0)
            delay = (actual - sched) / 60
            dep = (_iso(v["departureTime"]) - _iso(v["scheduledDepartureTime"])).total_seconds() / 60 if v.get("departureTime") and v.get("scheduledDepartureTime") else np.nan
            if np.isnan(dep) or not (VALID_MIN <= dep <= VALID_MAX):
                continue
            td = _iso(v["departureTime"])
            rows.append(dict(date=day, route=route[rid], trip_id=trip, stop_id=stop, stop=name, seq=int(v.get("viaIdx", 0)) + 1, sched_s=sched,
                             actual_s=int(_wall(td, d0)), epoch=int(td.timestamp()), delay=round(dep, 2), arr_delay=round(delay, 2),
                             veh="LOOP-" + (str(veh[rid]) if veh[rid] else "trip-" + trip[:8])))
        (_, lv), = stops[-1].items()   # the final stop: drop-off only, so it has an arrival time but no departure
        end_s = int(_wall(_iso(lv["arrivalTime"]), d0)) if lv.get("arrivalTime") else None
        trips.append(dict(date=day, route=route[rid], trip_id=trip, vehicle=veh[rid], riders=riders.get(rid), stops=len(stops),
                          skipped=sum(1 for x in stops if "Skipped" in x), ran=ran, end_s=end_s))
    vis = pd.DataFrame(rows).sort_values(["date", "epoch"]); skips = pd.DataFrame(sk).sort_values(["date", "route"])
    vis.to_csv(OUT / "loop_visits.csv", index=False); skips.to_csv(OUT / "loop_skips.csv", index=False)
    pd.DataFrame(trips).sort_values(["date", "route"]).to_csv(OUT / "loop_trips.csv", index=False)
    pd.DataFrame(unserved).to_csv(OUT / "loop_unserved.csv", index=False)
    print(f"  Loop: {len(vis):,} stop visits from {len(final):,} trips, {len(skips):,} scheduled visits marked Skipped")
    return vis, skips


def rail() -> pd.DataFrame:
    """Train lateness = latest NJ Transit countdown before departure, against the timetable time on the board.
    Status text such as CANCELLED is kept. The Dinky's board clears at its scheduled time, so only its cancellations are reliable."""
    est, status, last_poll = {}, {}, {}
    for r in records("dv"):
        t = local(r["poll"])
        try:   # the scheduled time is a clock time; take the calendar day (yesterday, today, tomorrow) closest to the poll
            hm = dt.datetime.strptime(r["sched"], "%I:%M %p")
            sc = min((dt.datetime.combine(t.date() + dt.timedelta(days=o), hm.time(), tzinfo=t.tzinfo) for o in (-1, 0, 1)), key=lambda x: abs((x - t).total_seconds()))
        except ValueError:
            continue
        k = (sc.date().isoformat(), r["station"], r["line"], r["train"], r["sched"])   # keyed by the scheduled day, so a train is counted once
        s = (r.get("status") or "").strip()
        m = re.match(r"in (\d+) Min", s, re.I)
        if m:
            d = (t + dt.timedelta(minutes=int(m.group(1))) - sc).total_seconds() / 60
            if -60 < d < 180:
                est[k] = d   # the last countdown before departure (records arrive in time order)
        elif s and s.upper() not in ("ALL ABOARD", "BOARDING"):
            status[k] = s.upper()
        last_poll[k] = r["poll"]
    rows = []
    for k in set(est) | set(status):
        day, station, line, train, sched = k
        rows.append(dict(date=day, station=station, line=line, train=train, sched=sched, delay=round(est[k], 1) if k in est else np.nan,
                         status=status.get(k, ""), cancelled="CANCEL" in status.get(k, "")))
    df = pd.DataFrame(rows).sort_values(["date", "line", "sched", "station", "train"]).reset_index(drop=True)
    df.to_csv(OUT / "rail.csv", index=False)
    print(f"  Rail: {len(df):,} departures ({int(df.cancelled.sum())} cancelled)")
    return df


def njt_bus() -> pd.DataFrame:
    """NJ Transit bus lateness = last prediction shown before the bus leaves, against its scheduled time.
    Keyed by service date as well as trip: trip numbers repeat every day."""
    last = {}
    for r in records("mybus"):
        if not r.get("predicted") or not r.get("sched") or r.get("veh") in (None, "", "EMPTY"):
            continue   # no live bus behind the prediction: it is only the timetable
        try:
            sc = dt.datetime.strptime(r["sched"], "%m/%d/%Y %I:%M:%S %p")
            pr = dt.datetime.strptime(r["predicted"], "%I:%M %p").replace(year=sc.year, month=sc.month, day=sc.day)
        except ValueError:
            continue
        d = (pr - sc).total_seconds() / 60
        if d < -720: d += 1440  # prediction past midnight
        if -30 < d < 180:
            last[(sc.date().isoformat(), r["route"], r["stop_id"], r["trip"])] = (d, r["stop"], r["poll"])
    rows = [dict(date=k[0], route=k[1], stop_id=k[2], trip=k[3], stop=v[1], delay=round(v[0], 1)) for k, v in last.items()]
    df = pd.DataFrame(rows).sort_values(["date", "route"])
    df.to_csv(OUT / "njt_bus.csv", index=False)
    print(f"  NJ Transit buses: {len(df):,} scheduled stops scored")
    return df


RAIN = re.compile(r"rain|drizzle|shower|thunder|snow|sleet", re.I)


def weather() -> pd.DataFrame:
    """Hourly weather from NWS Trenton observations. 'Rain' = the observation text reports precipitation
    (precipitationLastHour is usually empty at this station, so it is not used alone)."""
    rows, alerts = [], collections.Counter()
    for r in records("events"):
        w = r.get("weather") or {}
        t = local(r["poll"])
        rows.append(dict(date=t.date().isoformat(), hour=t.hour, temp=w.get("temperature"), wind=w.get("windSpeed"),
                         text=w.get("text") or "", precip=w.get("precipitationLastHour") or 0))
        for a in r.get("nws_alerts") or []:
            alerts[(t.date().isoformat(), a.get("event"))] += 1
    df = pd.DataFrame(rows)
    df["rain"] = df.text.str.contains(RAIN) | (df.precip.fillna(0) > 0)
    h = df.groupby(["date", "hour"]).agg(temp=("temp", "mean"), wind=("wind", "mean"), rain=("rain", "max"), text=("text", "last")).reset_index()
    h.to_csv(OUT / "weather.csv", index=False)
    pd.DataFrame([dict(date=d, event=e, polls=n) for (d, e), n in alerts.items()]).to_csv(OUT / "nws_alerts.csv", index=False)
    print(f"  Weather: {len(h):,} hours, {int(h.rain.sum())} with rain reported")
    return h


def coverage() -> dict:
    """How complete the log is: rows per feed, first and last poll, and gaps longer than 5 minutes in the 30 s GPS poll."""
    polls, rows = set(), collections.Counter()
    for prefix in ["vp", "loop", "dv", "mybus", "amtrak", "tu", "events", "usgs"]:
        for r in records(prefix):
            rows[prefix] += 1
            if prefix == "vp":
                polls.add(r["poll"])
    p = sorted(polls)
    gaps = [(a, b) for a, b in zip(p, p[1:]) if b - a > 300]
    return dict(rows=dict(rows), total_rows=sum(rows.values()), first=local(p[0]).isoformat() if p else None,
                last=local(p[-1]).isoformat() if p else None, days=round((p[-1] - p[0]) / 86400, 1) if p else 0,
                gaps_over_5min=[(local(a).strftime("%Y-%m-%d %H:%M"), round((b - a) / 60)) for a, b in gaps],
                gps_polls=len(p))


def run():
    OUT.mkdir(parents=True, exist_ok=True)
    print(f"Measuring from {DATA}")
    tigertransit(); loop(); rail(); njt_bus(); weather()
    cov = coverage()
    json.dump(cov, open(OUT / "coverage.json", "w"), indent=1)
    print(f"  Coverage: {cov['total_rows']:,} rows, {cov['days']} days, {len(cov['gaps_over_5min'])} GPS gaps over 5 min")
