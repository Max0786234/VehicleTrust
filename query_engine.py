"""Phase 3 — Query understanding and decomposition (deterministic, explainable, no LLM).

understand_query()  : natural-language text (+ optional OCR/explicit plate) ->
                      registration number, intents, attributes, required information.
decompose_query()   : understanding -> per-database subqueries (only the relevant
                      databases), with the reason, FK relations to traverse and wave.

Wave 1 subqueries run in parallel. Wave 2 subqueries depend on context discovered in
wave 1 (the audit log is keyed by record ids found in the other databases).
"""
import re
from typing import Any, Dict, List, Optional

from matching import (INDIAN_STATES, damerau_levenshtein_similarity, generate_ocr_confusion_variants,
                      normalize_plate)

STRICT_PLATE = re.compile(r"^(?:[A-Z]{2}\d{1,2}[A-Z]{0,3}\d{4}|\d{2}BH\d{4}[A-Z]{1,2})$")
LOOSE_PLATE = re.compile(r"^[A-Z0-9]{2}[A-Z0-9]{1,2}[A-Z0-9]{0,3}[A-Z0-9]{4}$")

INTENTS: Dict[str, Dict[str, Any]] = {
    "FULL_HISTORY": {
        "keywords": ["complete history", "full history", "entire history", "full report", "complete report",
                     "everything", "all details", "background check", "complete check", "full check"],
        "label": "Complete vehicle history"},
    "INSURANCE": {
        "keywords": ["insur", "policy", "policies", "coverage", "covered", "premium", "claim", "insurer"],
        "label": "Insurance status, coverage and claims"},
    "THEFT": {
        "keywords": ["stolen", "theft", "steal", "fir", "police", "recovered", "recovery", "missing"],
        "label": "Theft reports, investigation and recovery"},
    "SCRAPPING": {
        "keywords": ["scrap", "dismantl", "end of life", "end-of-life", "deregist", "written off", "total loss"],
        "label": "Scrapping / deregistration status"},
    "OWNERSHIP": {
        "keywords": ["owner", "ownership", "transfer", "sold", "bought", "previous owner", "who owns"],
        "label": "Ownership and transfer history"},
    "REGISTRATION": {
        "keywords": ["registration certificate", " rc ", "rc status", "rto", "registered", "registration status",
                     "validity", "renewal", "certificate"],
        "label": "Registration certificate and RTO events"},
    "SIMILARITY": {
        "keywords": ["similar", "resembl", "close to", "look like", "looks like", "near match", "fuzzy",
                     "variants", "lookalike"],
        "label": "Vehicles with similar registration numbers"},
    "DISCREPANCY": {
        "keywords": ["discrepan", "conflict", "mismatch", "inconsisten", "differ", "cleans", "data quality",
                     "wrong", "incorrect"],
        "label": "Cross-database discrepancies"},
    "AUDIT": {
        "keywords": ["audit", "modif", "changed", "correction", "cleansing history", "review history", "edited"],
        "label": "Cleansing / modification history"},
    "VEHICLE_DETAILS": {
        "keywords": ["make", "model", "colour", "color", "specification", "vehicle details", "car details",
                     "what car", "which vehicle", "manufacturer", "identify the vehicle", "identify this vehicle"],
        "label": "Vehicle identity and specifications"},
}

