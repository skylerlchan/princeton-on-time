"""Unit tests for the rules every number depends on. Run: python -m pytest -q"""
import math
import numpy as np
from pot.common import EARLY_MIN, LATE_MIN, haversine, hms, on_time, split_day
from pot.forecast import Window


def test_on_time_window_is_one_early_to_five_late():
    assert on_time(0) and on_time(-1) and on_time(5)
    assert not on_time(-1.01) and not on_time(5.01)
    assert (EARLY_MIN, LATE_MIN) == (-1.0, 5.0)


def test_haversine_40m_radius_scale():
    # 0.00036 deg of latitude is about 40 m
    assert 39 < haversine(40.35, -74.65, 40.35036, -74.65) < 41
    assert haversine(40.35, -74.65, 40.35, -74.65) == 0


def test_hms_handles_after_midnight_times():
    assert hms("25:10:00") == 25 * 3600 + 600


def test_window_uses_only_the_past():
    w = Window([100, 200, 300], [1.0, 2.0, 3.0])
    s, n = w.stats(np.array([300]), 150)       # [150, 300): only t=200
    assert n[0] == 1 and s[0] == 2.0
    v, age = w.last(np.array([300]))
    assert v[0] == 2.0 and math.isclose(age[0], 100 / 60)
    v, _ = w.last(np.array([50])); assert np.isnan(v[0])


def test_split_day_falls_back_to_median_on_short_samples():
    days = ["2026-11-11", "2026-11-12", "2026-11-13"]
    assert split_day(days, "2026-11-01") == "2026-11-12"
    assert split_day(["2026-10-30", "2026-11-02"], "2026-11-01") == "2026-11-01"


def test_service_seconds_past_midnight():
    """A departure at 00:30 on a trip that started the evening before is 24:30 of the earlier service day."""
    import datetime as dt
    from pot.measure import _service_seconds
    t = dt.datetime(2026, 11, 3, 0, 30)
    assert _service_seconds(t, "2026-11-02") == 24 * 3600 + 30 * 60
    assert _service_seconds(t, "2026-11-03") == 30 * 60
