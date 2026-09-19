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

    def pull(self, number):
        self.reads += 1
        if self.reads == self.stale_at:
            self.pr['head']['sha'] = 'changed'
        return copy.deepcopy(self.pr)

    def files(self, number):
        return [{'filename': 'config.py', 'status': 'modified', 'additions': 1, 'deletions': 1,
                 'patch': '@@ -1 +1 @@\n-bad\n+good'}]

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
        with patch('jev_labeler.__main__.GitHub', return_value=self.github), patch('jev_labeler.__main__.request_json', return_value=response()):
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
        with patch('jev_labeler.__main__.GitHub', return_value=self.github), patch('jev_labeler.__main__.request_json', return_value={'answers': {}}):
            with self.assertRaises(ValueError):
                run(self.args)
        self.assertEqual(self.github.writes, [])

    def test_review_pending_never_calls_jev(self):
        self.args.require_greptile = True
        with patch('jev_labeler.__main__.completed_review', return_value=None), patch('jev_labeler.__main__.GitHub', return_value=self.github), patch('jev_labeler.__main__.request_json') as model:
            self.assertEqual(run(self.args)['status'], 'waiting_for_greptile')
            model.assert_not_called()
        self.assertEqual(self.github.writes, [])

    def test_review_findings_are_passed_to_jev(self):
        from test_review import check
        self.args.require_greptile = True
        review = check()
        review['findings'] = [{'body': 'Missing error test'}]
        with patch('jev_labeler.__main__.completed_review', return_value=review), patch('jev_labeler.__main__.GitHub', return_value=self.github), patch('jev_labeler.__main__.request_json', return_value=response()) as model:
            result = run(self.args)
            import json
            state = json.loads(model.call_args.args[3]['state'])
            self.assertEqual(state['completed_greptile_review']['findings'], review['findings'])
            self.assertEqual(result['review_check_id'], 1)

    def test_changed_review_prevents_label_write(self):
        from test_review import check
        self.args.require_greptile = True
        self.args.apply = True
        with patch('jev_labeler.__main__.completed_review', side_effect=[check(), check(), None]), patch('jev_labeler.__main__.GitHub', return_value=self.github), patch('jev_labeler.__main__.request_json', return_value=response()):
            with self.assertRaisesRegex(RuntimeError, 'review changed'):
                run(self.args)
        self.assertEqual(self.github.writes, [])

    def test_repository_wide_diff_is_reported_not_labeled(self):
        self.args.require_greptile = True
        self.github.pr['changed_files'] = 1200
        self.github.files = lambda _: self.fail('Must not download an impossible evidence snapshot')
        with patch('jev_labeler.__main__.completed_review', return_value={'id': 1}), patch('jev_labeler.__main__.GitHub', return_value=self.github), patch('jev_labeler.__main__.request_json') as model:
            self.assertEqual(run(self.args)['status'], 'blocked_evidence')
            model.assert_not_called()
        self.assertEqual(self.github.writes, [])
