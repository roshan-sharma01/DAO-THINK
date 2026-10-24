"""Unit tests for the DAOThink research functions.

No unit test in this file performs a real network request. The autouse
``_no_real_network`` fixture blocks real HTTP calls and DNS lookups, so any
test that forgets to mock the network fails loudly instead of silently
depending on an external website.
"""

import socket

import pytest
import requests

from research_agent import research_tools
from research_agent.research_tools import (
    MAX_BYTES,
    TIMEOUT_SECONDS,
    fetch_source,
    research_sources,
    validate_public_url,
)

PUBLIC_IP = "93.184.216.34"
VALID_URL = "https://example.org/proposal"


def _addrinfo(ip: str):
    return [(socket.AF_INET, socket.SOCK_STREAM, socket.IPPROTO_TCP, "", (ip, 443))]


class FakeResponse:
    """Minimal stand-in for requests.Response supporting context-manager use."""

    def __init__(
        self,
        status_code: int = 200,
        headers: dict | None = None,
        body: bytes = b"",
        encoding: str | None = "utf-8",
        chunks: list | None = None,
    ):
        self.status_code = status_code
        self.headers = (
            headers
            if headers is not None
            else {"Content-Type": "text/html; charset=utf-8"}
        )
        self.encoding = encoding
        self._body = body
        self._chunks = chunks

    def __enter__(self):
        return self

    def __exit__(self, *exc_info):
        return False

    def raise_for_status(self):
        if self.status_code >= 400:
            raise requests.HTTPError(
                f"{self.status_code} Client Error", response=self
            )

    def iter_content(self, chunk_size: int = 8192):
        if self._chunks is not None:
            yield from self._chunks
            return
        for start in range(0, len(self._body), chunk_size):
            yield self._body[start : start + chunk_size]


HTML_PAGE = (
    b"<html><head><title>  Protocol Integration Funding  </title></head>"
    b"<body><h1>Proposal</h1><p>Funds a bridge integration.</p></body></html>"
)


def _resolve_to(monkeypatch, ip: str) -> None:
    monkeypatch.setattr(
        research_tools.socket, "getaddrinfo", lambda host, port: _addrinfo(ip)
    )


def _install_get(monkeypatch, response=None, exc=None, recorder: list | None = None):
    def fake_get(url, **kwargs):
        if recorder is not None:
            recorder.append({"url": url, "kwargs": kwargs})
        if exc is not None:
            raise exc
        return response

    monkeypatch.setattr(research_tools.requests, "get", fake_get)
    return fake_get


def _install_get_by_url(monkeypatch, responses: dict, recorder: list | None = None):
    def fake_get(url, **kwargs):
        if recorder is not None:
            recorder.append({"url": url, "kwargs": kwargs})
        outcome = responses[url]
        if isinstance(outcome, BaseException):
            raise outcome
        return outcome

    monkeypatch.setattr(research_tools.requests, "get", fake_get)
    return fake_get


@pytest.fixture(autouse=True)
def _no_real_network(monkeypatch):
    """Fail fast if a test tries to touch the real network."""

    def blocked_get(*args, **kwargs):
        raise AssertionError("unit tests must not perform real network requests")

    def blocked_resolve(*args, **kwargs):
        raise AssertionError("unit tests must not resolve real hostnames")

    monkeypatch.setattr(research_tools.requests, "get", blocked_get)
    monkeypatch.setattr(research_tools.socket, "getaddrinfo", blocked_resolve)


# --------------------------------------------------------------------------
# validate_public_url
# --------------------------------------------------------------------------


def test_accepts_valid_public_https_url(monkeypatch):
    _resolve_to(monkeypatch, PUBLIC_IP)
    validate_public_url(VALID_URL)


@pytest.mark.parametrize(
    "url",
    [
        "not-a-url",
        "https://",
        "",
        "ftp://example.org/proposal",
        "//example.org/proposal",
    ],
)
def test_rejects_malformed_urls(url):
    with pytest.raises(ValueError):
        validate_public_url(url)


def test_rejects_http_url():
    with pytest.raises(ValueError, match="HTTPS"):
        validate_public_url("http://example.org/proposal")


def test_rejects_localhost():
    with pytest.raises(ValueError, match="Local hosts"):
        validate_public_url("https://localhost/proposal")


@pytest.mark.parametrize(
    "url",
    [
        "https://dao.internal.local/proposal",
        "https://LOCALHOST/proposal",
    ],
)
def test_rejects_local_hostnames(url):
    with pytest.raises(ValueError, match="Local hosts"):
        validate_public_url(url)


def test_rejects_url_with_credentials():
    with pytest.raises(ValueError, match="Invalid source URL"):
        validate_public_url("https://user:pass@example.org/proposal")


