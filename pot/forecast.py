"""Step 3. Predict each TigerTransit departure's lateness 30 minutes before it is due, and ask: does the graph help?

Issue time t0 = scheduled arrival - 30 min. Every feature uses only arrivals observed before t0.
Train: Sep 30 to Oct 31. Test: Nov 1 onward (days the model never saw).

Baselines
  B0 timetable          predict 0 (the bus is on schedule)
  B1 last bus           the delay of the most recent bus at this stop before t0
  B2 history            median delay for this route, stop and hour in the training weeks
Models (gradient-boosted trees, absolute-error loss)
  M1 local              calendar, stop, the trip's own latest delay, this stop's and route's recent delays, weather
  M2 local + graph      M1 plus the mean delay in the last 30 min at the stops one and two hops upstream on the
                        timetable network (the stop graph built from consecutive stops in GTFS)
"""
from __future__ import annotations
import datetime as dt, json
import numpy as np, pandas as pd
from sklearn.ensemble import HistGradientBoostingClassifier, HistGradientBoostingRegressor
from sklearn.metrics import roc_auc_score
from .common import OUT, TZ, gtfs, gtfs_snapshots, save_json, split_day

H = 30 * 60          # horizon, seconds
SPLIT = "2026-11-01"  # override with env POT_SPLIT; on a short sample the median day is used


