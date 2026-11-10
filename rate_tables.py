"""Published rates with explicit product, term, and tier qualifiers."""

from collections import defaultdict
from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal
from itertools import groupby
import re
from urllib.parse import urlsplit

from contract import Answer, Conflict, Snapshot, Source

PERCENT = re.compile(r"(\d+(?:\.\d+)?)\s*%")
MONEY = re.compile(r"\$\s*(\d[\d,]*(?:\.\d+)?)(?:\s*([kKmM])\b)?")
TERM = re.compile(r"\b(\d+)\s*[-– ]?\s*(month|year)s?\b", re.I)
NUMBER_WORDS = dict(zip("one two three four five six seven eight nine ten eleven twelve".split(), range(1, 13)))
EFFECTIVE = re.compile(r"effective(?:\s+as of)?\s*:?\s*(\d{1,2}/\d{1,2}/\d{4})", re.I)
EXPIRES = re.compile(r"(?:offer expires|available (?:through|until))\s*(\d{1,2}/\d{1,2}/\d{4})", re.I)
SEPARATOR = re.compile(r":?-{3,}:?")
DEPOSIT = {"deposit", "certificate", "ira"}
RATE_WORD = re.compile(r"\b(?:rates?|aprs?|apys?|dividends?|yields?|interest)\b")
CARD = re.compile(r"\b(?:credit cards?|visa|platinum card|rewards card)\b")
MORTGAGE = re.compile(r"\b(?:mortgages?|home loans?|refinanc\w*|arm|construction loans?)\b")


def normalize(value):
    return " ".join(re.findall(r"[a-z0-9]+", value.casefold()))


def cells(line):
    return tuple(cell.strip() for cell in line.strip().strip("|").split("|"))


def amounts(text):
    return [Decimal(value.replace(",", "")) * {"k": 1000, "m": 1000000}.get(unit.lower(), 1)
            for value, unit in MONEY.findall(text)]


def term_months(text):
    text = re.sub(r"\b(" + "|".join(NUMBER_WORDS) + r")(?=[ -]+(?:months?|years?)\b)",
                  lambda match: str(NUMBER_WORDS[match[1]]), text.casefold())
    return {int(number) * (12 if unit == "year" else 1) for number, unit in TERM.findall(text)}


def _date(pattern, text):
    match = pattern.search(text)
    if match:
        try:
            return datetime.strptime(match[1], "%m/%d/%Y").date()
        except ValueError:
            pass
    return None


@dataclass(frozen=True)
class Rate:
    kind: str
    product: str
    tier: str
    metrics: tuple[tuple[str, str], ...]
    source: Source
    authority: int
    effective: date | None
    expires: date | None

    @property
    def key(self):
        tier = MONEY.sub(lambda match: f"usd {format(amounts(match[0])[0].normalize(), 'f')}", self.tier)
        product = normalize(self.product)
        if self.kind in ("certificate", "business certificate"):
            product = re.sub(r"\b(?:fixed|term|share|certificate|certificates|months?)\b", "", product)
        return self.kind, normalize(product), normalize(tier)

    def value(self, metric):
        return dict(self.metrics).get(metric, "")


def _columns(headers):
    return {
        index: ("APY" if "yield" in header or "apy" in header else
                "dividend rate" if "dividend" in header else
                "APR" if "apr" in header or "annual percentage rate" in header else "interest rate")
        for index, header in enumerate(headers)
        if header == "rate" or any(key in header for key in ("yield", "apy", "dividend rate", "apr", "annual percentage rate"))
    }


