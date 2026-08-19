import datetime
import json
import os
import tempfile
import unittest
from types import SimpleNamespace

from services.reporting import build_report_context, write_markdown_report


class ReportingTests(unittest.TestCase):
    def test_report_writes_markdown_and_metadata_sidecar(self):
        client = SimpleNamespace(id=7, name="Acme SEO", domain="example.com")
        snapshot = SimpleNamespace(id=42)
        settings = {"model_name": "test-model"}
        context = build_report_context(
            client,
            snapshot,
            {"summary": "baseline"},
            settings,
            now=datetime.datetime(2026, 8, 19, 12, 30),
        )
        with tempfile.TemporaryDirectory() as directory:
            artifact = write_markdown_report(directory, context, "## Summary\nAll good.")
            self.assertTrue(os.path.exists(artifact.markdown_path))
            self.assertTrue(os.path.exists(artifact.metadata_path))
            with open(artifact.metadata_path, encoding="utf-8") as handle:
                metadata = json.load(handle)
            self.assertEqual(metadata["snapshot_id"], 42)
            self.assertEqual(metadata["model_name"], "test-model")
            self.assertNotIn("brief", metadata)


if __name__ == "__main__":
    unittest.main()
