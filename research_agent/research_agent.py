import asyncio
import re

from dotenv import load_dotenv
from uagents import Agent, Context, Protocol
from uagents_core.contrib.protocols.chat import (
    ChatMessage,
    ChatAcknowledgement,
    TextContent,
    chat_protocol_spec,
)

from local_config import RESEARCH_PORT, local_mode_enabled, local_resolver, seed_from_env
from shared.models import ResearchRequest, ResearchResult
from research_agent.research_tools import MAX_SOURCES, research_proposal, research_sources

load_dotenv()

DEFAULT_PORT = RESEARCH_PORT


async def build_research_result(msg: ResearchRequest) -> ResearchResult:
    """Run the safety-checked research pipeline and map it to the wire model.

    Always returns a ResearchResult with the caller's proposal_id, so the
    Orchestrator receives an explicit evidence gap instead of a timeout.
    """
    if not msg.proposal_id.strip() or not msg.proposal_url.strip():
        return ResearchResult(
            proposal_id=msg.proposal_id,
            summary="Research was not performed.",
            findings=[],
            source_urls=[],
            limitations=["Request was missing a proposal ID or proposal URL."],
        )

    extra_urls = [u for u in msg.source_urls if u and u.strip()][:MAX_SOURCES]
    # requests is blocking; keep the agent's event loop responsive.
    result = await asyncio.to_thread(research_proposal, msg.proposal_url.strip(), extra_urls)

    gaps = list(result["evidence_gaps"])
    caveats = list(result["caveats"])
    if not msg.research_questions:
        caveats.append("No specific research questions were supplied.")

    if result["content_retrieved"]:
        summary = (
            f"Retrieved proposal \"{result['retrieved_title']}\" via "
            f"{result['retrieval_method']} at {result['retrieved_at']}; "
            f"{len(result['source_urls'])} source(s) retrieved in total."
        )
    elif result["retrieved_title"]:
        summary = (
            f"Retrieved only the title \"{result['retrieved_title']}\"; the proposal "
            "body was not available, so its content was not analyzed."
        )
    else:
        summary = "The proposal content could not be retrieved; nothing was analyzed."

    return ResearchResult(
        proposal_id=msg.proposal_id,
        summary=summary,
        findings=result["research_findings"],
        source_urls=result["source_urls"],
        limitations=list(dict.fromkeys(gaps)),
        retrieval_method=result["retrieval_method"],
        retrieved_at=result["retrieved_at"],
        retrieved_title=result["retrieved_title"],
        proposal_text=result["proposal_text"],
        proposal_facts=result["proposal_facts"],
        proposal_content_retrieved=result["content_retrieved"],
        caveats=list(dict.fromkeys(caveats)),
    )

# Agent Chat Protocol (ACP).
chat_protocol = Protocol(
    name=chat_protocol_spec.name,
    version=chat_protocol_spec.version,
    spec=chat_protocol_spec,
)


def build_research_agent(
    port: int = DEFAULT_PORT,
    seed: str | None = None,
    loop=None,
) -> Agent:
    agent_kwargs = {
        "name": "daothink_research_agent",
        "seed": seed or seed_from_env("RESEARCH_AGENT_SEED"),
        "port": port,
        "mailbox": False if local_mode_enabled() else True,
    }

    # Local mode uses direct localhost endpoints and a seed-derived resolver.
    if local_mode_enabled():
        agent_kwargs["endpoint"] = [f"http://127.0.0.1:{port}/submit"]
        agent_kwargs["resolve"] = local_resolver()

    if loop is not None:
        agent_kwargs["loop"] = loop

    agent = Agent(**agent_kwargs)

    # --------------------------------------------------
    # 1. Existing structured research handler
    # --------------------------------------------------
    @agent.on_message(model=ResearchRequest)
    async def handle_research(
        ctx: Context,
        sender: str,
        msg: ResearchRequest,
    ):
        ctx.logger.info(
            f"Research requested for proposal: {msg.proposal_id}"
        )
        response = await build_research_result(msg)
        await ctx.send(sender, response)

    # --------------------------------------------------
    # 2. ACP acknowledgement handler
    # --------------------------------------------------
    @chat_protocol.on_message(model=ChatAcknowledgement)
    async def handle_acknowledgement(
        ctx: Context,
        sender: str,
        msg: ChatAcknowledgement,
    ):
        ctx.logger.info(
            f"ACP acknowledgement received from {sender}: "
            f"{msg.acknowledged_msg_id}"
        )

    # --------------------------------------------------
    # 3. ACP chat handler
    # --------------------------------------------------
    @chat_protocol.on_message(model=ChatMessage)
    async def handle_chat(
        ctx: Context,
        sender: str,
        msg: ChatMessage,
    ):
        # Acknowledge the incoming message.
        if msg.msg_id is not None:
            await ctx.send(
                sender,
                ChatAcknowledgement(
                    acknowledged_msg_id=msg.msg_id
                ),
            )

        # Extract ordinary text from ACP content.
        text = " ".join(
            item.text
            for item in msg.content
            if isinstance(item, TextContent)
        ).strip()

        if not text:
            reply = (
                "Please send a research request as text and include "
                "HTTPS source URLs to investigate."
            )
            await ctx.send(
                sender,
                ChatMessage(content=[TextContent(text=reply)]),
            )
            return

        # Extract URLs from the message.
        urls = re.findall(r"https?://\S+", text)
        urls = [
            url.rstrip(".,);]")
            for url in urls
        ][:MAX_SOURCES]

        # Run the existing safety-checked research pipeline.
        result = await asyncio.to_thread(research_sources, urls)
        findings = result["research_findings"]
        gaps = result["evidence_gaps"]

        if findings:
            reply = "Research findings:\n" + "\n".join(
                f"- {finding}" for finding in findings
            )
        else:
            reply = (
                "I couldn't retrieve usable evidence from the supplied "
                "URLs. Please include relevant HTTPS source URLs."
            )

        if gaps:
            reply += "\n\nEvidence gaps:\n" + "\n".join(
                f"- {gap}" for gap in gaps
            )

        await ctx.send(
            sender,
            ChatMessage(content=[TextContent(text=reply)]),
        )

    # Register ACP and publish its manifest.
    agent.include(
        chat_protocol,
        publish_manifest=True,
    )

    # --------------------------------------------------
    # 4. Startup logging
    # --------------------------------------------------
    @agent.on_event("startup")
    async def startup(ctx: Context):
        ctx.logger.info("DAOThink Research Agent is running.")
        ctx.logger.info(f"Agent address: {agent.address}")
        ctx.logger.info("ACP chat protocol enabled.")
        ctx.logger.info("Mailbox enabled: %s", not local_mode_enabled())

    return agent


if __name__ == "__main__":
    build_research_agent().run()
