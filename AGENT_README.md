# DAOThink Orchestrator

Human-in-the-loop research for DAO governance proposals.

**Send:** a Snapshot proposal link, e.g. `https://snapshot.org/#/<space>/proposal/<id>`
(or JSON with `proposal_id`, `proposal_url`, and optional `proposal_title`,
`requested_amount`, `treasury_balance`).

**You get:** an evidence-labelled report with the proposal's stated purpose, facts
read from the Snapshot API (state, choices, vote totals, quorum), benefits and
risks *as claimed by the proposal*, stated dependencies and amounts (quoted, never
converted), evidence gaps, caveats and a conservative recommendation.

**Important limits**

- Decision support only. It never votes, signs, or moves funds. `READY_FOR_HUMAN_REVIEW`
  is not approval.
- Statements marked "Proposal says" are the proposer's claims, not verified facts.
- Vote totals measure voting power, not merit. A quorum of 0 means "not configured",
  not "no quorum required".
- Retrieved text is treated as untrusted data; instructions inside it are flagged, not followed.
- Treasury exposure is only computed from figures you supply.

Not affiliated with or endorsed by Fetch.ai or Snapshot.
