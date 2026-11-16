"""Step 2b. Checks of the measured departure times against other public records (in place of a stopwatch check).
For the Loop, two separate paths through the same TripShot feed record the same event (a consistency check, not an independent one): the 30-second poll of the stop-state page
(first poll showing Present or Departed) and the arrival time the driver's device logged. If both are right, the poll
should trail the logged time by 0 to 30 seconds."""
from __future__ import annotations
import numpy as np, pandas as pd
from .common import OUT, local, records, save_json

POLL30_FROM = 1791100000  # 2026-10-04: the Loop page has been polled every 30 s since


def run():
    first = {}
    for r in records("loop"):
        if r["poll"] < POLL30_FROM: continue
        day = local(r["poll"]).date().isoformat()
        for v in r.get("visits") or []:
            if (v.get("liveVisitDetails") or {}).get("state") in ("Present", "Departed"):
                first.setdefault((v["sharedTripId"], v["sharedStopId"], day), r["poll"])
    lv = pd.read_csv(OUT / "loop_visits.csv")
    arr_epoch = lv.epoch - (lv.delay - lv.arr_delay) * 60
    d = np.array([(first[k] - a) / 60 for k, a in zip(zip(lv.trip_id, lv.stop_id, lv.date), arr_epoch) if k in first])
    out = dict(loop_departures=int(len(lv)), coverage_share=round(len(d) / len(lv) * 100, 1),
               within_1min_share_of_all=round(float((np.abs(d) <= 1).sum() / len(lv) * 100), 1), pairs=int(len(d)), median_lag_min=round(float(np.median(d)), 2), abs_p50=round(float(np.percentile(np.abs(d), 50)), 2),
               abs_p90=round(float(np.percentile(np.abs(d), 90)), 2), within_1min_share=round(float((np.abs(d) <= 1).mean() * 100), 1))
    out = {"state_page_vs_logged": out, "gps_vs_logged": gps_check(), "tigertransit_gps_vs_published": tu_check()}
    save_json(out, "validation.json")
    o = out["state_page_vs_logged"]
    print(f"  Loop cross-check: {o['pairs']:,} pairs, {o['within_1min_share']}% agree within 1 min, median lag {o['median_lag_min']} min")
    return out


def gps_check():
    """Second check, from a different sensor: the Loop bus's own GPS position (reported in the same feed every 30 s)
    against the departure time the driver's device logged. Departure by GPS = last fix within 40 m of the stop in the
    15 minutes around the logged time."""
    import datetime as dt
    from .common import gtfs_for, haversine
    pos = {}
    for r in records("loop"):
        for lr in r.get("liveRides") or []:
            vs = lr.get("vehicleStatus") or {}; loc = vs.get("location") or {}; rid = (lr.get("ride") or {}).get("rideId")
            if rid and loc.get("lt") is not None:
                pos.setdefault(rid.rsplit(":", 1)[0] + "|" + rid.rsplit(":", 1)[1], []).append((r["poll"], loc["lt"], loc["lg"]))
    lv = pd.read_csv(OUT / "loop_visits.csv"); diffs = []
    for row in lv.itertuples():
        P = pos.get(f"{row.trip_id}|{row.date}")
        if not P: continue
        G = gtfs_for(row.date); xy = G["stop_xy"].get(row.stop_id)
        if not xy: continue
        near = [p for p, la, lo in P if abs(p - row.epoch) <= 900 and haversine(la, lo, xy[0], xy[1]) <= 40]
        if near: diffs.append((max(near) - row.epoch) / 60)
    d = np.array(diffs)
    out = dict(loop_departures=int(len(lv)), coverage_share=round(len(d) / len(lv) * 100, 1),
               within_1min_share_of_all=round(float((np.abs(d) <= 1).sum() / len(lv) * 100), 1), pairs=int(len(d)), median_diff_min=round(float(np.median(d)), 2), abs_p50=round(float(np.percentile(np.abs(d), 50)), 2),
               abs_p90=round(float(np.percentile(np.abs(d), 90)), 2), within_1min_share=round(float((np.abs(d) <= 1).mean() * 100), 1))
    print(f"  Loop GPS check: {out['pairs']:,} departures, {out['within_1min_share']}% within 1 min of the logged time, median {out['median_diff_min']} min")
    return out


def tu_check():
    """TigerTransit: our GPS-derived departure against the departure time TripShot itself publishes in its public
    trip-update feed. That feed (polled every 5 minutes) keeps stops a bus has already passed, with their actual times.
    A stop counts as passed when its published departure is at least 2 minutes before the poll; the latest such poll is used."""
    pub = {}
    for r in records("tu"):
        for x in r.get("stops") or []:
            dep = x.get("dep") or x.get("arr")
            if dep and r["poll"] - dep >= 120:
                pub[(r["trip_id"], x["stop_id"], x.get("seq"))] = (r["poll"], dep)   # records arrive in time order: the latest wins
    tt = pd.read_csv(OUT / "tt_arrivals.csv", dtype={"route": str}); tt = tt[tt.route != "WS"]
    d = []
    for trip, stop, seq, ep in zip(tt.trip_id, tt.stop_id, tt.seq, tt.epoch):
        v = pub.get((trip, stop, seq))
        if v and abs(v[1] - ep) < 1800: d.append((ep - v[1]) / 60)   # same trip on the same day (within 30 min)
    d = np.array(d)
    return dict(tigertransit_departures=int(len(tt)), pairs=int(len(d)), coverage_share=round(len(d) / len(tt) * 100, 1),
                median_diff_min=round(float(np.median(d)), 2), abs_p50=round(float(np.percentile(np.abs(d), 50)), 2),
                abs_p90=round(float(np.percentile(np.abs(d), 90)), 2), within_1min_share=round(float((np.abs(d) <= 1).mean() * 100), 1))
