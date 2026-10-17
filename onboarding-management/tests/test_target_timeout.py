"""Scenario C: equipment API times out / fails; other targets stay intact."""

from app.event_receiver import parse_event
from app.models import OverallStatus


def _fault(portal, target, mode, remaining=-1):
    portal._client.post(
        "/_admin/faults",
        json={"target": target, "mode": mode, "remaining": remaining},
    )


def test_transient_failure_recovers_on_retry(make_orchestrator, portal, sample_event):
    _fault(portal, "equipment", "temporary", remaining=1)
    orchestrator = make_orchestrator()

    result = orchestrator.process(parse_event(sample_event("new_hire.json")))

    equipment = next(o for o in result.outcomes if o.target == "equipment")
    assert equipment.status == "SUCCESS"
    assert equipment.attempts == 2
    assert result.overall_status is OverallStatus.COMPLETED


def test_persistent_failure_partially_completes(
    make_orchestrator, portal, sample_event
):
    _fault(portal, "equipment", "temporary", remaining=-1)
    orchestrator = make_orchestrator(max_retries=2)

    result = orchestrator.process(parse_event(sample_event("new_hire.json")))

    assert result.overall_status is OverallStatus.PARTIALLY_COMPLETED
    equipment = next(o for o in result.outcomes if o.target == "equipment")
    workday = next(o for o in result.outcomes if o.target == "workday")
    assert equipment.status == "RETRY_PENDING"
    assert equipment.attempts == 3  # 1 attempt + 2 retries
    assert workday.status == "SUCCESS"  # successful targets are preserved

    exceptions = orchestrator.exceptions.open_exceptions()
    assert any(e.exception_type == "retry_exhausted" for e in exceptions)


def test_unknown_outcome_is_reconciled(make_orchestrator, portal, sample_event):
    # timeout applies the write but returns 504 -> unknown outcome
    _fault(portal, "equipment", "timeout", remaining=1)
    orchestrator = make_orchestrator()

    result = orchestrator.process(parse_event(sample_event("new_hire.json")))

    equipment = next(o for o in result.outcomes if o.target == "equipment")
    assert equipment.status == "SUCCESS"
    assert "reconcil" in equipment.detail
