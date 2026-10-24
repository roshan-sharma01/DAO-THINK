
from analyst.strategy import analyze_strategy

result = analyze_strategy(
    proposal_title="DAO protocol integration",
    requested_amount=50000,
    treasury_balance=200000,
    research_findings=[
        "The proposal requests 50,000 USDC.",
        "The stated goal is protocol integration.",
    ],
    source_urls=["https://example.org/sample-proposal"],
    alternatives=[
        "Approve full amount",
        "Approve a smaller pilot",
        "Take no action",
    ],
)

assert result["treasury_risk"]["treasury_exposure_percent"] == 25.0

print("Analysis function works.")
print("Exposure:", result["treasury_risk"]["treasury_exposure_percent"], "%")
print("Recommendation:", result["recommendation"])
