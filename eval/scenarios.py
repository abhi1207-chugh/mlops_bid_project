"""Fixed L3 retrieval evaluation set with explicit outcomes and full supporting passages."""
from __future__ import annotations

import copy


# Verbatim supporting excerpts from corpus/text/*.txt. Every scenario carries
# these passages (not merely document labels) so a reviewer can inspect why its
# expected route is correct. Citations are scored by document/clause reference.
SUPPORT_PASSAGES: dict[tuple[str, str], str] = {
    ("TENDER-NITR-390", "Clause 1"): (
        "1. Tender Fee & Earnest Money Deposit (EMD): A non-refundable Tender Fee of Rs. 1500/- "
        "(Rupees One Thousand Five hundred only) and refundable EMD of Rs. 1,00,000/- "
        "(Rupees One Lakh only) to be deposited through ONLINE mode only."
    ),
    ("TENDER-NITR-390", "Clause 2"): (
        "2. EMD Exemption: Micro and Small Enterprises (MSEs) as defined in MSE Procurement Policy "
        "issued by Department of Micro, Small and Medium Enterprises (MSME) for goods produced and "
        "services rendered, are exempted from paying EMD/Bid Security. Accordingly, MSEs shall be "
        "required to submit valid Udyam Registration Certificate for availing benefit under MSE "
        "Procurement Policy. The benefit as above to MSMEs shall be available only for Goods produced "
        "and services rendered by MSMEs. However, traders are excluded from the purview of MSME Procurement Policy."
    ),
    ("TENDER-NITR-390", "Clause 3"): (
        "3. Startup(s) as recognized by Department for Promotion of Industry and Internal Trade (DPIIT), "
        "Govt. of India, are exempted from paying EMD/Bid Security. However, they have to enclose "
        "valid self-attested registration certificate(s) along with the tender to this effect."
    ),
    ("TENDER-NITR-390", "Clause 5"): (
        "5. Bidder Turn Over Criteria: The minimum average annual financial turnover of the bidder "
        "during the three financial years, ending on 31st March 2026, should be Rs. 1,50,00,000 "
        "(One Crore and Fifty lakhs). Documentary evidence in the form of certified Audited Balance "
        "Sheets of relevant periods OR a certificate from the Chartered Accountant / Cost Accountant "
        "indicating the turnover details for the relevant period shall be uploaded with the bid."
    ),
    ("TENDER-NITR-390", "Clause 6"): (
        "6. Bidder Experience Criteria: The bidder must have supplied same or similar category products "
        "during last 5 financial years ending on 31 March 2026. Relevant documents in support of the "
        "experience criteria must be submitted along with the bid."
    ),
    ("TENDER-NITR-390", "Clause 11"): (
        "11. Documents to be submitted: (i) Cover – I: Technical Part (all documents must be self-attested): "
        "Valid Legal Status, PAN Card, GST Registration Certificate, Tender Acceptance Letter, Bid Security "
        "Declaration (for EMD-exempted bidder), Bid-specific OEM Authorization letter, experience documents, "
        "turnover documents, product Data Sheet, Escalation Matrix for Service Support, and Warranty declaration "
        "on OEM letterhead. Bids not accompanied by any of the above documents shall be rejected summarily."
    ),
    ("DOE-OM-2016-07-25", "Para 3"): (
        "3. As per Rule 160(i)(a) of GFR, 2005, there is already a provision that the bidding document should "
        "contain criteria for eligibility and qualification to be met by the bidders such as minimum level of "
        "experience, past performance, technical capability, manufacturing facilities and financial position etc. "
        "In view of above, it is further clarified that all Central Ministries / Departments may relax condition "
        "of prior turnover and prior experience in public procurement to all Startups (whether MSEs or otherwise) "
        "subject to meeting of quality and technical specifications in accordance with the relevant provisions of GFR, 2005."
    ),
    ("DOE-OM-2016-09-20", "Para 2"): (
        "2. A doubt has arisen if it makes optional for Central Ministries/ Departments to relax condition of "
        "prior experience and prior turnover in public procurement to Startups. In this regard, it is again clarified "
        "that normally for all public procurement, the Central Ministries/ Departments have to ensure that criteria "
        "of prior turnover and prior experience for all Startups is relaxed subject to their meeting of quality and "
        "technical specifications."
    ),
    ("GFR-2017-CH6", "Rule 173(i)"): (
        "Rule 173 (i): The text of the bidding document should be self-contained and comprehensive without any "
        "ambiguities. All essential information, which a bidder needs for sending responsive bid, should be clearly "
        "spelt out in the bidding document in simple language. The condition of prior turnover and prior experience "
        "may be relaxed for Startups (as defined by Department of Industrial Policy and Promotion) subject to meeting "
        "of quality and technical specifications and making suitable provisions in the bidding document."
    ),
    ("MSME-CIRCULAR-2016-03-10", "Para 4"): (
        "(4) In exercise of Para 16 of Public Procurement Policy for Micro and Small Enterprises Order 2012, "
        "it is clarified that all Central Ministries/Departments/Central Public Sector Undertakings may relax "
        "condition of prior turnover and prior experience with respect to Micro and Small Enterprises in all public "
        "procurements subject to meeting of quality and technical specifications."
    ),
}

