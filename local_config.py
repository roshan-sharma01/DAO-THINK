"""Shared local-development networking for DAOThink agents.

Set DAOTHINK_LOCAL=1 and configure unique seeds for all three agents.
In local mode, agent addresses are derived from those seeds and mapped to
localhost submit endpoints. Set DAOTHINK_LOCAL=0 for hosted Agentverse mode.
"""

import os
from dotenv import load_dotenv
from uagents_core.identity import Identity

load_dotenv()

RESEARCH_SEED_ENV = "RESEARCH_AGENT_SEED"
ANALYSIS_SEED_ENV = "ANALYSIS_AGENT_SEED"
ORCHESTRATOR_SEED_ENV = "ORCHESTRATOR_SEED"
RESEARCH_PORT = 8001
ANALYSIS_PORT = 8002
ORCHESTRATOR_PORT = 8000
TEST_CLIENT_PORT = 8003

_AGENT_PORTS = (
    (RESEARCH_SEED_ENV, RESEARCH_PORT),
    (ANALYSIS_SEED_ENV, ANALYSIS_PORT),
    (ORCHESTRATOR_SEED_ENV, ORCHESTRATOR_PORT),
    ("TEST_CLIENT_SEED", TEST_CLIENT_PORT),
)


def local_mode_enabled() -> bool:
    return os.getenv("DAOTHINK_LOCAL", "1").strip().lower() not in {"0", "false", "no"}


def seed_from_env(name: str) -> str:
    seed = os.getenv(name, "").strip()
    if not seed:
        raise RuntimeError(f"{name} is missing from the root .env file.")
    return seed


def address_from_seed(seed: str) -> str:
    return Identity.from_seed(seed, 0).address


def local_endpoints() -> dict[str, str]:
    endpoints: dict[str, str] = {}
    for seed_env, port in _AGENT_PORTS:
        seed = os.getenv(seed_env, "").strip()
        if seed:
            endpoints[address_from_seed(seed)] = f"http://127.0.0.1:{port}/submit"
    return endpoints


def local_resolver():
    if not local_mode_enabled():
        return None
    from uagents.resolver import RulesBasedResolver
    return RulesBasedResolver(local_endpoints())


def peer_address(address_env: str, seed_env: str) -> str:
    """Resolve a peer's agent address.

    Local mode prefers the seed-derived address. Hosted mode prefers the
    explicitly configured (registered) address and falls back to the seed, which
    yields the same identity when all agents run from this repository.
    """
    explicit = os.getenv(address_env, "").strip()
    seed = os.getenv(seed_env, "").strip()
    if local_mode_enabled():
        return address_from_seed(seed) if seed else explicit
    return explicit or (address_from_seed(seed) if seed else "")
