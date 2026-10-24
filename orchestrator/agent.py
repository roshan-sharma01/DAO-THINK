import asyncio
import json
import logging
import os
import re
from pathlib import Path
from typing import Optional

from dotenv import load_dotenv
from uagents import Agent, Context, Protocol
from uagents_core.contrib.protocols.chat import (
    ChatAcknowledgement,
    ChatMessage,
    TextContent,
    chat_protocol_spec,
)

from orchestrator.report import build_decision_report, format_report
from local_config import (
    ORCHESTRATOR_PORT, local_mode_enabled, local_resolver, peer_address,
)
from research_agent.research_tools import is_snapshot_host, parse_snapshot_url
from shared.models import (
    AnalysisRequest,
    AnalysisResult,
    DAOAnalysisRequest,
    DecisionReport,
    ResearchRequest,
    ResearchResult,
)

load_dotenv()

# Research may fetch the proposal plus up to four supporting pages.
RESEARCH_TIMEOUT_SECONDS = 60
ANALYSIS_TIMEOUT_SECONDS = 30
REQUEST_TIMEOUT_SECONDS = RESEARCH_TIMEOUT_SECONDS  # backwards-compatible name
ALTERNATIVES = ["Approve as proposed", "Approve a smaller pilot", "Take no action"]
AGENT_DESCRIPTION = (
    "DAOThink: human-in-the-loop DAO governance research. Send a Snapshot proposal "
    "URL; get an evidence-labelled report of claims, risks and gaps. Decision "
    "support only - it never votes."
)

logger = logging.getLogger("daoaction.orchestrator")
mailbox_enabled = os.getenv("MAILBOX_ENABLED", "false").strip().lower()
if mailbox_enabled not in {"true", "false"}:
    raise ValueError("MAILBOX_ENABLED must be 'true' or 'false'.")

_local_mode = local_mode_enabled()
_readme = Path(__file__).resolve().parent.parent / "AGENT_README.md"
_agent_kwargs = {
    "name": os.getenv("AGENT_NAME") or "daoaction-orchestrator",
    "seed": os.getenv("ORCHESTRATOR_SEED") or None,
    "loop": asyncio.new_event_loop(),
    "port": ORCHESTRATOR_PORT if _local_mode else int(os.getenv("AGENT_PORT", "8000")),
    "mailbox": False if _local_mode else mailbox_enabled == "true",
    "description": AGENT_DESCRIPTION,
}
if _readme.exists():
    _agent_kwargs["readme_path"] = str(_readme)
if _local_mode:
    _agent_kwargs["endpoint"] = [f"http://127.0.0.1:{ORCHESTRATOR_PORT}/submit"]
    _agent_kwargs["resolve"] = local_resolver()
else:
    _agent_kwargs["endpoint"] = os.getenv("AGENT_ENDPOINT") or None
agent = Agent(**_agent_kwargs)
chat_protocol = Protocol(spec=chat_protocol_spec)


def _log_peer_issue(ctx: Context, message: str) -> None:
    if ctx.logger:
        ctx.logger.warning(message)
    else:
        logger.warning(message)


def _no_research(proposal_id: str, reason: str) -> ResearchResult:
    return ResearchResult(
        proposal_id=proposal_id,
        summary="No research results were received.",
        findings=[],
        source_urls=[],
        limitations=[reason],
    )


def validate_request(request: DAOAnalysisRequest) -> list[str]:
    problems = []
    if not request.proposal_id.strip():
        problems.append("proposal_id is required.")
    url = request.proposal_url.strip()
    if not url:
        problems.append("proposal_url is required.")
    elif not url.startswith("https://"):
        problems.append("proposal_url must be an https:// URL.")
    for name in ("requested_amount", "treasury_balance"):
        value = getattr(request, name)
        if value is not None and value < 0:
            problems.append(f"{name} cannot be negative.")
    return problems