_SUPPORT_REFS: dict[str, list[tuple[str, str]]] = {
    "B1": [
        ("TENDER-NITR-390", "Clause 5"),
        ("TENDER-NITR-390", "Clause 6"),
        ("TENDER-NITR-390", "Clause 3"),
        ("DOE-OM-2016-07-25", "Para 3"),
        ("DOE-OM-2016-09-20", "Para 2"),
        ("GFR-2017-CH6", "Rule 173(i)"),
    ],
    "B2": [
        ("TENDER-NITR-390", "Clause 1"),
        ("TENDER-NITR-390", "Clause 5"),
        ("TENDER-NITR-390", "Clause 6"),
        ("TENDER-NITR-390", "Clause 11"),
    ],
    "B3": [("TENDER-NITR-390", "Clause 5")],
    "B4": [("TENDER-NITR-390", "Clause 11")],
    "B5": [("TENDER-NITR-390", "Clause 5")],
    "B6": [
        ("TENDER-NITR-390", "Clause 2"),
        ("TENDER-NITR-390", "Clause 5"),
        ("MSME-CIRCULAR-2016-03-10", "Para 4"),
        ("GFR-2017-CH6", "Rule 173(i)"),
    ],
    "B7": [
        ("TENDER-NITR-390", "Clause 2"),
        ("TENDER-NITR-390", "Clause 5"),
        ("MSME-CIRCULAR-2016-03-10", "Para 4"),
        ("GFR-2017-CH6", "Rule 173(i)"),
    ],
    "B8": [("TENDER-NITR-390", "Clause 3")],
}


def _support(source_id: str) -> list[dict]:
    refs = _SUPPORT_REFS[source_id]
    missing = [ref for ref in refs if ref not in SUPPORT_PASSAGES]
    if missing:
        raise ValueError(f"Missing verbatim L3 support passages: {missing}")
    return [
        {"doc_id": doc_id, "clause_ref": clause_ref, "passage": SUPPORT_PASSAGES[(doc_id, clause_ref)]}
        for doc_id, clause_ref in refs
    ]


def _variant(
    base_by_id: dict[str, dict],
    ident: str,
    source: str,
    description: str,
    expected_route: str,
    changes: dict,
) -> dict:
    item = copy.deepcopy(base_by_id[source])
    item["id"] = ident
    item["description"] = description
    item["expected_route"] = expected_route
    item["bid"]["bidder_name"] = f"Evaluation {ident}"
    for field, value in changes.items():
        item["bid"][field] = copy.deepcopy(value)
    item["expected_support"] = _support(source)
    item["support_source_case"] = source
    return item


