
from analyst.strategy import analyze_strategy


def main():
    result = analyze_strategy(
        proposal_title="DAO protocol integration",
        requested_amount=50_000,
        treasury_balance=200_000,
        research_findings=[
            "The proposal requests 50,000 USDC.",
            "The stated goal is protocol integration.",
        ],
        source_urls=[
            "https://example.org/sample-proposal"
        ],
        alternatives=[
            "Approve the full amount",
            "Approve a smaller pilot",
            "Take no action",
        ],
    )

    print("DAOThink analysis result:")
    print(result)

    assert result["treasury_risk"]["treasury_exposure_percent"] == 25.0
    assert result["treasury_risk"]["risk_level"] == "moderate"
    assert result["recommendation"] == "HUMAN_REVIEW_REQUIRED"

    print("\nBasic checks passed.")


if __name__ == "__main__":
    main()
