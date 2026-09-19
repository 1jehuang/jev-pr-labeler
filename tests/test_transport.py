import io
import unittest
from unittest.mock import patch, MagicMock
from urllib.error import HTTPError
from jev_labeler.transport import NoRedirect, request_json


class TransportTests(unittest.TestCase):
    def test_no_redirects(self):
        self.assertIsNone(NoRedirect().redirect_request(None, None, 302, '', {}, 'https://attacker.test'))

    @patch('jev_labeler.transport.build_opener')
    def test_http_errors_do_not_leak_response(self, opener):
        opener.return_value.open.side_effect = HTTPError('https://secret', 403, 'TOKEN', {}, io.BytesIO(b'PRIVATE PR'))
        with self.assertRaisesRegex(RuntimeError, 'HTTP 403') as error:
            request_json('https://api.github.com/x', 'secret')
        self.assertNotIn('TOKEN', str(error.exception))
        self.assertNotIn('PRIVATE', str(error.exception))

    @patch('jev_labeler.transport.build_opener')
    def test_bounded_response(self, opener):
        opener.return_value.open.return_value.__enter__.return_value.read.return_value = b'123456'
        with self.assertRaisesRegex(RuntimeError, 'safety limit'):
            request_json('https://api.github.com/x', 'secret', limit=5)

    @patch('jev_labeler.transport.build_opener')
    def test_invalid_json_sanitized(self, opener):
        opener.return_value.open.return_value.__enter__.return_value.read.return_value = b'PRIVATE'
        with self.assertRaisesRegex(RuntimeError, 'invalid JSON'):
            request_json('https://api.github.com/x', 'secret')
