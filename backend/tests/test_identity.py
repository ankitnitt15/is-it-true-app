from unittest.mock import MagicMock

from fastapi import Request
from starlette.datastructures import Headers

from limits import identity


def _fake_request(cookie_header: str | None) -> Request:
    headers = [(b"cookie", cookie_header.encode())] if cookie_header else []
    scope = {"type": "http", "headers": headers}
    return Request(scope)


def test_resolve_id_reuses_existing_cookie():
    request = _fake_request(f"{identity.COOKIE_NAME}=existing-id-123")

    assert identity.resolve_id(request) == "existing-id-123"


def test_resolve_id_generates_fresh_id_when_no_cookie():
    request = _fake_request(None)

    anon_id = identity.resolve_id(request)

    assert anon_id  # non-empty
    # a second call with the same (cookie-less) request generates a
    # *different* id -- resolve_id doesn't cache, callers are expected to
    # set the cookie themselves so the next real request has one
    assert identity.resolve_id(request) != anon_id


def test_set_cookie_sets_expected_attributes():
    response = MagicMock()

    identity.set_cookie(response, "some-id")

    response.set_cookie.assert_called_once()
    _, kwargs = response.set_cookie.call_args
    assert kwargs["max_age"] == identity.COOKIE_MAX_AGE
    assert kwargs["httponly"] is True
