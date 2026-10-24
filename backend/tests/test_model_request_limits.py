from types import SimpleNamespace

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
