import unittest

from orchestrator.report import build_decision_report, format_report
from shared.models import AnalysisResult, ResearchResult


class DecisionReportTests(unittest.TestCase):
    def setUp(self) -> None:
        self.research = ResearchResult(
            proposal_id="proposal-1",
            summary="Research summary",
            findings=["Finding"],
            source_urls=["https://example.com/proposal"],
            limitations=[],
        )
        self.analysis = AnalysisResult(
            proposal_id="proposal-1",
            recommendation="Approve",
            strategy_assessment="Aligned",
            financial_assessment="Affordable",
            alternatives_assessment="No better alternative identified",
            critic_findings=[],
            risk_findings=["Execution risk"],
            evidence_gaps=[],
            review_status="ready_for_human_review",
        )

    def test_report_is_ready_only_when_evidence_is_complete(self) -> None:
        report = build_decision_report("Example proposal", self.research, self.analysis)

        self.assertEqual(report.status, "READY_FOR_HUMAN_REVIEW")

    def test_research_limitations_require_more_evidence(self) -> None:
        self.research.limitations = ["Source could not be independently verified."]

        report = build_decision_report("Example proposal", self.research, self.analysis)

        self.assertEqual(report.status, "MORE_EVIDENCE_REQUIRED")
        self.assertEqual(
            report.evidence_gaps,
            ["Source could not be independently verified."],
        )

    def test_missing_research_evidence_cannot_be_marked_ready(self) -> None:
        self.research.findings = []
        self.research.source_urls = []

        report = build_decision_report("Example proposal", self.research, self.analysis)

        self.assertEqual(report.status, "MORE_EVIDENCE_REQUIRED")
        self.assertEqual(
            report.evidence_gaps,
            [
                "Research agent returned no findings.",
                "Research agent returned no source URLs.",
            ],
        )

    def test_empty_analysis_and_mismatched_ids_cannot_be_marked_ready(self) -> None:
        self.analysis.recommendation = ""
        self.analysis.strategy_assessment = ""
        self.analysis.financial_assessment = ""
        self.analysis.alternatives_assessment = ""
        self.analysis.proposal_id = "different-proposal"

        report = build_decision_report("Example proposal", self.research, self.analysis)

        self.assertEqual(report.status, "MORE_EVIDENCE_REQUIRED")
        self.assertIn(
            "Analysis result proposal ID does not match the research result.",
            report.evidence_gaps,
        )
        self.assertIn("Analysis agent returned no recommendation.", report.evidence_gaps)
        self.assertIn(
            "Analysis agent returned no strategy assessment.",
            report.evidence_gaps,
        )
        self.assertIn(
            "Analysis agent returned no financial assessment.",
            report.evidence_gaps,
        )
        self.assertIn(
            "Analysis agent returned no alternatives assessment.",
            report.evidence_gaps,
        )

    def test_format_report_includes_key_decision_sections(self) -> None:
        report = build_decision_report("Example proposal", self.research, self.analysis)

        formatted = format_report(report)

        self.assertIn("**Recommendation:** Approve", formatted)
        self.assertIn("not independently verified", formatted)
        self.assertIn("**Human review:** Required", formatted)
        self.assertIn("## Risks", formatted)
        self.assertIn("https://example.com/proposal", formatted)


if __name__ == "__main__":
    unittest.main()
