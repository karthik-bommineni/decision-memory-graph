import unittest
from pathlib import Path

from ledger.adapters.claude import iter_normalized, normalize_conversation
from ledger.redact import redact_text

FIXTURE = Path(__file__).parent / "fixtures" / "tiny_claude.json"


class AdapterTests(unittest.TestCase):
    def test_normalize_claude_fixture(self):
        convs = list(iter_normalized(FIXTURE))
        self.assertEqual(len(convs), 1)
        conv = convs[0]
        self.assertEqual(conv["source"], "claude")
        self.assertEqual(conv["conv_id"], "conv-1")
        self.assertEqual(conv["title"], "Pick a database")
        self.assertEqual([m["role"] for m in conv["messages"]], ["user", "assistant", "user"])
        self.assertIn("Postgres", conv["messages"][2]["text"])

    def test_redact_email(self):
        self.assertIn("[REDACTED_EMAIL]", redact_text("write to test@example.com please"))

    def test_skip_empty_sender(self):
        raw = {
            "uuid": "x",
            "name": "empty",
            "chat_messages": [{"sender": "tool", "text": "noise", "created_at": "t"}],
        }
        self.assertIsNone(normalize_conversation(raw))


if __name__ == "__main__":
    unittest.main()
