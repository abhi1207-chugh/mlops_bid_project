from worker.verifier import quote_in_text, resolve_citations

R = {"T:1": {"doc_id": "T", "clause_ref": "Clause 5", "status": "live", "text": "turnover  should be\nRs. 1,50,00,000 (One Crore)"},
     "S:1": {"doc_id": "S", "clause_ref": "Para 1", "status": "superseded", "text": "old order text"}}


def test_quote_normalisation_and_fragments():
    assert quote_in_text("turnover should be Rs. 1,50,00,000", R["T:1"]["text"])
    assert quote_in_text("turnover ... One Crore", R["T:1"]["text"])
    assert not quote_in_text("turnover should be Rs. 2,00,00,000", R["T:1"]["text"])


def test_unretrieved_and_fabricated_citations_fail():
    ok, issues = resolve_citations([{"chunk_id": "T:1", "quote": "turnover should be"}], R)
    assert ok[0].doc_id == "T" and not issues
    _, issues = resolve_citations([{"chunk_id": "X:9", "quote": "anything"}], R)
    assert "not retrieved" in issues[0]
    _, issues = resolve_citations([{"chunk_id": "T:1", "quote": "invented words"}], R)
    assert "does not appear" in issues[0]
    _, issues = resolve_citations([{"chunk_id": "S:1", "quote": "old order"}], R)
    assert "superseded" in issues[0]


def test_malformed_citation_payloads_fail_closed():
    _, issues = resolve_citations({"chunk_id": "T:1"}, R)
    assert issues == ["citations must be a JSON array"]
    _, issues = resolve_citations(["not-an-object", {"quote": "turnover"}], R)
    assert "JSON object" in issues[0]
    assert "missing chunk_id" in issues[1]
