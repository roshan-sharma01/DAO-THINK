"""Safe retrieval of DAO proposals and supporting sources.

Everything fetched here is UNTRUSTED DATA. Proposal bodies and web pages may
contain text addressed to AI systems ("ignore previous instructions ..."). This
module only extracts text and structured facts; it never acts on fetched
content, and downstream analysis is deterministic (no model executes it).
"""

import ipaddress
import json
import re
import socket
from datetime import datetime, timezone
from typing import List, Optional, Tuple
from urllib.parse import urlparse

import requests
from bs4 import BeautifulSoup

MAX_BYTES = 1_000_000
TIMEOUT_SECONDS = 10
MAX_CHARS_PER_SOURCE = 4_000
MAX_PROPOSAL_CHARS = 20_000
# A generic page with less readable text than this is treated as an app shell
# or placeholder, not as retrieved proposal content.
MIN_PROPOSAL_CHARS = 300
MAX_SOURCES = 5
USER_AGENT = "DAOThinkResearch/1.1"

SNAPSHOT_GRAPHQL_URL = "https://hub.snapshot.org/graphql"
SNAPSHOT_HOSTS = {"snapshot.org", "www.snapshot.org", "snapshot.box", "www.snapshot.box"}
# Snapshot proposal ids: 0x-prefixed 32-byte hex, or legacy IPFS CIDs.
_SNAPSHOT_ID_RE = re.compile(r"^(0x[0-9a-fA-F]{64}|Qm[1-9A-HJ-NP-Za-km-z]{44}|baf[a-z2-7]{40,80})$")
_SNAPSHOT_SPACE_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,99}$")
_SNAPSHOT_FRAGMENT_RE = re.compile(r"^/?(?:(?P<net>[a-z]+):)?(?P<space>[^/]+)/proposal/(?P<id>[^/?#]+)/?$")

SNAPSHOT_PROPOSAL_QUERY = """
query Proposal($id: String!) {
  proposal(id: $id) {
    id title body choices start end snapshot state author created
    type quorum quorumType scores scores_total scores_state votes
    discussion link network flagged
    space { id name }
  }
}
"""


# --------------------------------------------------------------------------
# URL safety and bounded HTTP
# --------------------------------------------------------------------------


def validate_public_url(url: str) -> None:
    parsed = urlparse(url)
    if parsed.scheme != "https":
        raise ValueError("Only HTTPS sources are accepted.")
    if not parsed.hostname or parsed.username or parsed.password:
        raise ValueError("Invalid source URL.")

    host = parsed.hostname.lower()
    if host in {"localhost"} or host.endswith(".local") or host.endswith(".localhost"):
        raise ValueError("Local hosts are not allowed.")

    try:
        addresses = socket.getaddrinfo(host, 443)
    except socket.gaierror as exc:
        raise ValueError("Could not resolve source host.") from exc

    for address in addresses:
        ip = ipaddress.ip_address(address[4][0])
        if not ip.is_global:
            raise ValueError("Private or non-public addresses are blocked.")


def _read_bounded(response) -> bytes:
    chunks: List[bytes] = []
    total = 0
    for chunk in response.iter_content(chunk_size=8192):
        if not chunk:
            continue
        total += len(chunk)
        if total > MAX_BYTES:
            raise ValueError("Source exceeded the maximum allowed size.")
        chunks.append(chunk)
    return b"".join(chunks)


def _reject_redirects(response) -> None:
    # Redirects are never followed, so a public URL cannot bounce to a private host.
    if response.status_code in (301, 302, 303, 307, 308):
        raise ValueError("Redirected URLs are not accepted.")


