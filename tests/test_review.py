import copy
import unittest
from unittest.mock import Mock
from jev_labeler.review import completed_review, review_identity
from jev_labeler.after_review import targets

SHA = 'a' * 40


def check(**kwargs):
    result = {'id': 1, 'check_suite': {'id': 1}, 'head_sha': SHA, 'app': {'id': 867647}, 'name': 'Greptile Review',
              'status': 'completed', 'conclusion': 'success', 'started_at': '2026-09-19T00:00:00Z',
              'completed_at': '2026-09-19T00:02:00Z', 'output': {'summary': 'Reviewed'}}
    result.update(kwargs)
    return result


class ReviewTests(unittest.TestCase):
    def setUp(self):
        self.pr = {'number': 1, 'head': {'sha': SHA}}
        self.github = Mock()

    def test_completed_current_head(self):
        self.github.pages.return_value = [check()]
        self.assertEqual(completed_review(self.github, self.pr, False)['id'], 1)

    def test_forged_old_pending_or_cancelled_checks_do_not_gate(self):
        for candidate in [check(app={'id': 1}), check(head_sha='b' * 40), check(status='in_progress'),
                          check(conclusion='cancelled'), check(name='Another Review'), check(completed_at=None)]:
            self.github.pages.return_value = [candidate]
            self.assertIsNone(completed_review(self.github, self.pr, False))

    def test_latest_pending_rerun_supersedes_old_success(self):
        self.github.pages.return_value = [check(), check(id=2, status='in_progress')]
        self.assertIsNone(completed_review(self.github, self.pr, False))

    def test_failure_is_evidence_not_merge_permission(self):
        self.github.pages.return_value = [check(conclusion='failure')]
        self.assertEqual(completed_review(self.github, self.pr, False)['conclusion'], 'failure')

    def test_only_verified_current_review_findings(self):
        valid = {'performed_via_github_app': {'id': 867647}, 'updated_at': '2026-09-19T00:01:00Z', 'body': 'finding'}
        stale = {**valid, 'updated_at': '2026-09-18T23:59:00Z'}
        spoofed = {**valid, 'performed_via_github_app': {'id': 4}}
        inline = {**valid, 'commit_id': SHA, 'path': 'a.py'}
        old_inline = {**inline, 'commit_id': 'b' * 40}
        self.github.pages.side_effect = [[check()], [check()], [valid, stale, spoofed], [inline, old_inline]]
        evidence = completed_review(self.github, self.pr)
        self.assertEqual(len(evidence['findings']), 2)
        self.assertEqual(evidence['findings'][1]['path'], 'a.py')

    def test_oversized_review_abstains(self):
        self.github.pages.side_effect = [[check(output={'summary': 'x'*20001})], [check()], [], []]
        with self.assertRaisesRegex(ValueError, 'review exceeds'):
            completed_review(self.github, self.pr)

    def test_bad_sha_rejected_before_network(self):
        self.pr['head']['sha'] = '../secrets'
        with self.assertRaises(ValueError):
            completed_review(self.github, self.pr)
        self.github.pages.assert_not_called()

    def test_resolve_empty_event_association_from_current_heads(self):
        self.github.pages.return_value = [{'number': 1, 'head': {'sha': SHA}}, {'number': 2, 'head': {'sha': 'b'*40}}]
        self.assertEqual(targets(self.github, check_sha=SHA), [1])
        self.assertEqual(targets(self.github, check_sha='c'*40), [])
        self.assertEqual(targets(self.github, all_open=True), [1, 2])
        self.assertEqual(targets(self.github, pr=7), [7])

    def test_invalid_target(self):
        for kwargs in [{'pr': -1}, {'check_sha': '../secrets'}, {}]:
            with self.assertRaises(ValueError):
                targets(self.github, **kwargs)

    def test_rerequested_suite_blocks_old_completed_run(self):
        self.github.pages.side_effect = [[check()], [check(status='queued')]]
        self.assertIsNone(completed_review(self.github, self.pr, False))

    def test_reused_older_run_id_can_be_latest_execution(self):
        new_execution = check(id=1, started_at='2026-09-19T01:00:00Z', completed_at='2026-09-19T01:02:00Z')
        old_execution = check(id=2)
        self.github.pages.side_effect = [[new_execution, old_execution], [check()]]
        self.assertEqual(completed_review(self.github, self.pr, False)['id'], 1)

    def test_unknown_suite_fails_closed(self):
        self.github.pages.side_effect = [[check(check_suite={'id': 99})], [check()]]
        self.assertIsNone(completed_review(self.github, self.pr, False))
