from typing import Optional

from analyst.risk import assess_risk
from analyst.critic import critique_evidence
from analyst.evidence import extract_evidence


def analyze_strategy(
    proposal_title: str,
    requested_amount: Optional[float],
    treasury_balance: Optional[float],
    research_findings: list[str],
    source_urls: list[str],
    alternatives: list[str],
    proposal_text: str = "",
    content_retrieved: Optional[bool] = None,
) -> dict:
    """Evidence-grounded, conservative assessment. Never recommends approval."""
    if not proposal_title.strip():
        raise ValueError("Proposal title cannot be empty.")

    risk = assess_risk(
        requested_amount=requested_amount,
        treasury_balance=treasury_balance,
    )
    evidence = extract_evidence(proposal_text) if proposal_text else None

    critique = critique_evidence(
        research_findings=research_findings,
        source_urls=source_urls,
        alternatives=alternatives,
        content_retrieved=content_retrieved,
        injection_detected=bool(evidence and evidence["injection_detected"]),
    )

    if evidence and evidence["sentence_count"]:
        assessment = (
            f"Analyzed {evidence['sentence_count']} statement(s) from the retrieved "
            f"proposal text: {len(evidence['claimed_benefits'])} benefit claim(s), "
            f"{len(evidence['risk_statements'])} risk statement(s), "
            f"{len(evidence['dependencies'])} dependency statement(s) and "
            f"{len(evidence['stated_amounts'])} statement(s) with amounts were found. "
            "These are the proposer's claims; their accuracy, feasibility and "
            "alignment with the DAO's goals require human judgement."
        )
    elif research_findings:
        assessment = (
            f"Received {len(research_findings)} research finding(s) but no proposal "
            "text to analyze. Benefits, costs, feasibility, and alternatives need "
            "to be evaluated against the supplied evidence."
        )
    else:
        assessment = (
            "Insufficient evidence to evaluate strategic value."
        )

    if critique["evidence_gaps"]:
        recommendation = "DEFER_PENDING_EVIDENCE"
    elif risk["risk_level"] in {"critical", "high"} or (
        evidence and evidence["injection_detected"]
    ):
        recommendation = "ESCALATE_FOR_REVIEW"
    else:
        recommendation = "HUMAN_REVIEW_REQUIRED"

    return {
        "proposal_title": proposal_title,
        "strategy_assessment": assessment,
        "treasury_risk": risk,
        "critique": critique,
        "evidence": evidence,
        "recommendation": recommendation,
    }
