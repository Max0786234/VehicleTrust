"""Phase 3 — Unstructured document processing and context-driven retrieval.

Pipeline: load (TXT / MD / PDF / HTML) -> extract text -> clean -> extract metadata
-> chunk (overlapping word windows) -> index (BM25, pure Python) -> retrieve.

Retrieval is HYBRID and driven by the context accumulated from the structured
databases (not by the raw user text alone):
  * plate match        exact / OCR-noisy / fuzzy mention of the resolved registration number
  * identifier match   policy, claim, FIR, RC, scrapping-certificate numbers found in the DBs
  * BM25               lexical relevance of chunks to context terms (make, model, owner, insurer ...)
  * document type      expected types for the query intents and the discovered statuses
  * date proximity     document date near relevant structured dates (policy, theft, transfer ...)
  * context check      a look-alike plate whose make/model contradicts the DB context is REJECTED

No embeddings or external models: deterministic, explainable, fast on a laptop.
"""
import datetime
import math
import os
import re
from collections import Counter
from typing import Any, Dict, List, Optional, Tuple

import config
from matching import damerau_levenshtein_similarity, normalize_plate

try:
    from rapidfuzz import fuzz
except ImportError:  # pragma: no cover
    fuzz = None

SUPPORTED_EXTENSIONS = {".txt", ".md", ".pdf", ".html", ".htm"}
SYNTHETIC_MARKER = "SYNTHETIC DEMONSTRATION DOCUMENT"
DOC_PLATE = re.compile(r"\b([A-Z]{2})[\s\-.]?(\d{1,2})[\s\-.]?([A-Z]{1,3})[\s\-.]?(\d{4})\b")
DOC_BH_PLATE = re.compile(r"\b(\d{2})[\s\-.]?BH[\s\-.]?(\d{4})[\s\-.]?([A-Z]{1,2})\b")
STRICT_DOC_PLATE = re.compile(r"^(?:[A-Z]{2}\d{1,2}[A-Z]{1,3}\d{4}|\d{2}BH\d{4}[A-Z]{1,2})$")
FIELD_LINE = re.compile(r"^([A-Z][A-Za-z /()&-]{1,40}):\s*(.+)$")
DATE_RE = re.compile(r"\b(\d{4}-\d{2}-\d{2})\b")
IDENTIFIER_PATTERNS = {
    "policy_numbers": re.compile(r"\bPOL-[A-Z0-9]+(?:-[A-Z0-9]+)*\b"),
    "claim_numbers": re.compile(r"\bCLM-[A-Z0-9]+(?:-[A-Z0-9]+)*\b"),
    "fir_numbers": re.compile(r"\b[A-Z]{2}-[A-Z]{3}-\d{4}-\d{4}\b"),
    "rc_numbers": re.compile(r"\bRC-[A-Z0-9]+-\d{4}\b"),
    "certificate_numbers": re.compile(r"\bCOD-[A-Z0-9]+(?:-[A-Z0-9]+)*\b"),
}
STOPWORDS = set("""a an the of to in on for and or is are was were be been by with at from as this that it its
not no any may must will shall has have had after before under above per all only than into out over
""".split())

# keyword rules used when a document has no explicit "Document Type" header
TYPE_RULES = [
    ("Police Investigation Report", ["investigation progress", "investigation status", "recovery memo",
                                     "investigating officer"]),
    ("Theft Complaint", ["first information report", "motor vehicle theft"]),
    ("Scrapping Certificate", ["certificate of deposit", "scrapping facility", "scrapped"]),
    ("Registration Certificate", ["certificate of registration", "form 23"]),
    ("Insurance Claim Report", ["claim number", "claim settlement", "surveyor"]),
    ("Insurance Policy", ["policy schedule", "period of insurance"]),
    ("Vehicle Inspection Report", ["inspection report", "odometer"]),
    ("RTO Notice", ["public notice", "rto", "transport department"]),
    ("Compliance Certificate", ["pollution under control", "puc", "e-challan"]),
]

