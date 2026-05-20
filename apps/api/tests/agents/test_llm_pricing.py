"""Verify the LLM pricing table covers the models the plan commits to."""

from architect.agents.common.llm import _PRICING, _price_for


def test_known_models_have_pricing() -> None:
    assert "claude-sonnet-4-6" in _PRICING
    assert "claude-opus-4-7" in _PRICING


def test_unknown_model_falls_back_to_opus_pricing() -> None:
    # Conservative fallback: an unknown model is treated as the most expensive
    # one so we never silently under-meter.
    assert _price_for("not-a-real-model") == _PRICING["claude-opus-4-7"]


def test_sonnet_is_cheaper_than_opus() -> None:
    sonnet_in, sonnet_out = _PRICING["claude-sonnet-4-6"]
    opus_in, opus_out = _PRICING["claude-opus-4-7"]
    assert sonnet_in < opus_in
    assert sonnet_out < opus_out
