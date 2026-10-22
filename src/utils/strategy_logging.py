"""Optional research-only strategy summaries, not private chain-of-thought.

The generated STRATEGY element must never be sent to a tool, HTTP client,
opposing model, or back into a model's conversation history.
"""

import os
import re

STRATEGY_PROMPT = (
    "\n\nRESEARCH LOGGING (not part of the action or HTTP response): "
    "Before your normal output, write a concise, high-level decision summary "
    "inside <STRATEGY>...</STRATEGY>. State your current objective, the "
    "observation that matters most, and why you chose this next action or "
    "response (1-3 sentences). Then provide the normal output exactly as "
    "specified. Do not put the strategy inside <ACTION> or <RESPONSE>. "
    "The STRATEGY element is removed before other agents or the environment "
    "receive your output.\n"
)

def strategy_enabled() -> bool:
    return os.environ.get("HONEYVAL_LOG_STRATEGY", "").lower() in {"1", "true", "yes"}

def extract_strategy(response: str) -> tuple[str, str | None]:
    """Return (response without STRATEGY block, recorded summary)."""
    blocks = re.findall(r"<STRATEGY>(.*?)</STRATEGY>", response, flags=re.DOTALL | re.IGNORECASE)
    clean = re.sub(
        r"<STRATEGY>.*?</STRATEGY>", "", response,
        flags=re.DOTALL | re.IGNORECASE,
    ).strip()
    return clean, (blocks[-1].strip() if blocks else None)

# ====================== NLP RESEARCH EXTENSION ======================
# These strategy prompts and retries are NOT part of upstream Honeyval.
# Generated summaries are elicited explanations, NOT hidden model reasoning.
STRATEGY_RETRY_PROMPT = (
    "NLP RESEARCH OUTPUT CORRECTION: Your response did not include a "
    "<STRATEGY>...</STRATEGY> summary. Regenerate your COMPLETE output with "
    "a brief 1-3 sentence strategy before the usual output. Maintain the "
    "same intended action or HTTP content and status. This is not a request "
    "from the opposing model or the HTTP client."
)


def collect_strategy(response, usage, retry):
    """NLP RESEARCH EXTENSION: at most one correction before action delivery."""
    clean, strategy = extract_strategy(response)
    initial = response
    retry_response = None
    attempts = 1
    usage = dict(usage)
    if not strategy:
        attempts = 2
        retry_response, extra = retry(STRATEGY_RETRY_PROMPT)
        clean_retry, strategy_retry = extract_strategy(retry_response)
        for key, value in extra.items():
            if isinstance(value, (int, float)) and not isinstance(value, bool):
                usage[key] = usage.get(key, 0) + value
        expected_tag = "<ACTION>" if "<ACTION>" in clean else "<RESPONSE>"
        if strategy_retry and expected_tag in clean_retry:
            clean, strategy = clean_retry, strategy_retry
    audit = {
        "strategy_valid": bool(strategy),
        "strategy_attempts": attempts,
        "strategy_retried": attempts == 2,
        "strategy_initial_missing": attempts == 2,
        "strategy_initial_response": initial,
        "strategy_retry_response": retry_response,
    }
    return clean, strategy, usage, audit
