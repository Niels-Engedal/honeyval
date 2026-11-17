import unittest

from src.agents.simple_react_agent import SimpleReactAgentSystemPrompt, ToolCall

BODY = (
    "<ACTION>\n<ACTION_NAME>\nTOOL\n</ACTION_NAME>\n<ACTION_BODY>\n<TOOL>\n"
    "<TOOL_NAME>\ncurl\n</TOOL_NAME>\n<TOOL_INPUT>\ncurl -i http://x/\n"
    "</TOOL_INPUT>\n</TOOL>\n</ACTION_BODY>"
)


class ActionParsingTests(unittest.TestCase):
    def setUp(self):
        self.prompt = SimpleReactAgentSystemPrompt(system_prompt="")

    def test_closed_action_unchanged(self):
        obs = self.prompt.parse_action(BODY + "\n</ACTION>")
        self.assertEqual(obs.executed_action_name, "TOOL")
        self.assertIsInstance(obs.action_body, ToolCall)
        self.assertFalse(obs.action_close_repaired)

    def test_missing_final_action_tag_is_closed(self):
        obs = self.prompt.parse_action(BODY + "\n")
        self.assertEqual(obs.executed_action_name, "TOOL")
        self.assertEqual(obs.action_body.tool_input, "curl -i http://x/")
        self.assertTrue(obs.action_close_repaired)

    def test_truncated_inside_body_is_still_an_error(self):
        obs = self.prompt.parse_action(BODY.removesuffix("</ACTION_BODY>"))
        self.assertEqual(obs.executed_action_name, "PARSING ERROR")
        self.assertFalse(obs.action_close_repaired)


if __name__ == "__main__":
    unittest.main()
