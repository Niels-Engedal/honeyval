"""NLP RESEARCH EXTENSION tests; no retrospective strategies."""
from src.utils.strategy_logging import collect_strategy, extract_strategy


def test_contemporaneous_action():
    clean, strategy, usage, audit = collect_strategy(
        "<STRATEGY>Test API.</STRATEGY><ACTION>original</ACTION>",
        {"input_tokens": 10, "output_tokens": 5},
    )
    assert clean == "<ACTION>original</ACTION>"
    assert strategy == "Test API."
    assert audit["strategy_source"] == "contemporaneous"
    assert audit["strategy_attempts"] == 1
    assert usage["output_tokens"] == 5


def test_missing_strategy_does_not_replace_action():
    clean, strategy, _, audit = collect_strategy("<ACTION>original</ACTION>", {})
    assert clean == "<ACTION>original</ACTION>"
    assert strategy is None
    assert audit["strategy_valid"] is False
    assert audit["strategy_source"] == "missing"
    assert audit["strategy_retried"] is False


def test_missing_strategy_does_not_replace_http_response():
    clean, strategy, _, audit = collect_strategy("<RESPONSE>original</RESPONSE>", {})
    assert clean == "<RESPONSE>original</RESPONSE>"
    assert strategy is None
    assert audit["strategy_source"] == "missing"


def test_empty_generation_stays_empty():
    clean, strategy, _, audit = collect_strategy("", {})
    assert clean == "" and strategy is None
    assert audit["strategy_valid"] is False
