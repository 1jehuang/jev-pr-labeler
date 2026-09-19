"""Bounded, non-redirecting JSON transport. Never includes response bodies in errors."""
import json
from urllib.error import HTTPError, URLError
from urllib.request import HTTPRedirectHandler, Request, build_opener


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def request_json(url, token, method="GET", body=None, limit=8 * 1024 * 1024):
    headers = {"Authorization": f"Bearer {token}", "Accept": "application/json",
               "User-Agent": "jev-pr-labeler", "Content-Type": "application/json"}
    data = None if body is None else json.dumps(body, allow_nan=False).encode()
    request = Request(url, data=data, headers=headers, method=method)
    try:
        with build_opener(NoRedirect).open(request, timeout=45) as response:
            raw = response.read(limit + 1)
    except HTTPError as exc:
        raise RuntimeError(f"API request failed: HTTP {exc.code}. No labels should be assumed updated.") from None
    except (URLError, TimeoutError, OSError):
        raise RuntimeError("API connection failed or timed out.") from None
    if len(raw) > limit:
        raise RuntimeError("API response exceeded the safety limit.")
    try:
        return json.loads(raw) if raw else None
    except (ValueError, UnicodeError):
        raise RuntimeError("API returned invalid JSON.") from None
