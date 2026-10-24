# DAO-Think

DAO-Think is a human-in-the-loop decision-support system for DAO governance
proposals. Three uAgents cooperate:

```
user / ASI:One ──DAOAnalysisRequest or chat──▶ Orchestrator (8000)
                                                │ ResearchRequest
                                                ▼
                                         Research Agent (8001)
                                           Snapshot GraphQL hub / safe HTTPS fetch
                                                │ ResearchResult (title, body, facts, gaps, caveats)
                                                ▼
                                         Orchestrator ──AnalysisRequest──▶ Analyst Agent (8002)
                                                │                         deterministic, traceable
                                                ◀────────AnalysisResult───┘
                                                ▼
                                         DecisionReport (status + evidence) ──▶ human reviewer
```

It retrieves the real proposal, labels every statement by where it came from,
and returns a report for a person to review. It never votes, signs, or moves
funds, and `READY_FOR_HUMAN_REVIEW` is not an approval.

## What the report contains

| Section | Source | Trust level |
| --- | --- | --- |
| Facts from the source of record | Snapshot API (space, id, state, choices, voting window, vote totals, quorum) | Source of record for vote data |
| Stated purpose, benefits, dependencies, amounts | Sentences copied from the proposal, prefixed `Proposal says:` | The proposer's claims, not verified |
| Risks | Risk statements in the proposal + treasury-exposure notes + caller-figure checks | Mixed, each item labelled |
| Evidence gaps | Anything that blocks reliance (retrieval failure, empty body, title/ID mismatch, amounts without treasury figures) | Status becomes `MORE_EVIDENCE_REQUIRED` |
| Caveats | Non-blocking uncertainty (vote totals ≠ merit, quorum 0 = not configured, truncation) | Shown, does not block |
| Assumptions | The Analyst's own method limits | — |

Recommendations are only `DEFER_PENDING_EVIDENCE`, `ESCALATE_FOR_REVIEW`
(high treasury exposure or prompt-injection text) or `HUMAN_REVIEW_REQUIRED`.

## Setup (macOS / Linux)

Requires Python 3.10+.

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
python scripts/new_local_env.py        # writes .env with 4 fresh, distinct seeds (never printed)
```

Then edit `.env` and set the proposal to test. **Quote it**, because Snapshot
URLs contain `#`:

```dotenv
DAO_PROPOSAL_URL="https://snapshot.org/#/<space>/proposal/<proposal-id>"
```

Leave `DAO_REQUESTED_AMOUNT` / `DAO_TREASURY_BALANCE` blank unless you know the
real figures; DAOThink never guesses them. Keep `DAOTHINK_LOCAL=1` locally.

Windows (PowerShell): use `.\.venv\Scripts\Activate.ps1` and `Copy-Item`; the
end-to-end shell script is macOS/Linux only, so start the agents manually (below).

## Tests

```bash
python -m pytest -q
```

All unit tests are offline: network calls and DNS are mocked or blocked, so a
passing run proves logic, not live connectivity. The optional hosted mailbox test
(`tests/test_analysis_agent_integration.py`) skips unless you configure it.

## Local end-to-end run (three real agents)

One command starts the Research, Analyst and Orchestrator agents, sends your
proposal from a test client on port 8003, checks the report, and stops the agents:

```bash
./scripts/run_local_e2e.sh "https://snapshot.org/#/<space>/proposal/<proposal-id>"
```

It passes only if a `DecisionReport` arrives for the same `proposal_id`, the
proposal content was actually retrieved, the requested URL is among the sources,
and the Analyst produced a stated-purpose summary. Logs go to `logs/e2e-*/`.

Manual alternative (four terminals, repository root, venv active):

```bash
python -m research_agent.research_agent    # terminal 1, port 8001
python -m analyst.agent                    # terminal 2, port 8002
python -m orchestrator.agent               # terminal 3, port 8000
python -m tests.send_local_request         # terminal 4, port 8003
```

If a port is busy, find the stale process with `lsof -nP -iTCP:8000 -sTCP:LISTEN`.

