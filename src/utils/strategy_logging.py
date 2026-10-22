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
