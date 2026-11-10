"""Offline answers from dated website snapshots."""

from datetime import date
from dataclasses import dataclass

from contract import Answer, Conflict, Snapshot

from auto_rates import (
    AS_OF,
    AS_OF_DATE,
    AutoRate,
    answer_auto_rate,
    auto_rate_conflicts,
    extract_auto_rates,
    is_auto_rate_question,
)
from evidence import EvidenceIndex
from rate_tables import Rate, answer_rate, extract_rates, historical_rate_conflicts, resolved_rates


@dataclass
class IndexedSnapshot:
    auto: list[AutoRate]
    rates: list[Rate]
    evidence: EvidenceIndex


class WebsiteKnowledge:
    def __init__(self):
        self.snapshots: dict[date, IndexedSnapshot] = {}

    def ingest(self, snapshot: Snapshot) -> None:
        indexed = IndexedSnapshot(extract_auto_rates(snapshot), extract_rates(snapshot), EvidenceIndex(snapshot))
        self.snapshots[date.fromisoformat(snapshot.taken_on)] = indexed

    def answer(self, question: str, as_of: str | None = None) -> Answer:
        auto_rate = is_auto_rate_question(question)
        if as_of is None and AS_OF.search(question):
            inline_date = AS_OF_DATE.search(question)
            if inline_date is None:
                return Answer("Please provide the date in YYYY-MM-DD format.", confident=False)
            as_of = inline_date[1]
        try:
            cutoff = date.fromisoformat(as_of) if as_of is not None else date.max
        except ValueError:
            return Answer("Please provide the date in YYYY-MM-DD format.", confident=False)
        selected = max((day for day in self.snapshots if day <= cutoff), default=None)
        if selected is None:
            return Answer("I don't have a website snapshot for that date.", confident=False)

        snapshot = self.snapshots[selected]
        if auto_rate:
            return answer_auto_rate(question, snapshot.auto)
        rates, _ = resolved_rates(snapshot.rates, cutoff if as_of is not None else selected)
        structured = answer_rate(question, rates)
        if structured is not None:
            return structured
        answer = snapshot.evidence.answer(question, selected)
        if (not answer.confident and snapshot.evidence.is_fee_question(question)
                and not snapshot.evidence.has_fee_schedule()):
            for earlier in sorted((day for day in self.snapshots if day < selected), reverse=True):
                older = self.snapshots[earlier].evidence
                if older.has_fee_schedule():
                    last_known = older.fee(question)
                    if last_known.confident:
                        return Answer(
                            f"I couldn't verify a current fee. The schedule captured on {earlier.isoformat()} lists: "
                            f"{last_known.text}",
                            last_known.sources,
                            confident=False,
                        )
                    break
        return answer

    def conflicts(self) -> list[Conflict]:
        # When the same conflict recurs, cite its most recent observation.
        observed = {}
        history = []
        for day in sorted(self.snapshots, reverse=True):
            snapshot = self.snapshots[day]
            rates, rate_conflicts = resolved_rates(snapshot.rates, day)
            history.append((day, rates))
            for conflict in auto_rate_conflicts(snapshot.auto) + rate_conflicts + snapshot.evidence.conflicts():
                key = (conflict.topic, tuple(sorted(conflict.values)), conflict.resolution)
                observed.setdefault(key, conflict)
        for conflict in historical_rate_conflicts(history):
            key = (conflict.topic, tuple(sorted(conflict.values)), conflict.resolution)
            observed.setdefault(key, conflict)
        return list(observed.values())

def build() -> WebsiteKnowledge:
    return WebsiteKnowledge()
