"""Search and validate evidence for questions outside the rate tables."""

from collections import Counter, defaultdict
from dataclasses import dataclass
from datetime import date, datetime
import math
import re
from urllib.parse import urlsplit

from contract import Answer, Conflict, Source

from rate_tables import normalize

MONTH = r"(?:January|February|March|April|May|June|July|August|September|October|November|December)"
PUBLICATION = re.compile(rf"(?m)^({MONTH} \d{{1,2}}, \d{{4}})$")
ADDRESS = re.compile(r"\b\d{1,6} [^\n]{4,75},\s*[A-Z]{2},?\s+\d{5}\b")
PHONE = re.compile(r"(?<!\d)(?:1[- ])?\(?\d{3}\)?[- .]\d{3}[- .]\d{4}(?!\d)")
ROUTING = re.compile(r"\b(?:routing|aba)(?: number)?[\s:(*]*(\d{9})\b", re.I)
ROUTING_QUERY = re.compile(
    r"(?:what s|what is|where (?:can|do) i find|can you (?:repeat|give me|tell me)|(?:give|tell) me|repeat)?\s*"
    r"(?:(?:the|your|our|dupaco(?: community credit union)? s) )?"
    r"(?:routing|aba(?: routing)?) number(?: (?:for|of) dupaco(?: community credit union)?)?(?: again)?(?: please)?"
)
BRANCH_NOUN = re.compile(r"\b(?:branch|learning lab)\b")
BRANCH_QUERY = re.compile(r"\b(?:at|in|for|does|is|the) (?:the )?((?:\w+ ){1,5}?(?:branch|learning lab))\b")
BRANCH_COUNT = re.compile(r"\b(\d{1,3})\s+(?:full.service\s+)?branch(?:es|\s+(?:office\s+)?locations)\b", re.I)
CLOSURE = re.compile(rf"\b(?:will close|closed|closes|closing(?: on)?)\s+(?:on\s+)?({MONTH} \d{{1,2}}, \d{{4}})", re.I)
SCHEDULE = re.compile(r"^(?:Mon(?:day)?|Tue(?:sday)?|Wed(?:nesday)?|Thu(?:rsday)?|Fri(?:day)?|Sat(?:urday)?|Sun(?:day)?)[^\n]{1,100}$", re.I | re.M)
TIME = re.compile(r"\b\d{1,2}(?::\d{2})?\s*[ap]\.m\.", re.I)
LINK = re.compile(r"(?<!!)\[([^\]]+)\]\((https?://[^)\s]+)\)")
STOP = set("""a an and are about at be by can could do does for from give had has have how i in is it its me
my of on or our please repeat say should tell than that the their them there these they this to up us
was were what when where which who will with would you your dupaco credit union current right now
today general still same last know like s""".split())


def tokens(text):
    aliases = {"employees": "employee", "branches": "branch", "loans": "loan",
               "cards": "card", "rates": "rate", "fees": "fee", "hours": "hour",
               "locations": "location", "eligibility": "eligible", "banking": "bank",
               "recognized": "recognition", "volunteering": "volunteer"}
    return [aliases.get(word, word) for word in normalize(text).split() if word not in STOP]


def plain(text):
    text = re.sub(r"!\[[^\]]*\]\([^)]+\)", "", text)
    text = re.sub(r"\[([^\]]+)\]\([^)]+\)", r"\1", text)
    return re.sub(r"\*\*|__|(?m:^#+\s*)", "", text).strip()


def _publication(page):
    match = PUBLICATION.search(page.markdown[:600])
    return datetime.strptime(match[1], "%B %d, %Y").date() if match else date.min


@dataclass(frozen=True)
class Passage:
    text: str
    raw: str
    url: str
    title: str
    heading: str
    published: date

    @property
    def path(self):
        return urlsplit(self.url).path.rstrip("/") or "/"

    def source(self, snapshot_id):
        return Source(self.url, snapshot_id, self.raw)


