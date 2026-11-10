import json

import pytest

from common.contract import validate_bid

BIDDERS = {b["id"]: b for b in json.load(open("/app/eval/bidders.json"))}


@pytest.mark.parametrize("bid_id", [k for k in BIDDERS if k not in ("B11", "B12")])
def test_valid_bidders_accepted(bid_id):
    model, errors = validate_bid(BIDDERS[bid_id]["bid"])
    assert errors == [] and model is not None


def test_b12_quarantined_with_field_level_errors():
    model, errors = validate_bid(BIDDERS["B12"]["bid"])
    assert model is None
    fields = {e["field"] for e in errors}
    assert {"bidder_category_claimed", "avg_annual_turnover_inr"} <= fields


def test_b11_prompt_injection_is_blocked_before_an_agent_run():
    model, errors = validate_bid(BIDDERS["B11"]["bid"])
    assert model is None
    assert errors[0]["field"] == "remarks"
    assert errors[0]["type"] == "prompt_injection"


def test_cross_field_rules():
    bid = dict(BIDDERS["B2"]["bid"], emd_exemption_claimed=True)
    assert validate_bid(bid)[0] is None  # large enterprise cannot claim exemption
    bid = dict(BIDDERS["B2"]["bid"], documents_submitted=["pan"])
    assert validate_bid(bid)[0] is None  # EMD paid without proof
    assert validate_bid(["not", "an", "object"])[0] is None
    assert validate_bid(dict(BIDDERS["B2"]["bid"], surprise=1))[0] is None  # unknown field


def test_b8_flagged_not_rejected():
    model, _ = validate_bid(BIDDERS["B8"]["bid"])
    assert model.flags()


def test_json_schema_enums_match_model():
    schema = json.load(open("/app/contracts/bid_summary.schema.json"))
    from common.contract import BidSummary
    assert set(schema["properties"]) == set(BidSummary.model_fields)
