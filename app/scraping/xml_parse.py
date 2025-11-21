from __future__ import annotations

import re
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from datetime import date
from typing import Optional, Tuple


class MetadataParseError(Exception):
    """Raised when mandatory judgment metadata cannot be extracted from XML."""


@dataclass
class JudgmentMetadata:
    neutral_citation: str
    neutral_citation_number: Optional[int]
    court_code: str
    decision_date: date
    title: str
    parties: Optional[str]
    judge: Optional[str]


def parse_judgment_metadata_from_xml(xml_content: bytes) -> JudgmentMetadata:
    """Parse LegalDocML XML content and extract required metadata."""

    root = ET.fromstring(xml_content)
    neutral_citation = _extract_neutral_citation(root)
    decision_date = _extract_decision_date(root)
    court_code = _extract_court_code(root)
    title, parties = _extract_title_and_parties(root)
    judge = _extract_judge(root)
    neutral_citation_number = _extract_neutral_citation_number(neutral_citation)

    return JudgmentMetadata(
        neutral_citation=neutral_citation,
        neutral_citation_number=neutral_citation_number,
        court_code=court_code,
        decision_date=decision_date,
        title=title,
        parties=parties,
        judge=judge,
    )


def _extract_neutral_citation(root: ET.Element) -> str:
    for elem in root.iter():
        tag = _local_name(elem)
        if tag.lower() in {"frbralias", "neutralcitation", "neutral-citation"}:
            citation = elem.attrib.get("name") or (elem.text or "").strip()
            if citation:
                return citation
    raise MetadataParseError("Neutral citation not found in XML")


def _extract_decision_date(root: ET.Element) -> date:
    for elem in root.iter():
        tag = _local_name(elem)
        if tag.lower() in {"frbrdate", "decisiondate", "decision-date", "date"}:
            candidate = elem.attrib.get("date") or (elem.text or "").strip()
            if candidate:
                try:
                    return date.fromisoformat(candidate)
                except ValueError as exc:  # pragma: no cover - defensive clause
                    raise MetadataParseError("Invalid decision date format") from exc
    raise MetadataParseError("Decision date not found in XML")


def _extract_court_code(root: ET.Element) -> str:
    for elem in root.iter():
        tag = _local_name(elem)
        if tag.lower() in {"court", "courtcode", "court-code"}:
            value = (elem.text or "").strip()
            if value:
                return value
    raise MetadataParseError("Court code not found in XML")


def _extract_title_and_parties(root: ET.Element) -> Tuple[str, Optional[str]]:
    title = None
    parties = None
    for elem in root.iter():
        tag = _local_name(elem)
        if tag.lower() == "title" and (elem.text and elem.text.strip()):
            title = elem.text.strip()
        if tag.lower() == "parties" and (elem.text and elem.text.strip()):
            parties = elem.text.strip()
        if title and parties:
            break
    if not title:
        raise MetadataParseError("Title not found in XML")
    return title, parties


def _extract_judge(root: ET.Element) -> Optional[str]:
    for elem in root.iter():
        tag = _local_name(elem)
        if tag.lower() in {"judge", "judges", "author"}:
            if elem.text and elem.text.strip():
                return elem.text.strip()
    return None


def _extract_neutral_citation_number(neutral_citation: str) -> Optional[int]:
    numbers = re.findall(r"\b(\d{1,6})\b", neutral_citation)
    if numbers:
        try:
            return int(numbers[-1])
        except ValueError:  # pragma: no cover - unexpected string content
            return None
    return None


def _local_name(elem: ET.Element) -> str:
    if "}" in elem.tag:
        return elem.tag.split("}", 1)[1]
    return elem.tag
