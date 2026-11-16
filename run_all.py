#!/usr/bin/env python3
"""Run the whole Princeton On Time analysis end to end.

    python run_all.py                     # sample data shipped in data/sample (about 1 minute)
    POT_DATA=/path/to/data python run_all.py   # the full 47-day log (about 6 to 8 minutes)
    POT_SINCE=<6 weeks ago> POT_DATA=... python run_all.py --weekly   # weekly page only, into weekly/ (needs 6 weeks of logs)

Steps: measure -> summarize -> validate -> forecast -> graph network -> timetable -> figures -> weekly page (-> map, if geopandas is installed).
Every number in the poster and report is in results/*.json; every figure is in figures/.
"""
import os, sys, time
if "--weekly" in sys.argv:   # never overwrite the report's results/ in weekly mode
    os.environ.setdefault("POT_OUT", os.path.join(os.path.dirname(os.path.abspath(__file__)), "weekly"))
from pot import measure, summarize, validate, forecast, timetable, figures, weekly
from pot.common import DATA, OUT

if __name__ == "__main__":
    t = time.time()
    print(f"data: {DATA}\nresults: {OUT}")
    if "--weekly" in sys.argv:   # the weekly task: measure and rebuild the weekly page only (set POT_OUT to keep it apart from the report's results)
        measure.run(); weekly.run(); print(f"\ndone in {(time.time() - t) / 60:.1f} min"); sys.exit(0)
    def graph_network():
        try:
            from pot import gnn
        except ImportError:
            print("  skipped (pip install torch to run it)"); return
        gnn.run()
    for name, step in [("1 measure", measure.run), ("2 summarize", summarize.run), ("2b validate", validate.run), ("3 forecast", forecast.run), ("3b graph network", graph_network),
                       ("4 timetable", timetable.run), ("5 figures", figures.run), ("7 weekly page", weekly.run)]:
        print(f"\n== step {name}"); step()
    try:
        from pot import map as m; print("\n== step 6 map"); m.run()
    except ImportError:
        print("\n== step 6 map skipped (pip install geopandas to draw it)")
    print(f"\ndone in {(time.time() - t) / 60:.1f} min")
