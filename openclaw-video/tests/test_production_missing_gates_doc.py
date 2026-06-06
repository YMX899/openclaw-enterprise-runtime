from pathlib import Path
import re
import unittest


REPO_ROOT = Path(__file__).resolve().parents[2]
DOC_PATH = REPO_ROOT / "production-root-missing-gates-20260606.md"


class ProductionMissingGatesDocTests(unittest.TestCase):
    def test_doc_records_remaining_hard_gate_without_claiming_pass(self):
        text = DOC_PATH.read_text(encoding="utf-8")

        self.assertIn("root deployment is still NO_GO", text)
        self.assertIn("authenticated_dify_baseline", text)
        self.assertIn("remaining preflight gate: authenticated_dify_baseline", text)
        self.assertNotRegex(text, r"authenticated_baseline:\s*PASS\b")
        self.assertNotRegex(text, r"existing app message:\s*PASS\b")

    def test_doc_records_operator_deferred_sample_as_current_phase_only(self):
        text = DOC_PATH.read_text(encoding="utf-8")

        self.assertIn("REAL_SAMPLE_EVIDENCE.json", text)
        self.assertIn("explicitly deferred for the current Ubuntu 22.04", text)
        self.assertIn("ALLOW_DOUYIN_SAMPLE_DEFERRED=1", text)
        self.assertIn("Final production can still require it", text)

    def test_doc_does_not_record_sensitive_material(self):
        text = DOC_PATH.read_text(encoding="utf-8")
        forbidden = [
            r"Authorization:\s*Bearer\s+\S+",
            "Cookie" + r":\s*\S+=\S+",
            "CSRF" + r"[-_ ]?Token:\s*\S+",
            r"password\s*[:=]\s*\S+",
            r"sk-[0-9a-zA-Z]{16,}",
            r"-----BEGIN (?:OPENSSH|RSA|EC|PRIVATE) KEY-----",
        ]

        for pattern in forbidden:
            self.assertIsNone(re.search(pattern, text, re.IGNORECASE))


if __name__ == "__main__":
    unittest.main()
