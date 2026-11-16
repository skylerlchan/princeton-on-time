"""Optional figure: TigerTransit and Loop stops coloured by median departure lateness. Needs geopandas.
Base layers: GTFS route shapes and, if present, Princeton roads and boundary from the CEE420 P02 kit (env POT_BASEMAP)."""
from __future__ import annotations
import math, os, glob, io, zipfile
import matplotlib; matplotlib.use("Agg")
import matplotlib.pyplot as plt, pandas as pd
from .common import DATA, FIG, OUT, gtfs_snapshots

DARK, AMBER, TEAL, RED, INK = "#102A30", "#F2B134", "#5C8F94", "#C8443F", "#1C2A2E"


def run():
    import geopandas as gpd
    snap = gtfs_snapshots()[-1][1]; z = zipfile.ZipFile(snap); rd = lambda n: pd.read_csv(io.BytesIO(z.read(n)), dtype=str)
    stops, shapes, trips, routes = rd("stops.txt"), rd("shapes.txt"), rd("trips.txt"), rd("routes.txt")
    tt = pd.read_csv(OUT / "tt_arrivals.csv", dtype={"route": str}); lp = pd.read_csv(OUT / "loop_visits.csv", dtype={"route": str})
    ev = pd.concat([tt[tt.route != "WS"], lp]); g = ev.groupby("stop_id").delay.agg(med="median", n="size").reset_index(); g = g[g.n >= 100]
    xy = stops.set_index("stop_id"); g = g[g.stop_id.isin(xy.index)]
    g["lat"] = g.stop_id.map(xy.stop_lat).astype(float); g["lon"] = g.stop_id.map(xy.stop_lon).astype(float); g["name"] = g.stop_id.map(xy.stop_name)
    fig, ax = plt.subplots(figsize=(7.2, 6.4))
    base = os.environ.get("POT_BASEMAP")
    if base and os.path.exists(base):
        gpd.read_file(base, layer="roads").to_crs(4326).plot(ax=ax, color="#E4E2DC", lw=0.4, zorder=1)
        gpd.read_file(base, layer="boundary").to_crs(4326).boundary.plot(ax=ax, color=TEAL, lw=1, ls="--", zorder=2)
    shapes["lat"] = shapes.shape_pt_lat.astype(float); shapes["lon"] = shapes.shape_pt_lon.astype(float); shapes["seq"] = shapes.shape_pt_sequence.astype(int)
    rn = dict(zip(routes.route_id, routes.route_short_name)); sr = {t.shape_id: rn.get(t.route_id) for t in trips.itertuples()}
    for sid, s in shapes.groupby("shape_id"):
        r = sr.get(sid)
        if r in (None, "WS"): continue
        s = s.sort_values("seq"); ax.plot(s.lon, s.lat, color=AMBER if r.startswith("TPL") else DARK, alpha=0.55 if r.startswith("TPL") else 0.25, lw=1.6, zorder=3)
    cmap = matplotlib.colors.LinearSegmentedColormap.from_list("l", [TEAL, "#F4F1E8", RED]); norm = matplotlib.colors.TwoSlopeNorm(vmin=-1, vcenter=0, vmax=4)
    sc = ax.scatter(g.lon, g.lat, c=g.med, cmap=cmap, norm=norm, s=22 + g.n / 60, edgecolor=DARK, lw=0.5, zorder=5)
    place = {"Avalon": (-30, 60, "right"), "Nassau": (-60, 50, "right"), "Senior": (-50, -75, "right"), "Alexander": (15, 14, "left")}
    for r in g.sort_values("med", ascending=False).head(4).itertuples():
        dx, dy, ha = next((v for k, v in place.items() if k in r.name), (10, 10, "left"))
        ax.annotate(f"{r.name.replace(' (WB)', '').replace(' (SB)', '').replace(' (NB)', '')}", (r.lon, r.lat), xytext=(dx, dy), textcoords="offset points",
                    fontsize=10, color=INK, fontweight="bold", ha=ha, zorder=6, arrowprops=dict(arrowstyle="-", color=INK, lw=0.6))
    ax.set_xlim(g.lon.min() - 0.01, g.lon.max() + 0.01); ax.set_ylim(g.lat.min() - 0.006, g.lat.max() + 0.006); ax.set_aspect(1 / math.cos(math.radians(40.35)))
    ax.set_xticks([]); ax.set_yticks([]); ax.set_xlabel(""); ax.set_ylabel(""); [s.set_visible(False) for s in ax.spines.values()]
    cb = fig.colorbar(sc, ax=ax, shrink=0.55, pad=0.04); cb.set_label("Median minutes late, all routes", fontsize=11)
    ax.plot([], [], color=DARK, alpha=0.4, lw=2, label="TigerTransit routes (darker where they overlap)"); ax.plot([], [], color=AMBER, lw=2, label="Princeton Loop"); ax.scatter([], [], s=22 + 500 / 60, color="#DDD", edgecolor=DARK, lw=0.5, label="500 departures"); ax.scatter([], [], s=22 + 3000 / 60, color="#DDD", edgecolor=DARK, lw=0.5, label="3,000 departures")
    ax.legend(frameon=False, fontsize=11, loc="upper left", bbox_to_anchor=(0.0, 0.0), ncol=2)
    # 1 km scale bar and north arrow, top right
    x1, y0 = g.lon.max() + 0.005, g.lat.max() - 0.012; km = 1 / (111.32 * math.cos(math.radians(40.35)))
    ax.plot([x1 - km, x1], [y0, y0], color=INK, lw=2.5, zorder=7); ax.text(x1 - km / 2, y0 + 0.0012, "1 km", ha="center", fontsize=11, color=INK)
    ax.annotate("N", xy=(x1 - 0.002, y0 + 0.012), xytext=(x1 - 0.002, y0 + 0.005), ha="center", fontsize=12, fontweight="bold", color=INK,
                arrowprops=dict(arrowstyle="-|>", color=INK, lw=1.5))
    FIG.mkdir(exist_ok=True, parents=True); fig.savefig(FIG / "fig2_map.png", bbox_inches="tight", dpi=300, facecolor="white"); plt.close(fig)
    print("  map written")


if __name__ == "__main__":
    run()
