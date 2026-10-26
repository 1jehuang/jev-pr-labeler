"""Structural trust-boundary checks plus real execution of the composite action step."""
import os
import re
import subprocess
import tempfile
import textwrap
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
ACTION = ROOT / "action.yml"


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

    def test_every_declared_input_reaches_the_step(self):
        text = ACTION.read_text()
        declared = text.split("\ninputs:\n", 1)[1].split("\nruns:\n", 1)[0]
        inputs = re.findall(r"^  ([a-z][a-z-]+):$", declared, re.MULTILINE)
        self.assertEqual(sorted(inputs), sorted(["github-token", "openrouter-api-key", "repository",
                                                 "pull-request", "check-sha", "require-greptile",
                                                 "apply"]))
        for name in inputs:
            self.assertIn("inputs.%s }}" % name, text, name)


def composite_script():
    """The bash body of the composite step, so a test can run the real wiring."""
    lines = ACTION.read_text().splitlines()
    start = next(index for index, line in enumerate(lines) if line.strip() == "run: |")
    indent = len(lines[start]) - len(lines[start].lstrip())
    body = []
    for line in lines[start + 1:]:
        if line.strip() and len(line) - len(line.lstrip()) <= indent:
            break
        body.append(line)
    return textwrap.dedent("\n".join(body))


def action_env_keys():
    """Env names the composite step declares, so the stub harness cannot drift."""
    lines = ACTION.read_text().splitlines()
    start = next(index for index, line in enumerate(lines) if line.strip() == "env:")
    indent = len(lines[start]) - len(lines[start].lstrip())
    keys = []
    for line in lines[start + 1:]:
        if line.strip() and len(line) - len(line.lstrip()) <= indent:
            break
        name = line.strip().split(":", 1)[0]
        if name:
            keys.append(name)
    return keys


# Mirrors the defaults declared in action.yml. Every key there must appear here so a
# step that reads an input cannot silently skip the stubbed python3 in these tests.
STEP_ENV = {
    "PYTHONPATH": ".",
    "GITHUB_TOKEN": "test-token",
    "GH_TOKEN": "test-token",
    "OPENROUTER_API_KEY": "test-key",
    "LABEL_REPOSITORY": "owner/repo",
    "LABEL_PR": "",
    "LABEL_CHECK_SHA": "",
    "LABEL_REQUIRE_REVIEW": "true",
    "LABEL_APPLY": "false",
}


class CompositeActionTests(unittest.TestCase):
    """Run the step with a stub python3: the input-to-flag mapping is production behavior."""

    def test_step_env_mirrors_action_yml(self):
        missing = [key for key in action_env_keys() if key not in STEP_ENV]
        self.assertEqual(missing, [], "the stub env omits action.yml env keys: %s" % missing)

    def run_step(self, **inputs):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            record = root / "argv.txt"
            stub = root / "python3"
            stub.write_text('#!/bin/sh\nprintf "%s\\n" "$@" > "$ARGV_FILE"\n')
            stub.chmod(0o755)
            env = {
                "PATH": "%s%s%s" % (root, os.pathsep, os.environ["PATH"]),
                "GITHUB_ACTION_PATH": str(root),
                "ARGV_FILE": str(record),
            }
            env.update(STEP_ENV)
            env.update(inputs)
            result = subprocess.run(["bash", "-e", "-o", "pipefail", "-c", composite_script()],
                                    env=env, cwd=directory, capture_output=True, text=True)
            argv = record.read_text().splitlines() if record.exists() else []
        return result, argv

    def test_pull_request_selects_the_pr_flag(self):
        result, argv = self.run_step(LABEL_PR="123")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(argv, ["-m", "jev_labeler.after_review", "--repo", "owner/repo",
                                "--pr", "123"])

    def test_check_sha_selects_the_sha_flag(self):
        result, argv = self.run_step(LABEL_CHECK_SHA="a" * 40)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(argv, ["-m", "jev_labeler.after_review", "--repo", "owner/repo",
                                "--check-sha", "a" * 40])

    def test_exactly_one_selector_is_required(self):
        for label_pr, check_sha in (("123", "a" * 40), ("", "")):
            with self.subTest(pull_request=label_pr, check_sha=check_sha):
                result, argv = self.run_step(LABEL_PR=label_pr, LABEL_CHECK_SHA=check_sha)
                self.assertEqual(result.returncode, 1)
                self.assertIn("exactly one of pull-request or check-sha", result.stderr)
                self.assertEqual(argv, [])

    def test_require_greptile_opt_out_is_explicit(self):
        result, argv = self.run_step(LABEL_PR="7", LABEL_REQUIRE_REVIEW="false")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(argv[-1], "--without-greptile")
        result, argv = self.run_step(LABEL_PR="7")
        self.assertNotIn("--without-greptile", argv)

    def test_require_greptile_rejects_non_boolean(self):
        result, argv = self.run_step(LABEL_PR="7", LABEL_REQUIRE_REVIEW="yes")
        self.assertEqual(result.returncode, 1)
        self.assertIn("require-greptile must be true or false", result.stderr)
        self.assertEqual(argv, [])

    def test_apply_implies_ensure_labels(self):
        result, argv = self.run_step(LABEL_PR="7", LABEL_APPLY="true")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(argv[-2:], ["--apply", "--ensure-labels"])
        result, argv = self.run_step(LABEL_PR="7")
        self.assertNotIn("--apply", argv)
        self.assertNotIn("--ensure-labels", argv)

    def test_apply_rejects_non_boolean(self):
        result, argv = self.run_step(LABEL_PR="7", LABEL_APPLY="yes")
        self.assertEqual(result.returncode, 1)
        self.assertIn("apply must be true or false", result.stderr)
        self.assertEqual(argv, [])
