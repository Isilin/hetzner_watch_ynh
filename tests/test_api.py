import socket
import urllib.error
import urllib.parse

import pytest

from conftest import FakeOpener, FakeResponse, api_error, http_error, load_json
from hetzner_watch.api import MAX_PAGES, AuthError, HetznerClient, RateLimited, TransientError

TOKEN = "tok-abcdef-123456"


def client(opener, **kwargs):
    return HetznerClient(TOKEN, opener=opener, **kwargs)


def query(request):
    return dict(urllib.parse.parse_qsl(urllib.parse.urlsplit(request.full_url).query))


def test_pagination_merges_pages_and_stops_on_null_next_page():
    opener = FakeOpener(load_json("server_types_page1.json"), load_json("server_types_page2.json"))
    types = client(opener).fetch_server_types()
    assert [t["name"] for t in types] == ["cx23", "cx33", "cx43", "cax21", "cax31"]
    assert [query(r) for r in opener.requests] == [{"page": "1", "per_page": "50"}, {"page": "2", "per_page": "50"}]
    assert not opener.responses


def test_request_headers_and_endpoint():
    opener = FakeOpener(load_json("server_types_mixed.json"))
    client(opener, timeout=7).fetch_server_types()
    request = opener.requests[0]
    assert request.full_url.startswith("https://api.hetzner.cloud/v1/server_types?")
    assert request.get_header("Authorization") == f"Bearer {TOKEN}"
    assert request.get_header("User-agent").startswith("hetzner-watch/")
    assert opener.timeouts == [7]


def test_repr_does_not_leak_token():
    assert TOKEN not in repr(client(FakeOpener()))


def test_pagination_loop_guard():
    looping = {"server_types": [], "meta": {"pagination": {"next_page": 1}}}
    with pytest.raises(TransientError, match="pagination"):
        client(FakeOpener(looping)).fetch_server_types()

    def endless():
        page = 1
        while True:
            page += 1
            yield {"server_types": [], "meta": {"pagination": {"next_page": page}}}

    pages = endless()
    opener = FakeOpener(*[next(pages) for _ in range(MAX_PAGES + 1)])
    with pytest.raises(TransientError, match="interrompue"):
        client(opener).fetch_server_types()


def test_missing_server_types_field_is_transient():
    with pytest.raises(TransientError):
        client(FakeOpener({"oops": True})).fetch_server_types()


def test_invalid_json_is_transient():
    with pytest.raises(TransientError, match="JSON"):
        client(FakeOpener(FakeResponse(b"<html>502</html>"))).fetch_server_types()


@pytest.mark.parametrize(
    "error",
    [
        api_error(401, "unauthorized", "unable to authenticate"),
        api_error(403, "forbidden", "insufficient permissions"),
        http_error(401),  # corps absent
    ],
)
def test_auth_errors_are_fatal(error):
    with pytest.raises(AuthError):
        client(FakeOpener(error)).fetch_server_types()


def test_auth_error_message_never_contains_token():
    with pytest.raises(AuthError) as info:
        client(FakeOpener(api_error(401, "unauthorized", "unable to authenticate"))).fetch_server_types()
    assert TOKEN not in str(info.value)
    assert "unauthorized" in str(info.value)


@pytest.mark.parametrize(
    "error",
    [
        api_error(403, "maintenance", "maintenance in progress"),
        api_error(500, "server_error"),
        api_error(503, "unavailable"),
        http_error(502),
        api_error(410, "deprecated_api_endpoint"),
        urllib.error.URLError(socket.gaierror(-2, "Name or service not known")),
        socket.timeout("timed out"),
        ConnectionResetError(104, "reset"),
    ],
)
def test_transient_errors(error):
    with pytest.raises(TransientError):
        client(FakeOpener(error)).fetch_server_types()


def test_rate_limited_waits_60s_when_reset_is_far():
    now = 1_000_000.0
    error = api_error(429, "rate_limit_exceeded", headers={"RateLimit-Reset": str(int(now + 3000))})
    with pytest.raises(RateLimited) as info:
        client(FakeOpener(error), clock=lambda: now).fetch_server_types()
    assert info.value.retry_after == 60


def test_rate_limited_waits_until_reset_when_close():
    now = 1_000_000.0
    error = api_error(429, "rate_limit_exceeded", headers={"RateLimit-Reset": str(int(now + 12))})
    with pytest.raises(RateLimited) as info:
        client(FakeOpener(error), clock=lambda: now).fetch_server_types()
    assert info.value.retry_after == 12


def test_rate_limited_without_header():
    with pytest.raises(RateLimited) as info:
        client(FakeOpener(http_error(429))).fetch_server_types()
    assert info.value.retry_after == 60


def test_low_quota_warning(caplog):
    body = load_json("server_types_mixed.json")
    opener = FakeOpener(FakeResponse(body, {"RateLimit-Limit": "3600", "RateLimit-Remaining": "12"}))
    client(opener).fetch_server_types()
    assert "Quota API presque épuisé" in caplog.text
