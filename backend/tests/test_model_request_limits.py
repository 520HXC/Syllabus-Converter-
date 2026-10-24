import re
from datetime import date
from types import SimpleNamespace

import pytest

from app import processing
from app.config import Settings


def test_model_requests_use_sol_medium_and_bound_outputs_time_without_hidden_retries(monkeypatch):
    constructor = {}
    request = {}

    class Responses:
        def parse(self, **kwargs):
            request.update(kwargs)
            return SimpleNamespace(output_parsed=object())

    class Client:
        def __init__(self, **kwargs):
            constructor.update(kwargs)
            self.responses = Responses()

    monkeypatch.setattr(processing, "OpenAI", Client)
    settings = Settings(_env_file=None, auth_mode="dev", openai_api_key="fake-key")
    pages = [{"page": 1, "text": "Sample syllabus"}]
    processing.extract_with_openai(pages, settings)
    assert request["model"] == "gpt-6.1-sol"
    assert request["reasoning"] == {"effort": "medium"}
    assert constructor.get("max_retries") == 0
    assert constructor.get("timeout") == settings.openai_timeout_seconds
    assert request.get("max_output_tokens") == settings.max_model_output_tokens
    assert request["store"] is False


@pytest.mark.parametrize("model", [processing.CandidateEvent, processing.ScheduleAnchor,
                                    processing.RecurringRule])
@pytest.mark.parametrize("field", ["start_time", "end_time"])
def test_model_clock_schema_requires_local_time_without_timezone(model, field):
    choices = model.model_json_schema()["properties"][field]["anyOf"]
    clock_schema = next(choice for choice in choices if choice.get("type") == "string")
    pattern = clock_schema.get("pattern")
    assert pattern, "The provider contract must constrain local clocks, not RFC3339 offsets"
    assert clock_schema.get("format") != "time"
    for value in ["00:00:00", "08:00:00", "14:15:00", "23:59:00"]:
        assert re.fullmatch(pattern, value)
    for value in ["08:00:00Z", "23:59:00+00:00", "14:15:00-05:00", "24:00:00", "9:30"]:
        assert not re.fullmatch(pattern, value)


def test_legacy_clock_offsets_still_reach_source_validation():
    candidate = processing.CandidateEvent(
        title="Homework", event_type="assignment", source_quote="Homework time is unpublished.",
        source_page=1, confidence="low", year_was_explicit=True, start_time="23:59:00Z",
    )
    assert candidate.start_time.tzinfo is not None
    assert "TIME_CONFLICT" in processing.validate_candidate(
        candidate, [{"page": 1, "text": candidate.source_quote}],
        date(2026, 1, 1), date(2026, 12, 31),
    )[0]
