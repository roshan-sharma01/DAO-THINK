from typing import Optional


def assess_risk(
    requested_amount: Optional[float],
    treasury_balance: Optional[float],
) -> dict:
    """Assess basic treasury exposure using caller-supplied figures only.

    Figures are never inferred from proposal text: amounts in a proposal may be
    in different tokens, and the treasury balance is not in the proposal.
    """

    if requested_amount is None or treasury_balance is None:
        missing = [
            name
            for name, value in (
                ("requested amount", requested_amount),
                ("treasury balance", treasury_balance),
            )
            if value is None
        ]
        return {
            "treasury_exposure_percent": None,
            "risk_level": "not_assessed",
            "risk_findings": [
                "Treasury exposure not computed: the caller did not supply the "
                + " and ".join(missing)
                + "."
            ],
        }

    if requested_amount < 0 or treasury_balance < 0:
        raise ValueError("Amounts cannot be negative.")

    if treasury_balance == 0:
        exposure = None
        level = "unknown"
        findings = [
            "Treasury balance is zero or unavailable.",
            "Affordability cannot be established.",
        ]
    else:
        exposure = round(
            requested_amount / treasury_balance * 100, 2
        )

        if requested_amount > treasury_balance:
            level = "critical"
            findings = [
                "Requested amount exceeds the reported treasury."
            ]
        elif exposure > 25:
            level = "high"
            findings = [
                "Proposal consumes more than 25% of reported treasury."
            ]
        elif exposure > 10:
            level = "moderate"
            findings = [
                "Proposal consumes more than 10% of reported treasury."
            ]
        else:
            level = "lower_concentration"
            findings = [
                "Treasury concentration is below the configured "
                "10% review threshold."
            ]
        findings.insert(
            0,
            f"Caller-supplied figures: requested {requested_amount:,.2f} of a "
            f"reported treasury of {treasury_balance:,.2f} ({exposure}%).",
        )

    findings.extend([
        "Token volatility and liquidity are not assessed.",
        "Verify the balance, token denomination, and outstanding "
        "commitments before relying on this result.",
    ])

    return {
        "treasury_exposure_percent": exposure,
        "risk_level": level,
        "risk_findings": findings,
    }
