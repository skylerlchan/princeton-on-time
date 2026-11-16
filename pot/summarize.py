"""Step 2. Summary statistics behind every number in the poster and report -> results/summary.json and tables."""
from __future__ import annotations
import json
import numpy as np, pandas as pd
from .common import EARLY_MIN, LATE_MIN, OUT, save_json

SENIOR = ["Senior Resource", "Modern Aging", "Thanet Senior", "Elm Court", "Harriet Bryan"]


def _ot(d):
    """On-time share in percent; None when there are no departures (e.g. no weekend days in a short sample)."""
    d = np.asarray(d, float)
    return round(float(np.mean((d >= EARLY_MIN) & (d <= LATE_MIN)) * 100), 1) if len(d) else None


def _stats(d):
    d = np.asarray(d, float)
    if not len(d): return dict(n=0, on_time=None, early=None, late5=None, median=None, p90=None)
    return dict(n=int(len(d)), on_time=_ot(d), early=round(float(np.mean(d < EARLY_MIN) * 100), 1), late5=round(float(np.mean(d > LATE_MIN) * 100), 1),
                median=round(float(np.median(d)), 2), p90=round(float(np.percentile(d, 90)), 2))


def _boot_ci(d, B=1000, seed=0):
    """95% interval for the on-time share, resampling whole service days (arrivals on one day are not independent)."""
    rng = np.random.default_rng(seed)
    if not len(d): return None
    days = {k: g.delay.values for k, g in d.groupby("date")}
    keys = list(days); vals = []
    for _ in range(B):
        pick = rng.choice(keys, len(keys))
        x = np.concatenate([days[k] for k in pick]); vals.append(_ot(x))
    return [round(float(np.percentile(vals, 2.5)), 1), round(float(np.percentile(vals, 97.5)), 1)]


