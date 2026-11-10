import json

from pipeline.chunking import chunk_document

M = {d["doc_id"]: d for d in json.load(open("/app/corpus/manifest.json"))["documents"]}


def chunks(doc_id):
    return chunk_document(M[doc_id], open("/app/corpus/" + M[doc_id]["text"]).read())


def find(doc_id, ref):
    return [c for c in chunks(doc_id) if c.clause_ref == ref]


def test_tender_clauses():
    c5 = find("TENDER-NITR-390", "Clause 5")[0]
    assert "1,50,00,000" in c5.text and c5.doc_type == "tender"
    assert "experience" in find("TENDER-NITR-390", "Clause 6")[0].text.lower()
    assert "Startup" in find("TENDER-NITR-390", "Clause 3")[0].text


def test_annexure_items_not_mistaken_for_clauses():
    refs = [c.clause_ref for c in chunks("TENDER-NITR-390") if c.page >= 5]
    assert not any(r.startswith("Clause") for r in refs)


def test_gfr_rule_173i_on_page_11():
    c = find("GFR-2017-CH6", "Rule 173(i)")[0]
    assert c.page == 11 and "prior turnover" in c.text


def test_doe_oms_split_by_date():
    assert "prior turnover and priar experience" in " ".join(c.text for c in chunks("DOE-OM-2016-07-25")).replace("\n", " ")
    assert find("DOE-OM-2016-09-20", "Para 2")[0].page == 3


def test_superseded_status_carried():
    assert all(c.status == "superseded" for c in chunks("MII-ORDER-2017-06-15"))
