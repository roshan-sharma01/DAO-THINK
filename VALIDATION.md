# Validation record

Last updated: 25 October 2026. Each line says exactly what was and was not run.

## Passed (offline, in a sandbox without PyPI or Snapshot access)

`python -m pytest -q` → **123 passed, 1 skipped** (the skipped test is the hosted
Agentverse mailbox test, which needs a registered agent).

How it ran: PyPI was blocked in that sandbox, so `uagents` itself could not be
installed. Tests used the **real** `uagents-core 0.4.12` source (real `Model`
class, real Agent Chat Protocol models, real address derivation) cloned from
the official GitHub tag, plus a minimal stand-in for the `uagents` runtime
(Agent/Protocol registration only, no networking). Network and DNS were mocked.

Covered:
- Snapshot URL parsing; GraphQL query via variables; success, not found, API
  errors, invalid JSON, non-JSON, HTTP errors, timeouts, connection failures,
  redirects, oversized responses, private-IP resolution, malformed ids.
- Wrong space / wrong id / empty title rejected; empty body is a blocking gap;
  quorum 0 reported as "not configured", never "no quorum required".
- Client-rendered app shells are not treated as retrieved content.
- Analyst extracts purpose, benefits, risks, dependencies and amounts verbatim;
  no amounts are invented; prompt-injection text is flagged and escalated.
- Missing content defers; amounts without treasury figures become a gap;
  recommendations never include approval.
- Orchestrator: invalid requests never reach peers; timeouts, `None` replies,
  exceptions, malformed and mismatched-ID replies become evidence gaps;
  `proposal_id` preserved on every hop; title and Snapshot-ID mismatches flagged.
- In-process pipeline: the real Research → Analyst → Orchestrator logic, proving
  the Analyst receives the actual retrieved text and the report shows the
  requested proposal.
- Demo client builds requests only from your settings and rejects reports
  without retrieved content. Seeds never appear in reports or logs.

Also checked: every module compiles; `scripts/run_local_e2e.sh` passes
`bash -n`; `scripts/new_local_env.py` writes 4 distinct 64-hex seeds, mode 600,
and refuses to overwrite without `--rotate`.

## Not yet run — must be done on your machine

| Check | How | Status |
| --- | --- | --- |
| Install pinned deps (`uagents==0.26.1`) | `pip install -r requirements.txt` | Not run |
| Test suite with real uAgents | `python -m pytest -q` | Not run |
| Live Snapshot retrieval | part of the e2e script | Not run |
| Local three-agent e2e | `./scripts/run_local_e2e.sh "<snapshot url>"` | Not run |
| Agentverse mailbox registration | README → Hosted deployment | Not run |
| Hosted agent-to-agent delivery | README step 7 | Not run |
| ASI:One chat with a real proposal | README step 7 | Not run |
| Event-specific requirements | depends on the hackathon | Not checked |
