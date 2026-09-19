import argparse
import copy
import unittest
from unittest.mock import patch
from jev_labeler.__main__ import run
from jev_labeler.classifier import build_request


def response():
    questions = build_request({})['questions']
    answers = {}
    for key, question in questions.items():
        choice = {'type': 'bug', 'size': 'S', 'area: config': 'yes'}.get(key, 'no')
        answers[key] = {'type': 'choice', 'choice': choice, 'confidence': 1.0,
                        'probabilities': {c: float(c == choice) for c in question['criteria']}}
    return {'answers': answers, 'model': 'typesafe/jev-1.13'}


class FakeGitHub:
    def __init__(self, *args):
        self.pr = {'state': 'open', 'changed_files': 1, 'title': 'Fix config', 'body': '',
                   'head': {'sha': 'a'}, 'base': {'sha': 'b'}, 'labels': [{'name': 'existing'}]}
        self.writes = []
        self.reads = 0
        self.stale_at = None
        self.live_base = 'live-base'
        self.base_reads = 0
        self.base_stale_at = None

    def pull(self, number):
        self.reads += 1
        if self.reads == self.stale_at:
            self.pr['head']['sha'] = 'changed'
        return copy.deepcopy(self.pr)

    def files(self, number):
        return [{'filename': 'config.py', 'status': 'modified', 'additions': 1, 'deletions': 1,
                 'patch': '@@ -1 +1 @@\n-bad\n+good'}]

    def base_sha(self, pr):
        self.base_reads += 1
        if self.base_reads == self.base_stale_at:
            self.live_base = 'new-base'
        return self.live_base

    def compare_files(self, base, head):
        return self.files(1), {'source': 'github_immutable_compare', 'base_sha': base,
                              'head_sha': head, 'merge_base_sha': 'merge-base', 'changed_files': 1}

    def owned_labels(self, number, actor):
        return set()

    def pages(self, path):
        return [{'name': n} for n in ['type: bug', 'size: S', 'area: config']]

    def ensure_labels(self, labels):
        self.writes.append('ensure')

    def apply(self, number, additions, removals, actor=None):
        self.writes.append((additions, removals))
        names = {x['name'] for x in self.pr['labels']} | set(additions)
        names -= set(removals)
        self.pr['labels'] = [{'name': name} for name in names]


