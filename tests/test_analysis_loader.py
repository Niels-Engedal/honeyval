"""NLP RESEARCH EXTENSION: result-folder names parse into the right factors."""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts/nlp/analysis_scripts"))
from utils.honeyval_analysis_loader import parse_config  # noqa: E402


class ParseConfigTests(unittest.TestCase):
    def test_exploit_detect_is_not_split_into_the_defender_name(self):
        f = parse_config("nearai-deepseek-ai-DeepSeek-V4.1-Flash-1017-abliterated-python-curl"
                         "-m-exploit-detect-openai-gpt-6-luna-m-mislead")
        self.assertEqual(f["attacker_model"],
                         "nearai-deepseek-ai-DeepSeek-V4.1-Flash-1017-abliterated-python-curl")
        self.assertEqual(f["attacker_prompt_strategy"], "exploit-detect")
        self.assertEqual(f["defender_model"], "openai-gpt-6-luna")
        self.assertEqual(f["defender_prompt_strategy"], "mislead")

    def test_low_defender_effort(self):
        f = parse_config("openai-gpt-6-luna-python-curl-m-exploit-openai-gpt-6-luna-l-vulnerable")
        self.assertEqual((f["attacker_effort"], f["defender_effort"]), ("medium", "low"))
        self.assertEqual(f["defender_model"], "openai-gpt-6-luna")

    def test_hide_prompt_and_rule_based_honeypot(self):
        f = parse_config("openai-gpt-6-luna-python-curl-h-exploit-detect-hide-rule-based-none")
        self.assertEqual(f["attacker_prompt_strategy"], "exploit-detect-hide")
        self.assertEqual(f["defender_model"], "rule-based")
        self.assertIsNone(f["defender_effort"])

    def test_unknown_name_fails(self):
        with self.assertRaises(ValueError):
            parse_config("not-a-honeyval-folder")


if __name__ == "__main__":
    unittest.main()
