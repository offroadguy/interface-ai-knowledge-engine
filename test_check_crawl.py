"""Exercise the release decision against healthy and incomplete snapshots."""

from dataclasses import replace
import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from contract import Page, Snapshot
from scripts.check_crawl import Probe, check_crawl, load_probes

HEADER = "| Loan Program | Term | Annual Percentage Rate (As Low As) |\n| --- | --- | --- |"
AUTO_ROWS = (
    "| 2024-27 Model Year | 48 Months | 4.75% APR |",
    "| 2024-27 Model Year | 60 Months | 5.25% APR |",
)
PROBES = tuple(
    Probe(f"auto-{months}", f"What's the {months}-month auto loan APR for a 2025 vehicle?",
          f"The published {months}-month auto loan rate for a 2025 vehicle is as low as {rate}% APR.",
          "https://example.test/rates", row)
    for (months, rate), row in zip(((48, "4.75"), (60, "5.25")), AUTO_ROWS)
)


def auto_table(path, rows):
    return Page(f"https://example.test{path}", "Auto rates", "\n".join((HEADER, *rows)), "")


class CrawlCheckTests(unittest.TestCase):
    def test_loss_of_one_of_two_official_rate_facts_holds_the_candidate(self):
        reference = Snapshot("validated", "2026-01-01", [auto_table("/rates", AUTO_ROWS)])
        candidate = Snapshot("candidate", "2026-02-01", [
            auto_table("/rates", AUTO_ROWS[:1]),
            auto_table("/personal/loans/auto-loans", AUTO_ROWS[:1]),
            auto_table("/calculators/vehicle-affordability", AUTO_ROWS),
        ])

        report = check_crawl(reference, candidate)
        self.assertEqual(report["decision"], "hold")
        self.assertEqual(report["coverage"]["auto"], {"reference": 2, "candidate": 1})

    def test_rate_change_and_legacy_ira_header_do_not_hold_a_healthy_crawl(self):
        def ira_table(header):
            text = (f"| {header} | Dividend Rate | APY | Min. to Earn |\n"
                    "| --- | --- | --- | --- |\n"
                    "| Roth: 12 Month | 3.00% | 3.04% | $500 |")
            return Page("https://example.test/rates", "Rates", text, "")

        reference = Snapshot("validated", "2026-01-01", [
            ira_table("Term"), auto_table("/personal/loans/auto-loans", AUTO_ROWS),
        ])
        updated = tuple(row.replace("5.25%", "5.50%") for row in AUTO_ROWS)
        candidate = Snapshot("candidate", "2026-02-01", [
            ira_table("IRA Type"), auto_table("/personal/loans/auto-loans", updated),
        ])
        report = check_crawl(reference, candidate)
        self.assertEqual(report["decision"], "pass")
        self.assertEqual(report["coverage"]["ira"], {"reference": 2, "candidate": 2})
        self.assertNotIn("certificate", report["coverage"])

    def test_stale_candidate_and_empty_reference_fail_closed(self):
        snapshot = Snapshot("dated", "2026-02-01", [auto_table("/rates", AUTO_ROWS)])
        with self.assertRaisesRegex(ValueError, "newer"):
            check_crawl(snapshot, snapshot)
        with self.assertRaisesRegex(ValueError, "no usable"):
            check_crawl(Snapshot("empty", "2026-01-01", []), snapshot)

    def test_probes_hold_replaced_tier_and_corrupted_rate_at_equal_coverage(self):
        reference = Snapshot("validated", "2026-01-01", [auto_table("/rates", AUTO_ROWS)])
        candidate = Snapshot("candidate", "2026-02-01", [auto_table("/rates", (
            AUTO_ROWS[0].replace("48 Months", "72 Months"), AUTO_ROWS[1].replace("5.25%", "99.99%"),
        ))])
        self.assertEqual(check_crawl(reference, candidate)["decision"], "pass")
        report = check_crawl(reference, candidate, probes=PROBES)
        self.assertEqual(report["decision"], "hold")
        self.assertEqual(report["coverage"]["auto"], {"reference": 2, "candidate": 2})
        self.assertEqual(report["probes"], {"total": 2, "failed": 2})
        self.assertEqual([failure.split(":")[0] for failure in report["failures"]], ["probe auto-48", "probe auto-60"])

    def test_probe_config_and_candidate_citation(self):
        reference = Snapshot("validated", "2026-01-01", [auto_table("/rates", AUTO_ROWS)])
        candidate = replace(reference, snapshot_id="candidate", taken_on="2026-02-01")
        with TemporaryDirectory() as directory:
            path = Path(directory) / "probes.json"
            record = vars(PROBES[0])
            for bad in ([], [{"id": "only"}], [record, record]):
                path.write_text(json.dumps(bad), encoding="utf-8")
                with self.assertRaises(ValueError):
                    load_probes(path)
            path.write_text(json.dumps([record]), encoding="utf-8")
            probes = load_probes(path)
        self.assertEqual(check_crawl(reference, candidate, probes=probes)["decision"], "pass")
        for probe in (replace(probes[0], source_url="https://example.test/elsewhere"),
                      replace(probes[0], source_quote=AUTO_ROWS[1])):
            report = check_crawl(reference, candidate, probes=(probe,))
            self.assertEqual(report["decision"], "hold")
            self.assertEqual(report["failures"], ["probe auto-48: expected citation was not verified"])
