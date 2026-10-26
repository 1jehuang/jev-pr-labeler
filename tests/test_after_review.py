import argparse
import io
import json
import subprocess
import unittest
from unittest.mock import Mock, patch

from jev_labeler import __main__ as cli
from jev_labeler.after_review import dispatch, main


@patch.dict('os.environ', {'GH_TOKEN': 'fake-github'}, clear=True)
class BatchTests(unittest.TestCase):
    def setUp(self):
        self.args = argparse.Namespace(repo='owner/repo', pr=None, check_sha=None,
                                       all_open=True, threshold=.75, apply=False,
                                       ensure_labels=False, require_greptile=True)
        self.github = Mock()
        self.github.pages.return_value = [{'number': number} for number in (1, 2, 3)]
        self.first = {'pull_request': 1, 'status': 'waiting_for_greptile'}
        self.last = {'pull_request': 3, 'mode': 'dry-run', 'add': [], 'remove': []}

    def test_known_failures_preserve_other_pr_outcomes(self):
        for failure in (KeyError('PRIVATE'), TypeError('PRIVATE'), OSError('PRIVATE'),
                        RuntimeError('API connection failed.'), ValueError('Invalid provider usage')):
            with self.subTest(error=type(failure).__name__), \
                    patch('jev_labeler.after_review.GitHub', return_value=self.github), \
                    patch('jev_labeler.after_review.run', side_effect=[self.first, failure, self.last]) as run:
                report = dispatch(self.args)
                self.assertEqual(report['matched_open_prs'], 3)
                self.assertEqual(report['results'][0], self.first)
                self.assertEqual(report['results'][2], self.last)
                error = report['results'][1]
                self.assertEqual(error['pull_request'], 2)
                self.assertEqual(error['status'], 'error')
                self.assertNotIn('PRIVATE', error['reason'])
                if isinstance(failure, (ValueError, RuntimeError)):
                    self.assertEqual(error['reason'], str(failure))
                self.assertEqual([call.args[0].pr for call in run.call_args_list], [1, 2, 3])
                self.assertIsNone(self.args.pr)

    def test_batch_reports_aggregate_usage(self):
        first = dict(self.first, usage={'prompt_tokens': 10, 'completion_tokens': 2.5})
        last = dict(self.last, usage={'prompt_tokens': 5, 'completion_tokens': 1})
        with patch('jev_labeler.after_review.GitHub', return_value=self.github), \
                patch('jev_labeler.after_review.run',
                      side_effect=[first, RuntimeError('API request failed: HTTP 500.'), last]):
            report = dispatch(self.args)
        # 15/3.5 comes from the two successful PRs; the failed one contributes nothing.
        self.assertEqual(report['usage'], {'prompt_tokens': 15.0, 'completion_tokens': 3.5})
        self.assertEqual(report['results'][0]['usage'], first['usage'])

    def test_batch_without_any_usage_omits_totals(self):
        with patch('jev_labeler.after_review.GitHub', return_value=self.github), \
                patch('jev_labeler.after_review.run', side_effect=[self.first, self.last, self.last]):
            report = dispatch(self.args)
        self.assertNotIn('usage', report)

    def test_main_emits_complete_json_and_fails_when_one_pr_errors(self):
        closed = {'head': {'sha': 'a' * 40}, 'state': 'closed'}
        self.github.pull.side_effect = [closed, {}, closed]
        with patch('sys.argv', ['after_review', '--repo', 'owner/repo', '--all-open']), \
                patch('jev_labeler.after_review.GitHub', return_value=self.github), \
                patch('jev_labeler.__main__.GitHub', return_value=self.github), \
                patch('sys.stdout', new_callable=io.StringIO) as output, \
                patch('sys.stderr', new_callable=io.StringIO) as errors:
            self.assertEqual(main(), 1)
        report = json.loads(output.getvalue())
        self.assertEqual(len(report['results']), 3)
        self.assertEqual([item['status'] for item in report['results']],
                         ['skipped_closed', 'error', 'skipped_closed'])
        self.assertEqual(report['results'][2]['pull_request'], 3)
        self.assertNotIn('PRIVATE', output.getvalue())
        self.assertEqual(errors.getvalue(), '')

    def test_empty_batch_succeeds_without_classification(self):
        self.github.pages.return_value = []
        with patch('sys.argv', ['after_review', '--repo', 'owner/repo', '--all-open']), \
                patch('jev_labeler.after_review.GitHub', return_value=self.github), \
                patch('jev_labeler.after_review.run') as run, \
                patch('sys.stdout', new_callable=io.StringIO) as output:
            self.assertEqual(main(), 0)
        report = json.loads(output.getvalue())
        self.assertEqual(report['results'], [])
        self.assertNotIn('status', report)
        run.assert_not_called()

    def test_check_sha_without_a_live_head_reports_no_match(self):
        self.args.check_sha, self.args.all_open = 'b' * 40, False
        self.github.pages.return_value = [{'number': 1, 'head': {'sha': 'a' * 40}}]
        with patch('jev_labeler.after_review.GitHub', return_value=self.github), \
                patch('jev_labeler.after_review.run') as run:
            report = dispatch(self.args)
        self.assertEqual(report['status'], 'no_matching_open_prs')
        self.assertEqual(report['matched_open_prs'], 0)
        self.assertEqual(report['results'], [])
        self.assertIn('head SHA', report['reason'])
        run.assert_not_called()

    def test_check_sha_match_does_not_report_no_match(self):
        self.args.check_sha, self.args.all_open = 'a' * 40, False
        self.github.pages.return_value = [{'number': 1, 'head': {'sha': 'a' * 40}},
                                          {'number': 2, 'head': {'sha': 'b' * 40}}]
        with patch('jev_labeler.after_review.GitHub', return_value=self.github), \
                patch('jev_labeler.after_review.run', return_value=self.first):
            report = dispatch(self.args)
        self.assertEqual(report['matched_open_prs'], 1)
        self.assertNotIn('status', report)

    def test_cli_surfaces_actionable_local_errors(self):
        cases = ((['--all-open', '--threshold', 'nan'], 'Threshold must be finite'),
                 (['--check-sha', 'not-a-sha'], '40 lowercase hexadecimal'))
        for argv, expected in cases:
            with self.subTest(argv=argv), \
                    patch('sys.argv', ['after_review', '--repo', 'owner/repo', *argv]), \
                    patch('jev_labeler.after_review.GitHub') as github, \
                    patch('sys.stderr', new_callable=io.StringIO) as errors:
                self.assertEqual(main(), 1)
                self.assertTrue(errors.getvalue().startswith('jev-pr-labeler: '))
                self.assertIn(expected, errors.getvalue())
                self.assertNotIn('credentials', errors.getvalue())
                github.return_value.pages.assert_not_called()

    def test_cli_keeps_credential_helper_failures_generic(self):
        with patch.dict('os.environ', {}, clear=True), \
                patch('sys.argv', ['after_review', '--repo', 'owner/repo', '--all-open']), \
                patch('jev_labeler.after_review.subprocess.check_output',
                      side_effect=subprocess.CalledProcessError(1, ['gh', 'auth', 'token'])), \
                patch('sys.stderr', new_callable=io.StringIO) as errors:
            self.assertEqual(main(), 1)
        self.assertEqual(errors.getvalue(),
                         'jev-pr-labeler: could not read a GitHub token from gh; '
                         'set GH_TOKEN or authenticate gh.\n')

    def test_unexpected_programming_errors_are_not_swallowed(self):
        with patch('jev_labeler.after_review.GitHub', return_value=self.github), \
                patch('jev_labeler.after_review.run', side_effect=AssertionError('bug')):
            with self.assertRaises(AssertionError):
                dispatch(self.args)

    def test_invalid_threshold_is_rejected_before_credentials_or_api(self):
        for threshold in (float('nan'), float('inf'), -1, 2):
            self.args.threshold = threshold
            with self.subTest(threshold=threshold), patch.dict('os.environ', {}, clear=True), \
                    patch('jev_labeler.after_review.subprocess.check_output') as credentials, \
                    patch('jev_labeler.after_review.GitHub') as github:
                github.return_value.pages.return_value = []
                with self.assertRaisesRegex(ValueError, 'Threshold'):
                    dispatch(self.args)
                credentials.assert_not_called()
                github.assert_not_called()

    def test_valid_threshold_boundaries_allow_empty_batches(self):
        self.github.pages.return_value = []
        for threshold in (0, .75, 1):
            self.args.threshold = threshold
            with self.subTest(threshold=threshold), \
                    patch('jev_labeler.after_review.GitHub', return_value=self.github):
                self.assertEqual(dispatch(self.args)['results'], [])

    def test_single_pr_cli_keeps_sanitized_errors(self):
        for failure in (KeyError('PRIVATE'), TypeError('PRIVATE'), OSError('PRIVATE')):
            with self.subTest(error=type(failure).__name__), \
                    patch('sys.argv', ['jev-pr-labeler', '--repo', 'owner/repo', '--pr', '1']), \
                    patch('jev_labeler.__main__.run', side_effect=failure), \
                    patch('sys.stderr', new_callable=io.StringIO) as errors:
                self.assertEqual(cli.main(), 1)
                self.assertNotIn('PRIVATE', errors.getvalue())
                self.assertTrue(errors.getvalue().startswith('jev-pr-labeler: '))
