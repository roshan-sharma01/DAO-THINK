"""Offline tests for proposal retrieval. No test touches the real network."""

import socket

import pytest
import requests

from research_agent import research_tools as rt
from tests.fixtures import (
    PROPOSAL_ID, PROPOSAL_URL, SPACE, TITLE, graphql_body, snapshot_proposal,
)

PUBLIC_IP = "93.184.216.34"


class FakeResponse:
    def __init__(self, status_code=200, headers=None, body=b"", encoding="utf-8"):
        self.status_code = status_code
        self.headers = headers if headers is not None else {"Content-Type": "application/json"}
        self.encoding = encoding
        self._body = body

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def raise_for_status(self):
        if self.status_code >= 400:
            raise requests.HTTPError(f"{self.status_code} Error", response=self)

    def iter_content(self, chunk_size=8192):
        for start in range(0, len(self._body), chunk_size):
            yield self._body[start:start + chunk_size]


@pytest.fixture(autouse=True)
def no_network(monkeypatch):
    def blocked(*a, **k):
        raise AssertionError("unit tests must not perform real network requests")

    monkeypatch.setattr(rt.requests, "get", blocked)
    monkeypatch.setattr(rt.requests, "post", blocked)
    monkeypatch.setattr(rt.socket, "getaddrinfo", blocked)


def resolve_to(monkeypatch, ip=PUBLIC_IP):
    monkeypatch.setattr(
        rt.socket, "getaddrinfo",
        lambda host, port: [(socket.AF_INET, socket.SOCK_STREAM, 6, "", (ip, 443))],
    )


def post_returns(monkeypatch, response=None, exc=None, calls=None):
    def fake_post(url, **kwargs):
        if calls is not None:
            calls.append((url, kwargs))
        if exc is not None:
            raise exc
        return response

    monkeypatch.setattr(rt.requests, "post", fake_post)


# ---------------------------------------------------------------- URL parsing

@pytest.mark.parametrize("url", [
    PROPOSAL_URL,
    f"https://snapshot.box/#/s:{SPACE}/proposal/{PROPOSAL_ID}",
    f"https://www.snapshot.org/#/{SPACE}/proposal/{PROPOSAL_ID}/",
])
def test_parses_snapshot_urls(url):
    assert rt.parse_snapshot_url(url) == (SPACE, PROPOSAL_ID)


@pytest.mark.parametrize("url", [
    f"http://snapshot.org/#/{SPACE}/proposal/{PROPOSAL_ID}",          # not https
    f"https://snapshot.org/#/{SPACE}",                                 # no proposal
    f"https://snapshot.org/#/{SPACE}/proposal/not-an-id",              # bad id
    f"https://snapshot.box/#/sep:{SPACE}/proposal/{PROPOSAL_ID}",     # testnet hub
    f"https://evil.example/#/{SPACE}/proposal/{PROPOSAL_ID}",          # not snapshot
    f"https://snapshot.org/#/bad space/proposal/{PROPOSAL_ID}",        # bad space
])
def test_rejects_bad_snapshot_urls(url):
    with pytest.raises(ValueError):
        rt.parse_snapshot_url(url)


# ------------------------------------------------------------ GraphQL fetch

def test_fetch_uses_graphql_variables_and_safe_transport(monkeypatch):
    resolve_to(monkeypatch)
    calls = []
    post_returns(monkeypatch, FakeResponse(body=graphql_body(snapshot_proposal())), calls=calls)

    result = rt.fetch_snapshot_proposal(PROPOSAL_ID)

    assert result["error"] is None
    assert result["proposal"]["title"] == TITLE
    url, kwargs = calls[0]
    assert url == rt.SNAPSHOT_GRAPHQL_URL
    assert kwargs["json"]["variables"] == {"id": PROPOSAL_ID}
    assert PROPOSAL_ID not in kwargs["json"]["query"]  # never interpolated
    assert kwargs["allow_redirects"] is False and kwargs["stream"] is True
    assert kwargs["timeout"] == rt.TIMEOUT_SECONDS


