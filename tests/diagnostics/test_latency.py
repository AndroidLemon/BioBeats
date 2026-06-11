# Tests for the pure chunk-latency tracker: budget comparison, running
# aggregates (mean/worst/over-budget), and the end-of-session summary line.

from src.diagnostics.latency import ChunkBudgetTracker


def test_under_budget_chunk_is_not_flagged():
    tracker = ChunkBudgetTracker()
    assert tracker.record(1.5, 2.0) is False
    assert tracker.chunks == 1
    assert tracker.over_budget == 0


def test_over_budget_chunk_is_flagged_and_counted():
    tracker = ChunkBudgetTracker()
    assert tracker.record(2.3, 2.0) is True
    assert tracker.over_budget == 1


def test_exactly_on_budget_is_not_an_overrun():
    tracker = ChunkBudgetTracker()
    assert tracker.record(2.0, 2.0) is False


def test_aggregates_track_mean_worst_and_last():
    tracker = ChunkBudgetTracker()
    tracker.record(1.0, 2.0)
    tracker.record(3.0, 2.0)
    tracker.record(2.0, 2.0)
    assert tracker.mean_gen_seconds == 2.0
    assert tracker.worst_gen_seconds == 3.0
    assert tracker.last_gen_seconds == 2.0
    assert tracker.over_budget == 1


def test_summary_reports_the_session_numbers():
    tracker = ChunkBudgetTracker()
    tracker.record(1.0, 2.0)
    tracker.record(3.0, 2.0)
    line = tracker.summary()
    assert "2 chunks" in line
    assert "mean 2.00s / 2.00s budget (100%)" in line
    assert "worst 3.00s" in line
    assert "1 over budget" in line


def test_empty_tracker_has_safe_summary_and_mean():
    tracker = ChunkBudgetTracker()
    assert tracker.mean_gen_seconds == 0.0
    assert tracker.summary() == "latency: no chunks generated"