@patch.dict('os.environ', {'GH_TOKEN': 'fake-github', 'OPENROUTER_API_KEY': 'fake-openrouter', 'GITHUB_ACTIONS': ''})
class CLITests(unittest.TestCase):
    def setUp(self):
        self.args = argparse.Namespace(repo='owner/repo', pr=1, threshold=.75, apply=False, ensure_labels=False)
        self.github = FakeGitHub()

    def invoke(self):
        with patch('jev_labeler.__main__.GitHub', return_value=self.github), patch('jev_labeler.evidence.request_json', return_value=response()):
            return run(self.args)

    def test_dry_run_no_writes(self):
        self.assertEqual(self.invoke()['add'], ['area: config', 'size: S', 'type: bug'])
        self.assertEqual(self.github.writes, [])

    def test_apply_and_verify(self):
        self.args.apply = True
        self.assertTrue(self.invoke()['verified'])
        self.assertEqual(len(self.github.writes), 1)
        self.assertIn({'name': 'existing'}, self.github.pr['labels'])

    def test_stale_snapshot_no_writes(self):
        self.args.apply = True
        for stage in [2, 3, 4]:
            self.github = FakeGitHub()
            self.github.stale_at = stage
            with self.assertRaisesRegex(RuntimeError, 'PR changed'):
                self.invoke()
            self.assertEqual(self.github.writes, [])

    def test_invalid_confidence_no_network(self):
        for value in [float('nan'), float('inf'), -1, 2]:
            self.args.threshold = value
            with patch('jev_labeler.__main__.GitHub') as client:
                with self.assertRaisesRegex(ValueError, 'Threshold'):
                    run(self.args)
                client.assert_not_called()

    def test_case_insensitive_existing_schema(self):
        self.args.apply = True
        self.github.pages = lambda _: [{'name': n} for n in ['Type: Bug', 'SIZE: S', 'Area: Config']]
        self.assertTrue(self.invoke()['verified'])

    def test_missing_schema_no_writes(self):
        self.args.apply = True
        self.github.pages = lambda _: []
        with self.assertRaisesRegex(ValueError, 'labels are missing'):
            self.invoke()
        self.assertEqual(self.github.writes, [])

    def test_invalid_model_response_no_writes(self):
        self.args.apply = True
        with patch('jev_labeler.__main__.GitHub', return_value=self.github), patch('jev_labeler.evidence.request_json', return_value={'answers': {}}):
            with self.assertRaises(ValueError):
                run(self.args)
        self.assertEqual(self.github.writes, [])

    def test_review_gated_invalid_model_response_is_error_not_deferral(self):
        self.args.require_greptile = True
        self.args.apply = True
        with patch('jev_labeler.__main__.completed_review', return_value={'id': 1}), \
                patch('jev_labeler.__main__.GitHub', return_value=self.github), \
                patch('jev_labeler.evidence.request_json', return_value={'answers': {}}):
            with self.assertRaises(ValueError):
                run(self.args)
        self.assertEqual(self.github.writes, [])

    def test_review_pending_never_calls_jev(self):
        self.args.require_greptile = True
        with patch('jev_labeler.__main__.completed_review', return_value=None), patch('jev_labeler.__main__.GitHub', return_value=self.github), patch('jev_labeler.evidence.request_json') as model:
            self.assertEqual(run(self.args)['status'], 'waiting_for_greptile')
            model.assert_not_called()
        self.assertEqual(self.github.writes, [])

    def test_review_findings_are_passed_to_jev(self):
        from test_review import check
        self.args.require_greptile = True
        review = check()
        review['findings'] = [{'body': 'Missing error test'}]
        with patch('jev_labeler.__main__.completed_review', return_value=review), patch('jev_labeler.__main__.GitHub', return_value=self.github), patch('jev_labeler.evidence.request_json', return_value=response()) as model:
            result = run(self.args)
            import json
            state = json.loads(model.call_args.args[3]['state'])
            self.assertEqual(state['completed_greptile_review']['findings'], review['findings'])
            self.assertEqual(result['review_check_id'], 1)

    def test_changed_review_prevents_label_write(self):
        from test_review import check
        self.args.require_greptile = True
        self.args.apply = True
        with patch('jev_labeler.__main__.completed_review', side_effect=[check(), check(), None]), patch('jev_labeler.__main__.GitHub', return_value=self.github), patch('jev_labeler.evidence.request_json', return_value=response()):
            with self.assertRaisesRegex(RuntimeError, 'review changed'):
                run(self.args)
        self.assertEqual(self.github.writes, [])

    def test_stale_repository_wide_metadata_uses_actual_current_base_diff(self):
        self.args.require_greptile = True
        self.github.pr['changed_files'] = 1200
        with patch('jev_labeler.__main__.completed_review', return_value={'id': 1}):
            result = self.invoke()
        self.assertEqual(result['add'], ['area: config', 'size: S', 'type: bug'])
        self.assertEqual(result['evidence']['base_sha'], 'live-base')

    def test_live_base_changes_abort_even_when_pr_metadata_is_unchanged(self):
        self.args.apply = True
        for stage in (2, 3, 4):
            self.github = FakeGitHub()
            self.github.base_stale_at = stage
            with self.assertRaisesRegex(RuntimeError, 'PR changed'):
                self.invoke()
            self.assertEqual(self.github.writes, [])

    def test_partial_compare_fails_closed(self):
        self.args.require_greptile = True
        def fail(*args):
            raise ValueError('GitHub comparison file cap reached')
        self.github.compare_files = fail
        with patch('jev_labeler.__main__.completed_review', return_value={'id': 1}), patch('jev_labeler.__main__.GitHub', return_value=self.github), patch('jev_labeler.evidence.request_json') as model:
            self.assertEqual(run(self.args)['status'], 'blocked_evidence')
            model.assert_not_called()
        self.assertEqual(self.github.writes, [])

    def test_no_remaining_diff_does_not_invent_labels(self):
        self.github.compare_files = lambda *args: ([], {'changed_files': 0})
        with patch('jev_labeler.__main__.GitHub', return_value=self.github), patch('jev_labeler.evidence.request_json') as model:
            self.assertEqual(run(self.args)['status'], 'skipped_no_changes')
            model.assert_not_called()

    def test_hierarchical_never_removes_or_conflicts_with_owned_exclusive_labels(self):
        from jev_labeler.classifier import parse_response
        self.args.apply = True
        self.github.pr['labels'] = [{'name': n} for n in ('Type: Feature', 'SIZE: L', 'area: tui')]
        self.github.owned_labels = lambda *args: {'type: feature', 'size: l', 'area: tui'}
        decisions = parse_response(response(), build_request({}))
        with patch.dict('os.environ', {'GITHUB_ACTIONS': 'true'}), \
                patch('jev_labeler.__main__.GitHub', return_value=self.github), \
                patch('jev_labeler.__main__.classify', return_value=(decisions, {'lossy': True})):
            result = run(self.args)
        self.assertEqual(result['add'], ['area: config'])
        self.assertEqual(result['remove'], [])
        self.assertTrue(result['verified'])
        self.assertEqual({x['name'] for x in self.github.pr['labels']},
                         {'Type: Feature', 'SIZE: L', 'area: tui', 'area: config'})