def fetch_source(url: str, max_chars: Optional[int] = None) -> dict:
    limit = MAX_CHARS_PER_SOURCE if max_chars is None else max_chars
    try:
        validate_public_url(url)

        with requests.get(
            url,
            timeout=TIMEOUT_SECONDS,
            stream=True,
            allow_redirects=False,
            headers={"User-Agent": USER_AGENT},
        ) as response:
            _reject_redirects(response)
            response.raise_for_status()

            content_type = response.headers.get("Content-Type", "")
            if "html" not in content_type and "text" not in content_type:
                raise ValueError("Source is not a readable text or HTML page.")

            encoding = response.encoding or "utf-8"
            raw = _read_bounded(response)

        body = raw.decode(encoding, errors="replace")
        soup = BeautifulSoup(body, "html.parser")
        for tag in soup(["script", "style", "noscript", "nav", "header", "footer"]):
            tag.decompose()

        title_tag = soup.find("title")
        title = " ".join(title_tag.get_text().split()) if title_tag else ""

        text = " ".join(soup.get_text(separator=" ").split())
        if not text:
            raise ValueError("No readable text was found at the source.")

        return {
            "url": url,
            "title": title,
            "text": text[:limit],
            "truncated": len(text) > limit,
            "error": None,
        }
    except (ValueError, requests.RequestException) as exc:
        return {"url": url, "title": "", "text": "", "error": str(exc)}


# --------------------------------------------------------------------------
# Snapshot (source of record via its public GraphQL hub)
# --------------------------------------------------------------------------


def is_snapshot_host(url: str) -> bool:
    host = (urlparse(url).hostname or "").lower()
    return host in SNAPSHOT_HOSTS


def parse_snapshot_url(url: str) -> Tuple[str, str]:
    """Return (space, proposal_id) for a snapshot.org / snapshot.box proposal URL.

    Snapshot's web app is client-rendered: fetching the page returns only an
    app shell, so the proposal must be read from the GraphQL hub instead.
    """
    parsed = urlparse(url)
    if parsed.scheme != "https" or not is_snapshot_host(url):
        raise ValueError("Not a Snapshot proposal URL.")
    match = _SNAPSHOT_FRAGMENT_RE.match(parsed.fragment or "")
    if not match:
        raise ValueError(
            "Unrecognized Snapshot URL. Expected "
            "https://snapshot.org/#/<space>/proposal/<id>."
        )
    network, space, proposal_id = match.group("net"), match.group("space"), match.group("id")
    if network not in (None, "s"):
        # e.g. "sep:" (Sepolia testnet) lives on a different hub.
        raise ValueError(f"Snapshot network prefix '{network}:' is not supported.")
    if not _SNAPSHOT_SPACE_RE.match(space):
        raise ValueError("Snapshot space name is not valid.")
    if not _SNAPSHOT_ID_RE.match(proposal_id):
        raise ValueError("Snapshot proposal id is not valid.")
    return space, proposal_id


def fetch_snapshot_proposal(proposal_id: str) -> dict:
    """Query the Snapshot hub. Returns {"proposal": dict|None, "error": str|None}."""
    try:
        if not _SNAPSHOT_ID_RE.match(proposal_id or ""):
            raise ValueError("Snapshot proposal id is not valid.")
        validate_public_url(SNAPSHOT_GRAPHQL_URL)
        with requests.post(
            SNAPSHOT_GRAPHQL_URL,
            json={"query": SNAPSHOT_PROPOSAL_QUERY, "variables": {"id": proposal_id}},
            timeout=TIMEOUT_SECONDS,
            stream=True,
            allow_redirects=False,
            headers={"User-Agent": USER_AGENT, "Accept": "application/json"},
        ) as response:
            _reject_redirects(response)
            response.raise_for_status()
            if "json" not in response.headers.get("Content-Type", ""):
                raise ValueError("Snapshot API did not return JSON.")
            raw = _read_bounded(response)
        try:
            payload = json.loads(raw.decode("utf-8", errors="replace"))
        except json.JSONDecodeError as exc:
            raise ValueError("Snapshot API returned invalid JSON.") from exc
        if not isinstance(payload, dict):
            raise ValueError("Snapshot API returned an unexpected response.")
        if payload.get("errors"):
            raise ValueError("Snapshot API returned an error for this query.")
        data = payload.get("data")
        proposal = data.get("proposal") if isinstance(data, dict) else None
        if proposal is None:
            raise ValueError("Proposal was not found on Snapshot.")
        if not isinstance(proposal, dict):
            raise ValueError("Snapshot API returned an unexpected proposal format.")
        return {"proposal": proposal, "error": None}
    except (ValueError, requests.RequestException) as exc:
        return {"proposal": None, "error": str(exc)}


def _fmt_number(value) -> str:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return "unavailable"
    return f"{value:,.2f}".rstrip("0").rstrip(".")


