"""Contract tests using fabricated rates and snapshots."""

import unittest

from contract import Page, Snapshot
from solution import build

PRODUCT = "https://example.test/personal/loans/auto-motorcycle-loans"
RATE_SHEET = "https://example.test/rates"
CALCULATOR = "https://example.test/calculators/vehicle-affordability"
QUESTION = "What's the APR on a 60-month car loan for a 2020 vehicle?"


def page(url, *rows, header="| Loan Program | Term | Annual Percentage Rate (As Low As) |"):
    table = "\n".join((header, "| --- | --- | --- |", *rows))
    return Page(url, "", table, "2026-02-01")


class AutoRateTests(unittest.TestCase):
    def test_current_and_historical_answers_cite_the_applicable_row(self):
        engine = build()
        old = "| 2019–21 Model Year | 60 Months | 4.10% APR |"
        new = "| 2020-22 Model Year | 60 Months | 4.25% APR1 |"
        stale = "| 2019–21 Model Year | 60 Months | 4.10% APR |"
        engine.ingest(Snapshot("old", "2026-01-01", [page(PRODUCT, old)]))
        calculator = page(
            CALCULATOR,
            stale,
            "| 2019–21 Model Year | 60 Months | 9.99% |",
            "| Jumbo Certificate | 60 Months | 3.00% APY |",
            header="| Account Type | Balance Tier | Annual Percentage Yield |",
        )
        engine.ingest(Snapshot("new", "2026-02-01", [page(PRODUCT, new), calculator]))

        historical = engine.answer(QUESTION, as_of="2026-01-31")
        self.assertIn("4.10% APR", historical.text)
        self.assertEqual(historical.sources[0].snapshot_id, "old")
        self.assertEqual(engine.answer(f"{QUESTION} As of 2026-01-31"), historical)
        self.assertFalse(engine.answer(f"{QUESTION} As of January 2026").confident)
        self.assertFalse(engine.answer(QUESTION, as_of="2025-12-31").confident)

        for question in (QUESTION, "What is the auto financing rate for a 2020 model over 60 months?",
                         "What's the 60-month auto-loan APR for a 2020 vehicle?",
                         "What APR is available for a five-year auto loan on a 2020 model?"):
            current = engine.answer(question)
            self.assertTrue(current.confident)
            self.assertIn("as low as 4.25% APR", current.text)
            self.assertNotIn("4.10%", current.text)
            self.assertEqual(current.sources[0].snapshot_id, "new")
            self.assertEqual(current.sources[0].url, PRODUCT)
            self.assertEqual(current.sources[0].quote, new)
            self.assertTrue(current.conflict_note)

        conflict, = engine.conflicts()
        self.assertIn("2020–2021", conflict.topic)
        self.assertEqual(set(conflict.values), {"4.10%", "4.25%"})
        self.assertEqual(conflict.resolution, "4.25%")
        self.assertEqual({source.url for source in conflict.sources}, {PRODUCT, CALCULATOR})
        self.assertFalse(engine.answer("What is the maximum APR on a five-year auto loan for a 2020 model?").confident)

    def test_other_terms_and_nonoverlapping_tiers_are_not_conflicts(self):
        engine = build()
        engine.ingest(Snapshot("one", "2026-02-01", [
            page(PRODUCT, "| 2020-22 Model Year | 60 Months | 4.25% APR |",
                 "| 2020-22 Model Year | 48 Months | 4.00% APR |"),
            page(CALCULATOR, "| 2018-19 Model Year | 60 Months | 5.25% APR |"),
        ]))
        self.assertIn("4.00% APR", engine.answer(QUESTION.replace("60-month", "48-month")).text)
        self.assertFalse(engine.answer(QUESTION.replace("2020", "2019")).confident)
        self.assertFalse(engine.answer(QUESTION.replace("2020", "2024")).confident)
        self.assertEqual(engine.conflicts(), [])

    def test_equally_authoritative_sources_disagree(self):
        engine = build()
        engine.ingest(Snapshot("one", "2026-02-01", [
            page(PRODUCT, "| 2020-22 Model Year | 60 Months | 4.25% APR |"),
            page(RATE_SHEET, "| 2020-22 Model Year | 60 Months | 4.30% APR |"),
        ]))
        self.assertFalse(engine.answer(QUESTION).confident)
        conflict, = engine.conflicts()
        self.assertIsNone(conflict.resolution)
        self.assertFalse(engine.answer("What is the auto loan rate?").confident)


if __name__ == "__main__":
    unittest.main()
