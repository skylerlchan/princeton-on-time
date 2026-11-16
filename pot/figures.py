"""Step 5. Every figure in the poster and report, drawn from results/ only."""
from __future__ import annotations
import json, math
import matplotlib; matplotlib.use("Agg")
import matplotlib.pyplot as plt, numpy as np, pandas as pd
from .common import FIG, OUT

DARK, AMBER, PAPER, TEAL, RED, INK, MUTE, GREY = "#102A30", "#F2B134", "#FFFFFF", "#5C8F94", "#C8443F", "#1C2A2E", "#5E6E72", "#C9CED0"
plt.rcParams.update({"font.family": "DejaVu Sans", "font.size": 13, "xtick.labelsize": 12, "ytick.labelsize": 12, "legend.fontsize": 11, "axes.edgecolor": MUTE, "axes.labelcolor": INK, "xtick.color": INK,
                     "ytick.color": INK, "axes.spines.top": False, "axes.spines.right": False, "figure.dpi": 200})


def _save(fig, name):
    FIG.mkdir(parents=True, exist_ok=True); fig.savefig(FIG / name, bbox_inches="tight", facecolor="white", dpi=300); plt.close(fig)


def scorecard(S):
    rows = [("TigerTransit (campus)", S["services"]["TigerTransit"]), ("Loop Express", S["loop_route"]["TPLEXP"]),
            ("Loop Local", S["loop_route"]["TPL"]), ("NJ Transit 600/605/606", S["services"]["NJT bus 600/605/606"]),
            ("NEC trains (range)", S["services"]["NEC trains, Princeton Jct"])]
    fig, ax = plt.subplots(figsize=(7, 3.2))
    names = [r[0] for r in rows][::-1]; vals = [r[1]["on_time"] for r in rows][::-1]; ns = [r[1]["n"] for r in rows][::-1]
    cols = [DARK if v >= 80 else RED for v in vals]
    est = [n.startswith(("NJ Transit", "NEC")) for n in names]
    bars = ax.barh(names, vals, color=cols, height=0.62)
    ci = [r[1].get("ci95") for r in rows][::-1]
    for i, (c, n_) in enumerate(zip(ci, names)):   # 95% intervals from resampling days (not for the train range)
        if c and not n_.startswith("NEC"): [ax.plot(xx, yy, color="#B8C2C4", lw=2) for xx, yy in ((c, [i, i]), ([c[0]] * 2, [i - 0.15, i + 0.15]), ([c[1]] * 2, [i - 0.15, i + 0.15]))]
    for b_, e in zip(bars, est):
        if e: b_.set_hatch("///"); b_.set_edgecolor("white")
    lo = S.get("nec_on_time_unclipped")   # trains: the true share lies between the two ways of reading the countdown
    for i, (v, n) in enumerate(zip(vals, ns)):
        if names[i].startswith("NEC") and lo:
            bars[i].set_width(lo); ax.barh(i, v - lo, left=lo, color="#F4C7C4", height=0.62, hatch="///", edgecolor="white")
            ax.text(v + 1, i, f"{lo:.0f}-{v:.0f}%", va="center", fontsize=11, fontweight="bold", color=INK)
            ax.text(2, i, f"n={n:,}", va="center", fontsize=11, color="white", fontweight="bold", bbox=dict(facecolor="#00000055", edgecolor="none", pad=1)); continue
        ax.text(max(v, (ci[i] or [v, v])[1]) + 1, i, f"{v:.1f}%" if v % 1 else f"{v:.0f}%", va="center", fontsize=11, fontweight="bold", color=INK)
        ax.text(2, i, f"n={n:,}", va="center", fontsize=11, color="white", fontweight="bold", bbox=dict(facecolor="#00000055", edgecolor="none", pad=1))
    ax.axvline(80, color=AMBER, lw=2, ls="--"); ax.text(80.5, len(rows) - 0.45, "80% benchmark", color="#8A6200", fontsize=11)
    ax.set_xlim(0, 100); ax.set_xlabel("Departures within 1 min early to 5 min late (%)")
    _save(fig, "fig1_scorecard.png")