def _fmt_time(value) -> str:
    if isinstance(value, bool) or not isinstance(value, (int, float)) or value <= 0:
        return "unavailable"
    return datetime.fromtimestamp(value, tz=timezone.utc).strftime("%Y-%m-%d %H:%M UTC")


def snapshot_evidence(proposal: dict, expected_space: str, expected_id: str) -> dict:
    """Turn a Snapshot API proposal into labelled facts, text, gaps and caveats.

    Raises ValueError when the API returned a different proposal than requested.
    """
    returned_id = str(proposal.get("id") or "")
    if returned_id.lower() != expected_id.lower():
        raise ValueError("Snapshot returned a different proposal id than requested.")
    space = proposal.get("space") or {}
    space_id = str(space.get("id") or "") if isinstance(space, dict) else ""
    if space_id.lower() != expected_space.lower():
        raise ValueError(
            f"Proposal belongs to space '{space_id or 'unknown'}', not '{expected_space}'."
        )

    title = " ".join(str(proposal.get("title") or "").split())
    if not title:
        raise ValueError("Snapshot returned a proposal with an empty title.")
    body = str(proposal.get("body") or "").strip()

    facts: List[str] = []
    gaps: List[str] = []  # blocking: content cannot be relied on
    caveats: List[str] = []  # non-blocking uncertainty
    label = "Snapshot API"
    space_name = space.get("name") if isinstance(space, dict) else None
    facts.append(f"{label}: space {space_id}" + (f" ({space_name})" if space_name else ""))
    facts.append(f"{label}: proposal id {returned_id}")
    facts.append(f"{label}: author address {proposal.get('author') or 'unavailable'}")
    facts.append(f"{label}: state {proposal.get('state') or 'unavailable'}")
    facts.append(f"{label}: voting type {proposal.get('type') or 'unavailable'}")

    choices = [str(c) for c in (proposal.get("choices") or []) if str(c).strip()]
    facts.append(f"{label}: choices " + ("; ".join(choices) if choices else "unavailable"))
    facts.append(
        f"{label}: voting window {_fmt_time(proposal.get('start'))} to "
        f"{_fmt_time(proposal.get('end'))}"
    )
    if proposal.get("snapshot"):
        facts.append(
            f"{label}: voting power snapshot block {proposal.get('snapshot')} "
            f"on network {proposal.get('network') or 'unavailable'}"
        )

    scores = proposal.get("scores") or []
    if choices and isinstance(scores, list) and len(scores) == len(choices):
        breakdown = ", ".join(f"{c}={_fmt_number(s)}" for c, s in zip(choices, scores))
        facts.append(
            f"{label}: vote results ({proposal.get('scores_state') or 'state unknown'}) "
            f"{breakdown}; total voting power {_fmt_number(proposal.get('scores_total'))}; "
            f"{proposal.get('votes') if proposal.get('votes') is not None else 'unknown'} votes"
        )
        caveats.append(
            "Vote totals measure voting power cast, not the merit of the proposal."
        )
    else:
        caveats.append("Vote results were unavailable or did not match the choices.")

    quorum = proposal.get("quorum")
    quorum_type = proposal.get("quorumType") or "default"
    if isinstance(quorum, (int, float)) and not isinstance(quorum, bool) and quorum > 0:
        facts.append(f"{label}: quorum threshold {_fmt_number(quorum)} ({quorum_type})")
    else:
        facts.append(f"{label}: quorum not configured in proposal data (reported as 0)")
        caveats.append(
            "Quorum is unverifiable: Snapshot reported 0, which means no quorum is "
            "configured on the proposal, not that the DAO requires none. Check the "
            "DAO's governance rules."
        )

    if proposal.get("discussion"):
        facts.append(f"{label}: discussion link {proposal.get('discussion')} (not retrieved)")
    if proposal.get("flagged"):
        gaps.append("Snapshot has flagged this proposal; treat its content with caution.")

    content_retrieved = bool(body)
    if not body:
        gaps.append("Snapshot returned an empty proposal body; content could not be analyzed.")
    if len(body) > MAX_PROPOSAL_CHARS:
        caveats.append(
            f"Proposal body was truncated to {MAX_PROPOSAL_CHARS:,} characters for analysis."
        )
        body = body[:MAX_PROPOSAL_CHARS]

    return {
        "title": title,
        "text": body,
        "facts": facts,
        "gaps": gaps,
        "caveats": caveats,
        "content_retrieved": content_retrieved,
    }


