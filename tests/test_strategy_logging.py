"""Checks that research summaries are removed before normal parsing/delivery."""

from src.utils.strategy_logging import extract_strategy


def test_strategy_separated_from_action():
    raw = "<STRATEGY>Try login first.</STRATEGY>\n<ACTION><ACTION_NAME>TOOL</ACTION_NAME></ACTION>"
    clean, strategy = extract_strategy(raw)
    assert strategy == "Try login first."
    assert clean.startswith("<ACTION>")
    assert "<STRATEGY>" not in clean


def test_strategy_separated_from_http_reply():
    raw = "<STRATEGY>Reject bad password.</STRATEGY>\n<RESPONSE><CONTENT>Invalid credentials</CONTENT><STATUS>401</STATUS></RESPONSE>"
    clean, strategy = extract_strategy(raw)
    assert strategy == "Reject bad password."
    assert clean.startswith("<RESPONSE>")
    assert "<STRATEGY>" not in clean


def test_no_strategy_preserves_existing_output():
    raw = "<RESPONSE><STATUS>200</STATUS></RESPONSE>"
    clean, strategy = extract_strategy(raw)
    assert clean == raw
    assert strategy is None


# ====================== NLP RESEARCH EXTENSION ======================
def test_first_pass_valid_strategy_does_not_retry():
    from src.utils.strategy_logging import collect_strategy
    def must_not_retry(prompt):
        raise AssertionError("Unexpected retry")
    original = "<STRATEGY>Inspect routes.</STRATEGY><ACTION>x</ACTION>"
    clean, strategy, usage, audit = collect_strategy(
        original, {"input_tokens": 10, "output_tokens": 5}, must_not_retry
    )
    assert strategy == "Inspect routes."
    assert clean == "<ACTION>x</ACTION>"
    assert audit["strategy_attempts"] == 1
    assert usage["input_tokens"] == 10


def test_missing_strategy_one_correction_and_token_accounting():
    from src.utils.strategy_logging import collect_strategy
    called = []
    def retry(prompt):
        called.append(prompt)
        return "<STRATEGY>Try registration.</STRATEGY><ACTION>y</ACTION>", {
            "input_tokens": 3, "output_tokens": 4
        }
    clean, strategy, usage, audit = collect_strategy(
        "<ACTION>x</ACTION>", {"input_tokens": 10, "output_tokens": 5}, retry
    )
    assert len(called) == 1
    assert strategy == "Try registration."
    assert clean == "<ACTION>y</ACTION>"
    assert usage["input_tokens"] == 13
    assert usage["output_tokens"] == 9
    assert audit["strategy_attempts"] == 2
    assert audit["strategy_valid"]


def test_retry_failure_retains_original_action_and_flags_incomplete():
    from src.utils.strategy_logging import collect_strategy
    clean, strategy, _, audit = collect_strategy(
        "<ACTION>x</ACTION>", {}, lambda _: ("<ACTION>y</ACTION>", {})
    )
    assert clean == "<ACTION>x</ACTION>"
    assert strategy is None
    assert audit["strategy_valid"] is False
