import unittest
from unittest.mock import Mock
from jev_labeler.github import GitHub, fingerprint


class GitHubTests(unittest.TestCase):
    def setUp(self):
        self.client = GitHub('owner/repo', 'secret')
        self.client.request = Mock()

    def test_repository_injection_rejected(self):
        for repo in ['https://attacker.test', 'owner/repo/../../x', 'owner/repo?token=x', 'owner/repo\n']:
            with self.assertRaises(ValueError):
                GitHub(repo, 'secret')

    def test_invalid_pr(self):
        for number in [-1, 0, True, '1/labels']:
            with self.assertRaises(ValueError):
                self.client.pull(number)

    def test_pagination(self):
        self.client.request.side_effect = [[{}] * 100, [{'name': 'last'}]]
        result = self.client.pages('/labels')
        self.assertEqual(len(result), 101)
        self.client.request.assert_called_with('/labels?per_page=100&page=2')

    def test_pagination_cap_fails_closed(self):
        self.client.request.return_value = [{}] * 100
        with self.assertRaisesRegex(RuntimeError, 'partial snapshot'):
            self.client.pages('/labels', max_pages=2)

    def test_malformed_page(self):
        self.client.request.return_value = {'error': 'oops'}
        with self.assertRaises(RuntimeError):
            self.client.pages('/labels')

    def test_ownership_tracks_last_label_actor(self):
        def event(kind, actor):
            return {'event': kind, 'actor': {'login': actor}, 'label': {'name': 'size: S'}}
        self.client.request.return_value = [event('labeled', 'github-actions[bot]'), event('unlabeled', 'human'), event('labeled', 'human')]
        self.assertEqual(self.client.owned_labels(1, 'github-actions[bot]'), set())
        self.client.request.return_value.append(event('labeled', 'github-actions[bot]'))
        self.assertEqual(self.client.owned_labels(1, 'github-actions[bot]'), {'size: s'})

    def test_removal_path_is_encoded(self):
        self.client.apply(1, [], ['area: tui'])
        self.client.request.assert_called_once_with('/issues/1/labels/area%3A%20tui', 'DELETE')

    def test_only_create_missing_labels(self):
        self.client.request.side_effect = [[{'name': 'SIZE: S'}], None]
        self.client.ensure_labels({'size: S': {'color': '123456', 'description': 'leave alone'},
                                   'size: M': {'color': 'ffffff', 'description': 'new'}})
        self.assertEqual(self.client.request.call_count, 2)
        self.client.request.assert_called_with('/labels', 'POST', {'name': 'size: M', 'color': 'ffffff', 'description': 'new'})

    def test_label_provision_race_refetches_existing(self):
        from jev_labeler.transport import APIError
        self.client.request.side_effect = [[], APIError(422), [{'name': 'size: S'}]]
        self.client.ensure_labels({'size: S': {'color': 'ffffff', 'description': 'new'}})
        self.assertEqual(self.client.request.call_count, 3)

    def test_unrelated_provision_failure_not_hidden(self):
        from jev_labeler.transport import APIError
        self.client.request.side_effect = [[], APIError(422), []]
        with self.assertRaises(APIError):
            self.client.ensure_labels({'size: S': {'color': 'ffffff', 'description': 'new'}})

    def test_human_reapply_prevents_removal(self):
        self.client.owned_labels = Mock(return_value=set())
        with self.assertRaisesRegex(RuntimeError, 'ownership changed'):
            self.client.apply(1, [], ['size: S'], actor='github-actions[bot]')
        self.client.request.assert_not_called()
