"""The composite action must skip, not fail, when no OpenRouter key is configured."""
import os
from pathlib import Path
import subprocess
import tempfile
import unittest


def run_script():
    """Extract the composite step's `run: |` body without a YAML dependency."""
    lines = Path('action.yml').read_text().splitlines()
    start = next(i for i, line in enumerate(lines) if line.strip() == 'run: |') + 1
    indent = len(lines[start]) - len(lines[start].lstrip())
    body = []
    for line in lines[start:]:
        if line.strip() and len(line) - len(line.lstrip()) < indent:
            break
        body.append(line[indent:])
    return '\n'.join(body)


class ActionTests(unittest.TestCase):
    def run_action(self, key):
        with tempfile.TemporaryDirectory() as action_path:
            env = {**os.environ, 'GITHUB_ACTION_PATH': action_path, 'OPENROUTER_API_KEY': key,
                   'LABEL_REPOSITORY': 'owner/repo', 'LABEL_PR': '1', 'LABEL_CHECK_SHA': '',
                   'LABEL_REQUIRE_REVIEW': 'true', 'LABEL_APPLY': 'false', 'PYTHONPATH': action_path}
            return subprocess.run(['bash', '-c', run_script()], env=env, capture_output=True, text=True)

    def test_missing_key_skips_successfully(self):
        for key in ('', '  \n'):
            result = self.run_action(key)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertIn('skipping labeling', result.stdout)

    def test_present_key_still_runs_the_labeler(self):
        # The empty action path has no jev_labeler package, so reaching python proves no skip.
        result = self.run_action('fake-openrouter')
        self.assertNotEqual(result.returncode, 0)
        self.assertNotIn('skipping labeling', result.stdout)
        self.assertIn('No module named', result.stderr)


if __name__ == '__main__':
    unittest.main()
