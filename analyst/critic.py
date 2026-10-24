from typing import Optional


def critique_evidence(
    research_findings: list[str],
    source_urls: list[str],
    alternatives: list[str],
    content_retrieved: Optional[bool] = None,
    injection_detected: bool = False,
) -> dict:
    """Check whether the evidence can support a human review.

    ``content_retrieved`` is None for callers that predate structured research
    results; False means the proposal body itself was not retrieved.
    """
    findings = [
        item.strip()
        for item in research_findings
        if item.strip()
    ]
    sources = [
        url.strip()
        for url in source_urls
        if url.strip()
    ]
    options = [
        item.strip()
        for item in alternatives
        if item.strip()
    ]

    issues = []
    evidence_gaps = []

    if not findings:
        evidence_gaps.append("No research findings were supplied.")

    if not sources:
        evidence_gaps.append("No source links were supplied.")

    if content_retrieved is False:
        evidence_gaps.append(
            "The proposal body was not retrieved, so its claims could not be analyzed."
        )

    if findings and not sources:
        issues.append(
            "Claims cannot currently be traced to supporting sources."
        )

    if not options:
        evidence_gaps.append(
            "No alternatives were supplied, including the option "
            "of taking no action."
        )

    if injection_detected:
        issues.append(
            "The retrieved text contains instructions aimed at AI systems. They were "
            "treated as data and not followed; review the source for manipulation."
        )

    issues.extend([
        "Statements labelled 'Proposal says' are the proposer's claims, not "
        "independently verified facts.",
        "Verify material claims against their original sources.",
        "Check whether expected benefits are facts or assumptions.",
        "Check implementation dependencies and conflicts of interest.",
        "Vote totals reflect voting power, not proposal quality.",
    ])

    return {
        "critic_findings": issues,
        "evidence_gaps": evidence_gaps,
        "review_status": (
            "needs_more_evidence"
            if evidence_gaps
            else "ready_for_human_review"
        ),
    }
