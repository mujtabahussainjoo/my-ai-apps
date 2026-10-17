"""Scenario A: a valid new hire propagates to every required system."""

from app.event_receiver import parse_event
from app.models import OverallStatus, TargetSystem


def test_new_hire_updates_all_targets(make_orchestrator, portal, sample_event):
    orchestrator = make_orchestrator()

    result = orchestrator.process(parse_event(sample_event("new_hire.json")))

    assert result.overall_status is OverallStatus.COMPLETED
    targets = {outcome.target for outcome in result.outcomes}
    assert targets == {t.value for t in TargetSystem}
    assert all(outcome.status == "SUCCESS" for outcome in result.outcomes)

    # Every target can be verified independently.
    for target in TargetSystem:
        assert portal.verify(target, "EMP-100").exists


def test_audit_entry_recorded(make_orchestrator, sample_event):
    orchestrator = make_orchestrator()
    orchestrator.process(parse_event(sample_event("new_hire.json")))

    entries = orchestrator.audit.read()
    assert len(entries) == 1
    assert entries[0]["overall_status"] == "COMPLETED"
    assert entries[0]["operations"]