INTENT_DOC_TYPES = {
    "INSURANCE": ["Insurance Policy", "Insurance Claim Report", "Insurance Cancellation Notice", "Compliance Notice"],
    "THEFT": ["Theft Complaint", "Police Investigation Report", "Insurance Claim Report"],
    "SCRAPPING": ["Scrapping Certificate", "RTO Notice", "Insurance Claim Report"],
    "OWNERSHIP": ["Registration Certificate", "RTO Notice", "Vehicle Inspection Report"],
    "REGISTRATION": ["Registration Certificate", "RTO Notice"],
    "DISCREPANCY": ["Vehicle Inspection Report", "Registration Certificate", "Insurance Policy"],
    "VEHICLE_DETAILS": ["Vehicle Inspection Report", "Registration Certificate"],
    "SIMILARITY": ["Vehicle Inspection Report", "Registration Certificate"],
    "AUDIT": ["Vehicle Inspection Report", "Registration Certificate"],
    "GENERAL_STATUS": ["Insurance Policy", "Theft Complaint", "Scrapping Certificate", "Compliance Notice"],
}
STATUS_DOC_TYPES = {
    ("theft_status", "STOLEN"): ["Theft Complaint", "Police Investigation Report"],
    ("theft_status", "RECOVERED"): ["Theft Complaint", "Police Investigation Report", "Vehicle Inspection Report"],
    ("scrapping_status", "SCRAPPED"): ["Scrapping Certificate", "Insurance Claim Report"],
    ("scrapping_status", "PENDING_SCRAP"): ["Scrapping Certificate", "RTO Notice", "Insurance Claim Report"],
    ("insurance_status", "EXPIRED"): ["Compliance Notice", "Insurance Policy"],
    ("insurance_status", "CONFLICTING"): ["Insurance Policy", "Insurance Claim Report"],
}

# query-intent vocabulary added to the BM25 query (deterministic query expansion)
INTENT_TERMS = {
    "INSURANCE": ["insurance", "insured", "uninsured", "policy", "claim", "cover"],
    "THEFT": ["theft", "stolen", "fir", "police", "recovered", "investigation"],
    "SCRAPPING": ["scrapping", "scrapped", "deregistration", "deposit", "total", "loss"],
    "OWNERSHIP": ["owner", "ownership", "transfer"],
    "REGISTRATION": ["registration", "certificate", "rto"],
    "DISCREPANCY": ["inspection", "colour", "model"],
    "VEHICLE_DETAILS": ["inspection", "colour", "model"],
    "FULL_HISTORY": ["insurance", "registration", "theft", "inspection"],
    "GENERAL_STATUS": ["insurance", "theft", "scrapping"],
}

# document field -> structured fact key used for evidence checks
EVIDENCE_FIELD_MAP = {
    "make": "make", "model": "model", "colour": "colour",
    "policy status": "policy_status", "theft status": "theft_status", "rc status": "rc_status",
    "vehicle status": "scrapping_status", "registered owner": "owner", "insured name": "policy_holder",
    "new owner": "owner",
}

WEIGHTS = {"plate": 0.35, "identifiers": 0.20, "bm25": 0.20, "doc_type": 0.15, "date": 0.05, "context": 0.05}


def tokenize(text: str) -> List[str]:
    return [t for t in re.findall(r"[a-z0-9]+", text.lower()) if t not in STOPWORDS and len(t) > 1]


def clean_text(text: str) -> str:
    text = text.replace("\r\n", "\n").replace("\r", "\n").replace(" ", " ")
    text = re.sub(r"[‐-―]", "-", text)
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"<[^>]+>", " ", text) if "<html" in text.lower() else text
    lines = [line.strip() for line in text.split("\n")]
    text = "\n".join(lines)
    text = re.sub(r"\n{3,}", "\n\n", text).strip()
    return text.lstrip("# ").strip() if text.startswith("#") else text


def _syntax_corrected(token: str) -> Optional[str]:
    from query_engine import syntax_correct_plate
    return syntax_correct_plate(token, STRICT_DOC_PLATE)


