"""Step 4. Replay timetable fixes on held-out weeks before anyone is asked to adopt them.

Re-timed schedule: every trip keeps its scheduled start. Each later stop is set at the p-th percentile of the time
buses actually took from the trip's first stop to that stop in the fitting weeks (by route, time-of-day band and stop
position), never earlier than the stop before it. One percentile per trip, not per segment, so padding does not pile up.

Replay, departure by departure, for all routes at once (a bus often drives several routes in a day):
  holding   a bus ahead of the (new) timetable waits until the scheduled time; the wait carries to its later stops.
            `comply` is the share of trips on which the driver waits (1 = every trip, 0.5 = half the trips, chosen at random).
  knock-on  if the replay makes a trip end later than it really did, the same bus's next trip starts later by whatever
            its real layover cannot absorb (layover beyond 3 min is slack). Unchanged days reproduce exactly (tested).
GTFS marks every stop as a timepoint, so holding is allowed at every stop.

Percentile per route chosen on a validation week (the last 20% of the October days) with a schedule fit on the earlier
October days; then refit on all of October and scored once on the test weeks (Nov 1 onward).
"""
from __future__ import annotations
import numpy as np, pandas as pd
from .common import OUT, save_json, split_day, gtfs_for

SPLIT = "2026-11-01"  # override with env POT_SPLIT; on a short sample the median day is used
MIN_LAYOVER = 3.0     # minutes a driver needs between trips
PCTS = [50, 60, 70, 80, 90]


def _score(d):
    d = np.asarray(d, float)
    return dict(on_time=round(float(np.mean((d >= -1) & (d <= 5)) * 100), 1), early=round(float(np.mean(d < -1) * 100), 1),
                late5=round(float(np.mean(d > 5) * 100), 1), median=round(float(np.median(d)), 2))


def _obs() -> pd.DataFrame:
    tt = pd.read_csv(OUT / "tt_arrivals.csv", dtype={"route": str}); lp = pd.read_csv(OUT / "loop_visits.csv", dtype={"route": str})
    df = pd.concat([tt[tt.route != "WS"], lp], ignore_index=True)
    dow = pd.to_datetime(df.date).dt.dayofweek
    df = df.sort_values(["date", "trip_id", "seq"]).reset_index(drop=True)
    g = df.groupby(["date", "trip_id"])
    df["first_sched"] = g.sched_s.transform("first"); df["first_seq"] = g.seq.transform("first"); df["first_act"] = g.actual_s.transform("first")
    df["first_stop"] = g.stop_id.transform("first")   # with first_seq, identifies the trip's stop pattern
    # one time band per trip, from its scheduled start, so a trip never mixes two bands
    df["band"] = pd.cut(df.first_sched / 3600, [0, 9, 15, 19, 30], labels=["am", "mid", "pm", "eve"]).astype(str) + np.where(dow >= 5, "_wkend", "")
    # scheduled end of each trip (its last stop in that day's timetable) and how many stops it has
    ends, lens, starts = {}, {}, {}
    for day in df.date.unique():
        st = gtfs_for(day)["st"]; e = st.groupby("trip_id").agg(start=("sched_s", "min"), end=("sched_s", "max"), n=("seq", "max"))
        for t in df.trip_id[df.date == day].unique():
            if t in e.index: ends[(day, t)] = float(e.end[t]); lens[(day, t)] = int(e.n[t]); starts[(day, t)] = float(e.start[t])
    key = list(zip(df.date, df.trip_id))
    df["sched_end"] = [ends.get(k, np.nan) for k in key]; df["n_stops"] = [lens.get(k, -1) for k in key]
    df["sched_start"] = [starts.get(k, np.nan) for k in key]
    # observed trip start: the first scored departure, moved back by the scheduled time from the trip's first stop to it
    df["obs_start"] = df.first_act - (df.first_sched - df.sched_start).fillna(0).clip(lower=0)
    # observed trip end: the Loop's final-stop arrival when logged, else the last observed departure plus the scheduled remainder
    last_s, last_a = g.sched_s.transform("last"), g.actual_s.transform("last")
    df["obs_end"] = last_a + (df.sched_end - last_s).fillna(0).clip(lower=0)
    lt = pd.read_csv(OUT / "loop_trips.csv", dtype={"route": str})
    if "end_s" in lt:
        le = {(d, t): e for d, t, e in zip(lt.date, lt.trip_id, lt.end_s) if e == e}
        fe = np.array([le.get(k, np.nan) for k in key]); df["obs_end"] = np.where(np.isnan(fe), df.obs_end, np.maximum(fe, last_a))
    return df[["date", "route", "trip_id", "stop_id", "stop", "seq", "sched_s", "actual_s", "veh", "band", "delay", "first_sched", "first_seq",
               "first_act", "first_stop", "sched_start", "sched_end", "n_stops", "obs_start", "obs_end"]]


