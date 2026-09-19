"""Structural trust-boundary checks; live Actions execution validates the YAML."""
from pathlib import Path
import unittest


class WorkflowTests(unittest.TestCase):
    def test_trusted_app_filter_precedes_job_concurrency(self):
        text = Path('examples/label-pr.yml').read_text()
        self.assertNotIn('\nconcurrency:', text)
        self.assertIn("github.event.check_run.app.id == 867647", text)
        self.assertIn("github.event.check_suite.app.id == 867647", text)
        self.assertLess(text.index('    if:'), text.index('    concurrency:'))
        self.assertIn("github.event.check_run.app.id || github.event.check_suite.app.id || 'manual'", text)

    def test_both_review_completion_signals_and_no_pr_code(self):
        text = Path('examples/label-pr.yml').read_text()
        self.assertIn('  check_run:\n    types: [completed]', text)
        self.assertIn('  check_suite:\n    types: [completed]', text)
        self.assertNotIn('pull_request_target:', text)
        self.assertNotIn('actions/checkout', text)
        self.assertIn("require-greptile: 'true'", text)