def _epoch(date: str, sec: int) -> int:
    """Wall-clock time of a timetable entry (seconds after local midnight) as Unix time, correct across the Nov 1 clock change."""
    d = dt.date.fromisoformat(date) + dt.timedelta(days=int(sec) // 86400); s = int(sec) % 86400
    return int(dt.datetime(d.year, d.month, d.day, s // 3600, s % 3600 // 60, s % 60, tzinfo=TZ).timestamp())


class Window:
    """Mean of past delays in a time window, for one key (a stop, a route, or the whole system)."""
    def __init__(self, t, y):
        o = np.argsort(t); self.t = np.asarray(t)[o]; self.y = np.asarray(y)[o]
        self.c = np.concatenate([[0.0], np.cumsum(self.y)])
    def stats(self, t0, width):
        hi = np.searchsorted(self.t, t0, side="left"); lo = np.searchsorted(self.t, t0 - width, side="left")
        n = hi - lo; s = self.c[hi] - self.c[lo]
        return s, n
    def last(self, t0):
        hi = np.searchsorted(self.t, t0, side="left") - 1
        ok = hi >= 0
        val = np.where(ok, self.y[np.clip(hi, 0, None)], np.nan); age = np.where(ok, (t0 - self.t[np.clip(hi, 0, None)]) / 60, np.nan)
        return val, age


def stop_graph() -> dict[str, set]:
    """Upstream neighbours of every stop: stop a precedes stop b on some scheduled trip (any day, any route)."""
    up1 = {}
    for _, p in gtfs_snapshots():
        st = gtfs(p)["st"].sort_values(["trip_id", "seq"])
        a = st.stop_id.values; b = np.roll(a, -1); same = st.trip_id.values == np.roll(st.trip_id.values, -1)
        for x, y in zip(a[same], b[same]):
            if x != y: up1.setdefault(y, set()).add(x)
    up2 = {s: set().union(*(up1.get(u, set()) for u in us)) - us - {s} for s, us in up1.items()}
    return {"up1": up1, "up2": up2}


def build() -> pd.DataFrame:
    """One row per TigerTransit departure, with features known at t0 = scheduled time - 30 min."""
    df = pd.read_csv(OUT / "tt_arrivals.csv", dtype={"route": str}); df = df[df.route != "WS"].copy()
    wx = pd.read_csv(OUT / "weather.csv").set_index(["date", "hour"])
    df["sched_epoch"] = [_epoch(d, s) for d, s in zip(df.date, df.sched_s)]
    df["t0"] = df.sched_epoch - H
    df["hour"] = (df.sched_s // 3600).astype(int); df["dow"] = pd.to_datetime(df.date).dt.dayofweek
    df["weekend"] = (df.dow >= 5).astype(int); df["recess"] = df.date.between("2026-10-17", "2026-10-25").astype(int)
    df["progress"] = df.seq / df.trip_len.clip(lower=1)          # position in the trip from the timetable, not from what was observed
    # weather: the last full hour before the issue time t0
    lh = [(dt.datetime.fromtimestamp(t, TZ) - dt.timedelta(hours=1)) for t in df.t0]
    df["rain"] = [int(bool(wx.rain.get((x.date().isoformat(), x.hour), False))) for x in lh]
    df["temp"] = [wx.temp.get((x.date().isoformat(), x.hour), np.nan) for x in lh]
    t0 = df.t0.values
    feats = {}
    # system and route windows
    sysw = Window(df.epoch.values, df.delay.values); s, n = sysw.stats(t0, 1800)
    feats["sys_mean30"] = np.where(n > 0, s / np.maximum(n, 1), np.nan); feats["sys_n30"] = n
    feats["route_mean30"] = np.full(len(df), np.nan)
    for r, idx in df.groupby("route").indices.items():
        w = Window(df.epoch.values[idx], df.delay.values[idx]); s, n = w.stats(t0[idx], 1800)
        feats["route_mean30"][idx] = np.where(n > 0, s / np.maximum(n, 1), np.nan)
    # this stop: last bus and 60-min mean
    stop_w = {k: Window(df.epoch.values[i], df.delay.values[i]) for k, i in df.groupby("stop_id").indices.items()}
    feats["stop_last"] = np.full(len(df), np.nan); feats["stop_last_age"] = np.full(len(df), np.nan); feats["stop_mean60"] = np.full(len(df), np.nan)
    for k, idx in df.groupby("stop_id").indices.items():
        v, a = stop_w[k].last(t0[idx]); feats["stop_last"][idx] = v; feats["stop_last_age"][idx] = a
        s, n = stop_w[k].stats(t0[idx], 3600); feats["stop_mean60"][idx] = np.where(n > 0, s / np.maximum(n, 1), np.nan)
    # this trip: latest delay already observed on the same trip before t0
    feats["trip_last"] = np.full(len(df), np.nan)
    for k, idx in df.groupby(["date", "trip_id"]).indices.items():
        w = Window(df.epoch.values[idx], df.delay.values[idx]); v, _ = w.last(t0[idx]); feats["trip_last"][idx] = v
    # graph: upstream neighbours, 1 and 2 hops
    G = stop_graph()
    for hop in ("up1", "up2"):
        out = np.full(len(df), np.nan)
        for k, idx in df.groupby("stop_id").indices.items():
            S = np.zeros(len(idx)); N = np.zeros(len(idx))
            for u in G[hop].get(k, ()):
                if u in stop_w:
                    s, n = stop_w[u].stats(t0[idx], 1800); S += s; N += n
            out[idx] = np.where(N > 0, S / np.maximum(N, 1), np.nan)
        feats[f"graph_{hop}_mean30"] = out
    for k, v in feats.items(): df[k] = v
    # graph anomaly features: how much later than usual the upstream stops are running right now
    base = df[df.date < split_day(df.date, SPLIT)].groupby("stop_id").delay.median()
    df["anom"] = df.delay - df.stop_id.map(base).fillna(0)
    stop_a = {k: Window(df.epoch.values[i], df.anom.values[i]) for k, i in df.groupby("stop_id").indices.items()}
    for hop in ("up1", "up2"):
        out = np.full(len(df), np.nan)
        for k, idx in df.groupby("stop_id").indices.items():
            S = np.zeros(len(idx)); N = np.zeros(len(idx))
            for u in G[hop].get(k, ()):
                if u in stop_a:
                    s_, n_ = stop_a[u].stats(t0[idx], 1800); S += s_; N += n_
            out[idx] = np.where(N > 0, S / np.maximum(N, 1), np.nan)
        df[f"graph_{hop}_anom30"] = out
    df = df.drop(columns=["anom"])
    df["route_code"] = df.route.astype("category").cat.codes; df["stop_code"] = df.stop_id.astype("category").cat.codes
    return df


LOCAL = ["hour", "dow", "weekend", "recess", "route_code", "stop_code", "seq", "progress", "rain", "temp",
         "sys_mean30", "sys_n30", "route_mean30", "stop_last", "stop_last_age", "stop_mean60", "trip_last", "hist_med"]
GRAPH = LOCAL + ["graph_up1_mean30", "graph_up2_mean30", "graph_up1_anom30", "graph_up2_anom30"]


def _metrics(y, p):
    y = np.asarray(y); p = np.asarray(p); late, plate = y > 5, p > 5
    tp = int((late & plate).sum())
    return dict(mae=round(float(np.mean(np.abs(y - p))), 3), rmse=round(float(np.sqrt(np.mean((y - p) ** 2))), 3),
                late_precision=round(tp / max(int(plate.sum()), 1), 3), late_recall=round(tp / max(int(late.sum()), 1), 3))


def run():
    df = build()
    split = split_day(df.date, SPLIT)
    tr, te = df[df.date < split].copy(), df[df.date >= split].copy()
    def hist_table(d):
        return d.groupby(["route", "stop_id", "hour"]).delay.median(), d.groupby(["route", "stop_id"]).delay.median()
    def apply_hist(d, tabs):
        h, rs = tabs
        return [h.get((r, s, hh), rs.get((r, s), 0.0)) for r, s, hh in zip(d.route, d.stop_id, d.hour)]
    te["hist_med"] = apply_hist(te, hist_table(tr))
    # training rows get the history of the *other* training days (5 folds by day), so the feature is never in-sample
    days = np.array(sorted(tr.date.unique())); fold = {d: i % 5 for i, d in enumerate(days)}; tr["hist_med"] = 0.0
    for f in range(5):
        m = tr.date.map(fold) == f
        tr.loc[m, "hist_med"] = apply_hist(tr[m], hist_table(tr[~m]))
    preds = {"B0 timetable": np.zeros(len(te)), "B1 last bus at stop": te.stop_last.fillna(0).values, "B2 route-stop-hour history": te["hist_med"].values}
    importances = {}
    for name, cols in (("M1 local features", LOCAL), ("M2 local + graph", GRAPH)):
        cat = [cols.index("route_code"), cols.index("stop_code")]
        m = HistGradientBoostingRegressor(loss="absolute_error", max_iter=400, learning_rate=0.05, max_leaf_nodes=31,
                                          categorical_features=cat, random_state=0)
        m.fit(tr[cols], tr.delay); preds[name] = m.predict(te[cols])
    res = {k: _metrics(te.delay, p) for k, p in preds.items()}
    # Warning flags: probability that the arrival is more than 5 min late. Scored by AUC and by how many of the
    # 10% highest-risk arrivals were in fact late (a dispatcher could only act on a short list).
    ylate = (te.delay > 5).values; flags = {"B2 history (score = historical median)": te["hist_med"].values}
    for name, cols in (("M1 local features", LOCAL), ("M2 local + graph", GRAPH)):
        cat = [cols.index("route_code"), cols.index("stop_code")]
        c = HistGradientBoostingClassifier(max_iter=400, learning_rate=0.05, categorical_features=cat, random_state=0)
        c.fit(tr[cols], tr.delay > 5); flags[name] = c.predict_proba(te[cols])[:, 1]
    # AUC gain of the graph features, with a 95% interval from resampling test days
    a_l, a_g = flags["M1 local features"], flags["M2 local + graph"]; dd = te.date.values; uds = np.unique(dd); byd = {d: np.where(dd == d)[0] for d in uds}
    rng2 = np.random.default_rng(1); ag = []
    for _ in range(300):
        i = np.concatenate([byd[d] for d in rng2.choice(uds, len(uds))])
        if ylate[i].any() and (~ylate[i]).any(): ag.append(roc_auc_score(ylate[i], a_g[i]) - roc_auc_score(ylate[i], a_l[i]))
    auc_gain = dict(mean=round(float(np.mean(ag)), 4), ci95=[round(float(np.percentile(ag, 2.5)), 4), round(float(np.percentile(ag, 97.5)), 4)])
    warn = {}
    for k, sc in flags.items():
        top = sc >= np.quantile(sc, 0.9)
        warn[k] = dict(auc=round(float(roc_auc_score(ylate, sc)), 3), top10_late_share=round(float(ylate[top].mean() * 100), 1),
                       top10_catches=round(float(ylate[top].sum() / max(ylate.sum(), 1) * 100), 1))
    # 95% interval for the graph gain (MAE M1 minus MAE M2), resampling whole test days
    rng = np.random.default_rng(0); days = te.date.values; ud = np.unique(days); e1 = np.abs(te.delay.values - preds["M1 local features"]); e2 = np.abs(te.delay.values - preds["M2 local + graph"])
    eb = np.abs(te.delay.values - preds["B2 route-stop-hour history"])
    by = {d: np.where(days == d)[0] for d in ud}; gains, vs_hist = [], []
    for _ in range(1000):
        idx = np.concatenate([by[d] for d in rng.choice(ud, len(ud))]); gains.append(e1[idx].mean() - e2[idx].mean()); vs_hist.append(eb[idx].mean() - e2[idx].mean())
    out = dict(horizon_min=30, train_days=int(tr.date.nunique()), test_days=int(te.date.nunique()), n_train=int(len(tr)), n_test=int(len(te)),
               split=split, results=res, graph_gain_mae=dict(mean=round(float(np.mean(gains)), 3), ci95=[round(float(np.percentile(gains, 2.5)), 3), round(float(np.percentile(gains, 97.5)), 3)]),
               m2_vs_history_mae=dict(mean=round(float(np.mean(vs_hist)), 3), ci95=[round(float(np.percentile(vs_hist, 2.5)), 3), round(float(np.percentile(vs_hist, 97.5)), 3)]),
               test_late_share=round(float((te.delay > 5).mean() * 100), 1), late_warning=warn, graph_gain_auc=auc_gain)
    save_json(out, "forecast.json")
    te.assign(**{f"pred_{k.split()[0]}": v for k, v in preds.items()})[["date", "route", "stop", "delay"] + [f"pred_{k.split()[0]}" for k in preds]].to_csv(OUT / "forecast_test_predictions.csv", index=False)
    for k, v in res.items(): print(f"  {k:28s} MAE {v['mae']:.2f} min  RMSE {v['rmse']:.2f}  late>5 precision {v['late_precision']:.2f} recall {v['late_recall']:.2f}")
    print(f"  graph gain in MAE: {out['graph_gain_mae']}")
    for k, v in warn.items(): print(f"  late warning {k}: AUC {v['auc']}, top-10% flagged late {v['top10_late_share']}%, catches {v['top10_catches']}% of late arrivals")
    return out
