"""NL->spec generation with a fake LLM, so the whole path runs offline. Covers
the JSON-extraction quirks and that a bad model answer surfaces as an error
rather than reaching MetricFlow."""

from __future__ import annotations

import pytest

from analytics.nl2metric.generate import GenerationError, generate_spec


class FakeClient:
    """Returns a canned reply; records the prompt it was handed."""

    def __init__(self, reply: str) -> None:
        self.reply = reply
        self.seen_prompt: str | None = None

    def generate(self, prompt: str) -> str:
        self.seen_prompt = prompt
        return self.reply

    def embed(self, text: str) -> list[float]:  # part of the protocol, unused here
        raise NotImplementedError


def test_plain_json_reply(catalog):
    client = FakeClient(
        '{"metrics": ["launch_count"], "group_by": ["company__sector"], "limit": 10}'
    )
    gen = generate_spec("launches by sector", catalog, client)
    assert gen.spec.metrics == ("launch_count",)
    assert gen.spec.group_by == ("company__sector",)


def test_prompt_includes_catalog(catalog):
    client = FakeClient('{"metrics": ["launch_count"], "limit": 10}')
    generate_spec("how many launches", catalog, client)
    assert "launch_count" in client.seen_prompt
    assert "company__sector" in client.seen_prompt


def test_fenced_json_reply(catalog):
    reply = 'Here you go:\n```json\n{"metrics": ["launch_count"], "limit": 5}\n```'
    gen = generate_spec("count launches", catalog, client=FakeClient(reply))
    assert gen.spec.limit == 5


def test_json_embedded_in_prose(catalog):
    reply = 'Sure — {"metrics": ["launch_count"], "limit": 3} should do it.'
    gen = generate_spec("count launches", catalog, client=FakeClient(reply))
    assert gen.spec.metrics == ("launch_count",)


def test_no_json_raises(catalog):
    with pytest.raises(GenerationError, match="did not return a JSON object"):
        generate_spec("hi", catalog, client=FakeClient("I cannot help with that."))


def test_model_error_reply_raises(catalog):
    reply = '{"error": "no feedback metric exists in the catalog"}'
    with pytest.raises(GenerationError, match="no feedback metric"):
        generate_spec("share of open feedback", catalog, client=FakeClient(reply))


def test_unknown_metric_from_model_is_rejected(catalog):
    reply = '{"metrics": ["revenue"], "limit": 10}'
    with pytest.raises(GenerationError, match="invalid spec") as exc:
        generate_spec("total revenue", catalog, client=FakeClient(reply))
    assert any("unknown metric 'revenue'" in e for e in exc.value.errors)


def test_malformed_spec_from_model_is_rejected(catalog):
    reply = '{"metrics": ["launch_count"], "limit": 10, "bogus": 1}'
    with pytest.raises(GenerationError, match="malformed spec"):
        generate_spec("count launches", catalog, client=FakeClient(reply))


def test_missing_limit_from_model_is_rejected(catalog):
    reply = '{"metrics": ["launch_count"]}'
    with pytest.raises(GenerationError, match="invalid spec") as exc:
        generate_spec("count launches", catalog, client=FakeClient(reply))
    assert "limit is required" in exc.value.errors