def run():
    S = {}
    tt = pd.read_csv(OUT / "tt_arrivals.csv", dtype={"route": str, "train": str}); tt = tt[tt.route != "WS"]
    loop = pd.read_csv(OUT / "loop_visits.csv", dtype={"route": str, "train": str}); skips = pd.read_csv(OUT / "loop_skips.csv", dtype={"route": str, "train": str})
    rail = pd.read_csv(OUT / "rail.csv", dtype={"route": str, "train": str}); bus = pd.read_csv(OUT / "njt_bus.csv", dtype={"route": str, "train": str}); bus = bus[bus.route.isin(["600", "605", "606"])]
    wx = pd.read_csv(OUT / "weather.csv", dtype={"route": str, "train": str}); cov = json.load(open(OUT / "coverage.json"))
    for df in (tt, loop):
        df["dow"] = pd.to_datetime(df.date).dt.dayofweek; df["hour"] = (df.sched_s // 3600).astype(int)
        df["weekend"] = df.dow >= 5
        df["recess"] = df.date.between("2026-10-17", "2026-10-25")
    nec = rail[(rail.line == "NEC") & rail.delay.notna()].copy()
    # A train does not leave early. The board's last countdown can read a minute or two under the true time, so negative
    # estimates are set to 0 (on time); the early share for trains is therefore 0 by definition.
    S["nec_negative_estimates_share"] = round(float((nec.delay < 0).mean() * 100), 1)
    S["nec_on_time_unclipped"] = _ot(nec.delay)   # counting negative estimates as early, not on time: the lower bound
    nec["delay"] = nec.delay.clip(lower=0)
    S["coverage"] = cov
    S["services"] = {
        "TigerTransit": {**_stats(tt.delay), "ci95": _boot_ci(tt), "days": int(tt.date.nunique())},
        "Loop": {**_stats(loop.delay), "ci95": _boot_ci(loop), "days": int(loop.date.nunique())},
        "NJT bus 600/605/606": {**_stats(bus.delay), "ci95": _boot_ci(bus), "days": int(bus.date.nunique())},
        "NEC trains, Princeton Jct": {**_stats(nec.delay), "ci95": _boot_ci(nec), "days": int(nec.date.nunique())},
    }
    S["tt_route"] = {r: _stats(g.delay) for r, g in tt.groupby("route")}
    S["loop_route"] = {r: {**_stats(g.delay), "ci95": _boot_ci(g)} for r, g in loop.groupby("route")}
    S["bus_route"] = {r: _stats(g.delay) for r, g in bus.groupby("route")}
    stop = tt.groupby(["route", "stop"]).delay.agg(n="size", median="median", late5=lambda d: (d > LATE_MIN).mean() * 100, early=lambda d: (d < EARLY_MIN).mean() * 100).reset_index()
    stop = stop[stop.n >= 100]
    S["tt_worst_stops"] = stop.sort_values("median", ascending=False).head(8).round(1).to_dict("records")
    S["tt_earliest_stops"] = stop.sort_values("median").head(6).round(1).to_dict("records")
    lstop = loop.groupby(["route", "stop"]).delay.agg(n="size", median="median", late5=lambda d: (d > LATE_MIN).mean() * 100).reset_index()
    S["loop_worst_stops"] = lstop[lstop.n >= 50].sort_values("median", ascending=False).head(6).round(1).to_dict("records")
    S["tt_hour_weekday"] = tt[~tt.weekend & ~tt.recess].groupby("hour").delay.agg(median="median", p90=lambda d: d.quantile(.9), n="size").round(2).reset_index().to_dict("records")
    S["loop_hour"] = loop[~loop.weekend & ~loop.recess].groupby("hour").delay.agg(median="median", p90=lambda d: d.quantile(.9), n="size").query("n>=50").round(2).reset_index().to_dict("records")
    S["tt_day"] = tt.groupby("date").delay.agg(n="size", on_time=_ot).reset_index().to_dict("records")
    S["loop_day"] = loop.groupby("date").delay.agg(n="size", on_time=_ot).reset_index().to_dict("records")
    S["weekday_vs_weekend"] = {"TigerTransit": {"weekday": _ot(tt[~tt.weekend].delay), "weekend": _ot(tt[tt.weekend].delay)},
                               "Loop": {"weekday": _ot(loop[~loop.weekend].delay), "weekend": _ot(loop[loop.weekend].delay)}}
    S["recess"] = {"TigerTransit": {"term": _ot(tt[~tt.recess].delay), "recess": _ot(tt[tt.recess].delay)},
                   "Loop": {"term": _ot(loop[~loop.recess].delay), "recess": _ot(loop[loop.recess].delay)}}
    # skipped Loop stops
    sched_visits = len(loop) + len(skips)
    S["loop_skips"] = dict(total=int(len(skips)), share_of_visits=round(len(skips) / sched_visits * 100, 1),
                           by_route=skips.route.value_counts().to_dict(), by_stop=skips.stop.value_counts().head(10).to_dict(),
                           by_hour=skips.hour.value_counts().sort_index().to_dict(), by_date=skips.date.value_counts().sort_index().to_dict())
    # senior stops = stops named for senior housing or senior services (no other stop is labelled senior here)
    is_sen = lambda x: x.str.contains("|".join(SENIOR), case=False)
    served, skipped = loop.groupby("stop").size(), skips.groupby("stop").size()
    rate = pd.concat([served.rename("served"), skipped.rename("skipped")], axis=1).fillna(0)
    rate["rate"] = rate.skipped / (rate.served + rate.skipped) * 100
    S["loop_skips"]["by_stop_rate"] = rate.sort_values("rate", ascending=False).head(10).round(1).reset_index().rename(columns={"index": "stop"}).to_dict("records")
    sen = rate[is_sen(rate.index.to_series())]; oth = rate[~is_sen(rate.index.to_series())]
    # the fair comparison is within the Loop Local, which serves every senior stop (the Express skips far less)
    lv, ls = loop[loop.route == "TPL"], skips[skips.route == "TPL"]
    rl = pd.concat([lv.groupby("stop").size().rename("served"), ls.groupby("stop").size().rename("skipped")], axis=1).fillna(0)
    sl, ol = rl[is_sen(rl.index.to_series())], rl[~is_sen(rl.index.to_series())]
    S["loop_skips"]["local_senior_skip_rate"] = round(float(sl.skipped.sum() / (sl.served.sum() + sl.skipped.sum()) * 100), 1)
    S["loop_skips"]["local_other_skip_rate"] = round(float(ol.skipped.sum() / (ol.served.sum() + ol.skipped.sum()) * 100), 1)
    S["loop_skips"]["local_skip_rate"] = round(float(rl.skipped.sum() / (rl.served.sum() + rl.skipped.sum()) * 100), 1)
    S["loop_skips"]["senior_by_stop"] = {k: round(float(v.skipped / (v.served + v.skipped) * 100), 1) for k, v in sl.iterrows()}
    S["loop_skips"]["senior_stops"] = list(sen.index)
    S["loop_skips"]["senior_skip_rate"] = round(float(sen.skipped.sum() / (sen.served.sum() + sen.skipped.sum()) * 100), 1)
    S["loop_skips"]["other_skip_rate"] = round(float(oth.skipped.sum() / (oth.served.sum() + oth.skipped.sum()) * 100), 1)
    S["loop_skips"]["senior_share_of_skips"] = round(float(is_sen(skips.stop).mean() * 100), 1)
    lvh, lsh = lv.hour if "hour" in lv else lv.sched_s // 3600, ls.hour
    ev = int((lvh >= 19).sum()); es = int((lsh >= 19).sum())
    S["loop_skips"]["local_after7_skip_rate"] = round(float(es / (ev + es) * 100), 1)
    S["loop_skips"]["local_before7_skip_rate"] = round(float((len(ls) - es) / (len(lv) - ev + len(ls) - es) * 100), 1)
    S["loop_skips"]["local_after7_skips"] = es
    # is the senior gap only an evening effect? senior vs other Loop Local stops, before and after 7 pm,
    # and a 95% interval for the senior minus other gap from resampling whole service days
    vv = lv.assign(sk=0, h=lvh)[["date", "stop", "h", "sk"]]; ss = ls.assign(sk=1, h=lsh)[["date", "stop", "h", "sk"]]
    al = pd.concat([vv, ss], ignore_index=True); al["sen"] = is_sen(al.stop)
    rt = lambda x: round(float(x.sk.mean() * 100), 1) if len(x) else float("nan")
    S["loop_skips"]["senior_by_period"] = {per: dict(senior=rt(al[m & al.sen]), other=rt(al[m & ~al.sen]))
                                           for per, m in [("before_7pm", al.h < 19), ("after_7pm", al.h >= 19)]}
    rng = np.random.default_rng(2); dg = {k: g for k, g in al.groupby("date")}; dk_ = list(dg); gaps = []
    for _ in range(1000):
        x = pd.concat([dg[k] for k in rng.choice(dk_, len(dk_))]); gaps.append(x[x.sen].sk.mean() * 100 - x[~x.sen].sk.mean() * 100)
    S["loop_skips"]["local_senior_gap_ci95"] = [round(float(np.percentile(gaps, 2.5)), 1), round(float(np.percentile(gaps, 97.5)), 1)]
    # leave one senior stop out at a time: is the gap driven by a single stop?
    S["loop_skips"]["senior_leave_one_out"] = {x: round(float(al[al.sen & ~al.stop.str.contains(x, case=False)].sk.mean() * 100), 1) for x in SENIOR}
    S["loop_skips"]["senior_resource_skips_by_hour"] = {int(k): int(v) for k, v in ls[ls.stop.str.contains("Senior Resource")].hour.value_counts().sort_index().items()}
    # visits never marked served or skipped (state still Awaiting when the ride record closed), final stop excluded
    un = pd.read_csv(OUT / "loop_unserved.csv", dtype={"route": str}); trips_ = pd.read_csv(OUT / "loop_trips.csv", dtype={"route": str})
    S["loop_unserved"] = {r: dict(unmarked_visits=int(((un.route == r) & un.trip_ran).sum()), trips_never_served=int(((trips_.route == r) & ~trips_.ran).sum()),
                                  trips=int((trips_.route == r).sum())) for r in ["TPL", "TPLEXP"]}
    u_l = S["loop_unserved"]["TPL"]["unmarked_visits"]
    S["loop_skips"]["local_skip_rate_upper"] = round(float((len(ls) + u_l) / (len(lv) + len(ls) + u_l) * 100), 1)
    S["loop_skips"]["service_days"] = int(loop.date.nunique()); S["loop_skips"]["note"] = "the Loop does not run on Sundays"
    # rail
    S["nec"] = dict(**_stats(nec.delay), cancelled=int(rail[(rail.line == "NEC")].cancelled.sum()), departures=int((rail.line == "NEC").sum()),
                    max=round(float(nec.delay.max()), 1),
                    weekday_late5=round(float((nec[pd.to_datetime(nec.date).dt.dayofweek < 5].delay > 5).mean() * 100), 1),
                    weekend_late5=round(float((nec[pd.to_datetime(nec.date).dt.dayofweek >= 5].delay > 5).mean() * 100), 1))
    dk = rail[(rail.line == "PRIN") & (rail.station == "Princeton Junction")]
    S["dinky"] = dict(runs=int(len(dk)), cancelled=int(dk.cancelled.sum()), cancel_share=round(float(dk.cancelled.mean() * 100), 1))
    S["nec_day"] = nec.groupby("date").delay.agg(n="size", late5=lambda d: round((d > 5).mean() * 100, 1)).reset_index().to_dict("records")
    # weather: on-time share in rain hours vs dry hours (TigerTransit)
    w = wx.set_index(["date", "hour"]).rain
    def wkey(d, h):   # a departure at 24:30 of one service day falls in hour 0 of the next calendar day
        return (d, h) if h < 24 else ((pd.Timestamp(d) + pd.Timedelta(days=1)).date().isoformat(), h - 24)
    tt["rain"] = [bool(w.get(wkey(d, h), False)) for d, h in zip(tt.date, tt.hour)]
    # rain minus dry on-time share, with a 95% interval from resampling whole days
    rng = np.random.default_rng(1); days = {k: g for k, g in tt.groupby("date")}; keys = list(days); diffs = []
    for _ in range(1000):
        x = pd.concat([days[k] for k in rng.choice(keys, len(keys))])
        if x.rain.any(): diffs.append(_ot(x[x.rain].delay) - _ot(x[~x.rain].delay))
    S["weather"] = dict(hours=int(len(wx)), rain_hours=int(wx.rain.sum()), rain_days=int(wx[wx.rain].date.nunique()),
                        tt_on_time_rain=_ot(tt[tt.rain].delay), tt_on_time_dry=_ot(tt[~tt.rain].delay), tt_n_rain=int(tt.rain.sum()),
                        rain_minus_dry_ci95=[round(float(np.percentile(diffs, 2.5)), 1), round(float(np.percentile(diffs, 97.5)), 1)] if diffs else None)
    # the same test on the Loop (Local and Express together)
    lw = loop.assign(hour=loop.sched_s // 3600); lw["rain"] = [bool(w.get(wkey(d, h), False)) for d, h in zip(lw.date, lw.hour)]
    rng = np.random.default_rng(3); ldays = {k: g for k, g in lw.groupby("date")}; lk = list(ldays); ld = []
    for _ in range(1000):
        x = pd.concat([ldays[k] for k in rng.choice(lk, len(lk))])
        if x.rain.any() and (~x.rain).any(): ld.append(_ot(x[x.rain].delay) - _ot(x[~x.rain].delay))
    # same comparison within each hour of the day (rain vs dry at the same hour, weighted by rain departures), removing time-of-day mix
    def by_hour(d):
        g = d.assign(ot=d.delay.between(EARLY_MIN, LATE_MIN)).groupby(["hour", "rain"]).ot.agg(["mean", "size"]).unstack("rain").dropna()
        return round(float(((g[("mean", True)] - g[("mean", False)]) * g[("size", True)]).sum() / g[("size", True)].sum() * 100), 1)
    S["weather"]["tt_rain_minus_dry_same_hour"] = by_hour(tt); S["weather"]["loop_rain_minus_dry_same_hour"] = by_hour(lw)
    S["weather"].update(loop_on_time_rain=_ot(lw[lw.rain].delay), loop_on_time_dry=_ot(lw[~lw.rain].delay), loop_n_rain=int(lw.rain.sum()),
                        loop_rain_minus_dry_ci95=[round(float(np.percentile(ld, 2.5)), 1), round(float(np.percentile(ld, 97.5)), 1)] if ld else None)
    # how TigerTransit departures were timed: GPS fix within 40 m, or the moment the next-stop field moved on
    S["tt_method"] = {"passed_share": round(float((tt.how == "passed").mean() * 100), 1),
                      "median_delay_radius": round(float(tt[tt.how == "radius"].delay.median()), 2),
                      "median_delay_passed": round(float(tt[tt.how == "passed"].delay.median()), 2),
                      "ws_excluded": int(len(pd.read_csv(OUT / "tt_arrivals.csv", dtype={"route": str}).query("route == 'WS'")))}
    # arrival-based view, for comparison with the proposal's earlier figures
    S["arrival_based"] = {"TigerTransit": _stats(tt.arr_delay), "Loop": _stats(loop.arr_delay)}
    trips = pd.read_csv(OUT / "loop_trips.csv", dtype={"route": str})
    S["loop_riders_note"] = "highest rider count the operator's ride record reported during the trip (peak load, not boardings); meaning undocumented"
    S["loop_riders"] = {r: dict(trips=int(len(g)), mean_riders=round(float(g.riders.mean()), 2), median_riders=float(g.riders.median()),
                                zero_rider_share=round(float((g.riders == 0).mean() * 100), 1)) for r, g in trips.groupby("route")}
    save_json(S, "summary.json")
    stop.round(2).to_csv(OUT / "tt_stops.csv", index=False)
    print("  " + "; ".join(f"{k} {v['on_time']}% on time (n={v['n']:,})" for k, v in S["services"].items()))
    return S