def _classify(headers, row, context, path):
    first = headers[0]
    if first == "account type":
        return "deposit", row[0], row[1]
    if first in ("certificate", "ira type") or (
        first == "term" and "min to earn" in headers and "dividend rate" in headers
    ):
        kind = "ira" if first == "ira type" or path.startswith("/personal/retirement") else "certificate"
        if kind == "certificate" and path.startswith("/business/"):
            kind = "business certificate"
        return kind, row[0], row[-1]
    if first == "card type":
        card = re.search(r"\b(?:(?:business) )?(?:platinum|rewards) visa\b", normalize(row[0]))
        if not card:
            cards = list(re.finditer(r"\b(?:(?:business) )?(?:platinum|rewards) visa\b", normalize(context)))
            card = cards[-1] if cards else None
        if card:
            label = card[0].title()
            tier = "introductory balance transfer" if "introductory" in normalize(row[0]) else "standard purchase"
            return "card", label, tier
    if first == "program" and "points" in headers:
        if path not in ("/rates", "/personal/loans/home-loans", "/personal/loans/home-equity"):
            return None
        kind = "home equity refinance" if "home equity refinance" in normalize(context) else "mortgage"
        return kind, row[0].replace(",", ""), ""
    if first == "term" and ("personal loan" in normalize(context) or path.endswith("/personal-loans")):
        return "loan", "Personal loan", row[0]
    if first == "product":
        return "loan", row[0], ""
    if first in ("loan amount", "loan type"):
        label = ("Home improvement loan" if first == "loan amount" else
                 "Boat and RV loan" if re.search(r"boat|rv", context, re.I) else
                 "Motorcycle and powersport loan" if re.search(r"motorcycle|powersport", context, re.I) else "")
        if label and len(row) > 2:
            return "loan", label, " · ".join(row[:2])
    return None


def extract_rates(snapshot: Snapshot) -> list[Rate]:
    result = []
    for page in snapshot.pages:
        path = urlsplit(page.url).path.rstrip("/")
        if path in ("/rates", "/business/rates") or path.startswith("/rates/"):
            authority = 3
        elif path.startswith(("/personal/", "/business/")) and not path.startswith("/business/resources/"):
            authority = 3
        elif path.startswith(("/calculators/", "/promo", "/offers/")):
            authority = 1
        else:
            continue
        context = []
        all_lines = page.markdown.splitlines()
        offset = 0
        for is_table, block in groupby(all_lines, key=lambda line: line.lstrip().startswith("|")):
            lines = list(block)
            offset += len(lines)
            if not is_table:
                context.extend(line.strip().lstrip("# ").strip() for line in lines
                               if 0 < len(line.strip()) < 95 and "[" not in line)
                if path == "/personal/credit-cards":
                    for line in lines:
                        rate = re.search(r"\b(?:ongoing|competitive|standard) rate\b[^\n]*?(\d[\d.]*%)\s*[-–]\s*(\d[\d.]*%)\s*APR", line, re.I)
                        if not rate:
                            continue
                        preceding = "\n".join(all_lines[:offset]).rsplit(line, 1)[0]
                        cards = re.findall(r"(?im)^#{2,5}\s+((?:platinum|rewards) visa)\s*$", preceding)
                        if cards:
                            result.append(Rate("card", cards[-1].title(), "standard purchase",
                                               (("APR", f"{rate[1]}–{rate[2]}"),),
                                               Source(page.url, snapshot.snapshot_id, line.strip()),
                                               authority, None, None))
                if path.startswith(("/rates/", "/promo", "/offers/")):
                    for line in lines:
                        certificate = re.search(
                            r"\b(\d+[- ]months?\s+(?:(?:fixed|jumbo|share)\s+)*certificate(?:\s+special)?)"
                            r"\s+APY\s*:?\s*(\d+(?:\.\d+)?%)", line, re.I)
                        if certificate:
                            ended = re.search(r"(?:ends|ended|expires)\s+(\d{4}-\d{2}-\d{2})", line, re.I)
                            try:
                                expires = date.fromisoformat(ended[1]) if ended else None
                            except ValueError:
                                expires = None
                            result.append(Rate("certificate", certificate[1], "", (("APY", certificate[2]),),
                                               Source(page.url, snapshot.snapshot_id, line.strip()),
                                               authority, None, expires))
                continue
            if len(lines) < 3 or not all(SEPARATOR.fullmatch(c) for c in cells(lines[1])):
                continue
            header = tuple(normalize(c) for c in cells(lines[0]))
            columns = _columns(header)
            if not columns:
                continue
            # Find the table footnote directly after the rows, before the next table.
            tail = "\n".join(all_lines[offset:offset + 40]).split("\n|", 1)[0][:1200]
            effective, expires = _date(EFFECTIVE, tail), _date(EXPIRES, tail)
            for line in lines[2:]:
                row = cells(line)
                if len(row) != len(header):
                    continue
                label = _classify(header, row, " ".join(context[-3:]), path)
                if label is None:
                    continue
                metrics = tuple((metric, "–".join(f"{number}%" for number in PERCENT.findall(row[i])))
                                for i, metric in columns.items() if PERCENT.search(row[i]))
                if metrics:
                    result.append(Rate(*label, metrics, Source(page.url, snapshot.snapshot_id, line.strip()),
                                       authority, effective, expires))
    return result