# intent -> {service: [relations to traverse]}   (registry is the identity anchor)
INTENT_PLAN: Dict[str, Dict[str, List[str]]] = {
    "FULL_HISTORY": {
        "vehicle_registry": ["model", "manufacturer", "category", "owner", "owner_vehicles"],
        "insurance_records": ["provider", "holder", "coverage", "claims"],
        "registration_authority": ["office", "certificates", "transfers", "events"],
        "theft_scrapping": ["theft_reports", "investigations", "recoveries", "scrapping"],
        "audit_log": ["reviewer", "session", "evidence", "changes"]},
    "INSURANCE": {
        "vehicle_registry": ["model", "manufacturer", "owner"],
        "insurance_records": ["provider", "holder", "coverage", "claims"]},
    "THEFT": {
        "vehicle_registry": ["model", "manufacturer", "owner"],
        "theft_scrapping": ["theft_reports", "investigations", "recoveries"]},
    "SCRAPPING": {
        "vehicle_registry": ["model", "manufacturer"],
        "theft_scrapping": ["scrapping"],
        "registration_authority": ["certificates", "events"]},
    "OWNERSHIP": {
        "vehicle_registry": ["model", "manufacturer", "owner", "owner_vehicles"],
        "registration_authority": ["office", "transfers", "certificates"]},
    "REGISTRATION": {
        "vehicle_registry": ["model", "manufacturer", "category"],
        "registration_authority": ["office", "certificates", "events"]},
    "SIMILARITY": {
        "vehicle_registry": ["model", "manufacturer", "owner"],
        "registration_authority": ["office"]},
    "DISCREPANCY": {
        "vehicle_registry": ["model", "manufacturer", "category", "owner"],
        "registration_authority": ["office", "certificates", "transfers"],
        "insurance_records": ["provider", "holder"],
        "audit_log": ["reviewer", "session", "evidence", "changes"]},
    "AUDIT": {
        "vehicle_registry": ["model", "manufacturer"],
        "audit_log": ["reviewer", "session", "evidence", "changes"]},
    "VEHICLE_DETAILS": {
        "vehicle_registry": ["model", "manufacturer", "category", "owner"],
        "registration_authority": ["office", "certificates"]},
    # No explicit intent: "is this vehicle OK?" -> identity + insurance + theft/scrap status
    "GENERAL_STATUS": {
        "vehicle_registry": ["model", "manufacturer", "category", "owner"],
        "insurance_records": ["provider", "coverage"],
        "theft_scrapping": ["theft_reports", "scrapping"]},
}

SERVICE_REASONS = {
    "vehicle_registry": "Identity anchor: make, model, category, colour, owner (also feeds contextual matching and document retrieval)",
    "insurance_records": "Policy status, validity dates, insurer, coverage and claims",
    "registration_authority": "RTO registration, RC validity, ownership transfers and RTO events",
    "theft_scrapping": "Theft FIRs, investigation, recovery and scrapping records",
    "audit_log": "Previous cleansing decisions and data-change history for the records found in wave 1",
}

REQUIRED_INFO = {
    "FULL_HISTORY": ["vehicle identity", "current owner", "insurance status", "registration certificate status",
                     "ownership transfers", "theft status", "scrapping status", "audit history"],
    "INSURANCE": ["vehicle identity", "insurance status", "policy validity dates", "insurer", "coverage", "claims"],
    "THEFT": ["vehicle identity", "theft status", "theft reports"],
    "SCRAPPING": ["vehicle identity", "scrapping status", "registration certificate status"],
    "OWNERSHIP": ["vehicle identity", "current owner", "ownership transfers"],
    "REGISTRATION": ["vehicle identity", "registration certificate status", "rto events"],
    "SIMILARITY": ["similar registration numbers"],
    "DISCREPANCY": ["vehicle identity", "cross-database conflicts", "audit history"],
    "AUDIT": ["vehicle identity", "audit history"],
    "VEHICLE_DETAILS": ["vehicle identity"],
    "GENERAL_STATUS": ["vehicle identity", "insurance status", "theft status", "scrapping status"],
}

KNOWN_MAKES = ["Maruti Suzuki", "Mercedes-Benz", "Royal Enfield", "Volkswagen", "Mahindra", "Hyundai", "Renault",
               "Toyota", "Honda", "Skoda", "Tata", "BMW", "Kia", "MG", "Maruti", "Suzuki", "Audi", "Ford", "Nissan"]
KNOWN_MODELS = ["Innova Crysta", "Classic 350", "Scorpio-N", "3 Series", "C-Class", "City", "Nexon", "Swift", "Creta",
                "Innova", "Seltos", "XUV700", "Amaze", "i20", "Baleno", "Harrier", "Thar", "Fortuner", "Kiger", "Venue",
                "Tiago", "WagonR", "Elevate", "Scorpio", "Brezza", "Virtus", "Slavia", "Hector", "Punch", "Sonet",
                "Verna", "Dzire", "Altroz", "Exter"]
