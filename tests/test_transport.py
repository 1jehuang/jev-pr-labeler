import io
from email.utils import formatdate
from http.client import BadStatusLine, HTTPResponse, IncompleteRead
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import threading
import unittest
from unittest.mock import patch, MagicMock
from urllib.error import HTTPError, URLError
from jev_labeler import transport
from jev_labeler.transport import APIError, NoRedirect, request_json


def ok_response(payload=b'{"ok": true}'):
    response = MagicMock()
    response.__enter__.return_value.read.return_value = payload
    return response


class LoopbackHandler(BaseHTTPRequestHandler):
    """Answers like GitHub for the retry paths, and records every request it saw."""

    seen = []

    def _send(self, status, body=b'', retry_after=None, remaining=None):
        self.send_response(status)
        if retry_after is not None:
            self.send_header('Retry-After', retry_after)
        if remaining is not None:
            self.send_header('X-RateLimit-Remaining', remaining)
        self.send_header('Content-Length', str(len(body)))
        self.end_headers()
        if body:
            self.wfile.write(body)

    def do_GET(self):
        self.seen.append(('GET', self.path))
        hits = len([item for item in self.seen if item == ('GET', self.path)])
        if self.path == '/drop' and hits == 1:
            # Hang up with no response at all, like a reset mid-request.
            self.close_connection = True
        elif self.path == '/throttled' and hits == 1:
            self._send(403, b'PRIVATE BODY', remaining='0')
        elif self.path == '/flaky' and hits == 1:
            self._send(503, b'PRIVATE BODY', retry_after='1')
        elif self.path == '/always':
            self._send(429, b'PRIVATE BODY')
        elif self.path == '/long-wait':
            self._send(429, b'PRIVATE BODY', retry_after='60')
        elif self.path == '/date-wait':
            self._send(429, b'PRIVATE BODY', retry_after='Wed, 21 Oct 2099 07:28:00 GMT')
        elif self.path == '/forbidden':
            self._send(403, b'PRIVATE BODY')
        else:
            self._send(200, b'{"ok": true}')

    def do_POST(self):
        self.seen.append(('POST', self.path))
        self.rfile.read(int(self.headers.get('Content-Length') or 0))
        if self.path == '/write-drop':
            self.close_connection = True
        else:
            self._send(503, b'PRIVATE BODY')

    def log_message(self, *args):
        pass


