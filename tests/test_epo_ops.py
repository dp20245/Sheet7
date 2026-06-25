from __future__ import annotations

from datetime import UTC, datetime

import copy

from sheet7_pipeline.connectors.epo_ops import (
    _build_queries,
    _parse_biblio_document,
    _publication_refs,
    _split_applicant,
)
from sheet7_pipeline.schema import EvidenceEvent


SEARCH_SAMPLE = {
    "ops:world-patent-data": {
        "ops:biblio-search": {
            "ops:search-result": {
                "ops:publication-reference": [
                    {
                        "document-id": {
                            "@document-id-type": "docdb",
                            "country": {"$": "IN"},
                            "doc-number": {"$": "202417000001"},
                            "kind": {"$": "A"},
                        }
                    }
                ]
            }
        }
    }
}


BIBLIO_DOC = {
    "@country": "IN",
    "@doc-number": "202417000001",
    "@kind": "A",
    "bibliographic-data": {
        "publication-reference": {
            "document-id": [
                {
                    "@document-id-type": "docdb",
                    "country": {"$": "IN"},
                    "doc-number": {"$": "202417000001"},
                    "kind": {"$": "A"},
                    "date": {"$": "20240118"},
                }
            ]
        },
        "application-reference": {
            "document-id": [
                {
                    "@document-id-type": "docdb",
                    "country": {"$": "WO"},
                    "doc-number": {"$": "2023000001"},
                    "kind": {"$": "A1"},
                    "date": {"$": "20230105"},
                }
            ]
        },
        "parties": {
            "applicants": {
                "applicant": [
                    {
                        "applicant-name": {
                            "name": {"$": "Acme Mobility Ltd"}
                        }
                    }
                ]
            }
        },
        "invention-title": [
            {
                "@lang": "en",
                "$": "Battery thermal system for electric vehicles",
            }
        ],
    },
    "abstract": {
        "@lang": "en",
        "p": {
            "$": "A patent application describing a manufacturing-ready battery module.",
        },
    },
}


def test_publication_refs_from_search_sample():
    refs = _publication_refs(SEARCH_SAMPLE)
    assert refs == [
        {
            "type": "docdb",
            "country": "IN",
            "number": "202417000001",
            "kind": "A",
            "date": "",
        }
    ]


def test_build_queries_scopes_applicant_to_indian_publications():
    assert _build_queries(["Acme Mobility"]) == ['pa="Acme Mobility" and pn=IN']


def test_parse_biblio_document_produces_ip_event():
    ev = _parse_biblio_document(BIBLIO_DOC, "test_run", datetime(2026, 6, 25, tzinfo=UTC))
    assert ev is not None
    assert isinstance(ev, EvidenceEvent)
    assert ev.source == "epo_ops"
    assert ev.disclosure_layer == "ip"
    assert ev.signal_label == "india_ip_market_entry"
    assert ev.entity_key == "epo_ops:acme_mobility_ltd"
    assert ev.company_ids["publication_ref"] == "IN.202417000001.A"
    assert ev.company_ids["application_ref"] == "WO.2023000001.A1"
    assert "india" in ev.matched_terms
    assert "Acme Mobility Ltd" in ev.evidence_text
    assert 0 <= ev.candidate_score <= 100


def test_split_applicant_parses_country_code():
    assert _split_applicant("ICAR-INDIAN INSTITUTE [IN]") == ("ICAR-INDIAN INSTITUTE", "IN")
    assert _split_applicant("Honda Motor Co [JP]") == ("Honda Motor Co", "JP")
    assert _split_applicant("No Country Ltd") == ("No Country Ltd", "")


def test_foreign_only_skips_all_indian_applicants():
    doc = copy.deepcopy(BIBLIO_DOC)
    doc["bibliographic-data"]["parties"]["applicants"]["applicant"] = [
        {"applicant-name": {"name": {"$": "Domestic Bharat Labs [IN]"}}}
    ]
    # discovery mode (foreign_only=True) drops a purely-Indian applicant
    assert _parse_biblio_document(doc, "r", datetime(2026, 6, 25, tzinfo=UTC), foreign_only=True) is None
    # targeted mode keeps it, and the [IN] code is stripped from the name
    ev = _parse_biblio_document(doc, "r", datetime(2026, 6, 25, tzinfo=UTC), foreign_only=False)
    assert ev is not None
    assert ev.company_name == "Domestic Bharat Labs"
    assert ev.company_ids["applicant_country"] == "IN"


def test_foreign_only_keeps_foreign_applicant():
    doc = copy.deepcopy(BIBLIO_DOC)
    doc["bibliographic-data"]["parties"]["applicants"]["applicant"] = [
        {"applicant-name": {"name": {"$": "Honda Motor Co [JP]"}}}
    ]
    ev = _parse_biblio_document(doc, "r", datetime(2026, 6, 25, tzinfo=UTC), foreign_only=True)
    assert ev is not None
    assert ev.company_name == "Honda Motor Co"
    assert ev.company_ids["applicant_country"] == "JP"
