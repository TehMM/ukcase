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