class TransportTests(unittest.TestCase):
    @patch('jev_labeler.transport.build_opener')
    def test_protocol_errors_are_sanitized(self, opener):
        for failure in (BadStatusLine('PRIVATE RESPONSE'), IncompleteRead(b'PRIVATE RESPONSE')):
            with self.subTest(error=type(failure).__name__):
                opener.return_value.open.side_effect = failure
                with self.assertRaisesRegex(RuntimeError, 'API connection failed') as error:
                    request_json('https://api.github.com/x', 'secret')
                self.assertNotIn('PRIVATE', str(error.exception))

    @patch('jev_labeler.transport.time.sleep')
    @patch('jev_labeler.transport.build_opener')
    def test_truncated_chunked_response_is_sanitized(self, opener, sleep):
        responses = []

        def truncated(*args, **kwargs):
            socket = MagicMock()
            socket.makefile.return_value = io.BytesIO(
                b'HTTP/1.1 200 OK\r\nTransfer-Encoding: chunked\r\n\r\n20\r\nPRIVATE')
            response = HTTPResponse(socket)
            response.begin()
            responses.append(response)
            return response

        opener.return_value.open.side_effect = truncated
        with self.assertRaisesRegex(RuntimeError, 'API connection failed') as error:
            request_json('https://api.github.com/x', 'secret')
        self.assertNotIn('PRIVATE', str(error.exception))
        # A truncated body is a transient read fault, so it is retried and then reported.
        self.assertEqual(len(responses), transport.RETRY_ATTEMPTS)
        self.assertEqual(sleep.call_count, transport.RETRY_ATTEMPTS - 1)
        self.assertTrue(all(response.isclosed() for response in responses))

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

    @patch('jev_labeler.transport.time.sleep')
    @patch('jev_labeler.transport.build_opener')
    def test_transient_get_is_retried_after_retry_after(self, opener, sleep):
        opener.return_value.open.side_effect = [
            HTTPError('https://secret', 503, 'TOKEN', {'Retry-After': '2'}, io.BytesIO(b'PRIVATE')),
            ok_response(),
        ]
        self.assertEqual(request_json('https://api.github.com/x', 'secret'), {'ok': True})
        self.assertEqual(opener.return_value.open.call_count, 2)
        sleep.assert_called_once_with(2.0)

    @patch('jev_labeler.transport.time.sleep')
    @patch('jev_labeler.transport.build_opener')
    def test_exhausted_retries_fail_without_leaking_bodies(self, opener, sleep):
        opener.return_value.open.side_effect = [
            HTTPError('https://secret', status, 'TOKEN', {}, io.BytesIO(b'PRIVATE PR'))
            for status in (429, 502, 504)]
        with self.assertRaises(APIError) as error:
            request_json('https://api.github.com/x', 'secret')
        self.assertEqual(error.exception.status, 504)
        self.assertNotIn('PRIVATE', str(error.exception))
        self.assertEqual(opener.return_value.open.call_count, transport.RETRY_ATTEMPTS)
        self.assertEqual(sleep.call_count, transport.RETRY_ATTEMPTS - 1)

    @patch('jev_labeler.transport.time.sleep')
    @patch('jev_labeler.transport.build_opener')
    def test_writes_and_client_errors_are_never_retried(self, opener, sleep):
        for method, status in (('POST', 503), ('DELETE', 429), ('GET', 404), ('GET', 403)):
            with self.subTest(method=method, status=status):
                opener.return_value.open.reset_mock()
                opener.return_value.open.side_effect = HTTPError(
                    'https://secret', status, 'TOKEN', {}, io.BytesIO(b'PRIVATE'))
                with self.assertRaises(APIError) as error:
                    request_json('https://api.github.com/x', 'secret', method, {'a': 1})
                self.assertEqual(error.exception.status, status)
                self.assertEqual(opener.return_value.open.call_count, 1)
        sleep.assert_not_called()

    @patch('jev_labeler.transport.time.sleep')
    @patch('jev_labeler.transport.build_opener')
    def test_connection_failures_are_retried_for_reads(self, opener, sleep):
        opener.return_value.open.side_effect = [URLError('PRIVATE reset'), ok_response()]
        self.assertEqual(request_json('https://api.github.com/x', 'secret'), {'ok': True})
        self.assertEqual(opener.return_value.open.call_count, 2)
        sleep.assert_called_once_with(0.5)

    @patch('jev_labeler.transport.time.sleep')
    @patch('jev_labeler.transport.build_opener')
    def test_exhausted_connection_failures_stay_sanitized(self, opener, sleep):
        opener.return_value.open.side_effect = [
            URLError('PRIVATE'), TimeoutError('PRIVATE'), BadStatusLine('PRIVATE')]
        with self.assertRaisesRegex(RuntimeError, 'API connection failed') as error:
            request_json('https://api.github.com/x', 'secret')
        self.assertNotIn('PRIVATE', str(error.exception))
        self.assertEqual(opener.return_value.open.call_count, transport.RETRY_ATTEMPTS)
        self.assertEqual(sleep.call_count, transport.RETRY_ATTEMPTS - 1)

    @patch('jev_labeler.transport.time.sleep')
    @patch('jev_labeler.transport.build_opener')
    def test_write_connection_failure_is_not_retried(self, opener, sleep):
        opener.return_value.open.side_effect = URLError('PRIVATE')
        with self.assertRaisesRegex(RuntimeError, 'API connection failed') as error:
            request_json('https://api.github.com/x', 'secret', 'POST', {'a': 1})
        self.assertNotIn('PRIVATE', str(error.exception))
        self.assertEqual(opener.return_value.open.call_count, 1)
        sleep.assert_not_called()

    @patch('jev_labeler.transport.time.sleep')
    @patch('jev_labeler.transport.build_opener')
    def test_rate_limited_403_is_retried_for_reads(self, opener, sleep):
        opener.return_value.open.side_effect = [
            HTTPError('https://secret', 403, 'TOKEN',
                      {'X-RateLimit-Remaining': '0'}, io.BytesIO(b'PRIVATE')),
            ok_response(),
        ]
        self.assertEqual(request_json('https://api.github.com/x', 'secret'), {'ok': True})
        self.assertEqual(opener.return_value.open.call_count, 2)
        # No Retry-After on a throttle, so the bounded exponential backoff applies.
        sleep.assert_called_once_with(0.5)

    @patch('jev_labeler.transport.time.sleep')
    @patch('jev_labeler.transport.build_opener')
    def test_exhausted_rate_limit_mentions_throttling(self, opener, sleep):
        opener.return_value.open.side_effect = [
            HTTPError('https://secret', 403, 'TOKEN', {'Retry-After': '3'}, io.BytesIO(b'PRIVATE'))
            for _ in range(transport.RETRY_ATTEMPTS)]
        with self.assertRaises(APIError) as error:
            request_json('https://api.github.com/x', 'secret')
        self.assertEqual(error.exception.status, 403)
        self.assertIn('rate-limit', str(error.exception))
        self.assertNotIn('PRIVATE', str(error.exception))
        self.assertEqual(sleep.call_args_list, [((3.0,), {})] * (transport.RETRY_ATTEMPTS - 1))

    def test_retry_delay_is_bounded_and_ignores_unsafe_values(self):
        for raw, expected in ((None, 0.5), ('2', 2.0), ('5', 5.0), ('60', None),
                              ('0', 0.0), ('-3', 0.5), ('nan', 0.5), ('-inf', 0.5),
                              # An oversized value, including one that overflows to
                              # infinity, still asks for more than the wait budget.
                              ('inf', None), ('9' * 400, None)):
            with self.subTest(retry_after=raw):
                self.assertEqual(transport._retry_delay({'Retry-After': raw}, 0), expected)
        self.assertEqual(transport._retry_delay({'Retry-After': 'bogus'}, 2), 2.0)
        self.assertEqual(transport._retry_delay(None, 2), 2.0)

    @patch('jev_labeler.transport.time.sleep')
    @patch('jev_labeler.transport.build_opener')
    def test_bare_server_error_does_not_claim_a_rate_limit(self, opener, sleep):
        opener.return_value.open.side_effect = [
            HTTPError('https://secret', 503, 'TOKEN', {}, io.BytesIO(b'PRIVATE'))
            for _ in range(transport.RETRY_ATTEMPTS)]
        with self.assertRaises(APIError) as error:
            request_json('https://api.github.com/x', 'secret')
        self.assertEqual(error.exception.status, 503)
        # No rate-limit headers were sent, so the hint would misdescribe the failure.
        self.assertEqual(error.exception.hint, '')
        self.assertNotIn('rate-limit', str(error.exception))

    @patch('jev_labeler.transport.time.time', return_value=1445412480)
    def test_http_date_retry_after(self, clock):
        for offset, expected in ((-60, 0), (0, 0), (2, 2), (5, 5), (60, None)):
            with self.subTest(offset=offset):
                header = formatdate(clock.return_value + offset, usegmt=True)
                self.assertEqual(transport._retry_delay({'Retry-After': header}, 0), expected)
        self.assertEqual(transport._retry_delay({'Retry-After': 'Wed Oct 21 07:28:02 2015'}, 0), 2)
        for header in ('not a date', 'Wed, 99 Oct 2015 07:28:00 GMT'):
            with self.subTest(header=header):
                self.assertEqual(transport._retry_delay({'Retry-After': header}, 0), 0.5)


