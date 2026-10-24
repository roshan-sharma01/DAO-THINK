import asyncio
import logging
import os
import socket
from unittest.mock import AsyncMock, patch

from dotenv import load_dotenv
from uagents import Agent


def _get_ephemeral_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


def main() -> None:
    load_dotenv()
    test_seed = os.getenv("ANALYSIS_INTEGRATION_TEST_SEED", "").strip()
    if not test_seed:
        raise SystemExit(
            "Set ANALYSIS_INTEGRATION_TEST_SEED in your ignored .env file first."
        )

    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
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

    print(
        "This temporary local agent uses the dedicated integration-test identity. "
        "It does not start the production Orchestrator."
    )
    print(
        "Use the Agent Inspector URL printed below to sign in and connect this "
        "identity to Agentverse. Keep this process running until Inspector confirms "
        "the connection, then press Ctrl+C."
    )

    try:
        with (
            patch.object(agent, "_update_agent_status", new_callable=AsyncMock),
            patch.object(agent, "start_registration_loop"),
            patch("uagents.asgi.HOST", "127.0.0.1"),
        ):
            agent.run()
    finally:
        asyncio.set_event_loop(None)


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    main()
