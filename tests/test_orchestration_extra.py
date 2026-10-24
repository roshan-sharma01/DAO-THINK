import asyncio
import inspect
import logging
import os
import unittest
from unittest.mock import AsyncMock, Mock, patch
from uuid import uuid4

import analyst.agent as analyst_agent_module
import orchestrator.agent as orchestrator_agent_module
import research_agent.research_agent as research_agent_module
from uagents import Model
from uagents_core.contrib.protocols.chat import ChatMessage, TextContent, chat_protocol_spec

from orchestrator.agent import (
    analyze_proposal, consistency_gaps, handle_chat_message, parse_chat_request,
)
from orchestrator.report import build_decision_report, format_report
from shared.models import AnalysisResult, DAOAnalysisRequest, ResearchResult
from tests.fixtures import PROPOSAL_ID, PROPOSAL_URL, TITLE
from tests import send_local_request


class Ctx:
    def __init__(self, responses=()):
        self.logger = Mock()
        self.send_and_receive = AsyncMock(side_effect=list(responses))
        self.send = AsyncMock()


PEERS = {"DAOTHINK_LOCAL": "0", "RESEARCH_AGENT_ADDRESS": "r", "ANALYSIS_AGENT_ADDRESS": "a"}


def research(**kw):
    values = dict(proposal_id=PROPOSAL_ID, summary="s", findings=["f"],
                  source_urls=[PROPOSAL_URL], limitations=[], retrieved_title=TITLE,
                  retrieval_method="snapshot_graphql", proposal_content_retrieved=True)
    values.update(kw)
    return ResearchResult(**values)


def analysis(**kw):
    values = dict(proposal_id=PROPOSAL_ID, recommendation="HUMAN_REVIEW_REQUIRED",
                  strategy_assessment="x", financial_assessment="y",
                  alternatives_assessment="z", critic_findings=[], risk_findings=[],
                  evidence_gaps=[], review_status="ready_for_human_review")
    values.update(kw)
    return AnalysisResult(**values)


class RequestValidationTests(unittest.TestCase):
    def test_invalid_requests_never_contact_peers(self):
        for req in (
            DAOAnalysisRequest(proposal_id="", proposal_url=PROPOSAL_URL),
            DAOAnalysisRequest(proposal_id="p", proposal_url="http://insecure.example/p"),
            DAOAnalysisRequest(proposal_id="p", proposal_url=""),
            DAOAnalysisRequest(proposal_id="p", proposal_url=PROPOSAL_URL, requested_amount=-5),
        ):
            ctx = Ctx()
            with patch.dict(os.environ, PEERS):
                report = asyncio.run(analyze_proposal(ctx, req))
            ctx.send_and_receive.assert_not_awaited()
            self.assertEqual(report.status, "MORE_EVIDENCE_REQUIRED")
            self.assertTrue(any(g.startswith("Invalid request:") for g in report.evidence_gaps))

    def test_none_response_from_peer_is_a_timeout_gap(self):
        # Real uAgents returns (None, status) when no reply arrives in time.
        ctx = Ctx([(None, Mock()), (None, Mock())])
        with patch.dict(os.environ, PEERS):
            report = asyncio.run(analyze_proposal(
                ctx, DAOAnalysisRequest(proposal_id=PROPOSAL_ID, proposal_url=PROPOSAL_URL)))
        self.assertIn("Research agent request timed out.", report.evidence_gaps)
        self.assertIn("Analysis agent request timed out.", report.evidence_gaps)
        self.assertEqual(report.proposal_id, PROPOSAL_ID)

    def test_proposal_id_is_preserved_end_to_end(self):
        ctx = Ctx([(research(), None), (analysis(), None)])
        with patch.dict(os.environ, PEERS):
            report = asyncio.run(analyze_proposal(
                ctx, DAOAnalysisRequest(proposal_id=PROPOSAL_ID, proposal_url=PROPOSAL_URL)))
        sent = [call.args[1] for call in ctx.send_and_receive.await_args_list]
        self.assertTrue(all(m.proposal_id == PROPOSAL_ID for m in sent))
        self.assertEqual(report.proposal_id, PROPOSAL_ID)
        self.assertEqual(report.status, "READY_FOR_HUMAN_REVIEW")


class ConsistencyTests(unittest.TestCase):
    def test_snapshot_id_mismatch(self):
        req = DAOAnalysisRequest(proposal_id="0x" + "cd" * 32, proposal_url=PROPOSAL_URL)
        self.assertTrue(any("does not match the Snapshot proposal id" in g
                            for g in consistency_gaps(req, research())))

    def test_matching_title_ignores_case_and_punctuation(self):
        req = DAOAnalysisRequest(proposal_id=PROPOSAL_ID, proposal_url=PROPOSAL_URL,
                                 proposal_title=TITLE.upper() + "!")
        self.assertEqual(consistency_gaps(req, research()), [])


