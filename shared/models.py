"""Canonical wire models shared by every DAOThink agent.

This file is the single source of truth for message schemas. Never redefine
these classes inside an individual agent: uAgents matches messages by schema
digest, so a copy that drifts by one field silently stops interoperating.

Fields added after the first release all have defaults, so a peer that only
sets the original fields still produces a valid message.
"""

from typing import List, Optional

from uagents import Model


class DAOAnalysisRequest(Model):
    proposal_id: str
    proposal_url: str
    # Optional: when omitted, the title retrieved from the source is used.
    # When supplied, it is compared against the retrieved title.
    proposal_title: str = ""
    # Optional caller-supplied figures. They are never inferred or invented.
    requested_amount: Optional[float] = None
    treasury_balance: Optional[float] = None


class ResearchRequest(Model):
    proposal_id: str
    proposal_title: str
    proposal_url: str
    research_questions: List[str] = []
    source_urls: List[str] = []


class ResearchResult(Model):
    proposal_id: str
    summary: str
    findings: List[str]
    source_urls: List[str]
    limitations: List[str]
    # How the proposal itself was retrieved: "snapshot_graphql", "html_page",
    # or "" when the proposal content could not be retrieved.
    retrieval_method: str = ""
    retrieved_at: str = ""
    # Title and body exactly as returned by the source (untrusted data).
    retrieved_title: str = ""
    proposal_text: str = ""
    # Structured facts read from the source of record (e.g. Snapshot API),
    # each prefixed with where it came from.
    proposal_facts: List[str] = []
    # True only when the actual proposal body was retrieved, not an app shell.
    proposal_content_retrieved: bool = False
    # Non-blocking uncertainty notes. `limitations` are blocking evidence gaps.
    caveats: List[str] = []


class AnalysisRequest(Model):
    proposal_id: str
    proposal_title: str
    research_findings: List[str]
    source_urls: List[str]
    alternatives: List[str]
    requested_amount: Optional[float] = None
    treasury_balance: Optional[float] = None
    evidence_gaps: List[str] = []
    proposal_text: str = ""
    proposal_facts: List[str] = []
    proposal_content_retrieved: bool = False
    caveats: List[str] = []


class AnalysisResult(Model):
    proposal_id: str
    recommendation: str
    strategy_assessment: str
    financial_assessment: str
    alternatives_assessment: str
    critic_findings: List[str]
    risk_findings: List[str]
    evidence_gaps: List[str]
    review_status: str
    proposal_summary: str = ""
    claimed_benefits: List[str] = []
    dependencies: List[str] = []
    stated_amounts: List[str] = []
    assumptions: List[str] = []
    caveats: List[str] = []


class DecisionReport(Model):
    proposal_id: str
    proposal_title: str
    research_summary: str
    research_findings: List[str]
    recommendation: str
    strategy_assessment: str
    financial_assessment: str
    alternatives_assessment: str
    critic_findings: List[str]
    risk_findings: List[str]
    evidence_gaps: List[str]
    source_urls: List[str]
    status: str
    requested_title: str = ""
    retrieval_method: str = ""
    retrieved_at: str = ""
    proposal_summary: str = ""
    proposal_facts: List[str] = []
    claimed_benefits: List[str] = []
    dependencies: List[str] = []
    stated_amounts: List[str] = []
    assumptions: List[str] = []
    caveats: List[str] = []
