> **Historical team notes.** This file describes an earlier two-agent layout
> (`shared_models.py`, `analysis_agent.py`). The root `README.md` is the current,
> authoritative guide; models live only in `shared/models.py`.

# DAOThink

Makes DAO proposal research traceable, useful and verifiable instead of asking an
LLM to summarise a proposal.

This repository contains **Member 1 (Research Agent)** and **Member 2 (Analysis &
Critic Agent)**. **Member 3's Orchestrator** — the entry point that coordinates
these two agents and produces the final decision brief — is developed separately
and is *not* part of this repository.

| Member | Agent | File | Port | Address |
| --- | --- | --- | --- | --- |
| 1 | Research | `research_agent.py` | 8001 | `agent1q0jpwfv5668nfaz5fjyfjmktw86zkxm30zclxutrczrw3whwy3vt7ywum6d` |
| 2 | Analysis & Critic | `analysis_agent.py` | 8002 | `agent1qvmam2xkxlcupkqkg3nfn83y6mntg7kj7ce9s28a6tq5vhwes9z0jlela2e` |

Addresses are derived deterministically from the seeds in `.env`. They are public
information; the seeds themselves are secrets and are never committed.

## Workflow

```
caller ──ResearchRequest──▶ Research Agent ──▶ validates the URLs, fetches them, extracts text
                              │  ResearchResult (findings + retrieved source URLs + evidence gaps)
                              ▼
                           Analysis Agent ──▶ deterministic strategy / critic / risk pass
                              │  AnalysisResult
                              ▼
                            caller
```

Member 3's Orchestrator sits in front of this: it sends the `ResearchRequest`,
forwards the returned findings, source URLs and evidence gaps into an
`AnalysisRequest`, and assembles the final decision brief. The two agents never
message each other directly.

Rules the code enforces:

- A URL appears in `ResearchResult.source_urls` **only** if it was actually
  retrieved. A URL that failed retrieval goes into `evidence_gaps` instead; it is
  never reported as retrieved.
- If nothing could be retrieved, the status is `insufficient_evidence` with **no**
  findings — nothing is invented.
- `requested_amount`, `treasury_balance` and `alternatives` are never produced by
  the Research Agent. The caller supplies them (or leaves them unset); the
  Analysis Agent reports "could not be assessed" rather than guessing.
- The Analysis Agent is deterministic and keyword-based: every statement is
  traceable to retrieved text, and no evidence means no recommendation.

## Files

| File | Purpose |
| --- | --- |
| `shared_models.py` | Shared message schemas (`ResearchRequest`/`ResearchResult`, `AnalysisRequest`/`AnalysisResult`) |
| `research_tools.py` | URL validation (SSRF guard) + retrieval + text extraction |
| `research_agent.py` | Member 1 agent |
| `analysis_tools.py` | Deterministic strategy / critic / risk logic |
| `analysis_agent.py` | Member 2 agent |
| `send_request.py` | Standalone sender / test client for the Research Agent (real uAgents messaging) |
| `local_config.py` | Seed/address/port wiring and the local resolver |
| `test_research_tools.py` | Unit tests for the research functions (37) |
| `test_integration.py` | Analysis logic tests + Research Agent contract and messaging tests (10) |

## Setup

Use the **workspace-root** virtual environment. Do not create a second one.

```bash
cd daothink
../.venv/bin/python -m pip install -r requirements.txt
../.venv/bin/python -c "import uagents, requests, bs4, dotenv; print('deps ok')"
```

If `python -m pip` reports `(base)` in the prompt, you are in the Conda base
interpreter, which does not have uAgents installed. Always use `../.venv/bin/python`.

### `.env`

`.env` lives next to the code and is gitignored. Required keys:

```
RESEARCH_AGENT_SEED=<random hex>
ANALYSIS_AGENT_SEED=<random hex>
ORCHESTRATOR_SEED=<random hex>
```

Optional keys:

