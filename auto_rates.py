"""Extract and compare published vehicle loan APRs."""

from collections import defaultdict
from dataclasses import dataclass
from decimal import Decimal
import re
from urllib.parse import urlsplit

from contract import Answer, Conflict, Snapshot, Source


# The product pages and central rate sheet publish rates. The calculator
# can corroborate a rate or expose a discrepancy, but is illustrative.
PUBLISHERS = (
    "/personal/loans/auto-motorcycle-loans",
    "/personal/loans/auto-loans",
    "/rates",
)
CALCULATOR = "/calculators/vehicle-affordability"
LOAN = re.compile(r"\b(?:auto|car|vehicle)\s+(?:loans?|financing)\b", re.I)
RATE = re.compile(r"\b(?:apr|rates?|annual percentage rate)\b", re.I)
TERM = re.compile(r"\b(\d{1,3})[\s-]*months?\b", re.I)
YEAR = re.compile(r"\b(?:19|20)\d{2}\b")
AS_OF = re.compile(r"\bas of\b", re.I)
AS_OF_DATE = re.compile(r"\bas of\s+(\d{4}-\d{2}-\d{2})\b", re.I)
DATED_PHRASE = re.compile(
    r"\bas of\s+(?:\d{4}-\d{2}-\d{2}|(?:[a-z]+\s+)?(?:\d{1,2},?\s+)?\d{4})\b",
    re.I,
)
TIER = re.compile(
    r"(\d{4})(?:\s*[-–—]\s*(\d{2}|\d{4}))? model year( \(and older\))?",
    re.I,
)
APR = re.compile(r"(\d+(?:\.\d+)?)\s*%\s*(APR\d*)?", re.I)


@dataclass(frozen=True)
class AutoRate:
    months: int
    first_year: int
    last_year: int
    apr: Decimal
    as_low_as: bool
    source: Source
    path: str

    @property
    def official(self) -> bool:
        return self.path in PUBLISHERS


def extract_auto_rates(snapshot: Snapshot) -> list[AutoRate]:
    rates = []
    for page in snapshot.pages:
        path = urlsplit(page.url).path.rstrip("/")
        if path not in (*PUBLISHERS, CALCULATOR):
            continue
        auto_table = False
        mislabeled_calculator = False
        as_low_as = False
        for line in page.markdown.splitlines():
            row = line.strip()
            if not row.startswith("|"):
                auto_table = False
                continue
            cells = [cell.strip() for cell in row.strip("|").split("|")]
            if len(cells) != 3:
                auto_table = False
                continue
            program, term, rate = cells
            labels = (program.casefold(), term.casefold())
            if labels in (("loan program", "term"), ("account type", "balance tier")):
                heading = rate.casefold()
                # The calculator's export can label its loan table as a deposit
                # table. In that format, require APR in the row itself.
                mislabeled_calculator = (
                    path == CALCULATOR and labels == ("account type", "balance tier")
                    and heading == "annual percentage yield"
                )
                auto_table = mislabeled_calculator or (
                    labels == ("loan program", "term")
                    and ("annual percentage rate" in heading or "apr" in heading)
                )
                as_low_as = "as low as" in heading
                continue
            tier = TIER.fullmatch(program)
            months = TERM.fullmatch(term)
            apr = APR.fullmatch(rate)
            if not (auto_table and tier and months and apr):
                continue
            if mislabeled_calculator and not apr[2]:
                continue
            start, end, older = tier.groups()
            first = int(start)
            last = int(start[:2] + end if end and len(end) == 2 else end or start)
            rates.append(AutoRate(
                int(months[1]), 0 if older else first, last, Decimal(apr[1]),
                as_low_as, Source(page.url, snapshot.snapshot_id, row), path,
            ))
    return rates


def is_auto_rate_question(question: str) -> bool:
    return bool(LOAN.search(question) and RATE.search(question))


def _year_label(first: int, last: int) -> str:
    if not first:
        return f"{last} and older"
    return str(first) if first == last else f"{first}–{last}"


def _apr_label(value: Decimal) -> str:
    return f"{value:f}%"


def answer_auto_rate(question: str, rates: list[AutoRate]) -> Answer:
    terms = {int(term) for term in TERM.findall(question)}
    years = {int(year) for year in YEAR.findall(DATED_PHRASE.sub("", question))}
    if len(terms) != 1 or len(years) != 1:
        return Answer("Please specify one loan term and one vehicle model year.", confident=False)
    months, year = next(iter(terms)), next(iter(years))
    candidates = [r for r in rates if r.months == months and r.first_year <= year <= r.last_year]
    official = [r for r in candidates if r.official]
    if not official:
        return Answer("I couldn't verify a published APR for that term and model year.", confident=False)
    if len({r.apr for r in official}) > 1:
        return Answer("I couldn't verify a single APR because the published rates disagree.", confident=False)
    winner = min(official, key=lambda r: (PUBLISHERS.index(r.path), r.source.url))
    note = None
    if any(not r.official and r.apr != winner.apr for r in candidates):
        note = "The published loan rate takes precedence over the calculator's illustrative rate."
    amount = _apr_label(winner.apr)
    qualifier = "as low as " if winner.as_low_as else ""
    return Answer(
        f"The published {months}-month auto loan rate for a {year} vehicle is {qualifier}{amount} APR.",
        [winner.source],
        conflict_note=note,
    )


def auto_rate_conflicts(rates: list[AutoRate]) -> list[Conflict]:
    """Compare only rows that apply to the same term and overlapping model years."""
    by_term = defaultdict(list)
    for rate in rates:
        by_term[rate.months].append(rate)

    conflicts = []
    for months, rows in sorted(by_term.items()):
        # Split at tier boundaries so all claims in a segment cover the same years.
        edges = sorted({edge for r in rows for edge in (r.first_year, r.last_year + 1)})
        for first, end in zip(edges, edges[1:]):
            claims = [r for r in rows if r.first_year <= first <= r.last_year]
            values = {r.apr for r in claims}
            official_values = {r.apr for r in claims if r.official}
            if len(values) < 2 or not official_values:
                continue
            winner = next(iter(official_values)) if len(official_values) == 1 else None
            evidence = {}
            for claim in sorted(claims, key=lambda r: (
                r.apr, PUBLISHERS.index(r.path) if r.official else len(PUBLISHERS), r.source.url
            )):
                evidence.setdefault(claim.apr, claim.source)
            conflicts.append(Conflict(
                topic=f"{months}-month auto loan APR, model years {_year_label(first, end - 1)}",
                values=[_apr_label(value) for value in sorted(values)],
                sources=list(evidence.values()),
                resolution=_apr_label(winner) if winner is not None else None,
                reason=(
                    "The published loan rate takes precedence over the calculator's illustrative rate."
                    if winner is not None else "Official rate tables disagree for the same term and model years."
                ),
            ))
    return conflicts
