from typing import Optional

from shared.models import AnalysisResult, DecisionReport, ResearchResult

READY = "READY_FOR_HUMAN_REVIEW"
MORE_EVIDENCE = "MORE_EVIDENCE_REQUIRED"


def build_decision_report(
    proposal_title: str,
    research: ResearchResult,
    analysis: AnalysisResult,
    requested_title: str = "",
    extra_gaps: Optional[list[str]] = None,
) -> DecisionReport:
    evidence_gaps = list(analysis.evidence_gaps)
    evidence_gaps.extend(
        limitation for limitation in research.limitations if limitation not in evidence_gaps
    )
    for gap in extra_gaps or []:
        if gap not in evidence_gaps:
            evidence_gaps.append(gap)
    if analysis.proposal_id != research.proposal_id:
        evidence_gaps.append("Analysis result proposal ID does not match the research result.")
    if not research.findings and "Research agent returned no findings." not in evidence_gaps:
        evidence_gaps.append("Research agent returned no findings.")
    if (
        not research.source_urls
        and "Research agent returned no source URLs." not in evidence_gaps
    ):
        evidence_gaps.append("Research agent returned no source URLs.")
    if not analysis.recommendation.strip():
        evidence_gaps.append("Analysis agent returned no recommendation.")
    for name, assessment in (
        ("strategy", analysis.strategy_assessment),
        ("financial", analysis.financial_assessment),
        ("alternatives", analysis.alternatives_assessment),
    ):
        if not assessment.strip():
            evidence_gaps.append(f"Analysis agent returned no {name} assessment.")
    # READY_FOR_HUMAN_REVIEW still means a person must decide; it is never approval.
    status = (
        MORE_EVIDENCE
        if evidence_gaps or analysis.review_status != "ready_for_human_review"
        else READY
    )
    caveats = list(dict.fromkeys(list(research.caveats) + list(analysis.caveats)))

    return DecisionReport(
        proposal_id=research.proposal_id,
        proposal_title=proposal_title,
        research_summary=research.summary,
        research_findings=research.findings,
        recommendation=analysis.recommendation,
        strategy_assessment=analysis.strategy_assessment,
        financial_assessment=analysis.financial_assessment,
        alternatives_assessment=analysis.alternatives_assessment,
        critic_findings=analysis.critic_findings,
        risk_findings=analysis.risk_findings,
        evidence_gaps=evidence_gaps,
        source_urls=research.source_urls,
        status=status,
        requested_title=requested_title,
        retrieval_method=research.retrieval_method,
        retrieved_at=research.retrieved_at,
        proposal_summary=analysis.proposal_summary,
        proposal_facts=research.proposal_facts,
        claimed_benefits=analysis.claimed_benefits,
        dependencies=analysis.dependencies,
        stated_amounts=analysis.stated_amounts,
        assumptions=analysis.assumptions,
        caveats=caveats,
    )


def format_report(report: DecisionReport) -> str:
    def format_list(items: list[str]) -> str:
        return "\n".join(f"- {item}" for item in items) if items else "- None reported"

    retrieval = (
        f"{report.retrieval_method} at {report.retrieved_at}"
        if report.retrieval_method else "proposal content was not retrieved"
    )
    lines = [
        f"# DAO proposal review: {report.proposal_title}",
        f"**Proposal ID:** {report.proposal_id}",
        f"**Status:** {report.status}",
        "**Human review:** Required; this report is decision support, not a vote or approval.",
        f"**Recommendation:** {report.recommendation}",
        f"**Retrieval:** {retrieval}",
    ]
    if report.requested_title and report.requested_title != report.proposal_title:
        lines.append(f"**Requested title:** {report.requested_title}")
    lines += [
        "",
        "## Stated purpose (from the proposal text, not independently verified)",
        report.proposal_summary or "- Not available",
        "",
        "## Facts from the source of record",
        format_list(report.proposal_facts),
        "",
        "## Benefits claimed by the proposal",
        format_list(report.claimed_benefits),
        "",
        "## Risks",
        format_list(report.risk_findings),
        "",
        "## Dependencies and implementation steps stated",
        format_list(report.dependencies),
        "",
        "## Amounts stated in the proposal (quoted, not converted)",
        format_list(report.stated_amounts),
        "",
        "## Agent assessments",
        "### Strategy",
        report.strategy_assessment,
        "",
        "### Financial",
        report.financial_assessment,
        "",
        "### Alternatives",
        report.alternatives_assessment,
        "",
        "## Research reported by the Research Agent (not independently verified)",
        report.research_summary,
        format_list(report.research_findings),
        "",
        "## Critic findings",
        format_list(report.critic_findings),
        "",
        "## Uncertainty and evidence gaps",
        format_list(report.evidence_gaps),
        "",
        "## Caveats",
        format_list(report.caveats),
        "",
        "## Analyst assumptions",
        format_list(report.assumptions),
        "",
        "## Source URLs supplied by the Research Agent (not verified)",
        format_list(report.source_urls),
    ]
    return "\n".join(lines)