def hours(S):
    t = pd.DataFrame(S["tt_hour_weekday"]); l = pd.DataFrame(S["loop_hour"])
    t = t[(t.n >= 200) & (t.hour < 24)]
    fig, ax = plt.subplots(figsize=(7, 3.2))
    ax.fill_between(t.hour, t["median"], t.p90, color=TEAL, alpha=0.18, lw=0, label="TigerTransit, median to 90th pct")
    ax.plot(t.hour, t["median"], color=TEAL, lw=2, label="TigerTransit median")
    ax.plot(l.hour, l["median"], color=RED, lw=2, label="Loop median")
    ax.plot(l.hour, l.p90, color=RED, lw=1.3, ls="--", label="Loop 90th pct")
    ax.axhline(5, color=AMBER, lw=1.2, ls=":"); ax.text(t.hour.max() - 0.2, 5.2, "5 min = late", color="#8A6200", fontsize=11, ha="right")
    ax.set_xticks(range(int(t.hour.min()), int(t.hour.max()) + 1, 2)); ax.set_xticklabels([f"{h}:00" for h in range(int(t.hour.min()), int(t.hour.max()) + 1, 2)], fontsize=11)
    ax.set_ylim(-0.5, 10); ax.set_xlabel("Scheduled hour (weekdays, term time)"); ax.set_ylabel("Minutes behind timetable")
    ax.legend(frameon=False, fontsize=11, loc="upper center", ncol=2, bbox_to_anchor=(0.5, 1.18))
    _save(fig, "fig3_hours.png")


def daily(S):
    t = pd.DataFrame(S["tt_day"]); l = pd.DataFrame(S["loop_day"])
    t = t[t.n >= 100]; l = l[l.n >= 50]
    fig, ax = plt.subplots(figsize=(7, 3))
    ax.axvspan(pd.Timestamp("2026-10-17"), pd.Timestamp("2026-10-25"), color=GREY, alpha=0.35, lw=0)
    ax.text(pd.Timestamp("2026-10-17 12:00"), 52, "fall recess", fontsize=11, color=MUTE)
    ax.plot(pd.to_datetime(t.date), t.on_time, color=TEAL, marker="o", ms=3, lw=1.5, label="TigerTransit")
    ax.plot(pd.to_datetime(l.date), l.on_time, color=RED, marker="o", ms=3, lw=1.5, label="Loop")
    ax.axhline(80, color=AMBER, ls="--", lw=1.2); ax.set_ylim(50, 100); ax.set_ylabel("On time (%)")
    ax.xaxis.set_major_formatter(matplotlib.dates.DateFormatter("%b %-d")); ax.legend(frameon=False, fontsize=11, loc="lower left")
    _save(fig, "fig4_daily.png")


def skips(S):
    """Skip rate (skipped / scheduled visits) by stop and by scheduled hour, from the Loop tables."""
    from .summarize import SENIOR as senior
    v = pd.read_csv(OUT / "loop_visits.csv"); k = pd.read_csv(OUT / "loop_skips.csv"); v["hour"] = v.sched_s // 3600
    st = pd.concat([v.groupby("stop").size().rename("s"), k.groupby("stop").size().rename("k")], axis=1).fillna(0)
    st["rate"] = st.k / (st.s + st.k) * 100; st = st[st.s + st.k >= 100].sort_values("rate").tail(8)
    hr = pd.concat([v.groupby("hour").size().rename("s"), k.groupby("hour").size().rename("k")], axis=1).fillna(0)
    hr = hr[hr.s + hr.k >= 100]; hr["rate"] = hr.k / (hr.s + hr.k) * 100
    fig, (a1, a2) = plt.subplots(1, 2, figsize=(9, 3.2), gridspec_kw=dict(width_ratios=[1.35, 1]))
    a1.barh(st.index, st.rate, color=[RED if any(x in n for x in senior) else GREY for n in st.index])
    for i, (r, n) in enumerate(zip(st.rate, st.k)): a1.text(r + 0.4, i, f"{r:.0f}%  ({int(n)})", va="center", fontsize=11)
    a1.set_xlabel("Share of scheduled visits skipped (%)"); a1.tick_params(axis="y", labelsize=11); a1.set_xlim(0, st.rate.max() * 1.3)
    a2.bar(hr.index, hr.rate, color=TEAL); a2.set_xlabel("Scheduled hour"); a2.set_ylabel("Skipped (%)")
    a2.set_xticks([7, 11, 15, 19]); a2.set_xticklabels(["7am", "11am", "3pm", "7pm"], fontsize=11)
    fig.tight_layout(); _save(fig, "fig5_skips.png")