@pytest.mark.parametrize("response, message", [
    (FakeResponse(body=graphql_body(None)), "not found"),
    (FakeResponse(body=b'{"errors": [{"message": "boom"}]}'), "returned an error"),
    (FakeResponse(body=b"{not json"), "invalid JSON"),
    (FakeResponse(body=b"[]"), "unexpected response"),
    (FakeResponse(headers={"Content-Type": "text/html"}, body=b"<html></html>"), "did not return JSON"),
    (FakeResponse(status_code=500), "500"),
    (FakeResponse(status_code=302, headers={"Location": "https://127.0.0.1/"}), "Redirected"),
])
def test_fetch_errors_are_reported_not_invented(monkeypatch, response, message):
    resolve_to(monkeypatch)
    post_returns(monkeypatch, response)

    result = rt.fetch_snapshot_proposal(PROPOSAL_ID)

    assert result["proposal"] is None
    assert message in result["error"]


@pytest.mark.parametrize("exc", [
    requests.exceptions.Timeout("timed out"),
    requests.exceptions.ConnectionError("network down"),
])
def test_fetch_network_failures(monkeypatch, exc):
    resolve_to(monkeypatch)
    post_returns(monkeypatch, exc=exc)

    result = rt.fetch_snapshot_proposal(PROPOSAL_ID)

    assert result["proposal"] is None and result["error"]


def test_fetch_rejects_oversized_response(monkeypatch):
    resolve_to(monkeypatch)
    monkeypatch.setattr(rt, "MAX_BYTES", 64)
    post_returns(monkeypatch, FakeResponse(body=graphql_body(snapshot_proposal())))

    result = rt.fetch_snapshot_proposal(PROPOSAL_ID)

    assert "maximum allowed size" in result["error"]


def test_fetch_blocks_private_resolution_before_any_request(monkeypatch):
    resolve_to(monkeypatch, "10.1.2.3")
    calls = []
    post_returns(monkeypatch, FakeResponse(body=graphql_body(snapshot_proposal())), calls=calls)

    result = rt.fetch_snapshot_proposal(PROPOSAL_ID)

    assert "non-public" in result["error"]
    assert calls == []


def test_fetch_rejects_invalid_id_without_request(monkeypatch):
    calls = []
    post_returns(monkeypatch, FakeResponse(), calls=calls)

    assert rt.fetch_snapshot_proposal('x") { id } #')["error"]
    assert calls == []


# ------------------------------------------------------- evidence building

def test_snapshot_evidence_labels_facts_and_quorum_semantics():
    evidence = rt.snapshot_evidence(snapshot_proposal(), SPACE, PROPOSAL_ID)

    assert evidence["title"] == TITLE
    assert evidence["content_retrieved"] is True
    assert all(f.startswith("Snapshot API:") for f in evidence["facts"])
    assert any("choices For; Against; Abstain" in f for f in evidence["facts"])
    assert any("For=1,200,000.5" in f and "321 votes" in f for f in evidence["facts"])
    # quorum 0 must not be described as "no quorum required"
    joined = " ".join(evidence["facts"] + evidence["caveats"]).lower()
    assert "not configured" in joined and "unverifiable" in joined
    assert "no quorum required" not in joined
    assert any("not the merit" in c for c in evidence["caveats"])
    assert evidence["gaps"] == []


def test_positive_quorum_is_reported_as_threshold():
    evidence = rt.snapshot_evidence(snapshot_proposal(quorum=500000), SPACE, PROPOSAL_ID)

    assert any("quorum threshold 500,000 (default)" in f for f in evidence["facts"])
    assert not any("Quorum is unverifiable" in c for c in evidence["caveats"])


@pytest.mark.parametrize("overrides, space, pid, message", [
    ({"id": "0x" + "cd" * 32}, SPACE, PROPOSAL_ID, "different proposal id"),
    ({"space": {"id": "other.eth", "name": "Other"}}, SPACE, PROPOSAL_ID, "belongs to space"),
    ({"title": "   "}, SPACE, PROPOSAL_ID, "empty title"),
])
def test_snapshot_evidence_rejects_wrong_or_empty_proposals(overrides, space, pid, message):
    with pytest.raises(ValueError, match=message):
        rt.snapshot_evidence(snapshot_proposal(**overrides), space, pid)


