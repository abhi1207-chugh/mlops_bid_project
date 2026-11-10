"""Twenty reproducible scenarios, including the required B1 case."""
from __future__ import annotations
import copy

def twenty(base: list[dict]) -> list[dict]:
    out = copy.deepcopy(base)
    # Expected corpus support makes relevance measurable rather than treating any
    # citation as relevant. Quarantined requests are intentionally excluded: no
    # model/corpus run is permitted for them.
    support = {
        "B1": [("TENDER-NITR-390", "Clause 5"), ("TENDER-NITR-390", "Clause 6"), ("GFR-2017-CH6", "Rule 173(i)")],
        "B2": [("TENDER-NITR-390", "Clause 5"), ("TENDER-NITR-390", "Clause 6")],
        "B3": [("TENDER-NITR-390", "Clause 5")], "B4": [("TENDER-NITR-390", "Clause 11")],
        "B5": [("TENDER-NITR-390", "Clause 5")], "B6": [("TENDER-NITR-390", "Clause 2")],
        "B7": [("TENDER-NITR-390", "Clause 5"), ("GFR-2017-CH6", "Rule 173(i)")],
        "B8": [("TENDER-NITR-390", "Clause 3")],
    }
    for item in out:
        item["expected_support"] = support.get(item["id"], [])
    seeds = [("B13", "B2", "pass_to_technical_evaluation"), ("B14", "B3", "reject_with_cited_condition"),
             ("B15", "B4", "reject_with_cited_condition"), ("B16", "B5", "seek_clarification"),
             ("B17", "B6", "escalate_to_human"), ("B18", "B7", "escalate_to_human"),
             ("B19", "B8", "seek_clarification"), ("B20", "B1", "escalate_to_human")]
    by_id = {x["id"]: x for x in base}
    for ident, source, route in seeds:
        item = copy.deepcopy(by_id[source]); item["id"] = ident; item["expected_route"] = route
        item["description"] = "Evaluation variant of " + source
        item["bid"]["bidder_name"] = "Evaluation " + ident
        item["expected_support"] = support.get(source, [])
        out.append(item)
    return out