def forecast(F):
    r = F["results"]; names = list(r)
    short = {"B0 timetable": "Time-\ntable", "B1 last bus at stop": "Last\nbus", "B2 route-stop-hour history": "History\ntable",
             "M1 local features": "Boosted\ntrees", "M2 local + graph": "Trees +\ngraph"}
    fig, (a1, a2) = plt.subplots(1, 2, figsize=(10, 3.4), gridspec_kw=dict(width_ratios=[1.6, 1]))
    v = [r[n]["mae"] for n in names]; c = [GREY, GREY, TEAL, DARK, DARK]; labels = [short[n] for n in names]
    gj = OUT / "gnn.json"
    if gj.exists():
        g = json.load(open(gj))["mae"]; v += [g["graph"], g["no graph"]]; c += [AMBER, "#F6D58E"]; labels += ["Graph\nnetwork", "Same,\nno links"]
    a1.bar(labels, v, color=c)
    for i, x in enumerate(v): a1.text(i, x + 0.03, f"{x:.2f}", ha="center", fontsize=11)
    a1.set_ylabel("Average error (min)"); a1.tick_params(axis="x", labelsize=10); a1.set_ylim(0, max(v) * 1.15); a1.set_title("Predicting lateness 30 min ahead", fontsize=11, loc="left")
    w = F["late_warning"]; wn = list(w)
    a2.bar(["History", "Local", "+ graph"], [w[k]["top10_late_share"] for k in wn], color=[TEAL, DARK, DARK])
    a2.axhline(F["test_late_share"], color=AMBER, ls="--"); a2.text(-0.45, F["test_late_share"] - 3.2, f"all departures: {F['test_late_share']}% late", fontsize=11, color="#8A6200", ha="left", bbox=dict(facecolor="white", edgecolor="none", pad=1))
    for i, k in enumerate(wn): a2.text(i, w[k]["top10_late_share"] + 0.6, f"{w[k]['top10_late_share']:.0f}%\nAUC {w[k]['auc']:.2f}", ha="center", fontsize=11)
    a2.set_ylabel("Late (>5 min) among the 10%\nhighest-risk departures"); a2.set_title("Late warnings", fontsize=11, loc="left")
    a2.set_ylim(0, max(w[k]["top10_late_share"] for k in wn) * 1.35)
    fig.tight_layout(); _save(fig, "fig6_forecast.png")


def timetable(T):
    """Test-week on-time share for today's timetable, holding early buses, and the re-timed schedule with holding."""
    R = pd.read_csv(OUT / "timetable_test.csv", dtype={"route": str})
    order = ["TPL", "TPLEXP", "1", "2", "3", "4", "5", "6A", "6B"]; lab = {"TPL": "Loop\nLocal", "TPLEXP": "Loop\nExpress"}
    val = lambda r, k: R[(R.route == r) & (R.timetable == k)].on_time.iloc[0]
    series = [("Today's timetable", GREY, "today"), ("Early buses wait on half the trips", "#A9CBCE", "today + hold (half)"), ("Early buses wait, every trip", TEAL, "today + hold"),
              ("Re-timed + early buses wait", DARK, "re-timed + hold"), ("Re-timed, nobody waits (shows what fails)", AMBER, "re-timed, no hold")]
    x = np.arange(len(order)); w = 0.16
    fig, ax = plt.subplots(figsize=(9, 3.4))
    for i, (l, c, k) in enumerate(series): ax.bar(x + (i - 2) * w, [val(r, k) for r in order], w, color=c, label=l)
    ax.axvspan(-0.5, 1.5, color="#F2B134", alpha=0.12, zorder=0); ax.axvline(1.5, color="#9AA5A8", lw=0.8)
    ax.text(0.5, 96.5, "run for the town", ha="center", fontsize=10, color="#8A6200"); ax.text(5, 96.5, "TigerTransit (University)", ha="center", fontsize=10, color="#5E6E72")
    ax.axhline(80, color=RED, ls=":", lw=1.2); ax.text(8.75, 81, "80%", color=RED, fontsize=11, ha="right")
    ax.set_xticks(x); ax.set_xticklabels([lab.get(r, "Rt " + r) for r in order], fontsize=11); ax.set_ylim(0, 101); ax.set_ylabel("On time, Nov 1 to 15 (%)")
    ax.legend(frameon=False, ncol=2, loc="lower center", bbox_to_anchor=(0.5, 1.0), fontsize=10)
    _save(fig, "fig7_timetable.png")


