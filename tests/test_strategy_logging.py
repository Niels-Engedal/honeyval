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
