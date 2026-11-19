"""NLP RESEARCH EXTENSION: the attacker's own history keeps its STRATEGY block."""
import os
import unittest
from logging import getLogger
from unittest import mock

from src.agents.simple_react_agent import (
    ActionObservation,
    SimpleReactAgent,
    SimpleReactAgentSystemPrompt,
)

RAW = (
    "<STRATEGY>Probe the endpoint first.</STRATEGY>\n"
    "<ACTION>\n<ACTION_NAME>\nGIVEUP\n</ACTION_NAME>\n<ACTION_BODY>\n"
    "</ACTION_BODY>\n</ACTION>"
)
USAGE = {"input_tokens": 1, "output_tokens": 1, "cached_tokens": 0, "cache_creation_tokens": 0}


def _agent():
    agent = object.__new__(SimpleReactAgent)
    agent._messages = []
    agent._history = [ActionObservation(executed_action_name="TOOL", environment_response="HTTP/1.1 200 OK")]
    agent._total_cost = 0.0
    agent._system_prompt = SimpleReactAgentSystemPrompt(system_prompt="")
    agent._make_call = mock.Mock(return_value=(RAW, USAGE))
    agent._update_cost = mock.Mock()
    agent._process_action = lambda obs: obs
    return agent


class AttackerHistoryTests(unittest.TestCase):
    @mock.patch.dict(os.environ, {"HONEYVAL_LOG_STRATEGY": "1"})
    def test_history_keeps_strategy_but_logs_it_separately(self):
        for step in ("initial", "inner"):
            with self.subTest(step=step):
                agent, metadata = _agent(), mock.Mock()
                if step == "initial":
                    agent._initial_step("Hack the app.", getLogger("test"), metadata)
                else:
                    agent._inner_step(getLogger("test"), metadata)
                self.assertEqual(agent._messages[-1], {"role": "assistant", "content": RAW})
                record = metadata.log.call_args.args[0]
                self.assertEqual(record["strategy"], "Probe the endpoint first.")
                self.assertNotIn("<STRATEGY>", record["raw_response"])
                self.assertEqual(record["event"], "GIVEUP")


if __name__ == "__main__":
    unittest.main()
