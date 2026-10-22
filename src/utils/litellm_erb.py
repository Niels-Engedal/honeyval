"""
Copyright 2026 Google LLC

Licensed under the Apache License, Version 2.0 (the "License");
you may not use this file except in compliance with the License.
You may obtain a copy of the License at

    https://www.apache.org/licenses/LICENSE-2.0

Unless required by applicable law or agreed to in writing, software
distributed under the License is distributed on an "AS IS" BASIS,
WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
See the License for the specific language governing permissions and
limitations under the License.
"""

import logging
import os
import warnings
from logging import Logger
from time import sleep
from typing import Tuple

import litellm
import numpy as np

# Suppress Pydantic serialization warnings from litellm
warnings.filterwarnings("ignore", category=UserWarning, module="pydantic.main")

warnings.filterwarnings("ignore", module="litellm")
litellm.suppress_debug_info = True
litellm.set_verbose = False
logging.getLogger("litellm").setLevel(logging.CRITICAL)
logging.getLogger("LiteLLM").setLevel(logging.CRITICAL)


def _is_anthropic_model(model: str) -> bool:
    return "anthropic" in model or "claude" in model


# Anthropic allows up to 4 explicit cache_control breakpoints per request and uses a
# 20-block lookback window to find matching cached prefixes.
_ANTHROPIC_MAX_BREAKPOINTS = 4
_ANTHROPIC_LOOKBACK_WINDOW = 20


def _add_anthropic_cache_control(messages: list[dict]) -> list[dict]:
    """
    Adaptively place up to 4 cache_control breakpoints for Anthropic prompt caching.

    Breakpoint placement strategy
    ──────────────────────────────
    The conversation is strictly append-only: content at any fixed index never changes
    across calls, so any breakpoint at a stable position is always a cache hit once
    written.

    Frontier (messages[-2]): the only breakpoint required for correctness in sequential
    use. Each call appends exactly 2 blocks (one user turn + one assistant reply), so
    the new frontier is always 2 positions ahead of the previous one — well within the
    20-block lookback → guaranteed cache hit every call. Cost per call: cache-read for
    everything up to the previous frontier (0.1×), cache-write for the 2 new blocks
    (1.25×), base input price for messages[-1] only.

    Intermediate anchors at positions 20, 40, 60 (multiples of the lookback window):
    not needed for sequential calls, but provide safety for reconstructed sessions
    where the frontier may jump more than 20 blocks in a single call. Because the
    conversation is append-only, content at these positions never changes → once
    written they are permanent cache hits at negligible cost (0.1×).

    Cache pricing recap: writes 1.25×, reads 0.1×, 5-minute TTL refreshed on each use.
    See: https://docs.litellm.ai/docs/completion/prompt_caching
    """
    n = len(messages)
    if n < 2:
        return messages

    frontier = n - 2  # second-to-last; the final message is never cached

    positions: set[int] = {frontier}

    # Fill remaining budget with stable intermediate anchors at fixed multiples of the
    # lookback window (positions 20, 40, 60). range(1, MAX) gives k ∈ {1,2,3}.
    for k in range(1, _ANTHROPIC_MAX_BREAKPOINTS):
        pos = k * _ANTHROPIC_LOOKBACK_WINDOW
        if pos < frontier:
            positions.add(pos)

    # If budget still remains, also cache n-1 (the last/current message). It becomes
    # a permanent history entry from the very next call onward, so caching it now
    # means the next round reads it at 0.1× instead of writing it at 1.25×.
    # This is especially impactful for short conversations where the intermediate
    # anchors above add nothing (frontier < 20).
    last = n - 1
    if len(positions) < _ANTHROPIC_MAX_BREAKPOINTS and last > frontier:
        positions.add(last)

    result = []
    for i, msg in enumerate(messages):
        if i not in positions:
            result.append(msg)
            continue
        content = msg.get("content", "")
        if isinstance(content, str):
            content_blocks = [
                {
                    "type": "text",
                    "text": content,
                    "cache_control": {"type": "ephemeral"},
                }
            ]
        elif isinstance(content, list):
            # Content is already in blocks format; add cache_control to the last block
            content_blocks = [block.copy() for block in content]
            if content_blocks:
                content_blocks[-1]["cache_control"] = {"type": "ephemeral"}
        else:
            result.append(msg)
            continue
        result.append({**msg, "content": content_blocks})

    return result