# --------------------------------------------------------------------------
# Research entry points
# --------------------------------------------------------------------------


def research_sources(urls: List[str]) -> dict:
    """Retrieve generic supporting pages (not the proposal of record)."""
    findings: List[str] = []
    used_sources: List[str] = []
    evidence_gaps: List[str] = []

    if not urls:
        evidence_gaps.append("No source URLs were supplied.")

    for url in urls[:MAX_SOURCES]:
        source = fetch_source(url)
        if source["error"] is not None:
            evidence_gaps.append(f"Could not retrieve {url}: {source['error']}")
            continue
        findings.append(f"[{url}] {source['text']}")
        used_sources.append(url)

    return {
        "research_findings": findings,
        "source_urls": used_sources,
        "evidence_gaps": evidence_gaps,
    }


def _now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def research_proposal(proposal_url: str, extra_urls: Optional[List[str]] = None) -> dict:
    """Retrieve the proposal of record, then any supporting sources.

    Only URLs that were actually retrieved appear in ``source_urls``; failures
    become evidence gaps. Nothing is invented when retrieval fails.
    """
    result = {
        "research_findings": [],
        "source_urls": [],
        "evidence_gaps": [],
        "caveats": [],
        "retrieval_method": "",
        "retrieved_at": _now_iso(),
        "retrieved_title": "",
        "proposal_text": "",
        "proposal_facts": [],
        "content_retrieved": False,
    }
    url = (proposal_url or "").strip()

    if not url:
        result["evidence_gaps"].append("No proposal URL was supplied.")
    elif is_snapshot_host(url):
        try:
            space, proposal_id = parse_snapshot_url(url)
            fetched = fetch_snapshot_proposal(proposal_id)
            if fetched["error"]:
                raise ValueError(fetched["error"])
            evidence = snapshot_evidence(fetched["proposal"], space, proposal_id)
        except ValueError as exc:
            result["evidence_gaps"].append(f"Could not retrieve Snapshot proposal {url}: {exc}")
        else:
            result.update(
                retrieval_method="snapshot_graphql",
                retrieved_title=evidence["title"],
                proposal_text=evidence["text"],
                proposal_facts=evidence["facts"],
                content_retrieved=evidence["content_retrieved"],
            )
            result["evidence_gaps"].extend(evidence["gaps"])
            result["caveats"].extend(evidence["caveats"])
            result["source_urls"].append(url)
            result["research_findings"].append(
                f"[{url}] Retrieved proposal \"{evidence['title']}\" from the Snapshot "
                f"GraphQL hub ({len(evidence['text']):,} characters of proposal text)."
            )
    else:
        source = fetch_source(url, max_chars=MAX_PROPOSAL_CHARS)
        if source["error"] is not None:
            result["evidence_gaps"].append(f"Could not retrieve {url}: {source['error']}")
        elif len(source["text"]) < MIN_PROPOSAL_CHARS:
            result["evidence_gaps"].append(
                f"{url} returned only {len(source['text'])} characters of readable text "
                "(possibly a client-rendered app shell); proposal content was not confirmed."
            )
        else:
            result.update(
                retrieval_method="html_page",
                retrieved_title=source["title"],
                proposal_text=source["text"],
                content_retrieved=True,
            )
            result["source_urls"].append(url)
            result["research_findings"].append(
                f"[{url}] Retrieved {len(source['text']):,} characters of page text"
                + (f" titled \"{source['title']}\"." if source["title"] else ".")
            )
            result["caveats"].append(
                "Proposal was read from a generic web page, not a governance source of "
                "record; page text may include unrelated content."
            )
            if source.get("truncated"):
                result["caveats"].append(
                    f"Page text was truncated to {MAX_PROPOSAL_CHARS:,} characters."
                )

    extras = [u for u in dict.fromkeys(extra_urls or []) if u and u.strip() != url]
    if extras:
        supporting = research_sources(extras[: max(0, MAX_SOURCES - 1)])
        result["research_findings"].extend(supporting["research_findings"])
        result["source_urls"].extend(supporting["source_urls"])
        result["evidence_gaps"].extend(supporting["evidence_gaps"])

    return result
