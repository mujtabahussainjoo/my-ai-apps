"""Scenario B: a conflicting location blocks unsafe updates."""

from app.event_receiver import parse_event
from app.models import OverallStatus


def test_location_conflict_blocks_and_records_exception(
    make_orchestrator, portal, sample_event
):
    orchestrator = make_orchestrator()

    result = orchestrator.process(parse_event(sample_event("location_conflict.json")))

    assert result.overall_status is OverallStatus.NEEDS_REVIEW
    assert "work_location" in result.blocked["workday"]
    assert result.outcomes == []  # nothing unsafe was pushed

    # The disputed value never reached the target systems.
    workday = portal.verify("workday", "EMP-102")
    assert not workday.exists or workday.record.get("work_location") != "Bangalore"

    exceptions = orchestrator.exceptions.open_exceptions()
    assert any(
        e.exception_type == "cross_system_conflict"
        and e.field_name == "work_location"
        for e in exceptions
    )


def test_conflict_exception_has_recommendation(make_orchestrator, sample_event):
    orchestrator = make_orchestrator()  # AI disabled -> deterministic fallback
    orchestrator.process(parse_event(sample_event("location_conflict.json")))

    exception = orchestrator.exceptions.open_exceptions()[0]
    assert exception.recommended_action == "human_review"
    assert exception.ai_used is False