def litellm_completion_erb(
    tries: int,
    min_wait: int,
    max_wait: int,
    model: str,
    messages: list[dict[str, str]],
    temperature: float = 0.6,
    reasoning_effort: str = "high",
    logger: Logger | None = None,
    enable_prompt_caching: bool = True,
    **litellm_kwargs,
) -> Tuple[str, dict[str, int]]:
    """
    Wrapper function to call the litellm completion API with exponential random backoff for stability.

    Args:
        tries (int): Number of tries to make to call the API.
        min_wait (int): Minimum waiting time after a failed call.
        max_wait (int): Maximum time to wait after a failed call.
        model (str): The name of the model to perform inference on.
        messages (list[dict[str, str]]): OpenAI API-style messages for the inference.
        temperature (float): Inference temeprature. Defaults to 0.6.
        reasoning_effort (str): Reasoning effort to use if the model is a reasoning model. Options are
          "low", "medium, "high, and "disable". Note that not every reasoning model supports setting
          the reasoning effort. In these cases, the parameter is simply ignored.
        logger (Logger): Optional logger instance.
        enable_prompt_caching (bool): Whether to add cache_control breakpoints to messages for
            Anthropic models. Other providers (OpenAI, Vertex, Together, OpenRouter) handle caching
            automatically or do not support it, so no explicit breakpoints are injected for them.
            Defaults to True.
        litellm_kwargs: All further keyword arguments that are to be passed on to litellm.completion.
            Relevant documentation: https://docs.litellm.ai/docs/completion/input

    Returns:
        str: The completion text.
        dict[str, int]: Token usage details with keys:
            - "input_tokens": number of input/prompt tokens.
            - "output_tokens": number of output/completion tokens.
            - "cached_tokens": number of cache-read tokens (0.1x cost for Anthropic).
            - "cache_creation_tokens": tokens written to cache (1.25x cost); Anthropic only,
              0 for all other providers.

    Raises:
        After the retries are exhausted, the latest API error is raised.
    """
    is_anthropic = _is_anthropic_model(model)
    n_tries = 0
    while True:
        n_tries += 1
        try:

            model_ = model
            if "vertex" in model:
                if "vertex_location" not in litellm_kwargs:
                    litellm_kwargs["vertex_location"] = "global"
            elif is_anthropic:
                anthropic_api_key = os.environ.get("ANTHROPIC_API_KEY")
                if not anthropic_api_key:
                    raise ValueError(
                        "Missing anthropic api key environment variable: ANTHROPIC_API_KEY"
                    )
            elif "together_ai" in model:
                together_api_key = os.environ.get("TOGETHERAI_API_KEY")
                if not together_api_key:
                    raise ValueError(
                        "Missing together.ai api key environment variable: TOGETHERAI_API_KEY"
                    )
            else:
                litellm_kwargs["base_url"] = os.environ.get("BIFROST_URL")
                litellm_kwargs["api_key"] = os.environ.get("BIFROST_KEY")
                # this is to make sure that litellm routes first to openai which redirects to bifrost
                model_ = "openai/" + model

            supported_params = litellm.get_supported_openai_params(model_)
            if supported_params is None:
                raise ValueError(
                    f"Could not identify the supported params for this model: {model_}. Perhaps you need to select the correct provider."
                )
            if "reasoning_effort" in supported_params:
                litellm_kwargs["reasoning_effort"] = reasoning_effort

            if is_anthropic and litellm_kwargs["reasoning_effort"] in [
                "low",
                "medium",
                "high",
                "max",
            ]:
                temperature = 1.0

            if is_anthropic and "top_p" in litellm_kwargs:
                del litellm_kwargs["top_p"]

            messages_to_send = (
                _add_anthropic_cache_control(messages)
                if enable_prompt_caching and is_anthropic
                else messages
            )

            response = litellm.completion(
                model=model_,
                messages=messages_to_send,
                temperature=temperature,
                drop_params=True,
                **litellm_kwargs,
            )
            text = response.choices[0].message.content
            if text is None:
                if logger is not None:
                    logger.error(
                        f"A LiteLLM Exception occurred: Response is None\n{response}"
                    )
                raise TypeError("None response was returned.")

            cached_tokens = 0
            if (
                hasattr(response.usage, "prompt_tokens_details")
                and response.usage.prompt_tokens_details is not None
            ):
                cached_tokens = (
                    getattr(response.usage.prompt_tokens_details, "cached_tokens", 0)
                    or 0
                )

            cache_creation_tokens = 0
            if is_anthropic:
                cache_creation_tokens = response.usage.cache_creation_input_tokens

            return (
                text,
                {
                    "input_tokens": response.usage.prompt_tokens,
                    "output_tokens": response.usage.completion_tokens,
                    "cached_tokens": cached_tokens,
                    "cache_creation_tokens": cache_creation_tokens,
                },
            )
        except Exception as e:
            tries_left = tries - n_tries
            if tries_left > 0:
                wait = np.random.randint(min_wait, min(min_wait + 2**n_tries, max_wait))
                if logger is not None:
                    logger.error(
                        f"An error occured while making a LiteLLM call:\n{e}.\nRetrying. Tries left: {tries_left}. Waiting for {wait}s."
                    )
                sleep(wait)
            else:
                if logger is not None:
                    logger.error(
                        f"Failed to make the LiteLLM call even after {tries} tries. Final error:\n{e}"
                    )
                raise e