KNOWN_COLOURS = ["white", "black", "silver", "grey", "gray", "red", "blue", "green", "brown", "gold", "orange",
                 "yellow", "khaki", "maroon"]
STATE_NAMES = ["Andhra Pradesh", "Arunachal Pradesh", "Assam", "Bihar", "Chandigarh", "Chhattisgarh", "Delhi", "Goa",
               "Gujarat", "Haryana", "Himachal Pradesh", "Jammu and Kashmir", "Jharkhand", "Karnataka", "Kerala",
               "Madhya Pradesh", "Maharashtra", "Odisha", "Puducherry", "Punjab", "Rajasthan", "Tamil Nadu",
               "Telangana", "Tripura", "Uttar Pradesh", "Uttarakhand", "West Bengal"]


# Canonical modern form (2-digit RTO code) is preferred when repairing OCR errors, so that
# "GJO1AB7777" repairs to GJ01AB7777 rather than the also-valid-but-unlikely GJ1OAB7777.
PREFERRED_PLATE = re.compile(r"^(?:[A-Z]{2}\d{2}[A-Z]{1,3}\d{4}|\d{2}BH\d{4}[A-Z]{1,2})$")


def syntax_correct_plate(candidate: str, strict: "re.Pattern" = STRICT_PLATE) -> Optional[str]:
    """Returns the best variant of `candidate` that satisfies Indian plate syntax (OCR repairs O/0, I/1 ...)."""
    if PREFERRED_PLATE.match(candidate):
        return candidate
    variants = generate_ocr_confusion_variants(candidate, max_variants=48)
    for pattern in (PREFERRED_PLATE, strict):
        for variant in variants:
            if pattern.match(variant):
                return variant
    return None


_syntax_corrected = syntax_correct_plate


def extract_plate(text: str) -> Dict[str, Any]:
    """Finds a registration number in free text, tolerating spaces/hyphens/dots and OCR glyph errors."""
    tokens = re.findall(r"[A-Za-z0-9]+", (text or "").upper())
    best: Optional[Dict[str, Any]] = None
    for size in (4, 3, 2, 1):
        for i in range(len(tokens) - size + 1):
            joined = "".join(tokens[i:i + size])
            if not (8 <= len(joined) <= 11) or not LOOSE_PLATE.match(joined):
                continue
            digits = sum(c.isdigit() for c in joined)
            letters = sum(c.isalpha() for c in joined)
            if digits < 3 or letters < 2:
                continue
            corrected = _syntax_corrected(joined)
            if corrected is None:
                continue
            state_ok = corrected[2:4] == "BH" or corrected[:2] in INDIAN_STATES
            candidate = {"raw": " ".join(tokens[i:i + size]), "plate": joined, "syntax_valid": joined == corrected,
                         "syntax_corrected": corrected,
                         "rank": (state_ok, bool(PREFERRED_PLATE.match(joined)), joined == corrected)}
            if best is None or candidate["rank"] > best["rank"]:
                best = candidate
        if best and best["rank"][0]:
            break
    if best:
        best.pop("rank")
    return best or {}


def _contains(text_l: str, keyword: str) -> bool:
    if keyword.startswith(" ") or keyword.endswith(" "):
        return keyword in f" {text_l} "
    return keyword in text_l


