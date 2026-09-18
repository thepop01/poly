from src.workers.activity_backfiller_worker import _should_escalate


def test_escalates_on_large_unexplained_residual():
    assert _should_escalate(unexplained_residual=15000, phase1_failure=False)


def test_escalates_on_phase1_failure():
    assert _should_escalate(unexplained_residual=0, phase1_failure=True)


def test_no_escalation_small_residual():
    assert not _should_escalate(unexplained_residual=500, phase1_failure=False)
