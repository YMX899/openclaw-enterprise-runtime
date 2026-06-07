from pathlib import Path
import re
import unittest


REPO_ROOT = Path(__file__).resolve().parents[2]
DOC_PATH = REPO_ROOT / "production-root-missing-gates-20260606.md"


class ProductionMissingGatesDocTests(unittest.TestCase):
    def test_doc_records_scope_change_without_claiming_sample_pass(self):
        text = DOC_PATH.read_text(encoding="utf-8")

        self.assertIn("root deployment is still NO_GO", text)
        self.assertIn("remaining production readiness gate: none expected from login/sample scope", text)
        self.assertIn("video link-read mode: ADOPTED", text)
        self.assertIn("OpenClaw standalone login evidence: PASS", text)
        self.assertIn("legacy ai001 console login is no longer a blocking", text)
        self.assertNotRegex(text, r"REAL_SAMPLE_EVIDENCE\.json:\s*PASS\b")

    def test_doc_records_real_sample_as_optional_diagnostic(self):
        text = DOC_PATH.read_text(encoding="utf-8")
        normalized = " ".join(text.split())

        self.assertIn("REAL_SAMPLE_EVIDENCE.json", text)
        self.assertIn("optional diagnostic evidence", text)
        self.assertIn("not required for the adopted link-read production scheme", normalized)

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