class LoopbackRetryTests(unittest.TestCase):
    """Drive the real urllib stack, which a mocked opener cannot exercise.

    Real HTTPError objects, real header casing on Retry-After, and real connection
    handling are all part of the behavior the action depends on. Sleep is patched so
    the retry policy is exercised without waiting.
    """

    @classmethod
    def setUpClass(cls):
        try:
            cls.server = ThreadingHTTPServer(('127.0.0.1', 0), LoopbackHandler)
        except OSError as exc:  # pragma: no cover - depends on the sandbox
            raise unittest.SkipTest(f'loopback sockets unavailable: {exc}')
        cls.thread = threading.Thread(target=cls.server.serve_forever, daemon=True)
        cls.thread.start()
        cls.root = 'http://127.0.0.1:%d' % cls.server.server_address[1]

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.server.server_close()
        cls.thread.join(5)

    def setUp(self):
        LoopbackHandler.seen = []

    @patch('jev_labeler.transport.time.sleep')
    def test_real_transient_read_recovers(self, sleep):
        self.assertEqual(request_json(self.root + '/flaky', 'secret'), {'ok': True})
        self.assertEqual(LoopbackHandler.seen, [('GET', '/flaky'), ('GET', '/flaky')])
        sleep.assert_called_once_with(1.0)

    @patch('jev_labeler.transport.time.sleep')
    def test_real_exhausted_reads_stay_sanitized(self, sleep):
        with self.assertRaises(APIError) as error:
            request_json(self.root + '/always', 'secret')
        self.assertEqual(error.exception.status, 429)
        # A real throttle still carries the rate-limit hint, unlike a bare 5xx.
        self.assertIn('rate-limit', str(error.exception))
        self.assertNotIn('PRIVATE', str(error.exception))
        self.assertEqual(len(LoopbackHandler.seen), transport.RETRY_ATTEMPTS)
        self.assertEqual(sleep.call_count, transport.RETRY_ATTEMPTS - 1)

    @patch('jev_labeler.transport.time.sleep')
    def test_real_long_retry_after_stops_without_retrying_early(self, sleep):
        with self.assertRaises(APIError) as error:
            request_json(self.root + '/long-wait', 'secret')
        self.assertEqual(error.exception.status, 429)
        self.assertEqual(LoopbackHandler.seen, [('GET', '/long-wait')])
        sleep.assert_not_called()

    @patch('jev_labeler.transport.time.sleep')
    def test_real_future_retry_date_stops_without_retrying_early(self, sleep):
        with self.assertRaises(APIError) as error:
            request_json(self.root + '/date-wait', 'secret')
        self.assertEqual(error.exception.status, 429)
        self.assertEqual(LoopbackHandler.seen, [('GET', '/date-wait')])
        sleep.assert_not_called()

    @patch('jev_labeler.transport.time.sleep')
    def test_real_client_errors_and_writes_are_not_retried(self, sleep):
        with self.assertRaises(APIError) as error:
            request_json(self.root + '/forbidden', 'secret')
        self.assertEqual(error.exception.status, 403)
        with self.assertRaises(APIError) as error:
            request_json(self.root + '/write', 'secret', 'POST', {'a': 1})
        self.assertEqual(error.exception.status, 503)
        self.assertEqual(LoopbackHandler.seen, [('GET', '/forbidden'), ('POST', '/write')])
        sleep.assert_not_called()

    @patch('jev_labeler.transport.time.sleep')
    def test_real_dropped_connection_is_retried(self, sleep):
        self.assertEqual(request_json(self.root + '/drop', 'secret'), {'ok': True})
        self.assertEqual(LoopbackHandler.seen, [('GET', '/drop'), ('GET', '/drop')])
        sleep.assert_called_once_with(0.5)

    @patch('jev_labeler.transport.time.sleep')
    def test_real_rate_limited_read_is_retried(self, sleep):
        self.assertEqual(request_json(self.root + '/throttled', 'secret'), {'ok': True})
        self.assertEqual(LoopbackHandler.seen, [('GET', '/throttled'), ('GET', '/throttled')])
        sleep.assert_called_once_with(0.5)

    @patch('jev_labeler.transport.time.sleep')
    def test_real_write_connection_drop_is_not_retried(self, sleep):
        with self.assertRaisesRegex(RuntimeError, 'API connection failed') as error:
            request_json(self.root + '/write-drop', 'secret', 'POST', {'a': 1})
        self.assertNotIn('PRIVATE', str(error.exception))
        self.assertEqual(LoopbackHandler.seen, [('POST', '/write-drop')])
        sleep.assert_not_called()