def _fit(tr) -> pd.DataFrame:
    """Percentiles of elapsed time from the trip's first stop, for trips observed from their first stop.
    Trips with an unusual pause (elapsed time over 1.25 x the median for that stop) are left out of the fit."""
    t = tr[tr.first_seq == tr.groupby(["route"]).seq.transform("min")].copy(); t["elapsed"] = (t.actual_s - t.first_act) / 60
    t = t[(t.elapsed >= 0) & (t.elapsed < 240)]
    med = t.groupby(["route", "band", "first_stop", "stop_id", "seq"]).elapsed.transform("median")
    bad = t[t.elapsed > 1.25 * med + 2].set_index(["date", "trip_id"]).index.unique()
    t = t[~t.set_index(["date", "trip_id"]).index.isin(bad)]
    K = ["route", "band", "first_stop", "stop_id", "seq"]   # keyed by stop pattern: one route can run several
    q = t.groupby(K).elapsed.quantile([p / 100 for p in PCTS]).unstack(); q.columns = [f"p{p}" for p in PCTS]
    q["n"] = t.groupby(K).size()
    return q[q.n >= 5]


def _propose(df, q, pick: dict) -> pd.DataFrame:
    """New scheduled time for every row; `pick` maps route -> percentile (None keeps today's timetable)."""
    df = df.copy(); prop = df.sched_s.astype(float).values.copy(); first_of = df.groupby("route").seq.min().to_dict()
    lut = {k: q[[c for c in q.columns if c.startswith("p")]].loc[k].to_dict() for k in q.index}
    for i, (rt, band, f0, sid, seq, fs, fq) in enumerate(zip(df.route, df.band, df.first_stop, df.stop_id, df.seq, df.first_sched, df.first_seq)):
        p = pick.get(rt)
        if p is None or fq != first_of.get(rt): continue
        v = lut.get((rt, band, f0, sid, seq))
        if v is not None and seq != fq: prop[i] = fs + 60 * v[f"p{p}"]
    df["prop_s"] = prop
    df["prop_s"] = df.groupby(["date", "trip_id"]).prop_s.cummax()   # never earlier than the stop before
    return df


def _simulate(df, hold=True, comply=1.0, min_layover=MIN_LAYOVER, seed=0, timepoints=None):
    """Replay every vehicle-day (all routes together). Returns new lateness against the proposed times.
    comply = share of trips on which the driver waits when early (each trip decided at random, fixed seed)."""
    rng = np.random.default_rng(seed)
    df = df.sort_values(["veh", "date", "sched_s", "seq"]).copy()
    new = np.empty(len(df)); pos = {ix: i for i, ix in enumerate(df.index)}
    for (veh, date), g in df.groupby(["veh", "date"], sort=False):
        extra_end, prev_obs_end = 0.0, None
        for trip, gt in g.groupby("trip_id", sort=False):
            gt = gt.sort_values("seq"); act = gt.actual_s.values.astype(float); prop = gt.prop_s.values; end = float(gt.obs_end.iloc[0]) if "obs_end" in gt else act[-1]
            shift = 0.0
            if prev_obs_end is not None and extra_end > 0:
                start = float(gt.obs_start.iloc[0]) if "obs_start" in gt else act[0]   # the trip's real start, not its first scored stop
                slack = max(0.0, start - prev_obs_end - 60 * min_layover)
                shift = max(0.0, extra_end - slack)
            carry = 0.0; out = np.empty(len(gt)); waits = hold and (comply >= 1 or rng.random() < comply)
            # holding only at `timepoints` evenly spaced scheduled stops per trip (by stop number), or at every stop
            tp = None if not timepoints else set(np.round(np.linspace(gt.seq.min(), max(gt.seq.max(), int(gt.n_stops.iloc[0]) - 1 if "n_stops" in gt else gt.seq.max()), timepoints)).astype(int))
            for i in range(len(gt)):
                t = act[i] + shift + carry
                if waits and t < prop[i] and (tp is None or int(gt.seq.iloc[i]) in tp):
                    carry += prop[i] - t; t = prop[i]
                out[i] = t
            for ix, v in zip(gt.index, out): new[pos[ix]] = v
            extra_end = out[-1] - act[-1]; prev_obs_end = end   # the real trip end, including legs after the last observed stop
    df["new_delay"] = (new - df.prop_s.values) / 60
    return df