class EvidenceIndex:
    def __init__(self, snapshot):
        self.snapshot = snapshot
        self.pages = {page.url: page for page in snapshot.pages}
        self.passages = []
        self.postings = defaultdict(list)
        for page in snapshot.pages:
            published = _publication(page)
            heading = ""
            content = re.split(r"(?im)^##\s+Handpicked for You\b", page.markdown, maxsplit=1)[0]
            blocks = (content.splitlines() if self._is_fee_schedule(urlsplit(page.url).path)
                      else re.split(r"\n\s*\n", content))
            for raw in blocks:
                clean = plain(raw)
                if raw.startswith("#"):
                    heading = clean
                    continue
                if len(clean) < 18 or len(clean) > 2400 or clean.startswith("|") or not re.search(r"[a-z]{3}", clean, re.I):
                    continue
                passage = Passage(clean, raw.strip(), page.url, page.title, heading, published)
                index = len(self.passages)
                self.passages.append(passage)
                counts = Counter(tokens(clean))
                metadata = set(tokens(f"{page.title} {heading}"))
                for term in counts.keys() | metadata:
                    weight = min(counts[term], 3) + (0.65 if term in metadata else 0)
                    self.postings[term].append((index, weight, term in counts))

    def ranked(self, query, predicate=lambda _: True):
        terms = set(tokens(query))
        scores = defaultdict(float)
        matches = defaultdict(set)
        for term in sorted(terms):
            postings = self.postings.get(term, ())
            idf = math.log1p((len(self.passages) + 1) / (len(postings) + 1))
            for index, weight, in_body in postings:
                scores[index] += weight * idf
                if in_body:
                    matches[index].add(term)
        ordered = sorted(scores, key=lambda i: (-scores[i], -len(matches[i]), self.passages[i].url, i))
        return [(self.passages[i], matches[i]) for i in ordered if predicate(self.passages[i])]

    def _answer(self, text, *passages):
        return Answer(text, [p.source(self.snapshot.snapshot_id) for p in passages])

    def _routing(self):
        claims = self._routing_claims()
        official = {value for value, p in claims if p.path == "/contact"}
        values = official or {value for value, _ in claims}
        if len(values) != 1:
            return unknown()
        value, = values
        sources = sorted((p for found, p in claims if found == value), key=lambda p: p.path != "/contact")
        return self._answer(f"The routing number is {value}.", *list({p.url: p for p in sources}.values())[:3])

    def _routing_claims(self):
        return [(match[1], p) for p in self.passages
                if p.path in ("/contact", "/business/cash-management", "/personal/checking-accounts", "/")
                for match in ROUTING.finditer(p.text)]

    def _branch_counts(self):
        claims = [(int(match[1]), p) for p in self.passages
                  if p.path.startswith(("/about", "/newsroom/")) and "dupaco" in p.text.casefold()
                  for match in BRANCH_COUNT.finditer(p.text) if int(match[1]) < 150]
        claims = [(value, p) for value, p in claims if not re.search(
            r"\b(?:joined|previously|in the \d{4}s|at the time)\b", p.text, re.I)]
        return sorted(claims, key=lambda item: (item[1].published, item[1].url), reverse=True)

    def conflicts(self):
        output = []
        for title, claims in (("Credit union routing number", self._routing_claims()),
                              ("Credit union branch count", self._branch_counts())):
            unique = {}
            for value, p in claims:
                unique.setdefault(str(value), p)
            if len(unique) < 2:
                continue
            if title.endswith("routing number"):
                official = {str(value) for value, p in claims if p.path == "/contact"}
                winner = next(iter(official)) if len(official) == 1 else None
                reason = "Prefer the contact page; abstain when the official listings disagree."
            else:
                best = claims[0][1]
                top = {str(value) for value, p in claims if p.published == best.published}
                winner = next(iter(top)) if len(top) == 1 else None
                reason = "Prefer the most recent dated report of the branch network."
            output.append(Conflict(title, list(unique),
                                   [p.source(self.snapshot.snapshot_id) for p in unique.values()], winner, reason))
        return output

    def _locator(self):
        page = next((page for page in self.pages.values() if urlsplit(page.url).path.rstrip("/") == "/contact"), None)
        if page is None:
            return unknown()
        return Answer(page.url, [Source(page.url, self.snapshot.snapshot_id)])

    def _address(self, question):
        candidates = self.ranked(question, lambda p: p.path == "/contact" and bool(ADDRESS.search(p.text)))
        entity = set(tokens(question)) - {"address", "branch", "location", "street", "located", "find", "zip", "atm"}
        matches = [p for p, body in candidates if entity and entity <= body]
        addresses = {ADDRESS.search(p.text)[0]: p for p in matches}
        if len(addresses) != 1:
            return unknown()
        address, passage = next(iter(addresses.items()))
        return self._answer(address, passage)

    def _hours(self, question, drive_up):
        q = normalize(question)
        entity = set(tokens(q)) - set(
            "branch lobby hour drive open close opening closing different all keep vary "
            "weekday weekend saturday sunday monday friday thursday tuesday wednesday "
            "regular typical schedule".split())
        marker = r"(?:Drive[- ]up|Drive[- ]through)" if drive_up else r"Lobby"
        candidates = []
        for page in self.pages.values():
            if _publication(page) > date.fromisoformat(self.snapshot.taken_on):
                continue
            for match in re.finditer(rf"(?im)^\s*(?:\*\*|#+\s*)?{marker}(?: hours)?\s*(?:\*\*)?\s*:?[^\S\n]*$", page.markdown):
                lines, raw_lines = [], []
                for line in page.markdown[match.end():].splitlines():
                    if not line.strip():
                        raw_lines.append(line)
                        continue
                    if not SCHEDULE.fullmatch(plain(line)):
                        break
                    raw_lines.append(line)
                    lines.append(line.strip())
                if not lines or not TIME.search(" ".join(lines)):
                    continue
                local = tokens(f"{page.title} {page.markdown[:1800]}")
                if entity and not entity <= set(local):
                    continue
                candidates.append(Passage(plain("\n".join(lines)), "\n".join(raw_lines).strip(),
                                          page.url, page.title, marker, _publication(page)))
        if not candidates:
            return unknown()
        candidates.sort(key=lambda p: (p.path == "/contact", p.published), reverse=True)
        best = candidates[0]
        if entity:
            return self._answer(f"The snapshot lists these hours: {best.text.replace(chr(10), '; ')}.", best)
        sample = max(candidates, key=lambda p: (len(TIME.findall(p.text)), p.published))
        other = [p for p in candidates if p.text != sample.text]
        examples = [sample] + sorted(other, key=lambda p: (
            len(set(TIME.findall(p.text)) - set(TIME.findall(sample.text))), p.published
        ), reverse=True)[:2]
        schedules = " / ".join(p.text.replace("\n", "; ") for p in examples)
        answer = self._answer(f"Hours vary by branch. Published examples: {schedules}. Check the locator for your branch.", *examples)
        locator = self._locator()
        if locator.confident:
            answer.sources.extend(locator.sources)
        return answer

    def answer(self, question, cutoff):
        q = question.casefold()
        if re.search(r"\b(?:routing|aba) number\b", q):
            return self._routing() if ROUTING_QUERY.fullmatch(normalize(question).removeprefix("please ")) else unknown()
        if re.search(r"\b(?:locator|branch and atm|branch & atm)\b", q) and re.search(r"url|link|locator|website", q):
            return self._locator()
        if re.search(r"how many\b.*\bbranches\b|\bbranch count\b", q):
            counts = self._branch_counts()
            if counts:
                value, evidence = counts[0]
                peers = {v for v, p in counts if p.published == evidence.published}
                if len(peers) == 1:
                    return self._answer(f"The snapshot reports {value} branch locations.", evidence)
            return unknown()
        if re.search(r"\b(?:address|located|street address)\b", q) and re.search(r"\b(?:branch|atm|learning lab)\b", q):
            return self._address(question)
        if re.search(r"\b(?:hours|schedule)\b", q) and re.search(r"\b(?:lobby|branch|drive[- ]up)\b", q):
            return self._hours(question, bool(re.search(r"drive[- ]up", q)))
        if re.search(r"\bbranch\b", q) and re.search(r"close|open|full.service|alternativ", q):
            if re.search(r"full.service|alternativ|where", q):
                return self._targeted(question, lambda p: "full-service branch" in p.text.casefold(), min_matches=2)
            ranked = self.ranked(question, lambda p: p.published <= cutoff and bool(CLOSURE.search(p.text)))
            entity = set(tokens(question)) - set(
                "branch close closes closed open opening closing october september "
                "august june july may march april january february november december".split())
            entity = {token for token in entity if not token.isdigit()}
            for passage, _ in ranked:
                if entity and entity <= set(tokens(f"{passage.title} {passage.heading} {passage.text}")):
                    closing = CLOSURE.search(passage.text)[1]
                    closing_day = datetime.strptime(closing, "%B %d, %Y").date()
                    status = "was scheduled" if closing_day <= cutoff else "is scheduled"
                    return self._answer(f"The branch {status} to close {closing}.", passage)
            return unknown()
        if re.search(r"\b(?:link|url|website)\b", q):
            return self._link(question)
        if re.search(r"\bjoin\b", q) and "online" in q:
            return self._link(question, "join")
        if "forbes" in q:
            candidates = [(p, body) for p, body in self.ranked(question) if "forbes" in body and
                          "forbes" in p.title.casefold() and p.published <= cutoff and
                          re.search(r"recogniz|rank|named", p.text, re.I)]
            if candidates:
                passage, _ = max(candidates, key=lambda pair: pair[0].published)
                return self._answer(passage.text, passage)
            return unknown()
        if re.search(r"eligible|eligibility|qualif", q) and re.search(r"member|join", q):
            options = [p for p in self.passages if p.path in ("/about/join", "/membership")
                       and "eligible to join" in p.heading.casefold() and p.raw.startswith("- ")]
            if options:
                region = next((p for p in self.passages if p.url == options[0].url and
                               re.search(r"find us in", p.text, re.I)), None)
                answer = " ".join(p.text.removeprefix("- ") for p in options)
                if region:
                    geography = re.search(r"You can find us in [^.]+\.", region.text, re.I)
                    if geography:
                        answer += " " + geography[0]
                    options.append(region)
                return self._answer(answer, *options)
            return unknown()
        if "volunteer time off" in q:
            return self._targeted("volunteer time off employee", lambda p: bool(re.search(r"\d+\s+(?:Dupaco\s+)?employees", p.text)),
                                  min_matches=3)
        if "mobile wallet" in q or "mobile payment" in q:
            return self._targeted(question, lambda p: "apple pay" in p.text.casefold() or "google pay" in p.text.casefold(),
                                  min_matches=1, combine=True)
        if re.search(r"\b(?:change|update)\b", q) and re.search(r"contact information|phone number|email address|mailing address", q):
            guidance = next((p for p in self.passages if re.search(
                r"verify your contact information in shine", p.text, re.I)), None)
            help_line = next((p for p in self.passages if p.path == "/contact" and
                              p.text.startswith("Phone:") and PHONE.search(p.text)), None)
            if guidance and help_line:
                phone = PHONE.search(help_line.text)[0]
                return self._answer(f"Check your contact information in Shine. For help changing it, call {phone}.",
                                    guidance, help_line)
            return unknown()
        if self.is_fee_question(question):
            result = self.fee(question)
            if result.confident or re.search(r"\bfees?\b|\bcharge\b", q):
                return result
        if re.search(r"\b(?:student|university|college)\b", q) and re.search(r"\b(?:loan|borrow|financ)", q):
            return self._targeted("student loan flexible repayment", lambda p: "student loan" in p.text.casefold()
                                  and p.path.endswith("/student-loans"), min_matches=2)
        return self._general(question)

    def _link(self, question, preferred=""):
        if re.search(r"\b(?:cd|certificate)", question, re.I) and "rate" in question.casefold():
            for page in self.pages.values():
                if urlsplit(page.url).path.rstrip("/") == "/personal/savings-account":
                    if re.search(r"certificate rates|savings account rates", page.markdown, re.I):
                        return Answer(page.url.rstrip("/") + "#rates", [Source(page.url, self.snapshot.snapshot_id)])
        for passage, body in self.ranked(question, lambda p: not preferred or p.path in ("/about/join", "/membership", "/")):
            for label, url in LINK.findall(passage.raw):
                host = urlsplit(url).hostname or ""
                if preferred and host.startswith(preferred + ".") and host.endswith(".dupaco.com"):
                    return self._answer(url, passage)
                if not preferred and len(body & set(tokens(label))) >= 2:
                    return self._answer(url, passage)
        return unknown()

    @staticmethod
    def _is_fee_schedule(path):
        return "fee-schedule" in path or path.rstrip("/") == "/fees"

    @staticmethod
    def is_fee_question(question):
        return bool(re.search(r"\bfees?\b|\bhow much\b|\bwhat does .* cost\b", question, re.I))

    def has_fee_schedule(self):
        return any(self._is_fee_schedule(urlsplit(url).path) for url in self.pages)

    def fee(self, question):
        query = set(tokens(question)) - {"fee", "much", "cost", "charge", "pay"}
        matches = []
        for p, _ in self.ranked(question, lambda item: self._is_fee_schedule(item.path)):
            price = re.search(r"\$\d|\bfree\b|\bno charge\b|\d+%", p.text, re.I)
            if not price:
                continue
            subject = set(tokens(p.text[:price.start()]))
            shared = query & subject
            if shared and len(shared) >= math.ceil(len(query) * 0.75):
                matches.append((len(shared), len(subject - shared), p))
        if not matches:
            return unknown()
        score = max((covered, -extra) for covered, extra, _ in matches)
        best = {p.text: p for covered, extra, p in matches if (covered, -extra) == score}
        if len(best) != 1:
            return unknown()
        text, passage = next(iter(best.items()))
        return self._answer(text, passage)

    def _targeted(self, question, predicate, *, min_matches, combine=False):
        candidates = [p for p, body in self.ranked(question, predicate) if len(body) >= min_matches]
        if not candidates:
            return unknown()
        chosen = [candidates[0]]
        if combine:
            chosen.extend(p for p in candidates[1:8] if p.url == chosen[0].url and p.text not in {x.text for x in chosen})
            chosen = chosen[:3]
        return self._answer(" ".join(p.text for p in chosen), *chosen)

    def _general(self, question):
        q = question.casefold()
        if re.search(r"\b(?:apr|apy|interest rate|dividend rate)\b", q):
            return unknown()
        query = set(tokens(question))
        normalized = normalize(question)
        branch = BRANCH_QUERY.search(normalized)
        needs_branch_evidence = BRANCH_NOUN.search(normalized)
        for passage, matches in self.ranked(question)[:25]:
            if needs_branch_evidence and not any(
                query <= set(tokens(line)) and (not branch or f" {branch[1]} " in f" {normalize(line)} ")
                for line in re.split(r"\n|(?<=[.!?])\s+", passage.text)
            ):
                continue
            if len(matches) < max(2, math.ceil(len(query) * 0.55)):
                continue
            if re.search(r"\b(?:how many|how much|fee|cost)\b", q) and not re.search(r"\d", passage.text):
                continue
            if re.search(r"\b(?:telephone|phone number|call)\b", q) and not PHONE.search(passage.text):
                continue
            if len(passage.text) < 35 or passage.text.endswith("?") or "calculator" in passage.path:
                continue
            if "program" in query and "program" not in matches:
                continue
            if "program" in query and not (query - {"program"}) <= matches:
                continue
            if passage.published > date.fromisoformat(self.snapshot.taken_on):
                continue
            return self._answer(passage.text, passage)
        return unknown()


def unknown():
    return Answer("I don't know. I couldn't verify that from the available website snapshot.", confident=False)