## Submitting a proposal

In ASI:One chat (or any Agent Chat Protocol client), send either a plain link:

```
Please review https://snapshot.org/#/<space>/proposal/<proposal-id>
```

or JSON:

```json
{"proposal_id": "<id>", "proposal_url": "https://snapshot.org/#/<space>/proposal/<id>",
 "requested_amount": 250000, "treasury_balance": 10000000}
```

`proposal_title` is optional; if supplied and it differs from the retrieved
title, the report flags the mismatch.

## Hosted deployment (Agentverse mailbox)

Local success is not proof of hosted success; test the hosted path separately.

1. In `.env` set `DAOTHINK_LOCAL=0` and `MAILBOX_ENABLED=true`. Use fresh seeds.
2. Start each agent on your machine (ports 8000/8001/8002 stay distinct). Each logs
   an **Agent Inspector** URL.
3. Open each Inspector URL in a browser signed in to Agentverse, click **Connect →
   Mailbox**. Each agent needs its own mailbox. Chrome 142+ / Brave ask for *Local
   Network Access*; click **Allow**, or the Inspector cannot see the local agent.
4. Wait for `Successfully registered as mailbox agent in Agentverse` in each log.
5. Set `RESEARCH_AGENT_ADDRESS` and `ANALYSIS_AGENT_ADDRESS` to the addresses the
   agents print (or leave blank to derive them from the seeds), and restart the
   Orchestrator.
6. In Agentverse, check the Orchestrator's profile (name, description and
   `AGENT_README.md` are published automatically) and that it shows as active.
7. Test agent-to-agent delivery, then chat with the Orchestrator from ASI:One
   using a real proposal link. Only call it hosted/ASI:One-ready after that works.

Agents must keep running to stay reachable. Nothing here spends funds; if any
step asks for tokens or payment, stop and check the event's official instructions.

## Configuration reference

See `.env.example`. Never commit `.env`, `private_keys.json`, or key files
(`.gitignore` covers them). If a seed has been shared, rotate it with
`python scripts/new_local_env.py --rotate`; agent addresses change as a result.

## Known limitations

- Statement classification is keyword-based; it can miss or misfile sentences.
- Only Snapshot (snapshot.org / snapshot.box mainnet hub) is read through an API.
  Other URLs are fetched as HTML; client-rendered pages are detected and reported
  as not retrieved rather than analyzed.
- The forum/discussion link is listed but not fetched.
- Amounts are quoted, not converted or priced; treasury balance must be supplied.
- SSRF protection validates DNS before connecting and refuses redirects, but does
  not pin the resolved IP (a DNS-rebinding window remains).
- Agents handle one message at a time; a slow retrieval delays other requests.
- Agentverse mailbox message-size limits were not verified. If hosted delivery of a
  very long proposal fails, lower `MAX_PROPOSAL_CHARS` in `research_tools.py`.

## Project layout

| Path | Purpose |
| --- | --- |
| `shared/models.py` | The only wire-model definitions (do not copy them into agents) |
| `research_agent/research_tools.py` | URL safety, bounded HTTP, Snapshot GraphQL, evidence building |
| `research_agent/research_agent.py` | Research uAgent |
| `analyst/evidence.py` | Deterministic statement extraction and injection detection |
| `analyst/strategy.py`, `critic.py`, `risk.py` | Assessment, evidence critique, treasury exposure |
| `analyst/agent.py` | Analyst uAgent |
| `orchestrator/agent.py`, `report.py` | Coordination, validation, chat protocol, report |
| `local_config.py` | Ports, seed-derived addresses, local resolver |
| `scripts/` | `.env` seed helper and local end-to-end script |
| `tests/` | Offline unit, pipeline and edge-case tests; demo client |
| `AGENT_README.md` | Agentverse profile text |
| `VALIDATION.md` | What has and has not been verified |

DAOThink is not affiliated with or endorsed by Fetch.ai or Snapshot. Its output is
not financial, legal or governance advice.
