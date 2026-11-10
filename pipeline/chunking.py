"""Clause-aware chunking. Each chunk carries doc_id, page, clause_ref, doc_type, date, status (L1/D2)."""
from __future__ import annotations

import re
from dataclasses import dataclass, field

MAX_CHUNK_CHARS = 1800


@dataclass
class Chunk:
    chunk_id: str
    doc_id: str
    page: int
    clause_ref: str
    doc_type: str
    date: str
    status: str
    title: str
    text: str
    extra: dict = field(default_factory=dict)

    def metadata(self) -> dict:
        return {k: v for k, v in self.__dict__.items() if k != "text"}


def _clean(t: str) -> str:
    return re.sub(r"[ \t]+", " ", re.sub(r"\n\s*\n+", "\n", t)).strip()


def _split_long(text: str, limit: int = MAX_CHUNK_CHARS) -> list[str]:
    if len(text) <= limit:
        return [text]
    parts, cur = [], ""
    for para in re.split(r"(?<=[.;:])\s*\n", text):
        if cur and len(cur) + len(para) > limit:
            parts.append(cur.strip())
            cur = ""
        cur += para + "\n"
    if cur.strip():
        parts.append(cur.strip())
    return parts


def _mk(doc: dict, page: int, ref: str, text: str, n: int = 0) -> Chunk:
    slug = re.sub(r"[^a-z0-9]+", "", ref.lower())
    cid = f"{doc['doc_id']}:p{page}:{slug}" + (f":{n}" if n else "")
    return Chunk(cid, doc["doc_id"], page, ref, doc["doc_type"], doc["effective_date"], doc["status"], doc["title"], _clean(text))


# ---- tender: numbered clauses 1-28 and Annexures I-III, page from form feeds ---------------------
def chunk_tender(doc: dict, raw: str) -> list[Chunk]:
    out: list[Chunk] = []
    in_annex = False  # numbered items after the first Annexure heading are annexure content, not clauses
    for page_no, page in enumerate(raw.split("\f"), start=1):
        if not page.strip():
            continue
        annex = [(m.start(), f"Annexure {m.group(1).strip()}") for m in
                 re.finditer(r"(?m)^\s*Annexure\s*[–-]\s*(I{1,3}|IV)\s*:", page)]
        clauses = [] if in_annex else [(m.start(), f"Clause {m.group(1)}") for m in
                                       re.finditer(r"(?m)^\s{0,6}(\d{1,2})\.\s+\S", page)]
        if annex:
            clauses = [c for c in clauses if c[0] < annex[0][0]]
            in_annex = True
        marks = sorted(clauses + annex)
        if not marks:
            out.append(_mk(doc, page_no, "Preamble", page))
            continue
        if marks[0][0] > 0 and page[: marks[0][0]].strip():
            carry = "Continuation" if page_no > 1 else "Preamble"
            out.append(_mk(doc, page_no, carry, page[: marks[0][0]]))
        for i, (start, ref) in enumerate(marks):
            end = marks[i + 1][0] if i + 1 < len(marks) else len(page)
            body = re.sub(r"\n\s*Page \d+ of \d+\s*$", "", page[start:end].rstrip())
            for n, piece in enumerate(_split_long(body)):
                out.append(_mk(doc, page_no, ref, piece, n))
    return _dedupe(out)


# ---- GFR: Rules, sub-rule split for long rules (so "Rule 173(i)" is its own citable chunk) ----------
_ROMAN = r"(?:i|ii|iii|iv|v|vi|vii|viii|ix|x|xi|xii|xiii|xiv|xv|xvi|xvii|xviii|xix|xx)"


