"""Fixed L3 retrieval evaluation set with explicit outcomes and supporting passages."""
from __future__ import annotations

import copy


# Each scenario is tied to the corpus passages that should support its expected
# screening outcome. These are document/clause references, not model-generated
# citations. B9/B10 are out-of-corpus-scope cases and B11/B12 are intake/guardrail
# cases; they remain covered by the agent and contract test suites rather than
# diluting the retrieval-quality evaluation denominator.
SUPPORT: dict[str, list[tuple[str, str]]] = {
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
    item["expected_support"] = copy.deepcopy(SUPPORT[source])
    item["support_source_case"] = source
    return item


def twenty(base: list[dict]) -> list[dict]:
    """Return 20 in-scope, reproducible cases with route and evidence expectations.

    The required section 4.1 startup-policy conflict is B1. Invalid-input cases
    B11/B12 and unsupported bidder categories B9/B10 are tested separately:
    they do not reach retrieval and therefore cannot honestly have a retrieved
    evidence passage in an L3 retrieval-quality denominator.
    """
    by_id = {item["id"]: item for item in base}
    required = ("B1", "B2", "B3", "B4", "B5", "B6", "B7", "B8")
    missing = [ident for ident in required if ident not in by_id]
    if missing:
        raise ValueError(f"L3 evaluation data is missing base cases: {missing}")

    out = []
    for ident in required:
        item = copy.deepcopy(by_id[ident])
        item["expected_support"] = copy.deepcopy(SUPPORT[ident])
        item["support_source_case"] = ident
        out.append(item)

    variants = [
        # Large-enterprise threshold and documentation boundaries.
        ("B13", "B2", "Large enterprise exactly at the turnover threshold",
         "pass_to_technical_evaluation",
         {"avg_annual_turnover_inr": 15_000_000, "turnover_years_reported": 3}),
        ("B14", "B2", "Large enterprise one rupee below the turnover threshold",
         "reject_with_cited_condition",
         {"avg_annual_turnover_inr": 14_999_999}),
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
        # MSE and startup policy / exemption variants.
        ("B21", "B6", "MSE bidder claims exemption and is not a trader",
         "escalate_to_human",
         {"is_trader": False}),
        ("B22", "B6", "MSE trader claims exemption and has low turnover",
         "escalate_to_human",
         {"is_trader": True, "avg_annual_turnover_inr": 5_000_000}),
        ("B23", "B1", "DPIIT-recognised startup with stronger financial and experience values",
         "escalate_to_human",
         {"avg_annual_turnover_inr": 50_000_000, "similar_work_experience_count": 5}),
        ("B24", "B8", "Startup still lacks DPIIT evidence despite stronger financial values",
         "seek_clarification",
         {"avg_annual_turnover_inr": 50_000_000, "similar_work_experience_count": 5}),
    ]

    for ident, source, description, route, changes in variants:
        out.append(_variant(by_id, ident, source, description, route, changes))

    if len(out) != 20:
        raise AssertionError(f"L3 evaluation set must contain exactly 20 cases, got {len(out)}")
    ids = [item["id"] for item in out]
    if len(ids) != len(set(ids)):
        raise AssertionError("L3 evaluation case IDs must be unique")
    for item in out:
        if not item.get("expected_route"):
            raise ValueError(f"{item['id']} has no expected outcome")
        if not item.get("expected_support"):
            raise ValueError(f"{item['id']} has no expected supporting passage")
    return out
