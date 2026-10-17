"""Scenario: duplicate events never repeat side effects."""

from app.event_receiver import parse_event
from app.models import OverallStatus


def test_duplicate_event_is_skipped(make_orchestrator, portal, sample_event):
    orchestrator = make_orchestrator()

    first = orchestrator.process(parse_event(sample_event("start_date_changed.json")))
    assert first.overall_status is OverallStatus.COMPLETED
    assert all(o.status == "SUCCESS" for o in first.outcomes)

    second = orchestrator.process(parse_event(sample_event("start_date_changed.json")))
    assert second.overall_status is OverallStatus.COMPLETED
    assert all(o.status == "SKIPPED_IDEMPOTENT" for o in second.outcomes)
    assert all(o.attempts == 0 for o in second.outcomes)


def test_ledger_marks_operation_complete(make_orchestrator, sample_event):
    orchestrator = make_orchestrator()
    orchestrator.process(parse_event(sample_event("start_date_changed.json")))

    key = orchestrator.ledger.operation_key(
        "EMP-101", "event-202", "workday", "upsert_employee"
    )
    assert orchestrator.ledger.is_done(key)
