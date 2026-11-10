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

    def test_routing_number_and_branch_service_require_the_right_subject(self):
        system = build()
        contact = page("/contact", "Contact", "Our routing number: 012345678")
        membership = page("/membership", "Membership", "Safe-deposit boxes and notary services are member benefits.")
        branch = page("/locations/riverton", "Riverton", "Safe deposit boxes are available at the Riverton branch.")
        system.ingest(Snapshot("current", "2026-02-01", [contact, membership, branch]))
        for question in ("What is the routing number for North Star Bank?", "What is North Star Bank's routing number?",
                         "Do you have safe deposit boxes at the Oakwood branch?"):
            with self.subTest(question=question):
                answer = system.answer(question)
                self.assertFalse(answer.confident)
                self.assertEqual(answer.sources, [])
        routing = system.answer("What is your routing number?")
        self.assertTrue(routing.confident)
        self.assertEqual(routing.sources[0].url, contact.url)
        service = system.answer("Do you have safe deposit boxes at the Riverton branch?")
        self.assertTrue(service.confident)
        self.assertEqual(service.sources[0].quote, branch.markdown)

    def test_shared_deposit_label_preserves_customer_segment_and_both_metrics(self):
        system = build()
        personal = deposit("2.00", "01/01/2026")
        business = page("/business/rates", "Business rates", personal.markdown.replace("2.00% | 2.00%", "2.80% | 2.85%"))
        system.ingest(Snapshot("jan", "2026-01-05", [personal, business]))
        system.ingest(Snapshot("feb", "2026-02-05", [personal]))
        ask = "What are the dividend rate and APY for business Share Savings on $5,000?"
        answer = system.answer(ask, as_of="2026-01-31")
        self.assertTrue(answer.confident)
        self.assertIn("2.80% dividend rate", answer.text)
        self.assertIn("2.85% APY", answer.text)
        self.assertEqual([(s.url, s.snapshot_id) for s in answer.sources], [(business.url, "jan")])
        self.assertFalse(system.answer(ask).confident)
        self.assertEqual(system.conflicts(), [])
        for product in ("Quantum Savings", "a Quantum Savings account"):
            self.assertFalse(system.answer(f"What APY does {product} pay on $5,000?").confident)
        self.assertTrue(system.answer("What APY does a savings account pay on $5,000?").confident)

    def test_loan_apr_requires_the_right_product_amount_and_term(self):
        system = build()
        small_boat = "| $10,000-24,999 | 36 Months | 7.20% |"
        large_boat = "| $25,000-39,999 | 60 Months | 7.10% |"
        atv = "| Model Year 2026-23 | 36 Months | 8.30% |"
        header = "| Loan Type | Term | APR (As Low As) |\n| --- | --- | --- |"
        recreational = page("/personal/loans/recreational-loans", "Recreational loans", "\n".join((
            "## Boat & RV Loan Rates", "", header, small_boat, large_boat, "",
            "ATV, Snowmobile & Jet Ski Loans", "", header, atv,
        )))
        personal = page("/personal/loans/personal-loans", "Personal loans", (
            "| Term | APR (As Low As) |\n| --- | --- |\n| 36 Months | 10.50% |"
        ))
        system.ingest(Snapshot("current", "2026-02-01", [recreational, personal]))
        question = "What's the APR on a $30,000 boat loan over 36 months?"
        self.assertFalse(system.answer(question).confident)
        self.assertFalse(system.answer(question.replace("$30,000", "$9,999")).confident)
        for question, row in ((question.replace("36", "60"), large_boat),
                              (question.replace("$30,000", "$24,999"), small_boat),
                              ("What's the APR on a 36-month 2024 model ATV loan?", atv)):
            with self.subTest(question=question):
                answer = system.answer(question)
                self.assertTrue(answer.confident)
                self.assertEqual([source.quote for source in answer.sources], [row])
        self.assertFalse(system.answer("What's the APR on a 36-month 2018 model ATV loan?").confident)
        self.assertFalse(system.answer("What is the maximum APR on a personal loan for 36 months?").confident)
        self.assertIn("as low as 10.50% APR", system.answer("What is the APR on a 36-month personal loan?").text)

    def test_two_named_cards_return_both_citations(self):
        system = build()
        cards = page("/rates", "Rates", (
            "| Card Type | APR |\n| --- | --- |\n| Platinum Visa | 11.25%–15.75% |\n"
            "| Rewards Visa | 13.25%–17.75% |\n| Business Platinum Visa | 13.99% |"
        ))
        system.ingest(Snapshot("current", "2026-02-01", [cards]))
        answer = system.answer("What are the APRs for Platinum Visa and Rewards Visa?")
        self.assertTrue(answer.confident)
        self.assertEqual({source.quote for source in answer.sources}, set(cards.markdown.splitlines()[2:4]))


if __name__ == "__main__":
    unittest.main()