def _by_route(sim):
    return {rt: _score(g.new_delay) for rt, g in sim.groupby("route")}


def _half(P, seeds=20):
    """Waiting on a random half of trips: average over 20 random draws, with the range across draws."""
    runs = [_by_route(_simulate(P, comply=0.5, seed=k)) for k in range(seeds)]
    out = {}
    for r in runs[0]:
        vals = [x[r] for x in runs if r in x]
        out[r] = {k: round(float(np.mean([v[k] for v in vals])), 1) for k in vals[0]}
        out[r]["on_time_range"] = [min(v["on_time"] for v in vals), max(v["on_time"] for v in vals)]
    return out


def run():
    obs = _obs(); split = split_day(obs.date, SPLIT)
    tr, te = obs[obs.date < split], obs[obs.date >= split]
    vdays = sorted(tr.date.unique()); vsplit = vdays[max(1, int(len(vdays) * 0.8))]
    fit_v, val = tr[tr.date < vsplit], tr[tr.date >= vsplit]
    routes = sorted(obs.route.unique())
    # 1. choose each route's percentile on the validation days (full holding), or keep today's timetable
    qv = _fit(fit_v); vscore = {"current": _by_route(_simulate(_propose(val, qv, {}), hold=True))}
    for p in PCTS: vscore[p] = _by_route(_simulate(_propose(val, qv, {r: p for r in routes}), hold=True))
    pick = {}
    for r in routes:
        cand = {k: vscore[k][r]["on_time"] for k in vscore if r in vscore[k]}
        best = max(cand, key=cand.get); pick[r] = None if best == "current" else best
    # 2. refit on all fitting days; score every variant once on the test weeks
    q = _fit(tr); P_cur = _propose(te, q, {}); P_pick = _propose(te, q, pick)
    q.reset_index().round(2).to_csv(OUT / "timetable_segments.csv", index=False)   # minutes from the first stop, by route, band and stop
    # 95% intervals for the Loop Local gains, resampling whole test days (the replay's day-to-day noise)
    S_hold, S_rt = _simulate(P_cur, comply=1.0), _simulate(P_pick, comply=1.0)
    def daily(sim, col):
        x = sim[sim.route == "TPL"]; return x.groupby("date")[col].apply(lambda d: ((d >= -1) & (d <= 5)).mean() * 100), x.groupby("date").size()
    base_d, nb = daily(P_cur.assign(new_delay=P_cur.delay), "new_delay"); hold_d, _ = daily(S_hold, "new_delay"); rt_d, _ = daily(S_rt, "new_delay")
    rng = np.random.default_rng(4); dd = list(base_d.index); g_hold, g_rt = [], []
    for _ in range(1000):
        k = rng.choice(dd, len(dd)); w_ = nb.loc[k].values
        b0 = np.average(base_d.loc[k], weights=w_); g_hold.append(np.average(hold_d.loc[k], weights=w_) - b0); g_rt.append(np.average(rt_d.loc[k], weights=w_) - b0)
    gain_ci = {"today + hold": [round(float(np.percentile(g_hold, q)), 1) for q in (2.5, 97.5)],
               "re-timed + hold": [round(float(np.percentile(g_rt, q)), 1) for q in (2.5, 97.5)]}
    variants = {
        "today": _by_route(P_cur.assign(new_delay=P_cur.delay)),
        "today + hold (half)": _half(P_cur),
        "today + hold": _by_route(_simulate(P_cur, comply=1.0)),
        "today + hold at 4 timepoints": _by_route(_simulate(P_cur, comply=1.0, timepoints=4)),   # sensitivity: wait only at about 4 stops per trip
        "today + hold, no knock-on": _by_route(_simulate(P_cur, comply=1.0, min_layover=-1e6)),   # sensitivity: unlimited layover slack
        "re-timed, no hold": _by_route(_simulate(P_pick, hold=False)),
        "re-timed + hold (half)": _half(P_pick),
        "re-timed + hold": _by_route(_simulate(P_pick, comply=1.0)),
    }
    for p in PCTS:
        Pp = _propose(te, q, {r: p for r in routes})
        variants[f"p{p} everywhere + hold"] = _by_route(_simulate(Pp, comply=1.0))
    n = te.groupby("route").size()
    rows = [dict(route=r, timetable=k, n=int(n[r]), **v[r]) for k, v in variants.items() for r in routes if r in v]
    R = pd.DataFrame(rows); R.to_csv(OUT / "timetable_test.csv", index=False)
    tot = {k: round(float(sum(v[r]["on_time"] * n[r] for r in v) / n[list(v)].sum()), 1) for k, v in variants.items()}
    # 3. cost: median scheduled vs re-timed trip length on the test weeks, trips observed from the first stop to the last
    #    stop with a departure (the Loop's final stop is drop-off only, so its last departure is one stop earlier)
    cost = {}
    full = P_pick.groupby(["date", "trip_id"]).agg(route=("route", "first"), band=("band", "first"), fq=("seq", "min"), lq=("seq", "max"), ns=("n_stops", "first"),
                                                  s0=("sched_s", "first"), s1=("sched_s", "last"), p1=("prop_s", "last"), a0=("actual_s", "first"), a1=("actual_s", "last"))
    full = full[(full.fq <= 1) & (full.lq >= full.ns - 1)]   # last stops are drop-off only and never scored
    for (rt, band), g in full.groupby(["route", "band"]):
        if len(g) >= 10:
            cost[f"{rt}|{band}"] = dict(trips=int(len(g)), scheduled_min=round(float(((g.s1 - g.s0) / 60).median()), 1),
                                        retimed_min=round(float(((g.p1 - g.s0) / 60).median()), 1), actual_min=round(float(((g.a1 - g.a0) / 60).median()), 1))
    # scheduled layover between consecutive trips of the same bus, by route and band (median minutes)
    tr_ = te.groupby(["date", "veh", "trip_id"]).agg(route=("route", "first"), band=("band", "first"), s0=("sched_start", "first"), s1=("sched_end", "first")).reset_index()
    tr_ = tr_.sort_values(["date", "veh", "s0"]); tr_["gap"] = (tr_.groupby(["date", "veh"]).s0.shift(-1) - tr_.s1) / 60
    for (rt, band), g in tr_[(tr_.gap >= 0) & (tr_.gap < 60)].groupby(["route", "band"]):
        if f"{rt}|{band}" in cost: cost[f"{rt}|{band}"]["sched_layover_min"] = round(float(g.gap.median()), 1)
    # extra minutes for riders already on board: how much later each Loop Local trip ends when early buses wait on every trip
    hs = _simulate(P_cur, comply=1.0); hs = hs[hs.route == "TPL"].assign(new_t=lambda x: x.new_delay * 60 + x.prop_s)
    ends = hs.sort_values("seq").groupby(["date", "trip_id"]).agg(a0=("actual_s", "first"), n0=("new_t", "first"), a=("actual_s", "last"), n=("new_t", "last"))
    # waiting added within the trip (end shift minus any knock-on start delay carried from the bus's previous trip):
    # the most a rider on board for the whole trip waits
    onboard = round(float((((ends.n - ends.a) - (ends.n0 - ends.a0)) / 60).mean()), 2)
    per_route = {r: dict(pick=(f"p{pick[r]}" if pick[r] else "today's timetable"), **{k: variants[k][r]["on_time"] for k in variants if r in variants[k]}) for r in routes}
    half_ranges = {r: {k: variants[k][r]["on_time_range"] for k in ("today + hold (half)", "re-timed + hold (half)") if r in variants[k]} for r in routes}
    out = dict(loop_local_gain_ci95_points=gain_ci, loop_local_wait_added_min_per_trip=onboard, half_wait_ranges_20_draws=half_ranges, split=split, validation_days=[str(vsplit), str(vdays[-1])], test_days=int(te.date.nunique()), per_route=per_route, totals=tot, trip_length=cost)
    save_json(out, "timetable.json")
    print(R.pivot(index="route", columns="timetable", values="on_time").to_string()); print("  picks:", {r: per_route[r]["pick"] for r in routes}); print("  totals:", tot)
    return out