def find_plates(text: str) -> Tuple[List[str], List[Dict[str, str]]]:
    """Returns (normalized plates, OCR-noisy mentions) found in free text."""
    upper = text.upper()
    plates: List[str] = []
    for m in list(DOC_PLATE.finditer(upper)) + list(DOC_BH_PLATE.finditer(upper)):
        p = normalize_plate(m.group(0))
        if STRICT_DOC_PLATE.match(p) and p not in plates:
            plates.append(p)
    noisy = []
    for token in re.findall(r"\b[A-Z0-9]{9,10}\b", upper):
        if token in plates or STRICT_DOC_PLATE.match(token):
            continue
        if sum(c.isdigit() for c in token) < 4 or sum(c.isalpha() for c in token) < 2:
            continue
        corrected = _syntax_corrected(token)
        if corrected and corrected != token:
            noisy.append({"raw": token, "corrected": corrected})
    return plates, noisy


class Document:
    def __init__(self, doc_id: str, path: str, fmt: str, text: str, metadata: Dict[str, Any]):
        self.doc_id, self.path, self.format, self.text, self.metadata = doc_id, path, fmt, text, metadata
        self.chunks: List[Dict[str, Any]] = []


class DocumentStore:
    def __init__(self, root: Optional[str] = None, chunk_words: int = 70, overlap: int = 20):
        self.root = root or config.DOCUMENTS_DIR
        self.chunk_words, self.overlap = chunk_words, overlap
        self.documents: Dict[str, Document] = {}
        self.chunks: List[Dict[str, Any]] = []
        self.errors: List[Dict[str, str]] = []
        self._df: Counter = Counter()
        self._avgdl = 0.0
        self.indexed_at: Optional[str] = None
        self.build()

    # ------------------------------------------------------------------ loading / extraction
    def _extract(self, path: str, ext: str) -> Tuple[str, Dict[str, Any]]:
        if ext == ".pdf":
            from pypdf import PdfReader
            reader = PdfReader(path)
            text = "\n".join(page.extract_text() or "" for page in reader.pages)
            info = reader.metadata or {}
            return text, {"pdf_title": getattr(info, "title", None), "pages": len(reader.pages)}
        with open(path, "r", encoding="utf-8", errors="replace") as fh:
            return fh.read(), {}

    def build(self) -> None:
        self.documents, self.chunks, self.errors = {}, [], []
        if not os.path.isdir(self.root):
            self.indexed_at = datetime.datetime.now().isoformat(timespec="seconds")
            return
        for dirpath, _dirs, files in os.walk(self.root):
            for name in sorted(files):
                ext = os.path.splitext(name)[1].lower()
                if ext not in SUPPORTED_EXTENSIONS or name.lower().startswith("readme"):
                    continue
                full = os.path.join(dirpath, name)
                try:
                    raw, extra = self._extract(full, ext)
                except Exception as exc:  # unreadable file: report, do not crash the index
                    self.errors.append({"path": full, "error": str(exc)})
                    continue
                text = clean_text(raw)
                rel = os.path.relpath(full, self.root).replace("\\", "/")
                meta = self.extract_metadata(text, rel, ext, extra)
                doc = Document(meta["doc_id"], rel, ext.lstrip("."), text, meta)
                doc.chunks = self._chunk(doc)
                self.documents[doc.doc_id] = doc
                self.chunks.extend(doc.chunks)
        self._df = Counter()
        for ch in self.chunks:
            self._df.update(set(ch["tokens"]))
        self._avgdl = sum(len(c["tokens"]) for c in self.chunks) / max(1, len(self.chunks))
        self.indexed_at = datetime.datetime.now().isoformat(timespec="seconds")

    # ------------------------------------------------------------------ metadata
    @staticmethod
    def extract_metadata(text: str, rel_path: str, ext: str, extra: Dict[str, Any]) -> Dict[str, Any]:
        fields: Dict[str, str] = {}
        for line in text.split("\n"):
            m = FIELD_LINE.match(line.strip())
            if m and m.group(1).lower() not in fields:
                fields[m.group(1).strip().lower()] = m.group(2).strip()
        plates, noisy = find_plates(text)
        header_plate = normalize_plate(fields.get("registration number")) if fields.get("registration number") else None
        if header_plate and header_plate not in plates:
            plates.insert(0, header_plate)
        lowered = text.lower()
        doc_type, type_source = fields.get("document type"), "header"
        if not doc_type:
            type_source = "inferred"
            doc_type = next((t for t, kws in TYPE_RULES if any(k in lowered for k in kws)), "Other")
        dates = sorted(set(DATE_RE.findall(text)))
        identifiers = {k: sorted(set(p.findall(text.upper()))) for k, p in IDENTIFIER_PATTERNS.items()}
        if fields.get("fir number"):
            identifiers["fir_numbers"] = sorted(set(identifiers["fir_numbers"]) | {fields["fir number"].upper()})
        tokens = [t for t in tokenize(text) if not t.isdigit()]
        keywords = [w for w, _ in Counter(tokens).most_common(12) if w not in ("synthetic", "demonstration", "document",
                                                                               "vehicletrust", "coursework", "record", "real")][:8]
        title_line = next((l for l in text.split("\n") if l and SYNTHETIC_MARKER not in l), "").lstrip("# ").strip()
        return {
            "doc_id": fields.get("document id") or os.path.splitext(os.path.basename(rel_path))[0],
            "title": extra.get("pdf_title") or title_line.title(),
            "document_type": doc_type, "document_type_source": type_source,
            "registration_numbers": plates, "primary_registration": header_plate or (plates[0] if plates else None),
            "noisy_plate_mentions": noisy,
            "date": fields.get("date") or (dates[0] if dates else None), "all_dates": dates,
            "issuer": fields.get("issued by"), "source": rel_path, "format": ext.lstrip("."),
            "fields": fields, "identifiers": identifiers, "keywords": keywords,
            "associated_entity": fields.get("registered owner") or fields.get("insured name") or fields.get("owner")
            or fields.get("complainant") or fields.get("new owner"),
            "synthetic": SYNTHETIC_MARKER in text, "pages": extra.get("pages"),
            "word_count": len(text.split()),
        }

    # ------------------------------------------------------------------ chunking / indexing
    def _chunk(self, doc: Document) -> List[Dict[str, Any]]:
        words = doc.text.split()
        step = max(1, self.chunk_words - self.overlap)
        chunks = []
        plate_tokens = [p.lower() for p in doc.metadata["registration_numbers"]]
        plate_tokens += [n["corrected"].lower() for n in doc.metadata["noisy_plate_mentions"]]
        for i, start in enumerate(range(0, max(1, len(words)), step)):
            piece = " ".join(words[start:start + self.chunk_words])
            if not piece:
                break
            tokens = tokenize(piece)
            # normalized plates make "DL 01 AB 1234" and "DL01AB1234" index identically
            piece_plates, piece_noisy = find_plates(piece)
            tokens += [p.lower() for p in piece_plates] + [n["corrected"].lower() for n in piece_noisy]
            if i == 0:
                tokens += plate_tokens
            chunks.append({"chunk_id": f"{doc.doc_id}#c{i}", "doc_id": doc.doc_id, "index": i, "text": piece,
                           "tokens": tokens, "tf": Counter(tokens)})
            if start + self.chunk_words >= len(words):
                break
        return chunks

    def bm25(self, query_tokens: List[str], k1: float = 1.5, b: float = 0.75) -> Dict[str, float]:
        n = max(1, len(self.chunks))
        scores: Dict[str, float] = {}
        for ch in self.chunks:
            dl = len(ch["tokens"]) or 1
            score = 0.0
            for q in set(query_tokens):
                f = ch["tf"].get(q, 0)
                if not f:
                    continue
                idf = math.log(1 + (n - self._df[q] + 0.5) / (self._df[q] + 0.5))
                score += idf * f * (k1 + 1) / (f + k1 * (1 - b + b * dl / self._avgdl))
            if score:
                scores[ch["chunk_id"]] = score
        return scores

    # ------------------------------------------------------------------ public API
    def stats(self) -> Dict[str, Any]:
        types = Counter(d.metadata["document_type"] for d in self.documents.values())
        formats = Counter(d.format for d in self.documents.values())
        return {"root": self.root, "documents": len(self.documents), "chunks": len(self.chunks),
                "vocabulary": len(self._df), "document_types": dict(types), "formats": dict(formats),
                "errors": self.errors, "indexed_at": self.indexed_at}

    def list_documents(self) -> List[Dict[str, Any]]:
        return [{**d.metadata, "chunks": len(d.chunks)} for d in self.documents.values()]

    def get(self, doc_id: str) -> Optional[Dict[str, Any]]:
        d = self.documents.get(doc_id)
        if not d:
            return None
        return {"metadata": d.metadata, "text": d.text,
                "chunks": [{"chunk_id": c["chunk_id"], "text": c["text"]} for c in d.chunks]}

    def search(self, query: str, top_k: int = 5, document_type: Optional[str] = None,
               registration_number: Optional[str] = None) -> List[Dict[str, Any]]:
        """Plain keyword search with optional metadata filters (used by the document browser)."""
        plate = normalize_plate(registration_number) if registration_number else None
        tokens = tokenize(query) + ([plate.lower()] if plate else [])
        tokens += [normalize_plate(p).lower() for p in find_plates(query)[0]]
        scores = self.bm25(tokens)
        best: Dict[str, Tuple[float, Dict[str, Any]]] = {}
        for ch in self.chunks:
            s = scores.get(ch["chunk_id"])
            if not s:
                continue
            meta = self.documents[ch["doc_id"]].metadata
            if document_type and meta["document_type"] != document_type:
                continue
            if plate and plate not in meta["registration_numbers"]:
                continue
            if ch["doc_id"] not in best or s > best[ch["doc_id"]][0]:
                best[ch["doc_id"]] = (s, ch)
        ranked = sorted(best.values(), key=lambda x: x[0], reverse=True)[:top_k]
        return [{"doc_id": ch["doc_id"], "bm25": round(s, 4), "snippet": ch["text"],
                 "metadata": self.documents[ch["doc_id"]].metadata} for s, ch in ranked]

    def retrieve_for_context(self, ctx: Dict[str, Any], top_k: int = 6, max_general: int = 2) -> Dict[str, Any]:
        """Context-driven hybrid retrieval. `ctx` is built by the federation layer from DB results."""
        plate = normalize_plate(ctx.get("plate"))
        intents = ctx.get("intents") or []
        identifiers = {k: {str(v).upper() for v in vals if v} for k, vals in (ctx.get("identifiers") or {}).items()}
        all_ids = set().union(*identifiers.values()) if identifiers else set()
        facts = ctx.get("facts") or {}
        expected = []
        for intent in intents:
            expected += INTENT_DOC_TYPES.get(intent, [])
        if "FULL_HISTORY" in intents:
            expected += [t for t, _ in TYPE_RULES] + ["Insurance Cancellation Notice", "Compliance Notice"]
        for (fact, value), types in STATUS_DOC_TYPES.items():
            if str(facts.get(fact, "")).upper() == value:
                expected += types
        expected = list(dict.fromkeys(expected))

        terms: List[str] = []
        for key in ("make", "model", "colour", "state"):
            if facts.get(key):
                terms += tokenize(str(facts[key]))
        for name in ctx.get("names") or []:
            terms += tokenize(name)
        for org in ctx.get("organisations") or []:
            terms += tokenize(org)
        for ident in all_ids:
            terms += tokenize(ident)
        for fact in ("policy_status", "theft_status", "scrapping_status", "rc_status", "insurance_status"):
            if facts.get(fact):
                terms += tokenize(str(facts[fact]))
        terms += tokenize(" ".join(ctx.get("intent_terms") or []))
        for intent in intents:
            terms += INTENT_TERMS.get(intent, [])
        if plate:
            terms += [plate.lower()] * 2
        bm25_scores = self.bm25(terms)
        doc_bm25: Dict[str, Tuple[float, Dict[str, Any]]] = {}
        for ch in self.chunks:
            s = bm25_scores.get(ch["chunk_id"], 0.0)
            if ch["doc_id"] not in doc_bm25 or s > doc_bm25[ch["doc_id"]][0]:
                doc_bm25[ch["doc_id"]] = (s, ch)
        max_bm25 = max([v[0] for v in doc_bm25.values()] + [1e-9])
        relevant_dates = [d for d in (datetime.date.fromisoformat(x) for x in ctx.get("dates") or [] if _is_date(x))]

        results, general, rejected = [], [], []
        for doc in self.documents.values():
            meta = doc.metadata
            reasons: List[str] = []
            # 1) plate component
            plate_score, plate_kind = 0.0, None
            primary = meta["primary_registration"]
            if plate and plate in meta["registration_numbers"] and (primary in (None, plate)):
                plate_score, plate_kind = 1.0, "exact"
                reasons.append(f"Document is about registration {plate} (exact after normalisation)")
            elif plate and plate in meta["registration_numbers"]:
                plate_score, plate_kind = 0.5, "secondary_mention"
                reasons.append(f"Mentions {plate} in passing; the document's own vehicle is {primary}")
            elif plate and any(n["corrected"] == plate for n in meta["noisy_plate_mentions"]):
                raw = next(n["raw"] for n in meta["noisy_plate_mentions"] if n["corrected"] == plate)
                plate_score, plate_kind = 0.9, "ocr_noisy"
                reasons.append(f"OCR-noisy plate mention '{raw}' repairs to {plate}")
            elif plate:
                sims = [(damerau_levenshtein_similarity(plate, p), p) for p in meta["registration_numbers"]]
                if sims and max(sims)[0] >= 0.80:
                    sim, near = max(sims)
                    plate_score, plate_kind = round(sim * 0.7, 4), "fuzzy"
                    reasons.append(f"Similar registration {near} (DL similarity {sim:.2f})")
            # 2) identifiers shared with structured records
            doc_ids = set().union(*[set(v) for v in meta["identifiers"].values()]) if meta["identifiers"] else set()
            shared = sorted(all_ids & doc_ids)
            id_score = min(1.0, 0.5 * len(shared))
            if shared:
                reasons.append(f"Shares identifier(s) with DB records: {', '.join(shared)}")
            # 3) context consistency (make/model) — guards against look-alike plates
            consistency, contradictions = _context_consistency(meta["fields"], facts)
            if plate_kind in ("fuzzy", "secondary_mention") and not shared and contradictions:
                rejected.append({"doc_id": meta["doc_id"], "title": meta["title"], "source": meta["source"],
                                 "reason": f"Plate {meta['primary_registration']} resembles {plate} but "
                                           f"{'; '.join(contradictions)} — a different vehicle"})
                continue
            if consistency > 0:
                reasons.append("Make/model consistent with structured context")
            # 4) BM25, 5) document type, 6) date proximity
            bm, best_chunk = doc_bm25.get(meta["doc_id"], (0.0, doc.chunks[0] if doc.chunks else {"text": ""}))
            bm_norm = round(bm / max_bm25, 4)
            type_score = 1.0 if meta["document_type"] in expected else 0.0
            if type_score:
                reasons.append(f"Document type '{meta['document_type']}' is relevant to {', '.join(intents) or 'query'}")
            date_score = 0.0
            if meta.get("date") and _is_date(meta["date"]) and relevant_dates:
                d0 = datetime.date.fromisoformat(meta["date"])
                gap = min(abs((d0 - d).days) for d in relevant_dates)
                if gap <= 60:
                    date_score = 1.0 if gap <= 14 else 0.5
                    reasons.append(f"Dated {meta['date']}, {gap} day(s) from a related DB event")
            breakdown = {"plate": plate_score, "identifiers": id_score, "bm25": bm_norm, "doc_type": type_score,
                         "date": date_score, "context": consistency}
            score = round(sum(WEIGHTS[k] * v for k, v in breakdown.items()), 4)
            vehicle_specific = plate_score > 0 or bool(shared)
            entry = {
                "doc_id": meta["doc_id"], "title": meta["title"], "document_type": meta["document_type"],
                "format": meta["format"], "source": meta["source"], "relevance_score": score,
                "score_breakdown": breakdown, "match_kind": plate_kind or ("identifier" if shared else "general"),
                "reasons": reasons, "metadata": meta, "snippet": best_chunk.get("text", ""),
                "extracted_text": doc.text[:1800],
                "evidence_checks": _evidence_checks(meta["fields"], facts, ctx.get("fact_alternatives") or {}),
            }
            if vehicle_specific:
                entry["scope"] = "vehicle_specific"
                results.append(entry)
            elif (not meta["registration_numbers"] and _mentions_state(doc.text, facts)
                  and ((type_score and bm_norm > 0.15) or bm_norm > 0.30)):
                entry["scope"] = "general"
                entry["reasons"].append("General notice for the vehicle's state; not specific to this vehicle")
                general.append(entry)
        results.sort(key=lambda e: e["relevance_score"], reverse=True)
        general.sort(key=lambda e: e["relevance_score"], reverse=True)
        return {"query_terms": sorted(set(terms)), "expected_document_types": expected,
                "documents": results[:top_k], "general_documents": general[:max_general],
                "rejected": rejected, "considered": len(self.documents),
                "matched_total": len(results)}