| Key | Default | Meaning |
| --- | --- | --- |
| `DAOTHINK_LOCAL` | `1` | `1` uses the local rules-based resolver. Set to `0` for a hosted/Agentverse run. |

`ORCHESTRATOR_SEED` is still required locally: `local_config.py` maps its derived
address to port 8000 in the local resolver, and `send_request.py` uses that
identity as its own resolvable address (see "Ports are not HTTP APIs"). Nothing in
this repository starts an orchestrator.

Never commit `.env`, and never paste seeds into source files, logs or chat.

## Running the system

Start order matters: each agent builds its resolver map at startup from the seeds
in `.env`, so the peer you send to must already be running.

```bash
cd daothink

# Terminal 1 — Member 1 (Research Agent, port 8001)
../.venv/bin/python research_agent.py

# Terminal 2 — Member 2 (Analysis Agent, port 8002)
../.venv/bin/python analysis_agent.py
```

Then, from a third terminal, send a real request to the running Research Agent:

```bash
../.venv/bin/python send_request.py --mode research
```

It prints the `ResearchResult` and exits non-zero if the reply violates the
contract. Member 3's Orchestrator is the entry point for the full
research → analysis flow; run it from its own repository.

### Sending your own proposal

`send_request.py` reads only the four `ResearchRequest` fields; other keys in the
file are ignored.

```json
{
  "proposal_id": "DAO-0001",
  "proposal_title": "Fund Protocol Integration Documentation",
  "research_questions": ["What does the proposal claim about funding?"],
  "source_urls": ["https://example.com/"]
}
```

```bash
../.venv/bin/python send_request.py --mode research my_proposal.json
```

### Ports are not HTTP APIs

`http://127.0.0.1:8001/submit` is the uAgents transport endpoint. You cannot
`curl` a `ResearchRequest` at it. Messages are signed envelopes sent with
`ctx.send_and_receive(...)`, and the agents must be able to *resolve* each other.
For local development that resolution is provided by `local_config.local_resolver()`
(a `RulesBasedResolver` mapping every address derived from the seeds in `.env` to
its local port).

That is also why `send_request.py` sends from the configured `ORCHESTRATOR_SEED`
identity on port 8000: a peer can only reply to an address it can resolve, and
reusing that already-configured identity needs no new secrets or settings. Do not
run anything else on port 8000 at the same time.

## Tests

```bash
cd daothink
../.venv/bin/python -m pytest -q          # everything
../.venv/bin/python -m pytest test_research_tools.py -q   # research unit tests only
../.venv/bin/python -m pytest -k e2e -v   # real messaging end-to-end only
```

Current status: **47 passed** (37 unit + 10 analysis/contract/messaging).

`test_research_tools.py` mocks `requests.get` and `socket.getaddrinfo`, so unit
tests never touch a real website or DNS server; an autouse fixture fails any test
that attempts a real network call. `test_integration.py` covers the Analysis
Agent's deterministic logic and the Research Agent's reply contract, and runs the
actual uAgents message transport in a subprocess for the `e2e` test (skipped
automatically if there is no outbound network or no Research Agent on port 8001).

### What each test covers

| Area | Tests |
| --- | --- |
| Analysis logic (Member 2) | `test_analysis_without_evidence_recommends_nothing`, `test_analysis_opposes_request_exceeding_treasury`, `test_analysis_flags_large_treasury_share`, `test_analysis_without_financials_adds_a_gap_instead_of_guessing`, `test_evidence_levels`, `test_detect_signals_only_reports_present_topics`, `test_financials_need_a_positive_balance` |
| Reply contract (Member 1) | `test_research_validator_rejects_mismatched_proposal_id`, `test_research_validator_accepts_insufficient_evidence_with_gaps` |
| Real messaging | `test_e2e_research_agent_real_messaging` |

## Research function coverage (`test_research_tools.py`)

**`validate_public_url` — the SSRF guard**

