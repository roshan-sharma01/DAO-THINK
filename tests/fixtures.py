"""SYNTHETIC test fixtures. Not real DAO data; used only by offline tests."""

import copy
import json

SPACE = "synthetic-dao.eth"
PROPOSAL_ID = "0x" + "ab" * 32
PROPOSAL_URL = f"https://snapshot.org/#/{SPACE}/proposal/{PROPOSAL_ID}"
TITLE = "[SYNTHETIC] Fund a security audit program"

BODY = """# Summary
This synthetic proposal requests funding for a twelve-month security audit program. It aims to reduce the risk of smart contract exploits across the protocol.

## Motivation
Recent incidents in similar protocols show that unaudited upgrades increase the risk of loss of user funds.
The program will improve user confidence and support faster, safer releases.

## Budget
The DAO treasury would transfer 250,000 USDC to the audit multisig in two tranches.
A further $40,000 is reserved for bug bounties.

## Implementation
Payment of the second tranche depends on milestone reports reviewed by the security council.
Funds will be held in a 3-of-5 multisig with a 48-hour timelock.
"""

SNAPSHOT_PROPOSAL = {
    "id": PROPOSAL_ID,
    "title": TITLE,
    "body": BODY,
    "choices": ["For", "Against", "Abstain"],
    "start": 1760000000,
    "end": 1760600000,
    "snapshot": 23000000,
    "state": "closed",
    "author": "0x" + "12" * 20,
    "created": 1759990000,
    "type": "single-choice",
    "quorum": 0,
    "quorumType": "default",
    "scores": [1200000.5, 300000, 5000],
    "scores_total": 1505000.5,
    "scores_state": "final",
    "votes": 321,
    "discussion": "https://forum.example.org/t/synthetic-audit",
    "link": PROPOSAL_URL,
    "network": "1",
    "flagged": False,
    "space": {"id": SPACE, "name": "Synthetic DAO"},
}


def snapshot_proposal(**overrides) -> dict:
    proposal = copy.deepcopy(SNAPSHOT_PROPOSAL)
    proposal.update(overrides)
    return proposal


def graphql_body(proposal) -> bytes:
    return json.dumps({"data": {"proposal": proposal}}).encode()