async def _request_research(
    ctx: Context,
    request: DAOAnalysisRequest,
    address: Optional[str],
) -> ResearchResult:
    address = address.strip() if address else ""
    if not address:
        return _no_research(request.proposal_id, "Research agent address is not configured.")

    try:
        response, _ = await ctx.send_and_receive(
            address,
            ResearchRequest(
                proposal_id=request.proposal_id,
                proposal_title=request.proposal_title,
                proposal_url=request.proposal_url,
                research_questions=[
                    "What benefits and costs are stated in the proposal?",
                    "What implementation dependencies or risks are documented?",
                    "What evidence is missing or independently unverified?",
                ],
                source_urls=[],
            ),
            response_type=ResearchResult,
            timeout=RESEARCH_TIMEOUT_SECONDS,
        )
    except asyncio.TimeoutError:
        _log_peer_issue(ctx, "Research agent did not respond before the timeout.")
        return _no_research(request.proposal_id, "Research agent request timed out.")
    except Exception as exc:
        _log_peer_issue(ctx, f"Research agent request failed ({type(exc).__name__}).")
        return _no_research(
            request.proposal_id, f"Research agent request failed ({type(exc).__name__})."
        )

    if response is None:
        _log_peer_issue(ctx, "Research agent did not respond before the timeout.")
        return _no_research(request.proposal_id, "Research agent request timed out.")
    if not isinstance(response, ResearchResult):
        _log_peer_issue(ctx, "Research agent returned an invalid result.")
        return _no_research(request.proposal_id, "Research agent did not return a valid result.")
    if response.proposal_id != request.proposal_id:
        _log_peer_issue(ctx, "Research agent returned a result for a different proposal.")
        return ResearchResult(
            proposal_id=request.proposal_id,
            summary="No research results were received for this proposal.",
            findings=[],
            source_urls=[],
            limitations=["Research agent returned a mismatched proposal ID."],
        )
    return response


async def _request_analysis(
    ctx: Context,
    request: DAOAnalysisRequest,
    research: ResearchResult,
    address: Optional[str],
) -> AnalysisResult:
    address = address.strip() if address else ""
    if not address:
        return _missing_analysis(request.proposal_id, ["Analysis agent address is not configured."])

    analysis_request = AnalysisRequest(
        proposal_id=request.proposal_id,
        proposal_title=research.retrieved_title or request.proposal_title or request.proposal_id,
        requested_amount=request.requested_amount,
        treasury_balance=request.treasury_balance,
        research_findings=research.findings,
        source_urls=research.source_urls,
        alternatives=list(ALTERNATIVES),
        evidence_gaps=research.limitations,
        proposal_text=research.proposal_text,
        proposal_facts=research.proposal_facts,
        proposal_content_retrieved=research.proposal_content_retrieved,
        caveats=research.caveats,
    )
    try:
        response, _ = await ctx.send_and_receive(
            address,
            analysis_request,
            response_type=AnalysisResult,
            timeout=ANALYSIS_TIMEOUT_SECONDS,
        )
    except asyncio.TimeoutError:
        _log_peer_issue(ctx, "Analysis agent did not respond before the timeout.")
        return _missing_analysis(request.proposal_id, ["Analysis agent request timed out."])
    except Exception as exc:
        _log_peer_issue(ctx, f"Analysis agent request failed ({type(exc).__name__}).")
        return _missing_analysis(
            request.proposal_id,
            [f"Analysis agent request failed ({type(exc).__name__})."],
        )

    if response is None:
        _log_peer_issue(ctx, "Analysis agent did not respond before the timeout.")
        return _missing_analysis(request.proposal_id, ["Analysis agent request timed out."])
    if not isinstance(response, AnalysisResult):
        _log_peer_issue(ctx, "Analysis agent returned an invalid result.")
        return _missing_analysis(
            request.proposal_id,
            ["Analysis agent did not return a valid result."],
        )
    if response.proposal_id != request.proposal_id:
        _log_peer_issue(ctx, "Analysis agent returned a result for a different proposal.")
        return _missing_analysis(
            request.proposal_id,
            ["Analysis agent returned a mismatched proposal ID."],
        )
    return response


def _missing_analysis(proposal_id: str, gaps: list[str]) -> AnalysisResult:
    return AnalysisResult(
        proposal_id=proposal_id,
        recommendation="No recommendation; human review requires more evidence.",
        strategy_assessment="Not assessed.",
        financial_assessment="Not assessed.",
        alternatives_assessment="Not assessed.",
        critic_findings=[],
        risk_findings=[],
        evidence_gaps=gaps,
        review_status="more_evidence_required",
    )


def _normalize_title(title: str) -> str:
    return re.sub(r"[^a-z0-9]+", " ", title.lower()).strip()