def resolved_rates(rows, cutoff):
    """Resolve each fact using official sources and explicit effective dates."""
    facts = defaultdict(list)
    for row in rows:
        if row.effective is None or row.effective <= cutoff:
            facts[row.key].append(row)
    winners, conflicts = [], []
    for claims in facts.values():
        # Compare a metric only to itself. Repeated copies are one value.
        by_metric = defaultdict(list)
        for row in claims:
            for metric, value in row.metrics:
                by_metric[metric].append((row, value))
        for metric, entries in by_metric.items():
            active = [(row, value) for row, value in entries if row.expires is None or cutoff <= row.expires]
            if not active:
                continue
            top_rank = max((row.authority, row.effective or date.min) for row, _ in active)
            top = [(row, value) for row, value in active
                   if (row.authority, row.effective or date.min) == top_rank]
            values = {_numeric_value(value) for _, value in top}
            winner = None
            if len(values) == 1 and top_rank[0] >= 3:
                # A product page gives more context than a duplicate on the central sheet.
                compatible = [(row, item) for row, item in active
                              if _numeric_value(item) in values and row.authority == top_rank[0]]
                winner, value = min(compatible, key=lambda pair: (
                    urlsplit(pair[0].source.url).path.rstrip("/").endswith("/rates"),
                    -(pair[0].effective or date.min).toordinal(), pair[0].source.url))
                winners.append((winner, metric, value))
            unique = {}
            for row, value in entries:
                unique.setdefault(_numeric_value(value), (value, row.source))
            if len(unique) > 1 and top_rank[0] >= 3:
                label = entries[0][0]
                if winner:
                    winning_value = winner.value(metric)
                    unique[_numeric_value(winning_value)] = (winning_value, winner.source)
                ordered = [unique[key] for key in sorted(unique)]
                expired = any(row.expires and row.expires < cutoff for row, _ in entries)
                conflicts.append(Conflict(
                    " ".join(filter(None, (label.product, label.tier, metric))),
                    [value for value, _ in ordered], [source for _, source in ordered],
                    winner.value(metric) if winner else None,
                    ("Prefer the active official rate over expired evidence." if winner and expired else
                     "Prefer official rates and the latest stated effective date." if winner else
                     "Equally authoritative rates disagree for the same product and tier."),
                ))
    return winners, conflicts


def _numeric_value(value):
    return tuple(Decimal(number) for number in PERCENT.findall(value))