| Test | Verified behaviour |
| --- | --- |
| `test_accepts_valid_public_https_url` | A public HTTPS URL resolving to a public IP is accepted |
| `test_rejects_malformed_urls` | Empty, scheme-less, relative and non-HTTPS-scheme strings are rejected |
| `test_rejects_http_url` | Plain HTTP is refused; only HTTPS sources are allowed |
| `test_rejects_localhost` / `test_rejects_local_hostnames` | `localhost`, `*.local` and case variants are refused |
| `test_rejects_url_with_credentials` | URLs embedding `user:pass@` are refused |
| `test_rejects_non_public_addresses` | Private, loopback, link-local and unspecified resolved IPs are blocked |
| `test_rejects_unresolvable_host` | DNS failure is a rejection, not a crash |

**`fetch_source` — retrieval and extraction**

| Test | Verified behaviour |
| --- | --- |
| `test_extracts_title_and_readable_text` | Page title and readable body text are extracted; markup is not returned |
| `test_strips_script_and_style_content` | `<script>`/`<style>` contents never reach the findings |
| `test_truncates_long_text` | Extracted text is capped at `MAX_CHARS_PER_SOURCE` |
| `test_request_uses_safe_transport_options` | Requests use a timeout, streaming and a bounded `User-Agent` |
| `test_does_not_follow_redirects` | `allow_redirects=False`, and a 3xx response is an error |
| `test_handles_http_error` / `test_handles_timeout` / `test_handles_connection_error` | Failures return an error with empty text instead of raising |
| `test_rejects_non_html_response` | Binary/PDF content types are refused |
| `test_rejects_oversized_response` | Responses over `MAX_BYTES` are refused while streaming |
| `test_rejects_page_with_no_readable_text` | A page with no usable text is an error, not an empty finding |
| `test_does_not_fabricate_findings_on_failure` | The failure payload carries no invented text |
| `test_blocks_unsafe_url_before_requesting` | Unsafe URLs are rejected before any HTTP request is made |

**`research_sources` — aggregation**

| Test | Verified behaviour |
| --- | --- |
| `test_returns_findings_for_retrieved_sources` | Findings keep the `[source_url]` prefix and are listed in `source_urls` |
| `test_records_failed_sources_as_evidence_gaps` | Failed sources become evidence gaps, not findings |
| `test_handles_empty_url_list` | An empty request returns a "no sources supplied" gap |
| `test_enforces_maximum_of_five_urls` | At most `MAX_SOURCES` (5) URLs are fetched |
| `test_separates_successful_and_failed_sources` | Mixed input splits correctly between findings and gaps |
| `test_unsafe_url_is_reported_as_gap_not_fetched` | An unsafe URL is reported as a gap and never fetched |

## Troubleshooting

| Symptom | Cause / fix |
| --- | --- |
| `ModuleNotFoundError: No module named 'uagents'` | You used the Conda base interpreter. Use `../.venv/bin/python`. |
| `RuntimeError: RESEARCH_AGENT_SEED is missing from .env` | `.env` is missing or lacks that key. |
| `[Errno 48] address already in use` | Another instance already holds the port. Stop it instead of starting a duplicate. |
| `Unable to resolve destination endpoint` in the logs | The peer address is not in the resolver map, or `DAOTHINK_LOCAL=0` while the agents are not registered on the Almanac. |
| `unable to resolve` but only for the *reply* | The caller's address must be resolvable by the callee; send from a configured identity (see "Ports are not HTTP APIs"). |
| `send_request.py` prints `FAIL: no response received` | The Research Agent is not running on port 8001, or its reply could not be resolved. Check terminal 1. |
| `Registration on Almanac API successful` then `I do not have enough funds` | Expected without funds. Local messaging does not need registration. |
| A `Phantom`/`RecursionError` traceback during shutdown | Known uAgents/CPython 3.13 teardown issue; `send_request.py` exits before teardown. |
| Pylance cannot resolve `uagents`/`dotenv` | Editor-only: point VS Code at `/Users/roshansharma/python asi one/.venv/bin/python`. |

## Known limitations

