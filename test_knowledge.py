"""Behavior checks on evidence that does not come from the public questions."""

import unittest

from contract import Page, Snapshot
from solution import build

ROOT = "https://example.test"


def page(path, title, text):
    return Page(ROOT + path, title, text, "")


def deposit(rate, effective):
    return page("/rates", "Rates", (
        "| Account Type | Balance Tier | Dividend Rate | Annual Percentage Yield |\n"
        "| --- | --- | --- | --- |\n"
        f"| Share Savings | $5,000+ | {rate}% | {rate}% |\n"
        "| Share Savings | $0 – $4,999.99 | 0.10% | 0.10% |\n\n"
        f"Rates are effective as of {effective}."
    ))


class KnowledgeTests(unittest.TestCase):
    def test_balance_boundary_and_historical_correction(self):
        system = build()
        system.ingest(Snapshot("jan", "2026-01-05", [deposit("2.00", "01/01/2026")]))
        system.ingest(Snapshot("feb", "2026-02-05", [deposit("2.10", "01/01/2026")]))
        system.ingest(Snapshot("mar", "2026-03-05", [deposit("2.50", "03/01/2026")]))
        question = "What APY does Share Savings pay on $5,000?"
        for cutoff, value, crawl in (
            ("2026-02-04", "2.00", "jan"), ("2026-02-10", "2.10", "feb"), (None, "2.50", "mar")
        ):
            with self.subTest(cutoff=cutoff):
                answer = system.answer(question, cutoff)
                self.assertTrue(answer.confident)
                self.assertIn(value + "% APY", answer.text)
                self.assertEqual(answer.sources[0].snapshot_id, crawl)
        self.assertIn("0.10% APY", system.answer(question.replace("$5,000", "$4,999.99")).text)
        apy, = [c for c in system.conflicts() if c.topic.endswith("APY")]
        self.assertEqual(set(apy.values), {"2.00%", "2.10%"})
        self.assertEqual(apy.resolution, "2.10%")

    def test_expired_offer_is_not_used_for_current_answer(self):
        system = build()
        published = page("/rates/certificates", "Certificates", "9-month certificate APY: 3.70%")
        expired = page("/offers/winter", "Winter offer", "9-month certificate APY 4.90% (offer ended 2026-01-31)")
        system.ingest(Snapshot("feb", "2026-02-05", [published, expired]))
        answer = system.answer("What APY is offered on a nine month certificate?")
        self.assertIn("3.70% APY", answer.text)
        self.assertNotIn("4.90%", answer.text)
        conflict, = system.conflicts()
        self.assertEqual(conflict.resolution, "3.70%")
        self.assertEqual({source.url for source in conflict.sources}, {published.url, expired.url})
        self.assertFalse(system.answer("What is the 9-month jumbo certificate APY?").confident)

    def test_missing_location_and_unverified_historical_fee(self):
        system = build()
        fees = page("/fees", "Fees", "Safe deposit box re-key fee: $37.50")
        contact = page("/contact", "Branch locator", "129 Market Road, Riverton, IA, 50001")
        system.ingest(Snapshot("jan", "2026-01-05", [fees, contact]))
        system.ingest(Snapshot("feb", "2026-02-05", [contact]))
        answer = system.answer("What is the safe deposit box re-key fee?")
        self.assertFalse(answer.confident)
        self.assertIn("$37.50", answer.text)
        self.assertEqual(answer.sources[0].snapshot_id, "jan")
        self.assertFalse(system.answer("What are the lobby hours for the Oakwood branch?").confident)
        self.assertTrue(system.answer("What is the address of the Riverton branch?").confident)


if __name__ == "__main__":
    unittest.main()
