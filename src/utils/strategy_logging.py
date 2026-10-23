"""NLP RESEARCH EXTENSION (not upstream): elicited strategies, not hidden reasoning."""
import os
import re

STRATEGY_PROMPT = (
    "\n\nNLP RESEARCH EXTENSION: Before the normal output, provide a brief "
    "high-level decision summary inside <STRATEGY>...</STRATEGY>. Then produce "
    "the original <ACTION> or <RESPONSE> normally. Keep strategy outside it.\n"
)
RETROSPECTIVE_PROMPT = (
    "NLP RESEARCH EXTENSION — logging only. The preceding assistant message "
    "is a FIXED decision that will be executed unchanged. Explain that already-"
    "selected decision in 1-3 sentences using ONLY <STRATEGY>...</STRATEGY>. "
    "Do not propose a new action or HTTP response."
)


def strategy_enabled():
    return os.environ.get("HONEYVAL_LOG_STRATEGY", "").lower() in {"1", "true", "yes"}


def extract_strategy(response):
    blocks = re.findall(r"<STRATEGY>(.*?)</STRATEGY>", response, re.DOTALL | re.I)
    clean = re.sub(r"<STRATEGY>.*?</STRATEGY>", "", response, flags=re.DOTALL | re.I).strip()
    return clean, (blocks[-1].strip() if blocks and blocks[-1].strip() else None)


def collect_strategy(response, usage, explain):
    """Never substitute another output for the model's first decision.

    explain(fixed_output, prompt) is an optional explanation-only call.
    Its output must never reach the environment or either agent's history.
    """
    clean, strategy = extract_strategy(response)
    provenance = "contemporaneous" if strategy else "missing"
    explanation_response = None
    attempts = 1
    total_usage = dict(usage)
    if not strategy:
        attempts = 2
        try:
            explanation_response, extra = explain(clean, RETROSPECTIVE_PROMPT)
            _, candidate = extract_strategy(explanation_response)
            if candidate:
                strategy = candidate
                provenance = "retrospective"
            for key, value in extra.items():
                if isinstance(value, (int, float)) and not isinstance(value, bool):
                    total_usage[key] = total_usage.get(key, 0) + value
        except Exception as exc:
            explanation_response = (
                f"STRATEGY_LOGGING_ERROR: {type(exc).__name__}: {exc}"
            )
    audit = {
        "strategy_valid": bool(strategy),
        "strategy_source": provenance,
        "strategy_attempts": attempts,
        "strategy_retried": attempts == 2,
        "strategy_initial_missing": attempts == 2,
        "strategy_initial_response": response,
        "strategy_retry_response": explanation_response,
        "strategy_explanation_response": explanation_response,
    }
    return clean, strategy, total_usage, audit
