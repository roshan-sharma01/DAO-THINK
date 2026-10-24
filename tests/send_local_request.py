"""Send one real proposal through the three local DAOThink agents.

Reads DAO_PROPOSAL_URL (required) and optional DAO_PROPOSAL_ID,
DAO_PROPOSAL_TITLE, DAO_REQUESTED_AMOUNT and DAO_TREASURY_BALANCE from the
environment / .env. Nothing is hardcoded: the title shown in the report comes
from the source, and amounts are only sent when you supply them.

Exits 0 only when a DecisionReport arrives that describes the requested
proposal with retrieved content; otherwise exits 1 with the reason.
"""

import asyncio
import os
import sys
from typing import Optional

from dotenv import load_dotenv
from uagents import Agent, Context

from shared.models import DAOAnalysisRequest, DecisionReport
from local_config import (
    TEST_CLIENT_PORT,
    address_from_seed,
    local_mode_enabled,
    local_resolver,
    seed_from_env,
)
from orchestrator.report import format_report
from research_agent.research_tools import is_snapshot_host, parse_snapshot_url

load_dotenv()


def _optional_float(name: str) -> Optional[float]:
    raw = os.getenv(name, "").strip()
    if not raw:
        return None
    try:
        return float(raw)
    except ValueError as exc:
        raise RuntimeError(f"{name} must be a number.") from exc


def build_request() -> DAOAnalysisRequest:
    url = os.getenv("DAO_PROPOSAL_URL", "").strip().strip('"')
    if not url.startswith("https://"):
        raise RuntimeError("Set DAO_PROPOSAL_URL to a public https:// proposal URL.")
    proposal_id = os.getenv("DAO_PROPOSAL_ID", "").strip()
    if not proposal_id:
        proposal_id = parse_snapshot_url(url)[1] if is_snapshot_host(url) else url
    return DAOAnalysisRequest(
        proposal_id=proposal_id,
        proposal_url=url,
        proposal_title=os.getenv("DAO_PROPOSAL_TITLE", "").strip(),
        requested_amount=_optional_float("DAO_REQUESTED_AMOUNT"),
        treasury_balance=_optional_float("DAO_TREASURY_BALANCE"),
    )


def check_report(request: DAOAnalysisRequest, report: DecisionReport) -> list[str]:
    """Return problems that mean the end-to-end run did not really succeed."""
    problems = []
    if report.proposal_id != request.proposal_id:
        problems.append("Report proposal_id differs from the request.")
    if not report.retrieval_method:
        problems.append("Proposal content was not retrieved (see evidence gaps).")
    if request.proposal_url not in report.source_urls:
        problems.append("The requested URL is not among the retrieved sources.")
    if not report.proposal_title or report.proposal_title == request.proposal_id:
        problems.append("No retrieved title in the report.")
    if not report.proposal_summary:
        problems.append("Analyst produced no stated-purpose summary from the proposal text.")
    return problems


def main() -> None:
    if not local_mode_enabled():
        raise RuntimeError("Set DAOTHINK_LOCAL=1 in your .env file.")

    request = build_request()
    outcome = {"code": 1}
    client = Agent(
        name="daothink-local-test-client",
        seed=seed_from_env("TEST_CLIENT_SEED"),
        port=TEST_CLIENT_PORT,
        endpoint=[f"http://127.0.0.1:{TEST_CLIENT_PORT}/submit"],
        resolve=local_resolver(),
        mailbox=False,
    )
    destination = address_from_seed(seed_from_env("ORCHESTRATOR_SEED"))

    @client.on_event("startup")
    async def send_proposal(ctx: Context) -> None:
        try:
            ctx.logger.info("Sending proposal %s (%s)", request.proposal_id, request.proposal_url)
            report, status = await ctx.send_and_receive(
                destination, request, response_type=DecisionReport, timeout=120,
            )
            ctx.logger.info("Delivery status: %s; detail: %s", status.status, status.detail)
            if report is None:
                ctx.logger.error("No DecisionReport received.")
                return
            print("\n" + format_report(report) + "\n", flush=True)
            problems = check_report(request, report)
            for problem in problems:
                ctx.logger.error("E2E check failed: %s", problem)
            if not problems:
                ctx.logger.info("E2E check passed: real report for the requested proposal.")
                outcome["code"] = 0
        finally:
            # Stop the client once the single request is done.
            asyncio.get_running_loop().call_later(0.5, lambda: os._exit(outcome["code"]))

    client.run()
    sys.exit(outcome["code"])


if __name__ == "__main__":
    main()
