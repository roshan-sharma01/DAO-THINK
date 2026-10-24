import asyncio
import os
import unittest
from uuid import uuid4
from unittest.mock import AsyncMock, Mock, patch

from orchestrator.agent import (
    ANALYSIS_TIMEOUT_SECONDS,
    RESEARCH_TIMEOUT_SECONDS,
    analyze_proposal,
    handle_chat_message,
)
from orchestrator.report import build_decision_report
from uagents_core.contrib.protocols.chat import ChatMessage
from shared.models import (
    AnalysisRequest,
    AnalysisResult,
    DAOAnalysisRequest,
    ResearchRequest,
    ResearchResult,
)


class MockPeerContext:
    def __init__(self, responses=()):
        self.logger = Mock()
        self.send_and_receive = AsyncMock(side_effect=responses)
        self.send = AsyncMock()


def proposal_request(**overrides) -> DAOAnalysisRequest:
    values = {
        "proposal_id": "proposal-1",
        "proposal_title": "Example proposal",
        "proposal_url": "https://example.com/proposal",
        "requested_amount": 25000,
        "treasury_balance": 100000,
    }
    values.update(overrides)
    return DAOAnalysisRequest(**values)


def research_result(**overrides) -> ResearchResult:
    values = {
        "proposal_id": "proposal-1",
        "summary": "Research summary.",
        "findings": ["Research finding."],
        "source_urls": ["https://example.com/proposal"],
        "limitations": [],
    }
    values.update(overrides)
    return ResearchResult(**values)


def analysis_result(**overrides) -> AnalysisResult:
    values = {
        "proposal_id": "proposal-1",
        "recommendation": "Consider for approval.",
        "strategy_assessment": "Aligned with the stated goals.",
        "financial_assessment": "Within the supplied budget.",
        "alternatives_assessment": "Alternatives need review.",
        "critic_findings": [],
        "risk_findings": ["Execution risk."],
        "evidence_gaps": [],
        "review_status": "ready_for_human_review",
    }
    values.update(overrides)
    return AnalysisResult(**values)


