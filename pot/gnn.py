"""Step 3b. Does the graph help? A spatio-temporal graph network against the same network without its edges.

Every TigerTransit stop is a node; an edge joins two stops that follow each other on any scheduled trip. For each
10-minute slot, each node carries how much later than usual its departures were (anomaly = delay minus the stop's
usual delay at that hour) and how many departures it saw. To predict a departure 30 minutes ahead, the model reads the
three slots that ended before the issue time t0, mixes each node with its neighbours (two graph-convolution layers),
runs a GRU over the three slots, and adds the result to the departure's historical median. It also sees the trip's own
latest departure before t0, as the boosted trees do.

The ablation is identical except that the adjacency matrix is the identity, so no information flows between stops.
Same data, same split as step 3 (train Sep 30 to Oct 31, test Nov 1 onward), three seeds each.
"""
from __future__ import annotations
import numpy as np, pandas as pd, torch
from .common import OUT, save_json, split_day
from .forecast import H, SPLIT, Window, _epoch, stop_graph

SLOT = 600; WIN = 3; SEEDS = (0, 1, 2)


def _data():
    df = pd.read_csv(OUT / "tt_arrivals.csv", dtype={"route": str}); df = df[df.route != "WS"].copy()
    df["sched_epoch"] = [_epoch(d, s) for d, s in zip(df.date, df.sched_s)]; df["t0"] = df.sched_epoch - H
    df["hour"] = (df.sched_s // 3600).astype(int); df["dow"] = pd.to_datetime(df.date).dt.dayofweek
    split = split_day(df.date, SPLIT); tr = df.date < split
    # usual delay by stop and hour, from training days only; training rows get out-of-fold values (5 folds by day)
    def table(d): return d.groupby(["stop_id", "hour"]).delay.median(), d.groupby("stop_id").delay.median()
    def look(d, t): h, s = t; return np.array([h.get((a, b), s.get(a, 0.0)) for a, b in zip(d.stop_id, d.hour)])
    df["base"] = 0.0; df.loc[~tr, "base"] = look(df[~tr], table(df[tr]))
    days = sorted(df[tr].date.unique()); fold = {d: i % 5 for i, d in enumerate(days)}
    for f in range(5):
        m = tr & (df.date.map(fold) == f); df.loc[m, "base"] = look(df[m], table(df[tr & (df.date.map(fold) != f)]))
    df["anom"] = df.delay - df.base
    # the trip's own latest departure before t0 (the strongest local signal, also given to the boosted trees)
    tl = np.full(len(df), np.nan); t0 = df.t0.values
    for _, i in df.groupby(["date", "trip_id"]).indices.items():
        v, _a = Window(df.epoch.values[i], df.delay.values[i]).last(t0[i]); tl[i] = v
    df["trip_last"] = np.nan_to_num(tl, nan=0.0); df["trip_seen"] = (~np.isnan(tl)).astype(float)
    return df, split


def _tensors(df):
    stops = sorted(df.stop_id.unique()); idx = {s: i for i, s in enumerate(stops)}; N = len(stops)
    up = stop_graph()["up1"]; A = np.eye(N, dtype=np.float32)
    for b, us in up.items():
        for a in us:
            if a in idx and b in idx: A[idx[a], idx[b]] = A[idx[b], idx[a]] = 1.0
    d = A.sum(1); Ahat = A / np.sqrt(np.outer(d, d))
    s0 = int(min(df.epoch.min(), df.t0.min()) // SLOT) - WIN - 2; T = int(max(df.epoch.max(), df.t0.max()) // SLOT) - s0 + 2
    X = np.zeros((T, N, 3), np.float32)      # mean anomaly, number of departures, any departure seen
    sl = (df.epoch // SLOT).astype(int) - s0; ni = df.stop_id.map(idx).values
    np.add.at(X[:, :, 0], (sl.values, ni), df.anom.values); np.add.at(X[:, :, 1], (sl.values, ni), 1.0)
    X[:, :, 0] = np.where(X[:, :, 1] > 0, X[:, :, 0] / np.maximum(X[:, :, 1], 1), 0.0); X[:, :, 2] = (X[:, :, 1] > 0)
    X[:, :, 1] = np.log1p(X[:, :, 1])
    last = (df.t0 // SLOT).astype(int).values - s0 - 1          # the last slot that ended at or before t0
    cal = np.stack([np.sin(2 * np.pi * df.hour / 24), np.cos(2 * np.pi * df.hour / 24), (df.dow >= 5).astype(float),
                    df.seq / df.trip_len.clip(lower=1), df.base, df.trip_last, df.trip_seen], 1).astype(np.float32)
    return torch.tensor(X), torch.tensor(Ahat), torch.tensor(last), torch.tensor(ni), torch.tensor(cal), N


class STGNN(torch.nn.Module):
    def __init__(self, A, hid=32):
        super().__init__(); self.register_buffer("A", A)
        self.g1 = torch.nn.Linear(3, hid); self.g2 = torch.nn.Linear(hid, hid)
        self.gru = torch.nn.GRU(hid, hid, batch_first=True)
        self.head = torch.nn.Sequential(torch.nn.Linear(hid + 7, 64), torch.nn.ReLU(), torch.nn.Linear(64, 1))
    def forward(self, Xw, node, cal):                            # Xw: (B, WIN, N, 3)
        h = torch.relu(self.A @ self.g1(Xw)); h = torch.relu(self.A @ self.g2(h))
        h = h[torch.arange(len(node)), :, node, :]               # (B, WIN, hid) for the departure's own stop
        _, z = self.gru(h); z = z[-1]
        return cal[:, 4] + self.head(torch.cat([z, cal], 1)).squeeze(1)   # historical median + learned correction


def _fit(X, A, last, node, cal, y, tr_i, te_i, seed, epochs=12):
    torch.manual_seed(seed); np.random.seed(seed)
    m = STGNN(A); opt = torch.optim.Adam(m.parameters(), lr=2e-3)
    win = lambda i: X[(last[i][:, None] - torch.arange(WIN - 1, -1, -1)[None, :]).clamp(min=0)]
    for _ in range(epochs):
        perm = tr_i[torch.randperm(len(tr_i))]
        for k in range(0, len(perm), 512):
            b = perm[k:k + 512]; loss = (m(win(b), node[b], cal[b]) - y[b]).abs().mean()
            opt.zero_grad(); loss.backward(); opt.step()
    with torch.no_grad():
        return torch.cat([m(win(te_i[k:k + 2048]), node[te_i[k:k + 2048]], cal[te_i[k:k + 2048]]) for k in range(0, len(te_i), 2048)]).numpy()


def run():
    torch.set_num_threads(max(1, torch.get_num_threads()))
    df, split = _data(); X, A, last, node, cal, N = _tensors(df)
    y = torch.tensor(df.delay.values, dtype=torch.float32)
    tr_i = torch.tensor(np.where(df.date < split)[0]); te_i = torch.tensor(np.where(df.date >= split)[0])
    yt = df.delay.values[te_i.numpy()]; days = df.date.values[te_i.numpy()]
    preds = {"graph": [], "no graph": []}
    for seed in SEEDS:
        preds["graph"].append(_fit(X, A, last, node, cal, y, tr_i, te_i, seed))
        preds["no graph"].append(_fit(X, torch.eye(N), last, node, cal, y, tr_i, te_i, seed))
    P = {k: np.mean(v, 0) for k, v in preds.items()}; P["history (stop and hour)"] = cal[te_i, 4].numpy()
    mae = {k: round(float(np.mean(np.abs(yt - p))), 3) for k, p in P.items()}
    per_seed = {k: [round(float(np.mean(np.abs(yt - p))), 3) for p in v] for k, v in preds.items()}
    rng = np.random.default_rng(0); ud = np.unique(days); by = {d: np.where(days == d)[0] for d in ud}
    eg, en = np.abs(yt - P["graph"]), np.abs(yt - P["no graph"]); gains = []
    for _ in range(1000):
        i = np.concatenate([by[d] for d in rng.choice(ud, len(ud))]); gains.append(en[i].mean() - eg[i].mean())
    out = dict(nodes=int(N), slots_per_window=WIN, slot_min=SLOT // 60, seeds=list(SEEDS), mae=mae, mae_per_seed=per_seed,
               graph_gain_mae=dict(mean=round(float(np.mean(gains)), 3), ci95=[round(float(np.percentile(gains, 2.5)), 3), round(float(np.percentile(gains, 97.5)), 3)]),
               n_train=int(len(tr_i)), n_test=int(len(te_i)))
    save_json(out, "gnn.json")
    print(f"  graph network MAE {mae['graph']}, same network without edges {mae['no graph']}, stop-hour history {mae['history (stop and hour)']}; graph gain {out['graph_gain_mae']}")
    return out
