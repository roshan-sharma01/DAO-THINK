"""DAOThink Analyst Agent using the root shared wire models."""

import os
from dotenv import load_dotenv
from uagents import Agent, Context

from shared.models import AnalysisRequest, AnalysisResult
from analyst.strategy import analyze_strategy
from local_config import ANALYSIS_PORT, local_mode_enabled, local_resolver, seed_from_env

load_dotenv()

ANALYST_ASSUMPTIONS = [
    "Statements were classified by keyword matching; some may be missed or misclassified.",
    "Amounts are quoted exactly as written; tokens were not converted or priced.",
    "No claim in the proposal was independently verified by the Analyst.",
    "The recommendation is decision support for a human reviewer, never an approval or vote.",
]


def build_analysis_result(msg: AnalysisRequest) -> AnalysisResult:
    """Pure analysis step: deterministic and traceable to the request contents."""
    try:
        if msg.requested_amount is not None and msg.requested_amount < 0:
            raise ValueError("Requested amount cannot be negative.")
        if msg.treasury_balance is not None and msg.treasury_balance <= 0:
            raise ValueError("Treasury balance must be greater than zero.")

        strategy = analyze_strategy(
            proposal_title=msg.proposal_title,
            requested_amount=msg.requested_amount,
            treasury_balance=msg.treasury_balance,
            research_findings=msg.research_findings,
            source_urls=msg.source_urls,
            alternatives=msg.alternatives,
            proposal_text=msg.proposal_text,
            content_retrieved=msg.proposal_content_retrieved,
        )
    except (ValueError, TypeError, KeyError, IndexError) as exc:
        return AnalysisResult(
            proposal_id=msg.proposal_id,
            recommendation="HUMAN_REVIEW_REQUIRED",
            strategy_assessment="Analysis could not be completed.",
            financial_assessment="Input validation or analysis failed.",
            alternatives_assessment="Not assessed.",
            critic_findings=["The request could not be fully analyzed."],
            risk_findings=[str(exc)],
            evidence_gaps=["Correct the input and retry."],
            review_status="invalid_request",
        )

    risk = strategy["treasury_risk"]
    critique = strategy["critique"]
    evidence = strategy["evidence"] or {}
    stated_amounts = evidence.get("stated_amounts", [])
    figures_missing = msg.requested_amount is None or msg.treasury_balance is None

    gaps = [gap for gap in msg.evidence_gaps if gap.strip()] + critique["evidence_gaps"]
    financial_parts = list(risk["risk_findings"])
    if figures_missing and stated_amounts:
        gaps.append(
            "The proposal states amounts, but requested_amount and treasury_balance "
            "were not supplied, so treasury exposure could not be assessed."
        )
        financial_parts.append(
            f"The proposal text contains {len(stated_amounts)} statement(s) with "
            "amounts (listed under stated amounts)."
        )
    elif figures_missing and evidence:
        financial_parts.append(
            "No funding amounts were found in the proposal text; financial exposure "
            "may not apply, but this was not verified."
        )

    risk_findings = list(evidence.get("risk_statements", []))
    treasury_statements = evidence.get("treasury_statements", [])
    if treasury_statements:
        risk_findings.append(
            f"Potential treasury exposure: {len(treasury_statements)} statement(s) describe "
            "funding, payments or transfers (see stated amounts)."
        )
    if evidence.get("injection_detected"):
        risk_findings.append(
            "Possible prompt-injection text in the proposal (treated as data, not followed)."
        )
    risk_findings += risk["risk_findings"]

    alternatives = [a for a in msg.alternatives if a.strip()]
    alternatives_assessment = (
        "Options for the human reviewer (not ranked by the Analyst): "
        + "; ".join(alternatives)
        + ". 'Take no action' is the baseline for comparison."
        if alternatives else "No alternatives were supplied."
    )

    evidence_gaps = list(dict.fromkeys(gaps))
    recommendation = strategy["recommendation"]
    if evidence_gaps and recommendation == "HUMAN_REVIEW_REQUIRED":
        # Keep the recommendation consistent with the gaps (incl. inherited ones).
        recommendation = "DEFER_PENDING_EVIDENCE"
    return AnalysisResult(
        proposal_id=msg.proposal_id,
        recommendation=recommendation,
        strategy_assessment=strategy["strategy_assessment"],
        financial_assessment=" ".join(financial_parts),
        alternatives_assessment=alternatives_assessment,
        critic_findings=critique["critic_findings"],
        risk_findings=list(dict.fromkeys(risk_findings)),
        evidence_gaps=evidence_gaps,
        review_status="needs_more_evidence" if evidence_gaps else critique["review_status"],
        proposal_summary=evidence.get("stated_purpose", ""),
        claimed_benefits=evidence.get("claimed_benefits", []),
        dependencies=evidence.get("dependencies", []),
        stated_amounts=stated_amounts,
        assumptions=list(ANALYST_ASSUMPTIONS),
        caveats=list(dict.fromkeys(c for c in msg.caveats if c.strip())),
    )


def build_agent() -> Agent:
    seed = seed_from_env("ANALYSIS_AGENT_SEED")
    local = local_mode_enabled()
    kwargs = {
        "name": os.getenv("ANALYSIS_AGENT_NAME", "daothink-analysis-agent"),
        "seed": seed,
        # Default to 8002 in every mode so it never collides with the Orchestrator (8000).
        "port": ANALYSIS_PORT if local else int(os.getenv("ANALYSIS_AGENT_PORT", str(ANALYSIS_PORT))),
        "mailbox": False if local else os.getenv("MAILBOX_ENABLED", "true").strip().lower() == "true",
    }
    if local:
        kwargs["endpoint"] = [f"http://127.0.0.1:{ANALYSIS_PORT}/submit"]
        kwargs["resolve"] = local_resolver()
    else:
        endpoint = os.getenv("ANALYSIS_AGENT_ENDPOINT", "").strip()
        if endpoint:
            kwargs["endpoint"] = [endpoint]

    agent = Agent(**kwargs)

    @agent.on_event("startup")
    async def startup(ctx: Context):
        ctx.logger.info("DAOThink Analyst Agent is online.")
        ctx.logger.info("Agent address: %s", agent.address)
        ctx.logger.info("Local mode: %s", local)

    @agent.on_message(model=AnalysisRequest, replies={AnalysisResult})
    async def handle_analysis(ctx: Context, sender: str, msg: AnalysisRequest):
        ctx.logger.info("Received analysis request for proposal %s from %s", msg.proposal_id, sender)
        result = build_analysis_result(msg)
        if result.review_status == "invalid_request":
            ctx.logger.warning("Analysis input was invalid for %s", msg.proposal_id)
        await ctx.send(sender, result)
        ctx.logger.info("Sent AnalysisResult for %s", msg.proposal_id)

    return agent


if __name__ == "__main__":
    build_agent().run()