def test_empty_body_is_a_blocking_gap_not_content():
    evidence = rt.snapshot_evidence(snapshot_proposal(body=""), SPACE, PROPOSAL_ID)

    assert evidence["content_retrieved"] is False
    assert any("empty proposal body" in g for g in evidence["gaps"])


def test_flagged_and_mismatched_scores():
    evidence = rt.snapshot_evidence(
        snapshot_proposal(flagged=True, scores=[1.0]), SPACE, PROPOSAL_ID
    )
    assert any("flagged" in g for g in evidence["gaps"])
    assert any("did not match the choices" in c for c in evidence["caveats"])


def test_long_body_is_truncated_with_caveat(monkeypatch):
    monkeypatch.setattr(rt, "MAX_PROPOSAL_CHARS", 50)
    evidence = rt.snapshot_evidence(snapshot_proposal(), SPACE, PROPOSAL_ID)

    assert len(evidence["text"]) == 50
    assert any("truncated" in c for c in evidence["caveats"])


# ------------------------------------------------------- research_proposal

def test_research_proposal_uses_api_never_the_client_rendered_page(monkeypatch):
    resolve_to(monkeypatch)
    post_returns(monkeypatch, FakeResponse(body=graphql_body(snapshot_proposal())))
    # requests.get stays blocked: fetching snapshot.org would fail the test.

    result = rt.research_proposal(PROPOSAL_URL)

    assert result["retrieval_method"] == "snapshot_graphql"
    assert result["content_retrieved"] is True
    assert result["retrieved_title"] == TITLE
    assert result["source_urls"] == [PROPOSAL_URL]
    assert "security audit program" in result["proposal_text"]
    assert result["retrieved_at"].endswith("Z")
    assert result["evidence_gaps"] == []


def test_research_proposal_failure_returns_gap_and_no_sources(monkeypatch):
    resolve_to(monkeypatch)
    post_returns(monkeypatch, FakeResponse(body=graphql_body(None)))

    result = rt.research_proposal(PROPOSAL_URL)

    assert result["content_retrieved"] is False
    assert result["source_urls"] == [] and result["research_findings"] == []
    assert result["retrieved_title"] == "" and result["proposal_text"] == ""
    assert any("not found" in g for g in result["evidence_gaps"])


def test_generic_app_shell_is_not_treated_as_proposal_content(monkeypatch):
    resolve_to(monkeypatch)
    shell = b"<html><head><title>DAO App</title></head><body><div id=app>Loading</div></body></html>"
    monkeypatch.setattr(
        rt.requests, "get",
        lambda url, **k: FakeResponse(headers={"Content-Type": "text/html"}, body=shell),
    )

    result = rt.research_proposal("https://gov.example.org/proposals/7")

    assert result["content_retrieved"] is False
    assert result["source_urls"] == []
    assert any("app shell" in g for g in result["evidence_gaps"])


def test_generic_page_with_content_is_retrieved_with_caveat(monkeypatch):
    resolve_to(monkeypatch)
    page = ("<html><head><title>Proposal 7</title></head><body><p>"
            + "This proposal funds documentation work for the protocol. " * 10
            + "</p></body></html>").encode()
    monkeypatch.setattr(
        rt.requests, "get",
        lambda url, **k: FakeResponse(headers={"Content-Type": "text/html"}, body=page),
    )

    result = rt.research_proposal("https://gov.example.org/proposals/7")

    assert result["retrieval_method"] == "html_page"
    assert result["retrieved_title"] == "Proposal 7"
    assert any("not a governance source of record" in c for c in result["caveats"])


def test_research_proposal_requires_a_url():
    result = rt.research_proposal("")
    assert result["evidence_gaps"] == ["No proposal URL was supplied."]
    assert result["content_retrieved"] is False


def test_unsafe_supporting_url_is_a_gap(monkeypatch):
    resolve_to(monkeypatch)
    post_returns(monkeypatch, FakeResponse(body=graphql_body(snapshot_proposal())))

    result = rt.research_proposal(PROPOSAL_URL, ["http://169.254.169.254/latest/meta-data"])

    assert result["source_urls"] == [PROPOSAL_URL]
    assert any("HTTPS" in g for g in result["evidence_gaps"])