def consistency_gaps(request: DAOAnalysisRequest, research: ResearchResult) -> list[str]:
    """Confirm the report describes the proposal that was requested."""
    gaps = []
    requested = request.proposal_title.strip()
    retrieved = research.retrieved_title.strip()
    if requested and retrieved and _normalize_title(requested) != _normalize_title(retrieved):
        gaps.append(
            f"Requested title \"{requested}\" does not match the retrieved title "
            f"\"{retrieved}\"; confirm the URL points to the intended proposal."
        )
    if is_snapshot_host(request.proposal_url):
        try:
            _, url_id = parse_snapshot_url(request.proposal_url)
        except ValueError:
            url_id = ""
        supplied = request.proposal_id.strip()
        if url_id and supplied.lower().startswith("0x") and supplied.lower() != url_id.lower():
            gaps.append(
                "proposal_id does not match the Snapshot proposal id in proposal_url."
            )
    return gaps


async def analyze_proposal(
    ctx: Context, request: DAOAnalysisRequest
) -> DecisionReport:
    problems = validate_request(request)
    if problems:
        research = _no_research(request.proposal_id, "Request was invalid; research not performed.")
        analysis = _missing_analysis(request.proposal_id, [f"Invalid request: {p}" for p in problems])
        return build_decision_report(
            request.proposal_title or request.proposal_id, research, analysis,
            requested_title=request.proposal_title,
        )

    research = await _request_research(
        ctx, request, peer_address("RESEARCH_AGENT_ADDRESS", "RESEARCH_AGENT_SEED")
    )
    analysis = await _request_analysis(
        ctx, request, research, peer_address("ANALYSIS_AGENT_ADDRESS", "ANALYSIS_AGENT_SEED")
    )
    display_title = research.retrieved_title or request.proposal_title or request.proposal_id
    return build_decision_report(
        display_title,
        research,
        analysis,
        requested_title=request.proposal_title,
        extra_gaps=consistency_gaps(request, research),
    )


_URL_RE = re.compile(r"https://[^\s<>\"']+")
CHAT_HELP = (
    "Send a DAO proposal link, for example:\n"
    "https://snapshot.org/#/<space>/proposal/<id>\n\n"
    "Or send JSON with proposal_id and proposal_url, plus optional proposal_title, "
    "requested_amount and treasury_balance (both amounts are needed for a treasury "
    "exposure check). DAOThink returns decision support for a human; it never votes."
)


def parse_chat_request(text: str) -> DAOAnalysisRequest:
    """Accept either a JSON object or plain text containing one proposal URL."""
    text = text.strip()
    if text.startswith("{"):
        payload = json.loads(text)
        if not isinstance(payload, dict):
            raise ValueError("Expected a JSON object.")
        return DAOAnalysisRequest(**payload)

    urls = [u.rstrip(".,);]") for u in _URL_RE.findall(text)]
    if not urls:
        raise ValueError("No https:// proposal URL was found in the message.")
    url = urls[0]
    proposal_id = url
    if is_snapshot_host(url):
        _, proposal_id = parse_snapshot_url(url)
    return DAOAnalysisRequest(proposal_id=proposal_id, proposal_url=url)


@agent.on_message(model=DAOAnalysisRequest, replies={DecisionReport})
async def handle_analysis_request(
    ctx: Context, sender: str, request: DAOAnalysisRequest
) -> None:
    report = await analyze_proposal(ctx, request)
    await ctx.send(sender, report)


@chat_protocol.on_message(model=ChatMessage)
async def handle_chat_message(
    ctx: Context, sender: str, message: ChatMessage
) -> None:
    await ctx.send(
        sender, ChatAcknowledgement(acknowledged_msg_id=message.msg_id)
    )
    text = message.text().strip()
    try:
        request = parse_chat_request(text)
    except (TypeError, ValueError) as exc:
        response_text = f"{CHAT_HELP}\n\nInput error: {exc}"
    else:
        report = await analyze_proposal(ctx, request)
        response_text = format_report(report)

    await ctx.send(sender, ChatMessage(content=[TextContent(text=response_text)]))


@chat_protocol.on_message(model=ChatAcknowledgement)
async def handle_chat_acknowledgement(
    _ctx: Context, _sender: str, _acknowledgement: ChatAcknowledgement
) -> None:
    if _ctx.logger:
        _ctx.logger.debug(
            "Received chat acknowledgement from %s for message %s.",
            _sender,
            _acknowledgement.acknowledged_msg_id,
        )
    return None


@agent.on_event("startup")
async def announce(ctx: Context) -> None:
    ctx.logger.info("DAOThink Orchestrator address: %s", agent.address)
    ctx.logger.info("Local mode: %s", _local_mode)


def main() -> None:
    agent.include(chat_protocol, publish_manifest=True)
    agent.run()


if __name__ == "__main__":
    main()
