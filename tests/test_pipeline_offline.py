"""In-process pipeline test with mocked HTTP only.

Runs the REAL Research handler logic, REAL Analyst logic and REAL Orchestrator
coordination, with agent messaging replaced by direct calls. This proves the
Analyst receives the actual research output and the report describes the
requested proposal. It does NOT prove live uAgents delivery (see README).
"""

import asyncio
import os
import socket
import unittest
from unittest.mock import AsyncMock, Mock, patch

import requests

from analyst.agent import build_analysis_result
from orchestrator.agent import analyze_proposal, parse_chat_request
from orchestrator.report import format_report
from research_agent import research_tools as rt
from research_agent.research_agent import build_research_result
from shared.models import AnalysisRequest, DAOAnalysisRequest, ResearchRequest
from tests.fixtures import (
    BODY, PROPOSAL_ID, PROPOSAL_URL, TITLE, graphql_body, snapshot_proposal,
)


class FakeResponse:
    def __init__(self, body, status_code=200):
        self.status_code = status_code
        self.headers = {"Content-Type": "application/json"}
        self._body = body

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def raise_for_status(self):
        if self.status_code >= 400:
            raise requests.HTTPError(str(self.status_code))

    def iter_content(self, chunk_size=8192):
        yield self._body


class RoutingContext:
    """Delivers each request to the real handler logic of the target agent."""

    def __init__(self):
        self.logger = Mock()
        self.send = AsyncMock()
        self.seen = []

    async def send_and_receive(self, address, message, response_type, timeout):
        self.seen.append(message)
        if isinstance(message, ResearchRequest):
            return await build_research_result(message), None
        if isinstance(message, AnalysisRequest):
            return build_analysis_result(message), None
        raise AssertionError(f"Unexpected message {type(message).__name__}")


class PipelineTests(unittest.TestCase):
    def setUp(self):
        env = {"DAOTHINK_LOCAL": "0", "RESEARCH_AGENT_ADDRESS": "research",
               "ANALYSIS_AGENT_ADDRESS": "analysis"}
        patches = [
            patch.dict(os.environ, env),
            patch.object(rt.socket, "getaddrinfo", lambda h, p: [
                (socket.AF_INET, socket.SOCK_STREAM, 6, "", ("93.184.216.34", 443))]),
            patch.object(rt.requests, "get", side_effect=AssertionError("no GET expected")),
        ]
        for p in patches:
            p.start()
            self.addCleanup(p.stop)

    def run_pipeline(self, request, proposal=None):
        body = graphql_body(proposal if proposal is not None else snapshot_proposal())
        context = RoutingContext()
        with patch.object(rt.requests, "post", lambda url, **k: FakeResponse(body)):
            report = asyncio.run(analyze_proposal(context, request))
        return report, context

    def test_real_proposal_flows_through_every_agent(self):
        request = DAOAnalysisRequest(proposal_id=PROPOSAL_ID, proposal_url=PROPOSAL_URL)

        report, context = self.run_pipeline(request)

        research_req, analysis_req = context.seen
        self.assertEqual(research_req.proposal_id, PROPOSAL_ID)
        # The Analyst received the actual retrieved text, not demo facts.
        self.assertEqual(analysis_req.proposal_text, BODY.strip())
        self.assertEqual(analysis_req.proposal_title, TITLE)
        self.assertTrue(analysis_req.proposal_content_retrieved)
        self.assertEqual(report.proposal_id, PROPOSAL_ID)
        self.assertEqual(report.proposal_title, TITLE)
        self.assertEqual(report.retrieval_method, "snapshot_graphql")
        self.assertEqual(report.source_urls, [PROPOSAL_URL])
        self.assertIn("security audit program", report.proposal_summary)
        self.assertTrue(report.claimed_benefits and report.dependencies and report.stated_amounts)
        self.assertTrue(any("quorum not configured" in f for f in report.proposal_facts))
        # Amounts are stated but no treasury figures were supplied: honest gap.
        self.assertEqual(report.status, "MORE_EVIDENCE_REQUIRED")
        text = format_report(report)
        self.assertIn("not a vote or approval", text)
        self.assertIn("## Benefits claimed by the proposal", text)

    def test_ready_for_review_when_evidence_and_figures_are_complete(self):
        request = DAOAnalysisRequest(
            proposal_id=PROPOSAL_ID, proposal_url=PROPOSAL_URL,
            requested_amount=290000, treasury_balance=10_000_000,
        )
        report, _ = self.run_pipeline(request)

        self.assertEqual(report.evidence_gaps, [])
        self.assertEqual(report.status, "READY_FOR_HUMAN_REVIEW")
        self.assertEqual(report.recommendation, "HUMAN_REVIEW_REQUIRED")
        self.assertTrue(report.caveats)  # quorum + vote-total caveats remain visible

    def test_title_mismatch_is_flagged(self):
        request = DAOAnalysisRequest(
            proposal_id=PROPOSAL_ID, proposal_url=PROPOSAL_URL,
            proposal_title="URC-5: Token Venue Policy",
        )
        report, _ = self.run_pipeline(request)

        self.assertEqual(report.status, "MORE_EVIDENCE_REQUIRED")
        self.assertEqual(report.proposal_title, TITLE)
        self.assertEqual(report.requested_title, "URC-5: Token Venue Policy")
        self.assertTrue(any("does not match the retrieved title" in g for g in report.evidence_gaps))

    def test_missing_proposal_produces_gaps_not_findings(self):
        request = DAOAnalysisRequest(proposal_id=PROPOSAL_ID, proposal_url=PROPOSAL_URL)
        body = b'{"data": {"proposal": null}}'
        context = RoutingContext()
        with patch.object(rt.requests, "post", lambda url, **k: FakeResponse(body)):
            report = asyncio.run(analyze_proposal(context, request))

        self.assertEqual(report.status, "MORE_EVIDENCE_REQUIRED")
        self.assertEqual(report.recommendation, "DEFER_PENDING_EVIDENCE")
        self.assertEqual(report.retrieval_method, "")
        self.assertEqual(report.source_urls, [])
        self.assertEqual(report.claimed_benefits, [])
        self.assertTrue(any("not found" in g for g in report.evidence_gaps))

    def test_chat_plain_text_snapshot_link(self):
        request = parse_chat_request(f"Please review {PROPOSAL_URL} thanks")
        self.assertEqual(request.proposal_id, PROPOSAL_ID)
        self.assertEqual(request.proposal_url, PROPOSAL_URL)

        report, _ = self.run_pipeline(request)
        self.assertEqual(report.proposal_title, TITLE)


if __name__ == "__main__":
    unittest.main()
