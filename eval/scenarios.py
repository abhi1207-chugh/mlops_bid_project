"""Twenty reproducible scenarios, including the required B1 case."""
from __future__ import annotations
import copy

def twenty(base: list[dict]) -> list[dict]:
    out = copy.deepcopy(base)
    seeds = [("B13", "B2", "pass_to_technical_evaluation"), ("B14", "B3", "reject_with_cited_condition"),
             ("B15", "B4", "reject_with_cited_condition"), ("B16", "B5", "seek_clarification"),
             ("B17", "B6", "escalate_to_human"), ("B18", "B7", "escalate_to_human"),
             ("B19", "B8", "seek_clarification"), ("B20", "B1", "escalate_to_human")]
    by_id = {x["id"]: x for x in base}
    for ident, source, route in seeds:
        item = copy.deepcopy(by_id[source]); item["id"] = ident; item["expected_route"] = route
        item["description"] = "Evaluation variant of " + source
        item["bid"]["bidder_name"] = "Evaluation " + ident
        out.append(item)
    return out
