"""Exercise the shipped module entry points without credentials or API calls."""
from pathlib import Path
import subprocess
import sys
import unittest


class CLIProcessTests(unittest.TestCase):
    def invoke(self, module, *args):
        return subprocess.run(
            [sys.executable, '-m', module, *args],
            cwd=Path(__file__).resolve().parents[1], env={'PATH': ''},
            capture_output=True, text=True, timeout=10)

    def test_both_entry_points_offer_help_without_credentials(self):
        for module in ('jev_labeler', 'jev_labeler.after_review'):
            with self.subTest(module=module):
                result = self.invoke(module, '--help')
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertIn('--repo', result.stdout)
                self.assertIn('--threshold', result.stdout)
                self.assertEqual(result.stderr, '')

    def test_invalid_thresholds_fail_before_credential_lookup(self):
        for module in ('jev_labeler', 'jev_labeler.after_review'):
            for threshold in ('nan', 'inf', '-1', '2'):
                with self.subTest(module=module, threshold=threshold):
                    result = self.invoke(module, '--repo', 'owner/repo', '--pr', '1',
                                         '--threshold', threshold)
                    self.assertEqual(result.returncode, 1)
                    self.assertEqual(result.stdout, '')
                    self.assertEqual(result.stderr,
                                     'jev-pr-labeler: Threshold must be finite and between 0 and 1.\n')
