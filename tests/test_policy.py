import copy
import unittest
from jev_labeler.policy import incidental, plan_labels, snapshot


def decision(labels=(), decisive=True):
    return {'labels': list(labels), 'decisive': decisive}


class PolicyTests(unittest.TestCase):
    def test_type_and_size_are_exclusive(self):
        current = {'size: S', 'type: bug', 'unrelated'}
        add, remove = plan_labels({'size': decision(['size: M']), 'type': decision(['type: feature'])}, current, current)
        self.assertEqual(add, ['size: M', 'type: feature'])
        self.assertEqual(remove, ['size: S', 'type: bug'])

    def test_human_choices_win(self):
        self.assertEqual(plan_labels({'size': decision(['size: M'])}, {'size: S'}, set()), ([], []))

    def test_uncertain_preserves_existing_labels(self):
        self.assertEqual(plan_labels({'size': decision([], False)}, {'size: S'}, {'size: S'}), ([], []))

    def test_remove_only_owned_area(self):
        self.assertEqual(plan_labels({'area: tui': decision()}, {'area: tui'}, set()), ([], []))
        self.assertEqual(plan_labels({'area: tui': decision()}, {'area: tui'}, {'area: tui'}), ([], ['area: tui']))

    def test_security_and_breaking_never_removed(self):
        for label in ['security', 'breaking-change']:
            self.assertEqual(plan_labels({label: decision()}, {label}, {label}), ([], []))

    def test_idempotent(self):
        labels = {'area: tui', 'size: S'}
        self.assertEqual(plan_labels({'size': decision(['size: S']), 'area: tui': decision(['area: tui'])}, labels, labels), ([], []))

    def test_incidental_rules(self):
        for path in ['Cargo.lock', 'web/package-lock.json', 'vendor/thing.py', 'foo/generated/bar.rs', 'a.generated.ts']:
            self.assertTrue(incidental(path), path)
        for path in ['src/vendor_api.rs', 'src/generated_parser.rs', 'lock.py']:
            self.assertFalse(incidental(path), path)


class SnapshotTests(unittest.TestCase):
    def setUp(self):
        self.pr = {'state': 'open', 'changed_files': 1, 'title': 'Change', 'body': 'Description'}
        self.file = {'filename': 'src/a.py', 'status': 'modified', 'additions': 1, 'deletions': 1,
                     'patch': '@@ -1 +1 @@\n-old\n+new'}

    def test_semantic_state_has_no_line_counts(self):
        state = snapshot(self.pr, [self.file])
        self.assertNotIn('additions', state['files'][0])
        self.assertEqual(state['files'][0]['patch'], self.file['patch'])

    def test_lockfile_content_omitted(self):
        self.file['filename'] = 'Cargo.lock'
        state = snapshot(self.pr, [self.file])
        self.assertNotIn('patch', state['files'][0])
        self.assertIn('note', state['files'][0])

    def test_rename_to_vendor_does_not_hide_source(self):
        self.file.update(filename='vendor/a.py', previous_filename='src/a.py')
        self.assertIn('patch', snapshot(self.pr, [self.file])['files'][0])

    def test_patch_missing(self):
        self.file.pop('patch')
        with self.assertRaisesRegex(ValueError, 'unavailable'):
            snapshot(self.pr, [self.file])

    def test_patch_truncated(self):
        self.file['additions'] = 100
        with self.assertRaisesRegex(ValueError, 'truncated'):
            snapshot(self.pr, [self.file])

    def test_complete_list_required(self):
        self.pr['changed_files'] = 2
        with self.assertRaisesRegex(ValueError, 'Incomplete'):
            snapshot(self.pr, [self.file])

    def test_state_budget(self):
        self.pr['body'] = 'a' * 40_000
        with self.assertRaisesRegex(ValueError, 'context'):
            snapshot(self.pr, [self.file])

    def test_closed_pr_not_classified(self):
        self.pr['state'] = 'closed'
        with self.assertRaisesRegex(ValueError, 'not open'):
            snapshot(self.pr, [self.file])