def historical_rate_conflicts(observations):
    """Report changed claims that purport to describe the same effective period."""
    periods = defaultdict(dict)
    for crawl, rows in sorted(observations):
        for row, metric, value in rows:
            if row.effective is not None:
                key = row.key, metric, row.effective
                periods[key][_numeric_value(value)] = (crawl, row, value)
    output = []
    for (_, metric, effective), claims in periods.items():
        if len(claims) < 2 or len({day for day, _, _ in claims.values()}) < 2:
            continue
        ranked = sorted(claims.values(), key=lambda item: (item[0], item[2]), reverse=True)
        latest, label, value = ranked[0]
        # Each observation has already passed the same-crawl precedence rules.
        if ranked[1][0] == latest:
            value = None
        output.append(Conflict(
            " ".join(filter(None, (label.product, label.tier, metric))),
            [v for _, _, v in ranked], [row.source for _, row, _ in ranked], value,
            f"Crawls disagree for the same published effective date ({effective.isoformat()}). "
            "Prefer the latest unambiguous official observation.",
        ))
    return output


def _deposit_rows(question, entries, kind):
    q = normalize(question)
    if kind == "deposit":
        wants_business = "business" in q
        entries = [item for item in entries if (
            "business" in normalize(item[0].product) or
            urlsplit(item[0].source.url).path.startswith("/business/")
        ) == wants_business]
    if kind in ("certificate", "business certificate", "ira"):
        entries = [item for item in entries if
                   ("jumbo" not in q or "jumbo" in normalize(item[0].product))
                   and ("special" not in q or "special" in normalize(item[0].product))
                   and ("roth" not in q or "roth" in normalize(item[0].product))
                   and ("traditional" not in q or "traditional" in normalize(item[0].product))]
        months = term_months(question)
        if months:
            entries = [item for item in entries if months & term_months(item[0].product)]
    else:
        named = {normalize(item[0].product) for item in entries if normalize(item[0].product) in q}
        if named:
            entries = [item for item in entries if normalize(item[0].product) in named]
        elif "checking" in q:
            entries = [item for item in entries if "checking" in normalize(item[0].product)]
        elif "money market" in q:
            entries = [item for item in entries if "money market" in normalize(item[0].product)]
        elif "savings" in q:
            entries = [item for item in entries if "savings" in normalize(item[0].product)]
    balance = amounts(question)
    if balance:
        def covers(item):
            tier = amounts(item[0].tier)
            if kind in ("certificate", "business certificate", "ira"):
                return not tier or min(balance) >= tier[0]
            return not tier or (tier[0] <= min(balance) and (len(tier) == 1 or max(balance) <= tier[-1]))
        entries = [item for item in entries if covers(item)]
    return entries