- `research_questions` are accepted but not yet used to select or filter source
  text; the agent returns extracted source text, not an interpretation.
- `MAX_SOURCES = 5` silently drops extra URLs; it does not report them as gaps.
- The URL checks are a basic safeguard, not a complete production SSRF defence
  (for example, DNS rebinding after validation is not addressed).
- The Analysis Agent is deterministic and keyword-based. That is deliberate for a
  hackathon: every statement is traceable to retrieved text. Adding an LLM pass
  must not remove the "insufficient evidence" path.

## Deployment (not done — requires your approval)

Nothing has been deployed, published or registered. The current setup is
local-only: `endpoint=["http://127.0.0.1:<port>/submit"]` plus a rules-based
resolver. **A local endpoint does not work on Agentverse** — remote agents cannot
reach `127.0.0.1`, so hosted runs need mailbox messaging or a public endpoint.

Steps required before any hosted deployment of these two agents:

1. **Agentverse registration** — sign in to <https://agentverse.ai>, create (or
   reuse) two agent profiles. Seeds are already local; do not paste them into a
   browser form — use the Agentverse CLI/`uagents` flow instead.
2. **Mailbox / hosted messaging** — for each agent, enable mailbox messaging so
   messages are queued at Agentverse instead of being delivered to `127.0.0.1`.
   In code this means constructing the agent with `mailbox=True` (and typically
   `agentverse=True`) and removing the local `endpoint` / local resolver.
3. **Almanac registration** — registration currently fails with "not enough funds".
   Fund the agent wallet (testnet faucet for `network="testnet"`) and register so
   peers can resolve these agents globally.
4. **Set `DAOTHINK_LOCAL=0`** for each agent so `local_resolver()` returns `None`
   and global resolution is used.
5. **Redeploy and verify** with `send_request.py`, confirming a real
   `ResearchResult` comes back through the hosted path.
6. **Update the address table** at the top of this README if the deployed
   Agentverse identities differ from the ones derived from the local seeds.
   Member 3's Orchestrator must then be pointed at these deployed addresses.

Do not run any of these until you explicitly approve it.

## ASI:One readiness

What is implemented locally:

- Both agents are real uAgents agents with typed `Model` schemas
  (`ResearchRequest`, `ResearchResult`, `AnalysisRequest`, `AnalysisResult`) and
  deterministic, non-fabricating behaviour.

What is **not** implemented yet:

- **Agent Chat Protocol**: uAgents 0.26 ships
  `uagents_core.contrib.protocols.chat` (protocol version `0.3.0`) with
  `ChatMessage`, `ChatAcknowledgement` and `TextContent`. Nothing in this
  repository registers this protocol, so ASI:One cannot hold a chat conversation
  with these agents. Wiring it locally is straightforward (`Protocol(spec=chat_protocol_spec)`
  plus a handler that replies with `ChatMessage(content=[TextContent(text=...)])`),
  but it still requires the dashboard steps below to be reachable from ASI:One.
- **Agentverse discoverability**: agents must be registered, have a name,
  description and README set on their profile, and be running with mailbox
  messaging before they appear as usable agents.
- **The user-facing entry point**: ASI:One would talk to Member 3's Orchestrator,
  which owns the final decision brief and lives in its own repository.

Manual checklist (dashboard / account actions that need your authorisation):

1. Create the agent profiles on Agentverse and confirm their addresses match the
   ones in the table above.
2. Enable **mailbox** for each agent so messages are not delivered to `127.0.0.1`.
3. Fund the agent wallets and complete Almanac registration.
4. Set each agent's profile name, description and README so it is discoverable.
5. Enable ASI:One access for the user-facing agent (Member 3's Orchestrator) and
   add Agent Chat Protocol support to the code, then re-verify end to end.
6. Only after the above: run `send_request.py` against the hosted deployment and
   confirm the reply is identical in shape to the local one.

Do **not** claim ASI:One compatibility until steps 1–6 have actually been done and
verified.
