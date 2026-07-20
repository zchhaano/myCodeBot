from __future__ import annotations

import json
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path

from qa_interaction_scan import scan_file


class ScanFileTests(unittest.TestCase):
    def setUp(self) -> None:
        self.start = datetime(2026, 7, 20, 8, 29, tzinfo=timezone.utc)
        self.end = datetime(2026, 7, 20, 8, 31, tzinfo=timezone.utc)

    def scan_text(self, text: str):
        record = {
            "type": "message",
            "timestamp": "2026-07-20T08:30:00Z",
            "message": {"role": "user", "content": text},
        }
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "session.jsonl"
            path.write_text(json.dumps(record) + "\n", encoding="utf-8")
            return scan_file("main", path, self.start, self.end)

    def test_ignores_cron_prompt_stored_as_user_message(self) -> None:
        findings = self.scan_text(
            "  [CRON:job-id Weekly QA] Prüfe unvollständige Workflows und failed actions."
        )

        self.assertEqual(findings, [])

    def test_keeps_normal_user_complaint(self) -> None:
        findings = self.scan_text("Die Antwort ist unvollständig.")

        self.assertEqual(len(findings), 1)
        self.assertEqual(findings[0].severity, "high")
        self.assertIn("unvollständig", findings[0].terms)


if __name__ == "__main__":
    unittest.main()