def understand_query(text: str, plate: Optional[str] = None, context: Optional[Dict[str, Any]] = None,
                     plate_source: Optional[str] = None) -> Dict[str, Any]:
    text = text or ""
    text_l = re.sub(r"\s+", " ", text.lower())
    found = extract_plate(text)
    if plate:
        normalized = normalize_plate(plate)
        source = plate_source or "explicit"
    elif found:
        normalized = found["plate"]
        source = "query_text"
    else:
        normalized, source = "", "none"
    corrected = _syntax_corrected(normalized) if normalized else None

    intents = [name for name, spec in INTENTS.items() if any(_contains(text_l, k) for k in spec["keywords"])]
    if "history" in text_l and not intents:
        intents = ["FULL_HISTORY"]
    if "FULL_HISTORY" in intents:
        intents = ["FULL_HISTORY"] + [i for i in intents if i not in ("FULL_HISTORY",)]
    if not intents:
        intents = ["GENERAL_STATUS"]

    attributes: Dict[str, Any] = {k: v for k, v in (context or {}).items() if v}
    for make in KNOWN_MAKES:
        if "make" not in attributes and re.search(rf"\b{re.escape(make.lower())}\b", text_l):
            attributes["make"] = make
    for model in KNOWN_MODELS:
        if "model" not in attributes and re.search(rf"\b{re.escape(model.lower())}\b", text_l):
            attributes["model"] = model
    for colour in KNOWN_COLOURS:
        if "colour" not in attributes and re.search(rf"\b{colour}\b", text_l):
            attributes["colour"] = colour.title()
    for state in STATE_NAMES:
        if "state" not in attributes and state.lower() in text_l:
            attributes["state"] = state
    years = sorted(set(re.findall(r"\b(20[0-3]\d)\b", text)))

    required: List[str] = []
    for intent in intents:
        for item in REQUIRED_INFO.get(intent, []):
            if item not in required:
                required.append(item)

    return {
        "original_query": text,
        "registration_number": normalized,
        "plate_source": source,
        "plate_text_span": found.get("raw") if source == "query_text" else None,
        "plate_syntax_valid": bool(normalized) and bool(STRICT_PLATE.match(normalized)),
        "plate_syntax_corrected": corrected if corrected and corrected != normalized else None,
        "ocr_variants": generate_ocr_confusion_variants(normalized)[:8] if normalized else [],
        "intents": intents,
        "intent_labels": [INTENTS.get(i, {}).get("label", "General vehicle status check") for i in intents],
        "attributes": attributes,
        "years_mentioned": years,
        "required_information": required,
        "state_code": normalized[:2] if normalized[:2] in INDIAN_STATES else None,
    }


def decompose_query(understanding: Dict[str, Any]) -> Dict[str, Any]:
    """Selects databases and builds their subqueries. Databases not needed are listed with a reason."""
    plan: Dict[str, Dict[str, Any]] = {}
    for intent in understanding["intents"]:
        for service, relations in INTENT_PLAN.get(intent, {}).items():
            entry = plan.setdefault(service, {"service": service, "intents": [], "include": []})
            entry["intents"].append(intent)
            for rel in relations:
                if rel not in entry["include"]:
                    entry["include"].append(rel)

    plate = understanding["registration_number"]
    attributes = understanding["attributes"]
    similar = "SIMILARITY" in understanding["intents"]
    subqueries = []
    for service, entry in plan.items():
        wave = 2 if service == "audit_log" else 1
        payload: Dict[str, Any] = {"plate": plate, "include": entry["include"],
                                   "mode": "similar" if similar and service in ("vehicle_registry", "registration_authority") else "lookup"}
        if service in ("vehicle_registry", "registration_authority"):
            payload["context"] = {k: attributes.get(k) for k in ("make", "model", "colour", "state") if attributes.get(k)}
        subqueries.append({
            "service": service, "wave": wave, "endpoint": "/federated/query", "payload": payload,
            "intents": entry["intents"], "reason": SERVICE_REASONS[service],
            "depends_on": ["record ids discovered in wave 1"] if wave == 2 else [],
        })
    order = ["vehicle_registry", "insurance_records", "registration_authority", "theft_scrapping", "audit_log"]
    subqueries.sort(key=lambda s: order.index(s["service"]))
    selected = {s["service"] for s in subqueries}
    skipped = [{"service": s, "reason": f"Not needed for intent(s) {', '.join(understanding['intents'])}"}
               for s in order if s not in selected]
    return {"subqueries": subqueries, "skipped": skipped, "selected_services": [s["service"] for s in subqueries]}


def plates_equivalent(a: str, b: str) -> bool:
    return normalize_plate(a) == normalize_plate(b) or damerau_levenshtein_similarity(a, b) >= 0.95