@pytest.mark.parametrize(
    "ip",
    [
        "10.0.0.5",          # private
        "192.168.1.10",      # private
        "127.0.0.1",         # loopback
        "169.254.1.1",       # link-local
        "0.0.0.0",           # unspecified
    ],
)
def test_rejects_non_public_addresses(monkeypatch, ip):
    _resolve_to(monkeypatch, ip)
    with pytest.raises(ValueError, match="non-public"):
        validate_public_url(VALID_URL)


def test_rejects_unresolvable_host(monkeypatch):
    def boom(host, port):
        raise socket.gaierror("name resolution failed")

    monkeypatch.setattr(research_tools.socket, "getaddrinfo", boom)
    with pytest.raises(ValueError, match="Could not resolve"):
        validate_public_url(VALID_URL)


# --------------------------------------------------------------------------
# fetch_source
# --------------------------------------------------------------------------


def test_extracts_title_and_readable_text(monkeypatch):
    _resolve_to(monkeypatch, PUBLIC_IP)
    _install_get(monkeypatch, response=FakeResponse(body=HTML_PAGE))

    result = fetch_source(VALID_URL)

    assert result["error"] is None
    assert result["url"] == VALID_URL
    assert result["title"] == "Protocol Integration Funding"
    assert "Funds a bridge integration." in result["text"]
    assert "<html>" not in result["text"]


def test_strips_script_and_style_content(monkeypatch):
    _resolve_to(monkeypatch, PUBLIC_IP)
    body = (
        b"<html><head><title>T</title><style>.hidden{color:red}</style></head>"
        b"<body><script>var secret = 42;</script><p>Visible claim</p></body></html>"
    )
    _install_get(monkeypatch, response=FakeResponse(body=body))

    result = fetch_source(VALID_URL)

    assert "Visible claim" in result["text"]
    assert "secret" not in result["text"]
    assert ".hidden" not in result["text"]


def test_truncates_long_text(monkeypatch):
    _resolve_to(monkeypatch, PUBLIC_IP)
    monkeypatch.setattr(research_tools, "MAX_CHARS_PER_SOURCE", 20)
    _install_get(
        monkeypatch, response=FakeResponse(body=b"<html><body>" + b"a" * 500 + b"</body></html>")
    )

    result = fetch_source(VALID_URL)

    assert result["error"] is None
    assert result["text"] == "a" * 20


def test_request_uses_safe_transport_options(monkeypatch):
    _resolve_to(monkeypatch, PUBLIC_IP)
    recorder: list = []
    _install_get(monkeypatch, response=FakeResponse(body=HTML_PAGE), recorder=recorder)

    fetch_source(VALID_URL)

    assert len(recorder) == 1
    kwargs = recorder[0]["kwargs"]
    assert kwargs["allow_redirects"] is False
    assert kwargs["stream"] is True
    assert kwargs["timeout"] == TIMEOUT_SECONDS
    assert "User-Agent" in kwargs["headers"]


def test_does_not_follow_redirects(monkeypatch):
    _resolve_to(monkeypatch, PUBLIC_IP)
    recorder: list = []
    _install_get(
        monkeypatch,
        response=FakeResponse(status_code=302, headers={"Location": "http://127.0.0.1/"}),
        recorder=recorder,
    )

    result = fetch_source(VALID_URL)

    assert recorder[0]["kwargs"]["allow_redirects"] is False
    assert result["error"] is not None
    assert "Redirected" in result["error"]


def test_handles_http_error(monkeypatch):
    _resolve_to(monkeypatch, PUBLIC_IP)
    _install_get(monkeypatch, response=FakeResponse(status_code=404))

    result = fetch_source(VALID_URL)

    assert result["error"] is not None
    assert result["text"] == ""
    assert result["title"] == ""


def test_handles_timeout(monkeypatch):
    _resolve_to(monkeypatch, PUBLIC_IP)
    _install_get(monkeypatch, exc=requests.exceptions.Timeout("timed out"))

    result = fetch_source(VALID_URL)

    assert result["error"] is not None
    assert result["text"] == ""


def test_handles_connection_error(monkeypatch):
    _resolve_to(monkeypatch, PUBLIC_IP)
    _install_get(monkeypatch, exc=requests.exceptions.ConnectionError("refused"))

    result = fetch_source(VALID_URL)

    assert result["error"] is not None
    assert result["text"] == ""


def test_rejects_non_html_response(monkeypatch):
    _resolve_to(monkeypatch, PUBLIC_IP)
    _install_get(
        monkeypatch,
        response=FakeResponse(
            headers={"Content-Type": "application/pdf"}, body=b"%PDF-1.7"
        ),
    )

    result = fetch_source(VALID_URL)

    assert result["error"] is not None
    assert "readable text or HTML" in result["error"]


