"""Scenario D: an off-cycle hire uses the same shared workflow."""

from app.event_receiver import parse_event
from app.models import OverallStatus, TargetSystem


def test_off_cycle_hire_uses_same_workflow(make_orchestrator, portal, sample_event):
    orchestrator = make_orchestrator()

    result = orchestrator.process(parse_event(sample_event("off_cycle_hire.json")))

    assert result.source == "workday_intake"
    assert result.overall_status is OverallStatus.COMPLETED
    assert {o.target for o in result.outcomes} == {t.value for t in TargetSystem}
    for target in TargetSystem:
        assert portal.verify(target, "EMP-103").exists


def test_malformed_event_is_rejected(make_orchestrator):
    orchestrator = make_orchestrator()

    result = orchestrator.handle({"event_id": "broken"})

    assert result.overall_status is OverallStatus.FAILED
    assert "malformed" in result.message
    assert result.outcomes == []
