"""Bounded, non-redirecting JSON transport. Never includes response bodies in errors.

Transient failures of idempotent reads are retried a bounded number of times: HTTP 429,
gateway/server errors, connections that drop or time out, and a 403 that GitHub uses for an
exhausted rate limit (recognised only by its rate-limit headers, never a plain 403). Writes
and paid inference requests are never retried: a duplicate label write or a duplicate model
call is worse than a visible failure.
"""
import json
import math
import time
from datetime import timezone
from email.utils import parsedate_to_datetime
from http.client import HTTPException
from urllib.error import HTTPError, URLError
from urllib.request import HTTPRedirectHandler, Request, build_opener


RETRY_STATUSES = frozenset({429, 500, 502, 503, 504})
RETRY_ATTEMPTS = 3
MAX_RETRY_DELAY = 5.0
RATE_LIMIT_HINT = ("GitHub rate-limit headers indicate this read was throttled; wait for "
                   "the limit window to reset, then rerun.")


class APIError(RuntimeError):
    def __init__(self, status, hint=""):
        self.status = status
        self.hint = hint
        message = f"API request failed: HTTP {status}. No labels should be assumed updated."
        super().__init__(f"{message} {hint}" if hint else message)


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def _backoff(attempt):
    """Our own bounded exponential wait, used when the server gives no usable delay."""
    return min(0.5 * 2 ** attempt, MAX_RETRY_DELAY)


def _retry_delay(headers, attempt):
    """Return a bounded wait, or None when the server requires a longer delay."""
    value = (headers or {}).get("Retry-After")
    try:
        seconds = float(value)
    except (TypeError, ValueError):
        try:
            deadline = parsedate_to_datetime(value)
            if deadline.tzinfo is None:
                deadline = deadline.replace(tzinfo=timezone.utc)
            seconds = max(0.0, deadline.timestamp() - time.time())
        except (TypeError, ValueError, OverflowError, OSError):
            return _backoff(attempt)
    if math.isnan(seconds) or seconds < 0:
        # A bogus or negative value is no instruction at all, so use our own backoff.
        return _backoff(attempt)
    # A positive delay is the server's floor: infinity here means an oversized value
    # that overflowed, and both must stop rather than retry earlier than allowed.
    return seconds if seconds <= MAX_RETRY_DELAY else None


def _rate_limited(headers):
    """GitHub also reports an exhausted limit as 403; only a limit header justifies waiting."""
    try:
        values = {str(key).lower(): value for key, value in (headers or {}).items()}
    except AttributeError:
        return False
    return bool(values.get("retry-after")) or str(values.get("x-ratelimit-remaining")) == "0"


def request_json(url, token, method="GET", body=None, limit=8 * 1024 * 1024):
    headers = {"Authorization": f"Bearer {token}", "Accept": "application/json",
               "User-Agent": "jev-pr-labeler", "Content-Type": "application/json"}
    data = None if body is None else json.dumps(body, allow_nan=False).encode()
    request = Request(url, data=data, headers=headers, method=method)
    attempts = RETRY_ATTEMPTS if method == "GET" else 1
    for attempt in range(attempts):
        last = attempt + 1 >= attempts
        try:
            with build_opener(NoRedirect).open(request, timeout=45) as response:
                raw = response.read(limit + 1)
            break
        except HTTPError as exc:
            status, response_headers = exc.code, exc.headers
            exc.close()
            # Only 429 and a header-backed 403 are actually rate limits; a bare 5xx is
            # a server fault, so the rate-limit hint would misdescribe it.
            rate_limited = status == 429 or (status == 403 and _rate_limited(response_headers))
            throttled = rate_limited or status in RETRY_STATUSES
            if throttled and not last:
                delay = _retry_delay(response_headers, attempt)
                if delay is not None:
                    time.sleep(delay)
                    continue
            raise APIError(status, RATE_LIMIT_HINT if rate_limited else "") from None
        except (URLError, TimeoutError, OSError, HTTPException):
            # A dropped connection or timeout before the body completes is safe to
            # repeat for an idempotent read, and is the most common transient fault.
            if last:
                raise RuntimeError("API connection failed or timed out.") from None
            time.sleep(_retry_delay(None, attempt))
    if len(raw) > limit:
        raise RuntimeError("API response exceeded the safety limit.")
    try:
        return json.loads(raw) if raw else None
    except (ValueError, UnicodeError):
        raise RuntimeError("API returned invalid JSON.") from None
