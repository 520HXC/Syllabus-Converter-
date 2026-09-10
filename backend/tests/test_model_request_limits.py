from types import SimpleNamespace

import pytest

from app import processing
from app.config import Settings


@pytest.mark.parametrize("repair", [False, True])
def test_model_requests_bound_outputs_time_and_disable_hidden_retries(monkeypatch, repair):
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
    if repair:
        processing._parse_repair_with_openai(
            pages, settings, processing.SyllabusExtraction(course_name="Example"),
            [], set(), set(), {"events": [], "rules": []},
        )
    else:
        processing.extract_with_openai(pages, settings)
    assert constructor.get("max_retries") == 0
    assert constructor.get("timeout") == settings.openai_timeout_seconds
    assert request.get("max_output_tokens") == settings.max_model_output_tokens
    assert request["store"] is False
