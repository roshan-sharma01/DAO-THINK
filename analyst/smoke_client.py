"""Local smoke-test client for the canonical Analyst Agent contract.

Prefer tests/send_local_request.py for the complete Research -> Analyst ->
Orchestrator workflow. This script sends one direct AnalysisRequest.
"""
import os
from dotenv import load_dotenv
from uagents import Agent, Context
from shared.models import AnalysisRequest, AnalysisResult
from local_config import local_mode_enabled, local_resolver, seed_from_env, peer_address

load_dotenv()


def main() -> None:
    seed = seed_from_env("TEST_CLIENT_SEED")
    local = local_mode_enabled()
    kwargs = {
        "name": "daothink-analyst-smoke-test-client",
        "seed": seed,
        "port": 8003 if local else int(os.getenv("TEST_CLIENT_PORT", "8003")),
        "mailbox": False if local else os.getenv("MAILBOX_ENABLED", "true").lower() == "true",
    }
    if local:
        kwargs["endpoint"] = ["http://127.0.0.1:8003/submit"]
        kwargs["resolve"] = local_resolver()
    client = Agent(**kwargs)
    target = peer_address("ANALYSIS_AGENT_ADDRESS", "ANALYSIS_AGENT_SEED")

    @client.on_event("startup")
    async def send_request(ctx: Context):
        request = AnalysisRequest(
            proposal_id="daoaction-analyst-smoke-test",
            proposal_title="[FICTIONAL TEST] DAO protocol integration",
            requested_amount=1.0,
            treasury_balance=100.0,
            research_findings=["Fictional smoke-test evidence only."],
            source_urls=[],
            alternatives=["Approve a pilot", "Take no action"],
            evidence_gaps=["This is a fictional smoke test."],
        )
        response, status = await ctx.send_and_receive(
            target, request, response_type=AnalysisResult, timeout=20
        )
        ctx.logger.info("Delivery status: %s (%s)", status.status, status.detail)
        ctx.logger.info("Received AnalysisResult: %s", response.proposal_id)

    client.run()


if __name__ == "__main__":
    main()
