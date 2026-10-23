"""NLP RESEARCH EXTENSION tests (without changing upstream Honeyval retries)."""
import ast
from pathlib import Path

from src.agents.prompts import SIMPLE_REACT_SYSTEM_PROMPT
from src.utils.strategy_logging import (
    add_strategy_instructions,
    collect_strategy,
    extract_strategy,
)


def _original_defender_prompt():
    """Read the real upstream template without importing Honeyval/Docker."""
    path = Path(__file__).resolve().parents[1] / "src/http_apps/http_llm_honeypot.py"
    tree = ast.parse(path.read_text(encoding="utf-8"))
    for node in tree.body:
        if isinstance(node, ast.Assign) and any(
            isinstance(t, ast.Name) and t.id == "HOSTED_WEBAPP_SYSTEM_PROMPT"
            for t in node.targets
        ):
            return ast.literal_eval(node.value)
    raise AssertionError("Defender system prompt not found")


def test_attacker_prompt_strategy_before_action_in_both_examples():
    original = SIMPLE_REACT_SYSTEM_PROMPT.format(actions="TOOL", tools="curl")
    updated = add_strategy_instructions(original, role="attacker")
    assert original.count("<STRATEGY>") == 0
    assert updated.count("<STRATEGY>") == 2
    assert updated.count("<ACTION>") == original.count("<ACTION>")
    assert updated.index("<STRATEGY>") < updated.index("<ACTION>")
    assert "chosen NEXT action" in updated
    assert "3-5 concrete sentences" in updated
    assert "GIVEUP or SUCCESS" in updated
    assert "In each turn, you may execute only one action." in updated


def test_defender_prompt_strategy_before_response_in_both_examples():
    original = _original_defender_prompt().format(
        openapi_scheme="test-spec", additional_instructions="mislead test"
    )
    updated = add_strategy_instructions(original, role="defender")
    assert updated.count("<STRATEGY>") == 2
    assert updated.count("<RESPONSE>") == original.count("<RESPONSE>")
    assert updated.index("<STRATEGY>") < updated.index("<RESPONSE>")
    assert "mislead test" in updated
    assert "ADDITIONAL INSTRUCTIONS" in updated
    assert "3-5 concrete sentences" in updated
    assert "do not apply" in updated
    assert "<HEADER>" in updated


def test_unknown_or_changed_schema_fails_explicitly():
    for prompt, role in [
        ("unrelated schema", "attacker"),
        ("irrelevant", "defender"),
        ("anything", "unknown"),
    ]:
        try:
            add_strategy_instructions(prompt, role=role)
        except ValueError:
            pass
        else:
            raise AssertionError(f"Expected a schema error for {role}")


def test_strategy_separate_from_executed_action():
    raw = "<STRATEGY>Check routes.</STRATEGY>\n<ACTION>original</ACTION>"
    clean, strategy, usage, audit = collect_strategy(raw, {"input_tokens": 10})
    assert clean == "<ACTION>original</ACTION>"
    assert strategy == "Check routes."
    assert audit["strategy_source"] == "contemporaneous"
    assert audit["strategy_attempts"] == 1 and audit["strategy_retried"] is False
    assert audit["strategy_initial_response"] == raw
    assert audit["strategy_prompt_version"] == "strategic-rationale-v2"
    assert usage["input_tokens"] == 10


def test_strategy_separate_from_http_reply():
    clean, strategy = extract_strategy(
        "<STRATEGY>Return 401.</STRATEGY>\n<RESPONSE><STATUS>401</STATUS></RESPONSE>"
    )
    assert clean == "<RESPONSE><STATUS>401</STATUS></RESPONSE>"
    assert strategy == "Return 401."


def test_missing_strategy_does_not_replace_action_or_http_reply():
    for raw in ["<ACTION>original</ACTION>", "<RESPONSE>original</RESPONSE>", ""]:
        clean, strategy, _, audit = collect_strategy(raw, {})
        assert clean == raw
        assert strategy is None
        assert audit["strategy_source"] == "missing"
        assert audit["strategy_valid"] is False
        assert audit["strategy_retried"] is False
