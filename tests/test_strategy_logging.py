"""NLP RESEARCH EXTENSION tests: first decisions remain immutable."""
from src.utils.strategy_logging import collect_strategy, extract_strategy

def test_first_pass():
    def unexpected(*args):
        raise AssertionError("No explanation needed")
    raw = "<STRATEGY>Probe paths.</STRATEGY><ACTION>original</ACTION>"
    clean, strategy, _, audit = collect_strategy(raw, {}, unexpected)
    assert clean == "<ACTION>original</ACTION>"
    assert strategy == "Probe paths."
    assert audit["strategy_source"] == "contemporaneous"

def test_retrospective_keeps_first_action():
    calls = []
    def explain(original, prompt):
        calls.append(original)
        return "<STRATEGY>Original action explained.</STRATEGY><ACTION>different</ACTION>", {"input_tokens": 5, "output_tokens": 7}
    clean, strategy, usage, audit = collect_strategy(
        "<ACTION>original</ACTION>", {"input_tokens": 10, "output_tokens": 3}, explain
    )
    assert calls == ["<ACTION>original</ACTION>"]
    assert clean == "<ACTION>original</ACTION>"
    assert strategy == "Original action explained."
    assert audit["strategy_source"] == "retrospective"
    assert usage["input_tokens"] == 15 and usage["output_tokens"] == 10

def test_missing_explanation_retains_output():
    clean, strategy, _, audit = collect_strategy(
        "<RESPONSE>fixed</RESPONSE>", {}, lambda *_: ("missing", {})
    )
    assert clean == "<RESPONSE>fixed</RESPONSE>"
    assert strategy is None and audit["strategy_source"] == "missing"

def test_explanation_error_does_not_break_execution():
    def fail(*args):
        raise RuntimeError("test failure")
    clean, strategy, _, audit = collect_strategy("<ACTION>original</ACTION>", {}, fail)
    assert clean == "<ACTION>original</ACTION>" and strategy is None
    assert "STRATEGY_LOGGING_ERROR" in audit["strategy_explanation_response"]