def chunk_gfr(doc: dict, raw: str) -> list[Chunk]:
    out: list[Chunk] = []
    for page_no, page in enumerate(raw.split("\f"), start=1):
        # layout puts "Rule" and the number on separate lines: normalise to "Rule N"
        norm = re.sub(r"(?m)^Rule\s*\n\s*(\d{3})\s*\n", r"Rule \1 ", page)
        marks = [(m.start(), m.group(1)) for m in re.finditer(r"(?m)^Rule (\d{3})\b", norm)]
        if not marks:
            if norm.strip():
                out.append(_mk(doc, page_no, "Page text", norm))
            continue
        if marks[0][0] > 0 and norm[: marks[0][0]].strip():
            out.append(_mk(doc, page_no, "Continuation", norm[: marks[0][0]]))
        for i, (start, rule) in enumerate(marks):
            end = marks[i + 1][0] if i + 1 < len(marks) else len(norm)
            body = norm[start:end]
            subs = [(m.start(), m.group(1)) for m in re.finditer(rf"(?:(?<=\s)|^)\(({_ROMAN})\)(?=\s)", body)]
            if len(body) > 500 and subs:
                head = body[: subs[0][0]]
                out.append(_mk(doc, page_no, f"Rule {rule}", head))
                for j, (s, label) in enumerate(subs):
                    e = subs[j + 1][0] if j + 1 < len(subs) else len(body)
                    out.append(_mk(doc, page_no, f"Rule {rule}({label})", f"Rule {rule} ({label}) " + body[s + len(label) + 2:e]))
            else:
                for n, piece in enumerate(_split_long(body)):
                    out.append(_mk(doc, page_no, f"Rule {rule}", piece, n))
    return _dedupe(out)


# ---- orders/circulars: one doc per page range, numbered paragraphs ---------------------------------
def chunk_paragraphs(doc: dict, raw: str, page_no: int) -> list[Chunk]:
    marks = [(m.start(), m.group(1)) for m in re.finditer(r"(?m)^\s*\(?(\d{1,2})[.)]\s+\S", raw)]
    out: list[Chunk] = []
    if not marks:
        return [_mk(doc, page_no, "Full text", raw)]
    head = raw[: marks[0][0]]
    if head.strip():
        out.append(_mk(doc, page_no, "Preamble", head))
    for i, (s, num) in enumerate(marks):
        e = marks[i + 1][0] if i + 1 < len(marks) else len(raw)
        for n, piece in enumerate(_split_long(raw[s:e])):
            out.append(_mk(doc, page_no, f"Para {num}", piece, n))
    return out


def chunk_generic(doc: dict, raw: str) -> list[Chunk]:
    marked = [(int(m.group(1)), body) for m, body in _pages_by_marker(raw)]
    pages = marked or [(i, p) for i, p in enumerate(raw.split("\f"), start=1)]
    out: list[Chunk] = []
    for page_no, page in pages:
        if page.strip():
            for n, piece in enumerate(_split_long(_clean(page))):
                out.append(_mk(doc, page_no, f"Page {page_no} section {n + 1}", piece))
    return _dedupe(out)


def _dedupe(chunks: list[Chunk]) -> list[Chunk]:
    seen: dict[str, int] = {}
    for c in chunks:
        k = seen.get(c.chunk_id, 0)
        seen[c.chunk_id] = k + 1
        if k:
            c.chunk_id = f"{c.chunk_id}:{k}"
    return chunks


def chunk_document(doc: dict, raw: str) -> list[Chunk]:
    """Dispatch on doc_id. `raw` is the text file content (shared by the three DoE/DPE orders)."""
    did = doc["doc_id"]
    if did.startswith("TENDER"):
        return chunk_tender(doc, raw)
    if did.startswith("GFR"):
        return chunk_gfr(doc, raw)
    if did.startswith(("DOE-OM", "DPE-OM")):
        pages = {int(m.group(1)): body for m, body in _pages_by_marker(raw)}
        out: list[Chunk] = []
        for p in doc.get("pages", []):
            if p in pages:
                out += chunk_paragraphs(doc, pages[p], p)
        return out
    if did.startswith("MSME"):
        pages = raw.split("\f")
        out = []
        for page_no, text in enumerate(pages, start=1):
            if text.strip():
                out += chunk_paragraphs(doc, text, page_no) if page_no == len(pages) - (1 if not pages[-1].strip() else 0) \
                    else [_mk(doc, page_no, "Covering letter", text)]
        return out
    return chunk_generic(doc, raw)


def _pages_by_marker(raw: str):
    parts = re.split(r"(?m)^\[PAGE (\d+)[^\]]*\]\s*$", raw)
    # parts = [pre, n1, body1, n2, body2, ...]
    class _M:  # tiny shim so callers can use .group(1)
        def __init__(self, n): self.n = n
        def group(self, _): return self.n
    for i in range(1, len(parts) - 1, 2):
        yield _M(parts[i]), parts[i + 1]
