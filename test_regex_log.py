import re
import unittest


CHAT_LINE_RE = re.compile(
    r"^\d{1,2}/\d{1,2}/\d{4} \d{1,2}:\d{2}:\d{2} [AP]M: (\w+): (.+)\.$"
)


class ChatLogRegexTests(unittest.TestCase):
    def test_matches_xrc_chat_line(self):
        match = CHAT_LINE_RE.match("6/3/2025 2:06:07 AM: whatdidido: gg.")

        self.assertIsNotNone(match)
        self.assertEqual(match.group(1), "whatdidido")
        self.assertEqual(match.group(2), "gg")

    def test_rejects_non_chat_log_line(self):
        self.assertIsNone(CHAT_LINE_RE.match("Player Nick joined on position Red 1 from IP=127.0.0.1."))


if __name__ == "__main__":
    unittest.main()
