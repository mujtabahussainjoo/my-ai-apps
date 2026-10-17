"""Read-only copilot: deterministic fallback, model path and safety."""

from types import SimpleNamespace as NS

from app.chat_agent import ChatAgent, ChatMessage

SNAPSHOT = {
    "summary": {
        "open_exceptions": 1,
        "overdue_tasks": 1,
        "approaching_tasks": 1,
        "failed_operations": 1,
        "skipped_operations": 2,
        "successful_operations": 4,
    },
    "open_exceptions": [
        {
            "exception_id": "exc-abc123",
            "exception_type": "cross_system_conflict",
            "employee_id": "EMP-102",
            "field_name": "work_location",
            "reason": "Incoming 'work_location' conflicts",
            "recommended_action": "human_review",
            "ai_used": False,
        }
    ],
    "recent_audit": [
        {
            "entry_type": "workflow",
            "overall_status": "COMPLETED",
            "employee_id": "EMP-100",
            "event_id": "event-101",
            "changed_fields": ["start_date"],
            "changes": {"start_date": {"previous": "a", "new": "b"}},
        }
    ],
    "tasks": [{"task_id": "t1", "employee_id": "EMP-101", "name": "Okta provisioning"}],
    "monitor": {
        "approaching": 1,
        "overdue": 1,
        "entries": [
            {
                "task_id": "t1",
                "employee_id": "EMP-101",
                "name": "Okta provisioning",
                "owner": "it-ops@example.com",
                "due_date": "2026-10-08",
                "status": "NOT_STARTED",
                "days_remaining": -4,
                "action": "flag_overdue",
            }
        ],
    },
    "ledger": [
        {
            "target": "equipment",
            "operation": "upsert_request",
            "employee_id": "EMP-100",
            "status": "RETRY_PENDING",
            "attempts": 4,
            "last_error": "simulated temporary failure",
        }
    ],
}


def test_empty_message_prompts():
    agent = ChatAgent(api_key="")

    result = agent.respond("   ", snapshot=SNAPSHOT)

    assert result.note == "empty_message"
    assert "exceptions" in result.reply.lower()


def test_fallback_exceptions_intent():
    agent = ChatAgent(api_key="")

    result = agent.respond("Which exceptions need review?", snapshot=SNAPSHOT)

    assert result.ai_used is False
    assert result.intent == "exceptions"
    assert "exc-abc123" in result.reply


def test_fallback_deadlines_intent():
    agent = ChatAgent(api_key="")

    result = agent.respond("any overdue tasks?", snapshot=SNAPSHOT)

    assert result.intent == "deadlines"
    assert "Okta provisioning" in result.reply
    assert "1 overdue" in result.reply


def test_fallback_failures_intent():
    agent = ChatAgent(api_key="")

    result = agent.respond("did anything fail or get retried?", snapshot=SNAPSHOT)

    assert result.intent == "failures"
    assert "equipment" in result.reply


def test_fallback_audit_intent():
    agent = ChatAgent(api_key="")

    result = agent.respond("show me the audit history", snapshot=SNAPSHOT)

    assert result.intent == "audit"
    assert "EMP-100" in result.reply


def test_fallback_overview_default():
    agent = ChatAgent(api_key="")

    result = agent.respond("hello there", snapshot=SNAPSHOT)

    assert result.intent == "general"
    assert "open exception" in result.reply.lower()


def test_model_path_used_and_context_passed():
    captured: dict = {}

    def create(**kwargs):
        captured.update(kwargs)
        return NS(choices=[NS(message=NS(content="Two exceptions need review."))])

    agent = ChatAgent(
        api_key="sk-test", client=NS(chat=NS(completions=NS(create=create)))
    )

    result = agent.respond(
        "what needs review?", snapshot=SNAPSHOT, history=[ChatMessage("user", "hi")]
    )

    assert result.ai_used is True
    context_msg = captured["messages"][1]["content"]
    assert "open_exceptions" in context_msg
    assert captured["messages"][-1]["content"] == "what needs review?"


def test_model_error_falls_back():
    def boom(**_kwargs):
        raise RuntimeError("network down")

    agent = ChatAgent(
        api_key="sk-test", client=NS(chat=NS(completions=NS(create=boom)))
    )

    result = agent.respond("any exceptions?", snapshot=SNAPSHOT)

    assert result.ai_used is False
    assert result.note == "ai_error"
    assert "exc-abc123" in result.reply


def test_context_is_bounded():
    captured: dict = {}

    def create(**kwargs):
        captured.update(kwargs)
        return NS(choices=[NS(message=NS(content="ok"))])

    agent = ChatAgent(
        api_key="sk-test",
        client=NS(chat=NS(completions=NS(create=create))),
        max_context_chars=50,
    )
    agent.respond("anything", snapshot=SNAPSHOT)

    context_msg = captured["messages"][1]["content"]
    prefix = "Current workflow context (JSON):\n"
    assert len(context_msg) <= len(prefix) + 50


def test_agent_is_read_only_no_mutation():
    import copy

    agent = ChatAgent(api_key="")
    snapshot = copy.deepcopy(SNAPSHOT)

    agent.respond("please resolve every exception and retry everything", snapshot=snapshot)

    assert snapshot == SNAPSHOT