def twenty(base: list[dict]) -> list[dict]:
    """Return 20 in-scope cases with expected outcome and verbatim evidence.

    B1 is the required section 4.1 startup-policy conflict. Invalid intake cases
    and out-of-scope bidder categories are tested separately because they do not
    reach retrieval and therefore have no retrieved passage to score.
    """
    by_id = {item["id"]: item for item in base}
    required = ("B1", "B2", "B3", "B4", "B5", "B6", "B7", "B8")
    missing = [ident for ident in required if ident not in by_id]
    if missing:
        raise ValueError(f"L3 evaluation data is missing base cases: {missing}")

    out = []
    for ident in required:
        item = copy.deepcopy(by_id[ident])
        item["expected_support"] = _support(ident)
        item["support_source_case"] = ident
        out.append(item)

    variants = [
        ("B13", "B2", "Large enterprise exactly at the turnover threshold",
         "pass_to_technical_evaluation",
         {"avg_annual_turnover_inr": 15_000_000, "turnover_years_reported": 3}),
        ("B14", "B2", "Large enterprise one rupee below the turnover threshold",
         "reject_with_cited_condition", {"avg_annual_turnover_inr": 14_999_999}),
        ("B15", "B2", "Adequate turnover amount but only two years documented",
         "seek_clarification",
         {"avg_annual_turnover_inr": 25_000_000, "turnover_years_reported": 2,
          "turnover_certificate_covers_three_years": False}),
        ("B16", "B2", "Only the data sheet is missing",
         "reject_with_cited_condition",
         {"documents_submitted": [d for d in by_id["B2"]["bid"]["documents_submitted"]
                                  if d != "data_sheet"]}),
        ("B17", "B2", "Only OEM authorisation is missing",
         "reject_with_cited_condition",
         {"documents_submitted": [d for d in by_id["B2"]["bid"]["documents_submitted"]
                                  if d != "oem_authorization"]}),
        ("B18", "B2", "Compliant enterprise with higher turnover and experience",
         "pass_to_technical_evaluation",
         {"avg_annual_turnover_inr": 50_000_000, "similar_work_experience_count": 5}),
        ("B19", "B2", "Turnover is below threshold even though the period is incomplete",
         "reject_with_cited_condition",
         {"avg_annual_turnover_inr": 14_000_000, "turnover_years_reported": 1,
          "turnover_certificate_covers_three_years": False}),
        ("B20", "B5", "Turnover certificate covers two rather than three years",
         "seek_clarification",
         {"turnover_years_reported": 2, "turnover_certificate_covers_three_years": False}),
        ("B21", "B6", "MSE bidder claims exemption and is not a trader",
         "escalate_to_human", {"is_trader": False}),
        ("B22", "B6", "MSE trader claims exemption and has low turnover",
         "escalate_to_human", {"is_trader": True, "avg_annual_turnover_inr": 5_000_000}),
        ("B23", "B1", "DPIIT-recognised startup with stronger financial and experience values",
         "escalate_to_human",
         {"avg_annual_turnover_inr": 50_000_000, "similar_work_experience_count": 5}),
        ("B24", "B8", "Startup still lacks DPIIT evidence despite stronger financial values",
         "seek_clarification",
         {"avg_annual_turnover_inr": 50_000_000, "similar_work_experience_count": 5}),
    ]
    for ident, source, description, route, changes in variants:
        out.append(_variant(by_id, ident, description=description, source=source,
                            expected_route=route, changes=changes))

    if len(out) != 20:
        raise AssertionError(f"L3 evaluation set must contain exactly 20 cases, got {len(out)}")
    ids = [item["id"] for item in out]
    if len(ids) != len(set(ids)):
        raise AssertionError("L3 evaluation case IDs must be unique")
    for item in out:
        if not item.get("expected_route") or not item.get("expected_support"):
            raise ValueError(f"{item['id']} must have an expected outcome and supporting passage")
    return out