def test_rejects_oversized_response(monkeypatch):
    _resolve_to(monkeypatch, PUBLIC_IP)
    monkeypatch.setattr(research_tools, "MAX_BYTES", 32)
    _install_get(monkeypatch, response=FakeResponse(body=b"<html>" + b"x" * 500 + b"</html>"))

    result = fetch_source(VALID_URL)

    assert result["error"] is not None
    assert "maximum allowed size" in result["error"]


def test_rejects_page_with_no_readable_text(monkeypatch):
    _resolve_to(monkeypatch, PUBLIC_IP)
    _install_get(monkeypatch, response=FakeResponse(body=b"<html><body><script>x=1</script></body></html>"))

    result = fetch_source(VALID_URL)

    assert result["error"] is not None
    assert result["text"] == ""


def test_does_not_fabricate_findings_on_failure(monkeypatch):
    _resolve_to(monkeypatch, PUBLIC_IP)
    _install_get(monkeypatch, exc=requests.exceptions.Timeout("timed out"))

    result = fetch_source(VALID_URL)

    assert result == {"url": VALID_URL, "title": "", "text": "", "error": "timed out"}


def test_blocks_unsafe_url_before_requesting(monkeypatch):
    _resolve_to(monkeypatch, "10.0.0.5")
    recorder: list = []
    _install_get(monkeypatch, response=FakeResponse(body=HTML_PAGE), recorder=recorder)

    result = fetch_source(VALID_URL)

    assert result["error"] is not None
    assert recorder == []


def test_max_bytes_is_one_megabyte():
    assert MAX_BYTES == 1_000_000


# --------------------------------------------------------------------------
# research_sources
# --------------------------------------------------------------------------


def test_returns_findings_for_retrieved_sources(monkeypatch):
    _resolve_to(monkeypatch, PUBLIC_IP)
    second = "https://example.org/forum"
    _install_get_by_url(
        monkeypatch,
        {
            VALID_URL: FakeResponse(body=HTML_PAGE),
            second: FakeResponse(body=b"<html><head><title>Thread</title></head><body><p>Discussion</p></body></html>"),
        },
    )

    result = research_sources([VALID_URL, second])

    assert len(result["research_findings"]) == 2
    assert result["source_urls"] == [VALID_URL, second]
    assert result["evidence_gaps"] == []
    assert result["research_findings"][0].startswith(f"[{VALID_URL}]")


def test_records_failed_sources_as_evidence_gaps(monkeypatch):
    _resolve_to(monkeypatch, PUBLIC_IP)
    _install_get_by_url(monkeypatch, {VALID_URL: FakeResponse(status_code=404)})

    result = research_sources([VALID_URL])

    assert result["research_findings"] == []
    assert result["source_urls"] == []
    assert len(result["evidence_gaps"]) == 1
    assert VALID_URL in result["evidence_gaps"][0]


def test_handles_empty_url_list():
    result = research_sources([])

    assert result["research_findings"] == []
    assert result["source_urls"] == []
    assert result["evidence_gaps"] == ["No source URLs were supplied."]


def test_enforces_maximum_of_five_urls(monkeypatch):
    _resolve_to(monkeypatch, PUBLIC_IP)
    urls = [f"https://example.org/p{i}" for i in range(6)]
    recorder: list = []
    _install_get_by_url(
        monkeypatch,
        {url: FakeResponse(body=HTML_PAGE) for url in urls},
        recorder=recorder,
    )

    result = research_sources(urls)

    assert len(recorder) == research_tools.MAX_SOURCES == 5
    assert len(result["source_urls"]) == 5
    assert urls[5] not in result["source_urls"]


def test_separates_successful_and_failed_sources(monkeypatch):
    _resolve_to(monkeypatch, PUBLIC_IP)
    bad = "https://example.org/missing"
    _install_get_by_url(
        monkeypatch,
        {
            bad: FakeResponse(status_code=500),
            VALID_URL: FakeResponse(body=HTML_PAGE),
        },
    )

    result = research_sources([bad, VALID_URL])

    assert len(result["research_findings"]) == 1
    assert result["source_urls"] == [VALID_URL]
    assert len(result["evidence_gaps"]) == 1
    assert bad in result["evidence_gaps"][0]


def test_unsafe_url_is_reported_as_gap_not_fetched(monkeypatch):
    recorder: list = []
    _install_get(monkeypatch, response=FakeResponse(body=HTML_PAGE), recorder=recorder)

    result = research_sources(["https://localhost/private"])

    assert recorder == []
    assert result["research_findings"] == []
    assert len(result["evidence_gaps"]) == 1
