"""AI helper: advisory, schema-validated and safe when unavailable."""

from types import SimpleNamespace as NS

from app.ai_helper import AIHelper


def _fake_client(content):
    def create(**_kwargs):
        return NS(choices=[NS(message=NS(content=content))])

    return NS(chat=NS(completions=NS(create=create)))


def test_disabled_uses_deterministic_fallback():
    helper = AIHelper(api_key="")

    result = helper.classify(exception_type="retry_exhausted", reason="r")

    assert result.ai_used is False
    assert result.recommended_action == "escalate_owner"
    assert result.note == "ai_disabled"


def test_valid_ai_response_is_used():
    content = (
        '{"exception_type":"location_mismatch",'
        '"recommended_action":"human_review",'
        '"reason":"Two records differ"}'
    )
    helper = AIHelper(api_key="sk-test", client=_fake_client(content))

    result = helper.classify(exception_type="cross_system_conflict", reason="x")

    assert result.ai_used is True
    assert result.recommended_action == "human_review"


def test_disallowed_action_falls_back():
    content = '{"exception_type":"x","recommended_action":"auto_approve"}'
    helper = AIHelper(api_key="sk-test", client=_fake_client(content))

    result = helper.classify(exception_type="cross_system_conflict", reason="x")

    assert result.ai_used is False
    assert result.recommended_action == "human_review"


def test_client_error_falls_back():
    def boom(**_kwargs):
        raise RuntimeError("network down")

    helper = AIHelper(
        api_key="sk-test", client=NS(chat=NS(completions=NS(create=boom)))
    )

    result = helper.classify(exception_type="unknown_location", reason="x")

    assert result.ai_used is False
    assert result.recommended_action == "request_data_correction"


def test_prompt_contains_only_minimal_context():
    captured: dict = {}

    def create(**kwargs):
        captured.update(kwargs)
        return NS(
            choices=[
                NS(
                    message=NS(
                        content='{"exception_type":"t",'
                        '"recommended_action":"human_review","reason":"r"}'
                    )
                )
            ]
        )

    helper = AIHelper(
        api_key="sk-test", client=NS(chat=NS(completions=NS(create=create)))
    )
    helper.classify(
        exception_type="cross_system_conflict",
        reason="location differs",
        field_name="work_location",
    )

    user_payload = captured["messages"][1]["content"]
    assert "email" not in user_payload.lower()
    assert "address" not in user_payload.lower()
    assert "work_location" in user_payload
