from datetime import datetime, timezone
from src.workers.window_stats import compute_category_window_stats

def _cp(cid, pnl, bought, end, cat_title):
    return {"conditionId": cid, "realizedPnl": pnl, "totalBought": bought,
            "endDate": end, "title": cat_title}

def _classify(title):
    # test stub: title *is* the category
    return title

def test_overall_and_category_slicing():
    # 3 SPORTS (2 win), 1 POLITICS (loss)
    closed = [
        _cp("a", 100.0, 50.0, "2026-01-04T00:00:00Z", "SPORTS"),
        _cp("b", -20.0, 40.0, "2026-01-03T00:00:00Z", "SPORTS"),
        _cp("c", 10.0, 5.0,  "2026-01-02T00:00:00Z", "SPORTS"),
        _cp("d", -5.0, 30.0, "2026-01-01T00:00:00Z", "POLITICS"),
    ]
    out = compute_category_window_stats(closed, [100], _classify)
    ov = out[("OVERALL", 100)]
    assert ov["resolved_count"] == 4
    assert ov["winning_count"] == 2
    assert round(ov["pnl"], 2) == 85.0
    assert round(ov["volume"], 2) == 125.0
    assert ov["win_rate"] == 0.5
    assert round(ov["roi_pct"], 2) == 68.0
    assert ov["last_active"] == datetime(2026, 1, 4, tzinfo=timezone.utc)
    sp = out[("SPORTS", 100)]
    assert sp["resolved_count"] == 3
    assert sp["winning_count"] == 2

def test_window_smaller_than_count():
    closed = [_cp(str(i), 1.0, 1.0, f"2026-01-{i+1:02d}T00:00:00Z", "CRYPTO") for i in range(5)]
    out = compute_category_window_stats(closed, [2], _classify)
    # only the 2 most recent (endDate desc) count
    assert out[("CRYPTO", 2)]["resolved_count"] == 2
    assert out[("OVERALL", 2)]["resolved_count"] == 2

def test_empty():
    out = compute_category_window_stats([], [100], _classify)
    assert out == {}