class OrchestrationTests(unittest.TestCase):
    def setUp(self) -> None:
        self.configured_peers = {
            "RESEARCH_AGENT_ADDRESS": "research-test-address",
            "ANALYSIS_AGENT_ADDRESS": "analysis-test-address",
            # Keep tests hermetic: ignore DAOTHINK_LOCAL=1 from a developer's .env.
            "DAOTHINK_LOCAL": "0",
        }

    def run_analysis(self, context, **environment_overrides):
        environment = {**self.configured_peers, **environment_overrides}
        with patch.dict(os.environ, environment):
            return asyncio.run(analyze_proposal(context, proposal_request()))

    def test_configured_peers_produce_a_human_review_report(self) -> None:
        context = MockPeerContext(
            [
                (research_result(), None),
                (analysis_result(), None),
            ]
        )

        report = self.run_analysis(context)

        self.assertEqual(report.status, "READY_FOR_HUMAN_REVIEW")
        self.assertEqual(report.research_findings, ["Research finding."])
        self.assertEqual(context.send_and_receive.await_count, 2)
        first_call, second_call = context.send_and_receive.await_args_list
        self.assertEqual(first_call.args[0], self.configured_peers["RESEARCH_AGENT_ADDRESS"])
        self.assertIsInstance(first_call.args[1], ResearchRequest)
        self.assertIsInstance(second_call.args[1], AnalysisRequest)
        self.assertEqual(first_call.kwargs["timeout"], RESEARCH_TIMEOUT_SECONDS)
        self.assertEqual(second_call.kwargs["timeout"], ANALYSIS_TIMEOUT_SECONDS)

    def test_missing_peer_addresses_produce_evidence_gaps(self) -> None:
        context = MockPeerContext()

        report = self.run_analysis(
            context,
            RESEARCH_AGENT_ADDRESS=" ",
            ANALYSIS_AGENT_ADDRESS="",
            # Hosted mode falls back to seed-derived addresses; clear those too.
            RESEARCH_AGENT_SEED="",
            ANALYSIS_AGENT_SEED="",
        )

        self.assertEqual(report.status, "MORE_EVIDENCE_REQUIRED")
        self.assertTrue(any("Research agent" in gap for gap in report.evidence_gaps))
        self.assertTrue(any("Analysis agent" in gap for gap in report.evidence_gaps))
        self.assertIn("No recommendation", report.recommendation)
        context.send_and_receive.assert_not_awaited()

    def test_missing_financial_inputs_still_run_analysis_without_inventing_figures(self) -> None:
        # Real proposals rarely come with a treasury balance; analysis must still
        # run on the evidence, and the missing figures must stay missing (None).
        context = MockPeerContext([(research_result(), None), (analysis_result(), None)])
        request = proposal_request(requested_amount=None, treasury_balance=None)

        with patch.dict(os.environ, self.configured_peers):
            asyncio.run(analyze_proposal(context, request))

        self.assertEqual(context.send_and_receive.await_count, 2)
        sent = context.send_and_receive.await_args_list[1].args[1]
        self.assertIsInstance(sent, AnalysisRequest)
        self.assertIsNone(sent.requested_amount)
        self.assertIsNone(sent.treasury_balance)

    def test_research_peer_timeout_is_reported(self) -> None:
        context = MockPeerContext(
            [
                asyncio.TimeoutError(),
                (analysis_result(), None),
            ]
        )

        report = self.run_analysis(context)

        self.assertEqual(report.status, "MORE_EVIDENCE_REQUIRED")
        self.assertIn("Research agent request timed out.", report.evidence_gaps)

    def test_analysis_peer_timeout_is_reported(self) -> None:
        context = MockPeerContext(
            [
                (research_result(), None),
                asyncio.TimeoutError(),
            ]
        )

        report = self.run_analysis(context)

        self.assertEqual(report.status, "MORE_EVIDENCE_REQUIRED")
        self.assertIn("Analysis agent request timed out.", report.evidence_gaps)
        self.assertIn("No recommendation", report.recommendation)

    def test_invalid_research_response_is_reported(self) -> None:
        context = MockPeerContext(
            [
                ("not a research result", None),
                (analysis_result(), None),
            ]
        )

        report = self.run_analysis(context)

        self.assertEqual(report.status, "MORE_EVIDENCE_REQUIRED")
        self.assertIn(
            "Research agent did not return a valid result.",
            report.evidence_gaps,
        )

    def test_invalid_analysis_response_is_reported(self) -> None:
        context = MockPeerContext(
            [
                (research_result(), None),
                ("not an analysis result", None),
            ]
        )

        report = self.run_analysis(context)

        self.assertEqual(report.status, "MORE_EVIDENCE_REQUIRED")
        self.assertIn(
            "Analysis agent did not return a valid result.",
            report.evidence_gaps,
        )

    def test_mismatched_research_id_is_reported(self) -> None:
        context = MockPeerContext(
            [
                (research_result(proposal_id="different-proposal"), None),
                (analysis_result(), None),
            ]
        )

        report = self.run_analysis(context)

        self.assertEqual(report.status, "MORE_EVIDENCE_REQUIRED")
        self.assertIn(
            "Research agent returned a mismatched proposal ID.",
            report.evidence_gaps,
        )

    def test_mismatched_analysis_id_is_reported(self) -> None:
        context = MockPeerContext(
            [
                (research_result(), None),
                (analysis_result(proposal_id="different-proposal"), None),
            ]
        )

        report = self.run_analysis(context)

        self.assertEqual(report.status, "MORE_EVIDENCE_REQUIRED")
        self.assertIn(
            "Analysis agent returned a mismatched proposal ID.",
            report.evidence_gaps,
        )

    def test_non_timeout_research_failure_does_not_abort_workflow(self) -> None:
        context = MockPeerContext(
            [
                RuntimeError("peer unavailable"),
                (analysis_result(), None),
            ]
        )

        report = self.run_analysis(context)

        self.assertEqual(report.status, "MORE_EVIDENCE_REQUIRED")
        self.assertIn("Research agent request failed (RuntimeError).", report.evidence_gaps)
        context.logger.warning.assert_called()

    def test_analysis_failure_does_not_abort_workflow(self) -> None:
        context = MockPeerContext(
            [
                (research_result(), None),
                RuntimeError("peer unavailable"),
            ]
        )

        report = self.run_analysis(context)

        self.assertEqual(report.status, "MORE_EVIDENCE_REQUIRED")
        self.assertIn(
            "Analysis agent request failed (RuntimeError).",
            report.evidence_gaps,
        )
        self.assertIn("No recommendation", report.recommendation)

    def test_invalid_chat_json_returns_validation_guidance(self) -> None:
        context = MockPeerContext()
        message = Mock(spec=ChatMessage)
        message.msg_id = uuid4()
        message.text.return_value = "{invalid"

        asyncio.run(handle_chat_message(context, "chat-user", message))

        context.send.assert_awaited()
        response = context.send.await_args_list[-1].args[1]
        self.assertIn("Input error:", response.text())

    def test_valid_peer_responses_are_logged(self) -> None:
        context = MockPeerContext(
            [
                (research_result(), None),
                (analysis_result(), None),
            ]
        )

        self.run_analysis(context)

        logged = " ".join(
            str(call.args[0]) for call in context.logger.info.call_args_list
        )
        self.assertIn("Research agent returned a valid result for proposal-1", logged)
        self.assertIn("Analysis agent returned a valid result for proposal-1", logged)

    def test_final_reply_log_does_not_claim_delivery(self) -> None:
        context = MockPeerContext()
        report = build_decision_report(
            "Example proposal", research_result(), analysis_result()
        )
        message = Mock(spec=ChatMessage)
        message.msg_id = uuid4()
        message.text.return_value = (
            '{"proposal_id": "proposal-1", "proposal_title": "Example proposal", '
            '"proposal_url": "https://example.com/proposal"}'
        )

        with patch("orchestrator.agent.analyze_proposal", AsyncMock(return_value=report)):
            asyncio.run(handle_chat_message(context, "chat-user", message))

        logged = " ".join(
            str(call.args[0]) for call in context.logger.info.call_args_list
        )
        self.assertIn("Final report handed to the chat layer for proposal-1", logged)
        self.assertIn("not confirmed", logged)

    def test_chat_receipt_is_logged_without_the_message_text(self) -> None:
        context = MockPeerContext()
        report = build_decision_report(
            "Example proposal", research_result(), analysis_result()
        )
        message = Mock(spec=ChatMessage)
        message.msg_id = uuid4()
        message_text = (
            '{"proposal_id": "proposal-1", "proposal_title": "Example proposal", '
            '"proposal_url": "https://example.com/proposal"}'
        )
        message.text.return_value = message_text

        with patch("orchestrator.agent.analyze_proposal", AsyncMock(return_value=report)):
            asyncio.run(handle_chat_message(context, "chat-user", message))

        calls = context.logger.info.call_args_list
        receipts = [
            call for call in calls if "Received chat message" in str(call.args[0])
        ]
        self.assertEqual(len(receipts), 1)
        parsed = [
            call for call in calls if "Chat request parsed for proposal" in str(call.args[0])
        ]
        self.assertEqual(len(parsed), 1)
        # The validated proposal ID is the metadata that gets logged.
        self.assertEqual(parsed[0].args[1], "proposal-1")
        # No log record may contain the raw message text.
        self.assertNotIn(message_text, " ".join(str(call) for call in calls))

    def test_chat_json_input_still_dispatches_a_proposal(self) -> None:
        context = MockPeerContext()
        report = build_decision_report(
            "Example proposal", research_result(), analysis_result()
        )
        message = Mock(spec=ChatMessage)
        message.msg_id = uuid4()
        message.text.return_value = (
            '{"proposal_id": "proposal-1", "proposal_title": "Example proposal", '
            '"proposal_url": "https://example.com/proposal", '
            '"requested_amount": 25000, "treasury_balance": 100000}'
        )
        analyze = AsyncMock(return_value=report)

        with patch("orchestrator.agent.analyze_proposal", analyze):
            asyncio.run(handle_chat_message(context, "chat-user", message))

        analyze.assert_awaited_once()
        submitted_request = analyze.await_args.args[1]
        self.assertIsInstance(submitted_request, DAOAnalysisRequest)
        self.assertEqual(submitted_request.proposal_id, "proposal-1")
        self.assertIsInstance(context.send.await_args_list[-1].args[1], ChatMessage)


if __name__ == "__main__":
    unittest.main()