def answer_rate(question: str, resolved):
    """Return None for a non-rate question, otherwise a grounded answer or abstention."""
    q = question.casefold()
    if not RATE_WORD.search(q) or re.search(r"\b(?:link|url|website|where (?:can|do) i (?:find|see))\b", q):
        return None
    if re.search(r"\b(?:ira|roth)\b", q):
        kind = "ira"
    elif re.search(r"\b(?:certificates?|cds?)\b", q):
        kind = "business certificate" if "business" in q else "certificate"
    elif CARD.search(q):
        kind = "card"
    elif re.search(r"\b(?:home equity|heloc)\b", q):
        kind = "home equity refinance" if "refinanc" in q else "loan"
    elif MORTGAGE.search(q):
        kind = "mortgage"
    elif re.search(r"\b(?:savings|checking|money market|hsa|deposit)\b", q):
        kind = "deposit"
    elif re.search(r"\b(?:loans?|rv|heloc)\b", q):
        kind = "loan"
    else:
        return None
    entries = [item for item in resolved if item[0].kind == kind]
    if kind in DEPOSIT or kind == "business certificate":
        entries = _deposit_rows(question, entries, kind)
        metric = "dividend rate" if "dividend rate" in q and "apy" not in q else "APY"
        entries = [item for item in entries if item[1] == metric]
        requested = PERCENT.search(q)
        if requested and re.search(r"\b(?:pay|offer|earn|available|rate of|match)\b", q):
            matching = [item for item in entries if Decimal(PERCENT.search(item[2])[1]) == Decimal(requested[1])]
            if matching:
                if not any(normalize(item[0].product) in normalize(q) for item in entries):
                    # A broad savings question may include several distinct products.
                    plain = [item for item in entries if normalize(item[0].product) == "share savings"]
                    return _render(matching + plain[:1], limit=8)
                entries = matching
            elif entries:
                best = max(entries, key=lambda item: Decimal(PERCENT.search(item[2])[1]))
                return _render([best], lead="I couldn't verify the quoted rate. The highest listed match is")
        if re.search(r"\b(?:highest|maximum|best)\b", q):
            entries.sort(key=lambda item: Decimal(PERCENT.search(item[2])[1]), reverse=True)
            entries = entries[:1]
    elif kind == "card":
        entries = [item for item in entries if
                   ("business" not in q or "business" in normalize(item[0].product))
                   and ("personal" not in q or "business" not in normalize(item[0].product))
                   and all(name not in q or name in normalize(item[0].product) for name in ("platinum", "rewards"))
                   and ("introductory" in item[0].tier) == bool(re.search(r"intro|balance transfer", q))]
        if "business" not in q and re.search(r"platinum|rewards", q):
            entries = [item for item in entries if "business" not in normalize(item[0].product)]
    elif kind in ("mortgage", "home equity refinance"):
        if re.search(r"construction|adjustable|\barm\b|\d+\s*/\s*\d+", q):
            return _unknown()
        purpose = "refinance" if "refinanc" in q else "purchase"
        entries = [item for item in entries if purpose in item[0].product.casefold()]
        terms = {int(n) for n, unit in TERM.findall(q) if unit == "year"}
        if terms:
            entries = [item for item in entries if any(int(n) in terms and unit.lower() == "year"
                                                        for n, unit in TERM.findall(item[0].product))]
        balance = amounts(q)
        if balance and entries:
            candidates = [item for item in entries if amounts(item[0].product) and amounts(item[0].product)[0] >= balance[0]]
            if candidates:
                cap = min(amounts(item[0].product)[0] for item in candidates)
                entries = [item for item in candidates if amounts(item[0].product)[0] == cap]
            else:
                entries = []
        if re.search(r"\baprs?\b", q):
            entries = [item for item in entries if item[1] == "APR"]
        elif "interest rate" in q:
            entries = [item for item in entries if item[1] == "interest rate"]
        entries.sort(key=lambda item: (amounts(item[0].product) or [Decimal("Infinity")])[0])
    else:
        aliases = {"heloc": "home equity line of credit", "boat": "boat", "rv": "boat",
                   "personal loan": "personal loan", "home improvement": "home improvement",
                   "motorcycle": "motorcycle", "powersport": "motorcycle", "home equity": "home equity"}
        targets = {label for alias, label in aliases.items() if alias in q}
        if not targets:
            return _unknown()
        entries = [item for item in entries if any(label in item[0].product.lower() for label in targets)]
        terms = {int(number) * (12 if unit.lower() == "year" else 1) for number, unit in TERM.findall(q)}
        if terms:
            entries = [item for item in entries if any(int(number) in terms for number, _ in TERM.findall(item[0].tier))]
    return _render(entries)


def _unknown():
    return Answer("I don't know. I couldn't verify a published rate for that product and tier in this snapshot.",
                  confident=False)


def _render(entries, *, lead="", limit=24):
    if not entries:
        return _unknown()
    lines, sources = [], []
    for row, metric, value in entries[:limit]:
        label = row.product
        if row.tier:
            qualifier = "minimum " if row.kind in ("certificate", "business certificate", "ira") else ""
            if row.tier != "—":
                label += f" ({qualifier}{row.tier})"
        label = re.sub(r"(\$\d{1,3})(\d{3})(?=\D|$)", r"\1,\2", label)
        lines.append(f"{label}: {value} {metric}")
        if row.source not in sources:
            sources.append(row.source)
    prefix = f"{lead} " if lead else ""
    return Answer(prefix + "; ".join(lines) + ".", sources)