class ChatTests(unittest.TestCase):
    def test_plain_text_without_url_gets_help(self):
        ctx = Ctx()
        msg = ChatMessage(content=[TextContent(text="hello")])
        asyncio.run(handle_chat_message(ctx, "user", msg))
        ack, reply = (c.args[1] for c in ctx.send.await_args_list)
        self.assertEqual(ack.acknowledged_msg_id, msg.msg_id)
        self.assertIn("Send a DAO proposal link", reply.text())
        self.assertIn("Input error:", reply.text())

    def test_json_without_title_is_accepted(self):
        req = parse_chat_request(f'{{"proposal_id": "p1", "proposal_url": "{PROPOSAL_URL}"}}')
        self.assertEqual(req.proposal_title, "")
        self.assertIsNone(req.requested_amount)

    def test_non_snapshot_url_uses_url_as_id(self):
        req = parse_chat_request("check https://gov.example.org/p/9.")
        self.assertEqual(req.proposal_url, "https://gov.example.org/p/9")
        self.assertEqual(req.proposal_id, "https://gov.example.org/p/9")


class DemoClientTests(unittest.TestCase):
    def test_demo_request_has_no_hardcoded_metadata(self):
        env = {"DAO_PROPOSAL_URL": f'"{PROPOSAL_URL}"', "DAO_PROPOSAL_ID": "",
               "DAO_PROPOSAL_TITLE": "", "DAO_REQUESTED_AMOUNT": "", "DAO_TREASURY_BALANCE": ""}
        with patch.dict(os.environ, env):
            req = send_local_request.build_request()
        self.assertEqual(req.proposal_id, PROPOSAL_ID)
        self.assertEqual(req.proposal_url, PROPOSAL_URL)
        self.assertEqual(req.proposal_title, "")
        self.assertIsNone(req.requested_amount)
        self.assertIsNone(req.treasury_balance)

    def test_demo_check_rejects_reports_without_retrieved_content(self):
        req = DAOAnalysisRequest(proposal_id=PROPOSAL_ID, proposal_url=PROPOSAL_URL)
        empty = build_decision_report(PROPOSAL_ID, research(
            findings=[], source_urls=[], retrieved_title="", retrieval_method="",
            proposal_content_retrieved=False), analysis())
        self.assertTrue(send_local_request.check_report(req, empty))
        good = build_decision_report(TITLE, research(), analysis(proposal_summary="Purpose."))
        self.assertEqual(send_local_request.check_report(req, good), [])


THROWAWAY_SEEDS = {
    "ORCHESTRATOR_SEED": "1" * 64,
    "RESEARCH_AGENT_SEED": "2" * 64,
    "ANALYSIS_AGENT_SEED": "3" * 64,
}


class SecretHygieneTests(unittest.TestCase):
    def test_seeds_never_appear_in_reports_or_logs(self):
        # Throwaway seeds set here, so the leak check runs on any checkout
        # instead of depending on the developer's own .env being present.
        seeds = list(THROWAWAY_SEEDS.values())
        records = []
        handler = logging.Handler()
        handler.emit = lambda record: records.append(record.getMessage())
        logging.getLogger().addHandler(handler)
        try:
            ctx = Ctx([RuntimeError("peer down"), (analysis(), None)])
            with patch.dict(os.environ, {**PEERS, **THROWAWAY_SEEDS}):
                report = asyncio.run(analyze_proposal(
                    ctx, DAOAnalysisRequest(proposal_id=PROPOSAL_ID, proposal_url=PROPOSAL_URL)))
        finally:
            logging.getLogger().removeHandler(handler)
        logged = " ".join(records) + " ".join(str(c) for c in ctx.logger.mock_calls)
        text = format_report(report) + report.json()
        for seed in seeds:
            self.assertNotIn(seed, text)
            self.assertNotIn(seed, logged)


CHAT_PROTOCOL_IMPORT = "uagents_core.contrib.protocols.chat"


class AgentSurfaceTests(unittest.TestCase):
    """Only the Orchestrator exposes the public AgentChatProtocol.

    Declaration-level checks: they inspect what each agent module declares and
    imports, so they start no agent and touch no network.
    """

    def test_orchestrator_declares_the_public_chat_protocol(self):
        protocol = orchestrator_agent_module.chat_protocol
        self.assertEqual(protocol.spec.name, "AgentChatProtocol")
        self.assertEqual(protocol.spec.digest, chat_protocol_spec.digest)

    def test_orchestrator_registers_a_chat_message_handler(self):
        self.assertIn(
            Model.build_schema_digest(ChatMessage),
            orchestrator_agent_module.chat_protocol.models,
        )

    def test_workers_declare_no_chat_protocol_surface(self):
        for module in (research_agent_module, analyst_agent_module):
            with self.subTest(module=module.__name__):
                self.assertFalse(hasattr(module, "chat_protocol"))
                self.assertFalse(hasattr(module, "chat_protocol_spec"))

    def test_workers_keep_their_structured_request_models(self):
        self.assertTrue(hasattr(research_agent_module, "ResearchRequest"))
        self.assertTrue(hasattr(analyst_agent_module, "AnalysisRequest"))

    def test_only_the_orchestrator_imports_the_chat_protocol(self):
        sources = {
            module.__name__: inspect.getsource(module)
            for module in (
                orchestrator_agent_module, research_agent_module, analyst_agent_module,
            )
        }
        # The guard must be capable of failing: the Orchestrator does import it.
        self.assertIn(CHAT_PROTOCOL_IMPORT, sources[orchestrator_agent_module.__name__])
        self.assertNotIn(CHAT_PROTOCOL_IMPORT, sources[research_agent_module.__name__])
        self.assertNotIn(CHAT_PROTOCOL_IMPORT, sources[analyst_agent_module.__name__])


if __name__ == "__main__":
    unittest.main()