def timetable_poster(T):
    """Poster version of the replay: the two Loop routes only, values printed on the bars."""
    R = pd.read_csv(OUT / "timetable_test.csv", dtype={"route": str})
    val = lambda r, k: R[(R.route == r) & (R.timetable == k)].on_time.iloc[0]
    series = [("Today", GREY, "today"), ("Half the trips wait", "#A9CBCE", "today + hold (half)"), ("Every early bus waits", TEAL, "today + hold"),
              ("Re-timed + waits", DARK, "re-timed + hold"), ("Re-timed, nobody waits", AMBER, "re-timed, no hold")]
    fig, ax = plt.subplots(figsize=(8, 3.8)); x = np.arange(2); w = 0.16
    for i, (l, c, k) in enumerate(series):
        v = [val(r, k) for r in ("TPL", "TPLEXP")]; b = ax.bar(x + (i - 2) * w, v, w, color=c, label=l)
        for xx, vv in zip(x + (i - 2) * w, v): ax.text(xx, vv + 1, f"{vv:.0f}", ha="center", fontsize=12, fontweight="bold", color=INK)
    ax.axhline(80, color=RED, ls=":", lw=1.2); ax.set_xticks(x); ax.set_xticklabels(["Loop Local", "Loop Express"], fontsize=14)
    ax.set_ylim(0, 108); ax.set_ylabel("On time (%)"); ax.legend(frameon=False, ncol=3, loc="lower center", bbox_to_anchor=(0.5, 1.0), fontsize=11)
    _save(fig, "fig7b_timetable_poster.png")


def forecast_poster(F):
    """Poster version of the forecast chart: average error only, plain labels."""
    r = F["results"]; names = ["B0 timetable", "B2 route-stop-hour history", "M1 local features"]
    lab = ["Assume\non time", "Table of past\nlateness", "Boosted\ntrees (ML)"]; v = [r[n]["mae"] for n in names]; c = [GREY, TEAL, DARK]
    gj = OUT / "gnn.json"
    if gj.exists():
        g = json.load(open(gj))["mae"]; v += [g["graph"], g["no graph"]]; lab += ["Graph\nnetwork", "Same, stop\nlinks removed"]; c += [AMBER, "#F6D58E"]
    fig, ax = plt.subplots(figsize=(8, 3.6)); ax.bar(lab, v, color=c, width=0.62)
    for i, x in enumerate(v): ax.text(i, x + 0.04, f"{x:.2f}", ha="center", fontsize=14, fontweight="bold")
    ax.set_ylabel("Average error 30 min ahead (min)"); ax.set_ylim(0, max(v) * 1.2)
    _save(fig, "fig6b_forecast_poster.png")


def run():
    S = json.load(open(OUT / "summary.json")); F = json.load(open(OUT / "forecast.json")); T = json.load(open(OUT / "timetable.json"))
    scorecard(S); hours(S); daily(S); skips(S); forecast(F); forecast_poster(F); timetable(T); timetable_poster(T)
    print(f"  figures written to {FIG}")
