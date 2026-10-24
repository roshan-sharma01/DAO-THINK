"""Deterministic, traceable extraction from retrieved proposal text.

Every item returned here is a sentence copied from the proposal (labelled
"Proposal says:") so a reviewer can find it in the source. Nothing is
summarized by a model, estimated, converted, or summed. Retrieved text is
untrusted data: instructions inside it are detected and reported, never followed.
"""

import re
from typing import List

MAX_ITEMS = 8
MAX_ITEM_CHARS = 300

_MD_IMAGE = re.compile(r"!\[[^\]]*\]\([^)]*\)")
_MD_LINK = re.compile(r"\[([^\]]+)\]\([^)]*\)")
_MD_NOISE = re.compile(r"[*_`>|]+")
_SENTENCE_SPLIT = re.compile(r"(?<=[.!?])\s+(?=[A-Z0-9\"'(])")

_AMOUNT = re.compile(
    r"(?:[$€£]\s?\d[\d,]*(?:\.\d+)?(?:\s?(?:k|m|mm|bn|million|billion|thousand)\b)?)"
    r"|(?:\b\d[\d,]*(?:\.\d+)?\s?(?:k|m|million|billion|bn|thousand)?\s?"
    r"(?:USDC|USDT|DAI|USD|ETH|WETH|ENS|UNI|ARB|OP|AAVE|COMP|GNO|LDO|tokens?)\b)",
    re.IGNORECASE,
)
_TREASURY_WORDS = re.compile(
    r"\b(treasury|grant|budget|fund|funding|transfer|pay|payment|compensat\w*|stream|"
    r"allocat\w*|spend\w*|request\w*|disburs\w*)\b",
    re.IGNORECASE,
)
_BENEFIT_WORDS = re.compile(
    r"\b(benefit\w*|improv\w*|increas\w*|reduc\w*|enabl\w*|support\w*|grow\w*|"
    r"expand\w*|strengthen\w*|incentiv\w*|attract\w*|enhanc\w*|lower\w*|sav(e|es|ing)|"
    r"faster|safer|better)\b",
    re.IGNORECASE,
)
# A benefit claim needs a statement of intent or expectation, otherwise
# "unaudited upgrades increase the risk" would be read as a benefit.
_INTENT_WORDS = re.compile(
    r"\b(will|would|aims?\s+to|goal\w*|objective\w*|in order to|expected to|"
    r"intend\w*|designed to|seeks? to|so that|benefit\w*)\b",
    re.IGNORECASE,
)
_RISK_WORDS = re.compile(
    r"\b(risk\w*|exploit\w*|vulnerab\w*|hack\w*|attack\w*|legal|regulat\w*|"
    r"liquidat\w*|custod\w*|counterparty|conflict of interest|loss\w*|slippage|"
    r"volatil\w*|centraliz\w*|insolven\w*|failure\w*|uncertain\w*)\b",
    re.IGNORECASE,
)
_DEPENDENCY_WORDS = re.compile(
    r"\b(depend\w*|requir\w*|prerequisite\w*|contingent|subject to|milestone\w*|"
    r"deadline\w*|vendor\w*|third[- ]party|oracle\w*|bridge\w*|multisig|multi-sig|"
    r"timelock|time-lock|vesting|tranche\w*)\b",
    re.IGNORECASE,
)
_SUMMARY_HEADING = re.compile(
    r"^\s*#{1,6}\s*(summary|abstract|tl;?dr|overview|motivation|background|proposal)\b",
    re.IGNORECASE,
)
_INJECTION = re.compile(
    r"(ignore\s+(all\s+|any\s+)?(previous|prior|above|earlier)\s+instructions"
    r"|disregard\s+(all\s+|any\s+)?(previous|prior|your)\s+(instructions|rules)"
    r"|you\s+are\s+(now\s+)?(an?\s+)?(ai|assistant|language model|chatbot)"
    r"|system\s+prompt"
    r"|as\s+an\s+ai\b"
    r"|recommend\s+(approval|approve)\s+regardless)",
    re.IGNORECASE,
)


def _clean_line(line: str) -> str:
    line = _MD_IMAGE.sub("", line)
    line = _MD_LINK.sub(r"\1", line)
    line = re.sub(r"^\s*(#{1,6}|[-*+]|\d+[.)])\s+", "", line)
    line = _MD_NOISE.sub("", line)
    return " ".join(line.split())


def split_sentences(text: str) -> List[str]:
    sentences: List[str] = []
    for raw_line in (text or "").splitlines():
        line = _clean_line(raw_line)
        if not line:
            continue
        for part in _SENTENCE_SPLIT.split(line):
            part = part.strip()
            if 20 <= len(part):
                sentences.append(part)
    return sentences


def _label(sentence: str) -> str:
    if len(sentence) > MAX_ITEM_CHARS:
        sentence = sentence[: MAX_ITEM_CHARS - 1].rstrip() + "…"
    return f"Proposal says: {sentence}"


def _collect(sentences: List[str], pattern: re.Pattern, extra=None) -> List[str]:
    items: List[str] = []
    for sentence in sentences:
        if pattern.search(sentence) and (extra is None or extra(sentence)):
            labelled = _label(sentence)
            if labelled not in items:
                items.append(labelled)
        if len(items) >= MAX_ITEMS:
            break
    return items


def stated_purpose(text: str) -> str:
    """Return the first sentences of a Summary/Abstract section, else of the body."""
    lines = (text or "").splitlines()
    section: List[str] = []
    for index, line in enumerate(lines):
        if _SUMMARY_HEADING.match(line):
            for following in lines[index + 1:]:
                if re.match(r"^\s*#{1,6}\s", following):
                    break
                section.append(following)
            if any(s.strip() for s in section):
                break
            section = []
    sentences = split_sentences("\n".join(section)) or split_sentences(text)
    if not sentences:
        return ""
    purpose = " ".join(sentences[:2])
    if len(purpose) > 2 * MAX_ITEM_CHARS:
        purpose = purpose[: 2 * MAX_ITEM_CHARS - 1].rstrip() + "…"
    return purpose


def classify(sentence: str) -> str:
    """Give each sentence at most one primary category."""
    if _DEPENDENCY_WORDS.search(sentence):
        return "dependency"
    if _BENEFIT_WORDS.search(sentence) and _INTENT_WORDS.search(sentence):
        return "benefit"
    if _RISK_WORDS.search(sentence):
        return "risk"
    return ""


def extract_evidence(text: str) -> dict:
    sentences = split_sentences(text)
    categories = {sentence: classify(sentence) for sentence in sentences}

    def of(kind):
        return _collect([s for s in sentences if categories[s] == kind], re.compile(r"."))

    return {
        "sentence_count": len(sentences),
        "stated_purpose": stated_purpose(text),
        "claimed_benefits": of("benefit"),
        "risk_statements": of("risk"),
        "dependencies": of("dependency"),
        "stated_amounts": _collect(sentences, _AMOUNT),
        "treasury_statements": _collect(
            sentences, _AMOUNT, extra=lambda s: bool(_TREASURY_WORDS.search(s))
        ),
        "injection_detected": bool(_INJECTION.search(text or "")),
    }
