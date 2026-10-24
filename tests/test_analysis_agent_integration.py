import asyncio
import logging
import os
import socket
import unittest
from uuid import uuid4
from unittest.mock import AsyncMock, patch

from dotenv import load_dotenv
from uagents import Agent, Model
from uagents_core.identity import parse_identifier
from uagents_core.types import DeliveryStatus

from shared.models import AnalysisRequest, AnalysisResult


REQUEST_TIMEOUT_SECONDS = 20
OVERALL_TIMEOUT_SECONDS = 35
logger = logging.getLogger(__name__)


class SDKDiagnosticCapture(logging.Handler):
    def __init__(self) -> None:
        super().__init__(level=logging.WARNING)
        self.sender_mailbox_missing = False
        self.unrecognized_schema_digests: list[str] = []

    def emit(self, record: logging.LogRecord) -> None:
        message = record.getMessage()
        if "Agent mailbox not found" in message:
            self.sender_mailbox_missing = True
        marker = "Received message with unrecognized schema digest:"
        if marker in message:
            self.unrecognized_schema_digests.append(
                message.split(marker, 1)[1].strip()
            )


def _get_ephemeral_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


class AnalysisAgentMailboxIntegrationTests(unittest.TestCase):
    def test_analysis_agent_returns_shared_analysis_result(self) -> None:
        load_dotenv()
        analysis_address = os.getenv("ANALYSIS_AGENT_ADDRESS", "").strip()
        test_seed = os.getenv("ANALYSIS_INTEGRATION_TEST_SEED", "").strip()

        if not analysis_address:
            self.skipTest("Set ANALYSIS_AGENT_ADDRESS to the real Analysis Agent address.")
        if not test_seed:
            self.skipTest(
                "Set ANALYSIS_INTEGRATION_TEST_SEED to a dedicated test sender seed "
                "for the sender mailbox provisioned through Agentverse Inspector."
            )

        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        runner: asyncio.Task | None = None
        timer: asyncio.TimerHandle | None = None
        sdk_diagnostics = SDKDiagnosticCapture()
        sdk_logger: logging.Logger | None = None
        try:
            response_future: asyncio.Future[AnalysisResult] = loop.create_future()
            self.proposal_id = f"daoaction-integration-{uuid4()}"
            logger.info(
                "Analysis integration destination address: %s", analysis_address
            )
            logger.info("Analysis integration proposal ID: %s", self.proposal_id)
            request = AnalysisRequest(
                proposal_id=self.proposal_id,
                proposal_title="[FICTIONAL TEST] DAO analysis schema check",
                requested_amount=1.0,
                treasury_balance=100.0,
                research_findings=[
                    "Fictional test input only; this is not a real DAO proposal or fact."
                ],
                source_urls=[],
                alternatives=[
                    "Fictional test input only; no real alternatives supplied."
                ],
            )
            agent = Agent(
                name="daoaction-analysis-integration-test",
                seed=test_seed,
                mailbox=True,
                port=_get_ephemeral_port(),
                loop=loop,
                enable_agent_inspector=True,
                publish_agent_details=False,
                report_events=False,
                mark_inactive_on_shutdown=False,
            )
            sdk_logger = agent._logger
            sdk_logger.addHandler(sdk_diagnostics)
            logger.info("Analysis integration sender address: %s", agent.address)
            _, _, destination_address = parse_identifier(analysis_address)
            if destination_address == agent.address:
                raise AssertionError(
                    "ANALYSIS_AGENT_ADDRESS is the same as the temporary integration "
                    "sender address, so this would send the request to itself. Replace "
                    "it with the address printed by Member 1's running Analysis Agent."
                )

            @agent.on_event("startup")
            async def send_sample_request(ctx) -> None:
                try:
                    logger.info(
                        "Dispatching AnalysisRequest to configured Analysis Agent "
                        "address %s for proposal %s.",
                        analysis_address,
                        request.proposal_id,
                    )
                    response, status = await ctx.send_and_receive(
                        analysis_address,
                        request,
                        response_type=AnalysisResult,
                        timeout=REQUEST_TIMEOUT_SECONDS,
                    )
                    logger.info(
                        "Analysis request delivery status: %s; detail: %s",
                        status.status.value,
                        status.detail or "(no detail)",
                    )
                    if status.status != DeliveryStatus.DELIVERED:
                        if sdk_diagnostics.sender_mailbox_missing:
                            unexpected_schema = ""
                            if sdk_diagnostics.unrecognized_schema_digests:
                                unexpected_schema = (
                                    " An inbound message used unrecognized schema "
                                    f"digest "
                                    f"{sdk_diagnostics.unrecognized_schema_digests[-1]}; "
                                    "it was not parsed as the expected "
                                    "AnalysisResult."
                                )
                            raise AssertionError(
                                "The test sender's Agentverse mailbox is missing "
                                "(uAgents mailbox endpoint returned 404). Run "
                                "`python -m tests.provision_analysis_test_mailbox`, "
                                "open the printed Inspector URL, connect this dedicated "
                                "test identity to Agentverse, stop the helper, then "
                                f"rerun this test.{unexpected_schema}"
                            )
                        if sdk_diagnostics.unrecognized_schema_digests:
                            digest = sdk_diagnostics.unrecognized_schema_digests[-1]
                            if digest == Model.build_schema_digest(AnalysisRequest):
                                mismatch = (
                                    "The observed inbound message used the "
                                    "AnalysisRequest schema, not the required "
                                    "AnalysisResult schema."
                                )
                            else:
                                mismatch = (
                                    "The Analysis Agent replied using an unrecognized "
                                    f"response schema digest {digest}; expected "
                                    "shared.models.AnalysisResult."
                                )
                            raise AssertionError(
                                f"{mismatch} Confirm Member 1 uses the exact shared "
                                "AnalysisRequest and AnalysisResult models."
                            )
                        if "Unable to resolve destination endpoint" in status.detail:
                            raise AssertionError(
                                "uAgents could not resolve ANALYSIS_AGENT_ADDRESS. "
                                "Compare this configured address with Member 1's "
                                "running Agent address and confirm it is registered "
                                "and active in Agentverse."
                            )
                        raise AssertionError(
                            "Request dispatch succeeded, but no valid AnalysisResult "
                            f"arrived before the peer response timeout: "
                            f"{status.detail or status.status.value}. Confirm the "
                            "Analysis Agent is running, accepts AnalysisRequest, and "
                            "replies with AnalysisResult using the same proposal_id."
                        )
                    if response is None:
                        raise AssertionError(
                            "Request delivery succeeded but no AnalysisResult arrived "
                            "before the response timeout."
                        )
                    logger.info(
                        "Received response model %s for proposal %s.",
                        type(response).__name__,
                        request.proposal_id,
                    )
                    if not isinstance(response, AnalysisResult):
                        raise AssertionError(
                            "Analysis Agent returned an unexpected response model: "
                            f"{type(response).__name__}; expected AnalysisResult."
                        )
                    logger.info(
                        "Validating AnalysisResult schema and proposal ID for %s.",
                        request.proposal_id,
                    )
                    if response.proposal_id != request.proposal_id:
                        raise AssertionError(
                            "Analysis Agent returned a mismatched proposal_id."
                        )
                    logger.info(
                        "AnalysisResult schema and proposal ID validated for %s.",
                        request.proposal_id,
                    )
                    response_future.set_result(response)
                except Exception as exc:
                    if not response_future.done():
                        if type(exc).__name__ == "ValidationError":
                            exc = AssertionError(
                                "Analysis Agent response failed AnalysisResult schema "
                                f"validation: {exc}"
                            )
                        response_future.set_exception(exc)
                finally:
                    if not runner.done():
                        loop.call_soon(runner.cancel)

            runner = loop.create_task(agent.run_async())

            def overall_timeout() -> None:
                if not response_future.done():
                    if sdk_diagnostics.sender_mailbox_missing:
                        message = (
                            "The test sender's Agentverse mailbox is missing. Run "
                            "`python -m tests.provision_analysis_test_mailbox`, use "
                            "the printed Inspector URL to connect the dedicated test "
                            "identity, then rerun this test."
                        )
                    elif sdk_diagnostics.unrecognized_schema_digests:
                        digest = sdk_diagnostics.unrecognized_schema_digests[-1]
                        if digest == Model.build_schema_digest(AnalysisRequest):
                            message = (
                                "The inbound message used the AnalysisRequest schema, "
                                "not the required AnalysisResult schema. Confirm Member "
                                "1 responds with shared.models.AnalysisResult."
                            )
                        else:
                            message = (
                                "The Analysis Agent sent an unrecognized response "
                                f"schema digest {digest}; expected "
                                "shared.models.AnalysisResult."
                            )
                    else:
                        message = (
                            "No AnalysisResult was received before the peer response "
                            "timeout. Confirm the Analysis Agent is running, accepts "
                            "shared.models.AnalysisRequest, and replies with "
                            "shared.models.AnalysisResult using the same proposal_id."
                        )
                    response_future.set_exception(
                        AssertionError(
                            f"{message} Overall timeout: "
                            f"{OVERALL_TIMEOUT_SECONDS} seconds."
                        )
                    )
                if runner is not None and not runner.done():
                    runner.cancel()

            timer = loop.call_later(OVERALL_TIMEOUT_SECONDS, overall_timeout)
            with (
                patch.object(agent, "_update_agent_status", new_callable=AsyncMock),
                patch.object(agent, "start_registration_loop"),
                patch("uagents.asgi.HOST", "127.0.0.1"),
            ):
                loop.run_until_complete(runner)
            response = response_future.result()
        except Exception as exc:
            if type(exc).__name__ == "ValidationError":
                self.fail(f"Analysis Agent response schema validation failed: {exc}")
            if isinstance(exc, AssertionError):
                raise
            self.fail(
                f"uAgents mailbox request failed ({type(exc).__name__}): {exc}. "
                "Check mailbox connectivity and the configured Analysis Agent address."
            )
        finally:
            if timer is not None:
                timer.cancel()
            if sdk_logger is not None:
                sdk_logger.removeHandler(sdk_diagnostics)
            if runner is not None and not runner.done():
                runner.cancel()
                loop.run_until_complete(asyncio.gather(runner, return_exceptions=True))

            pending_tasks = [
                task for task in asyncio.all_tasks(loop) if not task.done()
            ]
            for task in pending_tasks:
                task.cancel()
            if pending_tasks:
                loop.run_until_complete(
                    asyncio.gather(*pending_tasks, return_exceptions=True)
                )
            loop.run_until_complete(loop.shutdown_asyncgens())
            loop.close()
            asyncio.set_event_loop(None)

        self.assertIsInstance(response, AnalysisResult)
        self.assertEqual(response.proposal_id, self.proposal_id)


if __name__ == "__main__":
    unittest.main()