def _is_date(value: Any) -> bool:
    try:
        datetime.date.fromisoformat(str(value)[:10])
        return len(str(value)) >= 10
    except ValueError:
        return False


def _similar(a: str, b: str) -> bool:
    a, b = str(a).strip().lower(), str(b).strip().lower()
    if not a or not b:
        return True
    if a == b or a in b or b in a:
        return True
    return bool(fuzz and fuzz.token_set_ratio(a, b) >= 80)


def _context_consistency(fields: Dict[str, str], facts: Dict[str, Any]) -> Tuple[float, List[str]]:
    contradictions, agreements = [], 0
    for key in ("make", "model"):
        doc_val, db_val = fields.get(key), facts.get(key)
        if doc_val and db_val:
            if _similar(doc_val, db_val):
                agreements += 1
            else:
                contradictions.append(f"{key} '{doc_val}' vs DB '{db_val}'")
    return (1.0 if agreements and not contradictions else 0.0), contradictions


def _mentions_state(text: str, facts: Dict[str, Any]) -> bool:
    state = facts.get("state")
    return bool(state) and str(state).lower() in text.lower()


def _evidence_checks(fields: Dict[str, str], facts: Dict[str, Any],
                     alternatives: Optional[Dict[str, List[Dict[str, Any]]]] = None) -> List[Dict[str, Any]]:
    """Compares document-stated values with structured facts. Only states what the document says.

    SUPPORTS             document agrees with the primary database value
    SUPPORTS_ALTERNATIVE document agrees with another database's (conflicting) value
    CONFLICTS            document disagrees with every database value
    DOCUMENT_ONLY        no structured counterpart to compare with
    """
    alternatives = alternatives or {}
    checks = []
    for doc_key, fact_key in EVIDENCE_FIELD_MAP.items():
        doc_val = fields.get(doc_key)
        if not doc_val:
            continue
        db_val = facts.get(fact_key)
        if db_val is None or db_val == "":
            checks.append({"field": doc_key, "document_value": doc_val, "database_value": None, "status": "DOCUMENT_ONLY"})
            continue
        check = {"field": doc_key, "document_value": doc_val, "database_value": db_val}
        if _similar(doc_val, db_val) or _status_equivalent(doc_val, db_val):
            check["status"] = "SUPPORTS"
        else:
            alt = next((a for a in alternatives.get(fact_key, [])
                        if _similar(doc_val, a["value"]) or _status_equivalent(doc_val, a["value"])), None)
            if alt:
                check.update(status="SUPPORTS_ALTERNATIVE", supported_source=alt["source"], supported_value=alt["value"])
            else:
                check["status"] = "CONFLICTS"
        checks.append(check)
    return checks


def _status_equivalent(doc_val: str, db_val: Any) -> bool:
    a, b = str(doc_val).upper(), str(db_val).upper()
    groups = [{"ACTIVE", "ACTIVE AT ISSUE", "CURRENT"}, {"STOLEN", "OPEN"}]
    return any(a in g and b in g for g in groups)


_STORE: Optional[DocumentStore] = None


def get_store(rebuild: bool = False) -> DocumentStore:
    global _STORE
    if _STORE is None or rebuild:
        _STORE = DocumentStore()
    return _STORE
