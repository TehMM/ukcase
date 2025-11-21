from __future__ import annotations

import pathlib
import sys
from datetime import date

import pytest

ROOT = pathlib.Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:  # Ensure the repository root is importable
    sys.path.insert(0, str(ROOT))

from app.scraping.xml_parse import (  # noqa: E402
    JudgmentMetadata,
    MetadataParseError,
    parse_judgment_metadata_from_xml,
)


SAMPLE_XML = b"""
<akomaNtoso>
  <judgment>
    <meta>
      <identification>
        <FRBRWork>
          <FRBRdate date="2025-03-15" />
          <FRBRalias name="[2025] EWHC 3036 (Comm)" />
        </FRBRWork>
      </identification>
    </meta>
    <header>
      <case>
        <court>ewhc/comm</court>
        <parties>ACME v Smith</parties>
        <judges>
          <judge>Hon. Judge Example</judge>
        </judges>
      </case>
      <title>ACME v Smith</title>
    </header>
    <body />
  </judgment>
</akomaNtoso>
"""


def test_parse_judgment_metadata_from_xml():
    metadata = parse_judgment_metadata_from_xml(SAMPLE_XML)

    assert metadata == JudgmentMetadata(
        neutral_citation="[2025] EWHC 3036 (Comm)",
        neutral_citation_number=3036,
        court_code="ewhc/comm",
        decision_date=date(2025, 3, 15),
        title="ACME v Smith",
        parties="ACME v Smith",
        judge="Hon. Judge Example",
    )


def test_parse_judgment_metadata_requires_neutral_citation():
    xml_without_citation = SAMPLE_XML.replace(b"<FRBRalias name=\"[2025] EWHC 3036 (Comm)\" />", b"")

    with pytest.raises(MetadataParseError):
        parse_judgment_metadata_from_xml(xml_without_citation)


def test_parse_handles_namespaces_and_text_elements():
    xml = b"""
    <akomaNtoso xmlns:n="http://example.com">
      <n:judgment>
        <n:meta>
          <n:identification>
            <n:FRBRWork>
              <n:FRBRdate date="2024-01-02" />
              <n:neutralCitation>[2024] EWCA 12</n:neutralCitation>
            </n:FRBRWork>
          </n:identification>
        </n:meta>
        <n:header>
          <n:case>
            <n:courtCode>ewca/civ</n:courtCode>
            <n:judges>
              <n:judge>Example Judge</n:judge>
            </n:judges>
          </n:case>
          <n:title>Example v Sample</n:title>
        </n:header>
      </n:judgment>
    </akomaNtoso>
    """

    metadata = parse_judgment_metadata_from_xml(xml)

    assert metadata.neutral_citation == "[2024] EWCA 12"
    assert metadata.neutral_citation_number == 12
    assert metadata.court_code == "ewca/civ"
    assert metadata.decision_date == date(2024, 1, 2)
    assert metadata.title == "Example v Sample"
    assert metadata.parties is None
    assert metadata.judge == "Example Judge"


def test_parse_requires_decision_date():
    xml_without_date = SAMPLE_XML.replace(b"<FRBRdate date=\"2025-03-15\" />", b"")

    with pytest.raises(MetadataParseError):
        parse_judgment_metadata_from_xml(xml_without_date)


def test_parse_requires_title():
    xml_without_title = SAMPLE_XML.replace(b"<title>ACME v Smith</title>", b"")

    with pytest.raises(MetadataParseError):
        parse_judgment_metadata_from_xml(xml_without_title)


def test_parse_rejects_invalid_date_format():
    bad_date_xml = SAMPLE_XML.replace(b"2025-03-15", b"15-03-2025")

    with pytest.raises(MetadataParseError):
        parse_judgment_metadata_from_xml(bad_date_xml)
