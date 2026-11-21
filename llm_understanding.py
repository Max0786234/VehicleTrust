"""Optional LLM query understanding through a local Ollama server, with the rule-based parser as fallback.

Only the *understanding* step uses the language model (registration number, intents, attributes).
Decomposition, federation, matching, integration and retrieval stay deterministic.

Safety rules applied to the model's output (it can never introduce facts that are not in the query):
  * Ollama structured output: the reply must match a JSON schema whose intents are an enum of ours
  * intents outside the known set are dropped; an empty result falls back to the rules
  * a registration number is accepted only if it occurs in the query text (or equals the OCR/explicit plate)
  * attribute values (make/model/colour/state) are accepted only if they occur in the query text
  * any error, timeout or invalid JSON -> rule-based understanding, with the reason recorded

Configuration (.env):
  LLM_UNDERSTANDING = auto | on | off   (auto/on: try Ollama, fall back to rules; off: rules only)
  OLLAMA_URL        = http://127.0.0.1:11434
  OLLAMA_MODEL      = llama3.2
  LLM_TIMEOUT       = 30   (seconds)
"""
import json
import os
import re
import time
from typing import Any, Dict, List, Optional, Tuple

import httpx

from matching import damerau_levenshtein_similarity, normalize_plate
from query_engine import (INTENTS, KNOWN_COLOURS, KNOWN_MAKES, KNOWN_MODELS, REQUIRED_INFO, STATE_NAMES, STRICT_PLATE,
                          syntax_correct_plate, understand_query)


def settings() -> Dict[str, Any]:
    return {
        "mode": os.getenv("LLM_UNDERSTANDING", "auto").strip().lower() or "auto",
        "url": os.getenv("OLLAMA_URL", "http://127.0.0.1:11434").rstrip("/"),
        "model": os.getenv("OLLAMA_MODEL", "llama3.2").strip() or "llama3.2",
        "timeout": float(os.getenv("LLM_TIMEOUT", "30")),
    }


INTENT_GUIDE = {
    "FULL_HISTORY": "everything about the vehicle / complete history / background check",
    "INSURANCE": "insurance, policy, cover, claims, whether it is insured",
    "THEFT": "stolen, theft, FIR, police case, missing vehicle, recovery",
    "SCRAPPING": "scrapped, dismantled, written off, taken off the road permanently, end of life",
    "OWNERSHIP": "who owns it, owner, sale, transfer of ownership, previous owners",
    "REGISTRATION": "registration certificate (RC), RTO office, registration validity or suspension",
    "SIMILARITY": "vehicles with similar or look-alike registration numbers",
    "DISCREPANCY": "ONLY when the user suspects the records are wrong or disagree (mismatch, doesn't match, inconsistent)",
    "AUDIT": "audit trail, past corrections, who modified the record",
    "VEHICLE_DETAILS": "make, model, colour, specifications, identify the vehicle",
}

SCHEMA = {
    "type": "object",
    "properties": {
        "registration_number": {"type": "string"},
        "intents": {"type": "array", "items": {"type": "string", "enum": list(INTENTS) + ["GENERAL_STATUS"]}},
        "attributes": {
            "type": "object",
            "properties": {k: {"type": "string"} for k in ("make", "model", "colour", "state")},
        },
        "reasoning": {"type": "string"},
    },
    "required": ["registration_number", "intents", "attributes", "reasoning"],
}

SYSTEM_PROMPT = (
    "You convert a user's question about an Indian vehicle into JSON for a database system.\n"
    "Return ONLY JSON with keys: registration_number, intents, attributes, reasoning.\n"
    "- registration_number: the plate exactly as written in the question (e.g. 'DL 01 AB 1234'), or '' if none.\n"
    "- intents: the FEWEST codes that cover what the user asks (usually one or two):\n"
    + "\n".join(f"    {k}: {v}" for k, v in INTENT_GUIDE.items())
    + "\n    GENERAL_STATUS: only if nothing above applies\n"
    "- attributes: make, model, colour, state ONLY if the user literally mentions them; otherwise ''.\n"
    "- reasoning: at most 12 words.\n"
    "A question like 'is it clean - not stolen, not scrapped, insured?' asks about THEFT, SCRAPPING and INSURANCE.\n"
    "Never invent a registration number or attributes that are not in the question."
)

FEW_SHOT = [
    ("was AS01BC4433 ever reported missing to the police?",
     {"registration_number": "AS01BC4433", "intents": ["THEFT"],
      "attributes": {"make": "", "model": "", "colour": "", "state": ""}, "reasoning": "Asks only about a theft report."}),
    ("My cousin wants to buy a used grey Innova, UP16BT9900. Should he worry about who really owns it or whether it's covered?",
     {"registration_number": "UP16BT9900", "intents": ["OWNERSHIP", "INSURANCE"],
      "attributes": {"make": "", "model": "Innova", "colour": "grey", "state": ""},
      "reasoning": "Asks about the real owner and insurance cover."}),
    ("Was GJ 01 AB 7777 ever taken off the road for good or reported missing?",
     {"registration_number": "GJ 01 AB 7777", "intents": ["SCRAPPING", "THEFT"],
      "attributes": {"make": "", "model": "", "colour": "", "state": ""},
      "reasoning": "Taken off the road for good means scrapping; missing means theft."}),
]


def _compact(text: str) -> str:
    return re.sub(r"[^A-Z0-9]", "", (text or "").upper())


def _grounded_plate(llm_plate: str, text: str, explicit: Optional[str]) -> Optional[str]:
    plate = normalize_plate(llm_plate)
    if not plate or not (6 <= len(plate) <= 11):
        return None
    if explicit and (plate == normalize_plate(explicit) or damerau_levenshtein_similarity(plate, explicit) >= 0.9):
        return normalize_plate(explicit)
    if plate in _compact(text):
        return plate
    return None


def _grounded_attributes(attrs: Dict[str, Any], text: str, plate: str = "") -> Dict[str, str]:
    """Keeps only attribute values that literally occur in the question and look like real values:
    not a fragment of the registration number (e.g. 'UP' from 'UP 16 BT 9900'), make/model >= 3 chars,
    colours must contain a colour word, states must be a known state name."""
    out, low = {}, (text or "").lower()
    plate_compact = normalize_plate(plate)
    colours = set(KNOWN_COLOURS)
    states = {s.lower() for s in STATE_NAMES}
    for key in ("make", "model", "colour", "state"):
        val = str((attrs or {}).get(key) or "").strip()
        if not val or val.lower() not in low:
            continue
        compact = normalize_plate(val)
        if plate_compact and compact and compact in plate_compact:
            continue
        if key in ("make", "model") and len(compact) < 3:
            continue
        if key == "colour" and not any(w in colours for w in val.lower().split()):
            continue
        if key == "state" and val.lower() not in states:
            continue
        out[key] = val.title() if key in ("colour", "state") else val
    # Small models sometimes put a model name in 'make' (e.g. make='Innova'); use our vocabulary to fix the field.
    makes, models = {m.lower() for m in KNOWN_MAKES}, {m.lower() for m in KNOWN_MODELS}
    if out.get("make", "").lower() in models and out.get("make", "").lower() not in makes:
        out.setdefault("model", out["make"])
        out.pop("make")
    return out


SIMILARITY_CUES = ("similar", "alike", "resembl", "close to", "look like", "looks like", "near", "variant", "lookalike")
# DISCREPANCY adds the audit database and conflict focus; small models over-use it, so it needs a doubt cue.
DISCREPANCY_CUES = ("discrepan", "mismatch", "match", "disagree", "inconsisten", "conflict", "differ", "wrong",
                    "incorrect", "off", "add up", "fishy", "suspicious", "error", "mistake", "correct", "doubt", "fake")


async def _ask_ollama(text: str, cfg: Dict[str, Any], transport: Optional[httpx.AsyncBaseTransport]) -> Tuple[Dict[str, Any], str]:
    messages = [{"role": "system", "content": SYSTEM_PROMPT}]
    for q, a in FEW_SHOT:
        messages += [{"role": "user", "content": q}, {"role": "assistant", "content": json.dumps(a)}]
    messages.append({"role": "user", "content": text})
    payload: Dict[str, Any] = {"model": cfg["model"], "messages": messages, "stream": False, "format": SCHEMA,
                               "options": {"temperature": 0, "num_predict": 160}, "keep_alive": "30m"}
    if any(tag in cfg["model"].lower() for tag in ("qwen3", "deepseek-r1", "gpt-oss")):
        payload["think"] = False  # reasoning models: answer directly
    async with httpx.AsyncClient(timeout=httpx.Timeout(cfg["timeout"]), transport=transport) as client:
        resp = await client.post(f"{cfg['url']}/api/chat", json=payload)
    if resp.status_code != 200:
        raise RuntimeError(f"Ollama HTTP {resp.status_code}: {resp.text[:200]}")
    content = resp.json().get("message", {}).get("content", "")
    return json.loads(content), content


async def understand_with_llm(text: str, plate: Optional[str] = None, context: Optional[Dict[str, Any]] = None,
                              plate_source: Optional[str] = None, use_llm: Optional[bool] = None,
                              transport: Optional[httpx.AsyncBaseTransport] = None) -> Dict[str, Any]:
    """Returns an understanding dict (same shape as query_engine.understand_query) plus
    'understanding_method' and 'llm' details. Never raises: rules are the fallback."""
    rules = understand_query(text, plate, context, plate_source)
    cfg = settings()
    enabled = cfg["mode"] in ("auto", "on") if use_llm is None else bool(use_llm)
    info: Dict[str, Any] = {"enabled": enabled, "model": cfg["model"], "url": cfg["url"], "used": False}
    if not enabled or not (text or "").strip():
        info["fallback_reason"] = "LLM understanding disabled" if not enabled else "empty query text"
        return {**rules, "understanding_method": "rules", "llm": info}

    started = time.perf_counter()
    try:
        data, raw = await _ask_ollama(text, cfg, transport)
    except (httpx.HTTPError, RuntimeError, json.JSONDecodeError, ValueError) as exc:
        info.update(fallback_reason=f"{type(exc).__name__}: {str(exc)[:160] or 'no detail'}",
                    latency_ms=round((time.perf_counter() - started) * 1000, 1))
        return {**rules, "understanding_method": "rules (LLM unavailable)", "llm": info}
    info["latency_ms"] = round((time.perf_counter() - started) * 1000, 1)
    info["raw_output"] = raw[:1500]
    info["reasoning"] = str(data.get("reasoning", ""))[:300]

    intents = [i for i in (data.get("intents") or []) if i in INTENTS or i == "GENERAL_STATUS"]
    intents = list(dict.fromkeys(intents))
    if "SIMILARITY" in intents and not any(c in (text or "").lower() for c in SIMILARITY_CUES):
        intents.remove("SIMILARITY")  # look-alike mode changes matching; require an explicit comparison cue
    if "DISCREPANCY" in intents and not any(c in (text or "").lower() for c in DISCREPANCY_CUES):
        intents.remove("DISCREPANCY")
    if len(intents) > 1 and "GENERAL_STATUS" in intents:
        intents.remove("GENERAL_STATUS")
    if not intents:
        info["fallback_reason"] = "LLM returned no valid intent"
        return {**rules, "understanding_method": "rules (LLM output invalid)", "llm": info}
    # Explicit keyword hits from the rule parser are never dropped (missing a database is worse than one extra).
    keyword_added = [i for i in rules["intents"] if i != "GENERAL_STATUS" and i not in intents]
    intents = [i for i in intents if i != "GENERAL_STATUS" or not keyword_added] + keyword_added
    if "FULL_HISTORY" in intents:
        intents = ["FULL_HISTORY"] + [i for i in intents if i != "FULL_HISTORY"]

    rejected: List[str] = []
    llm_plate = str(data.get("registration_number") or "")
    grounded = _grounded_plate(llm_plate, text, plate)
    if llm_plate and not grounded:
        rejected.append(f"registration number '{llm_plate}' not found in the query")
    attrs = _grounded_attributes(data.get("attributes") or {}, text,
                                 rules["registration_number"] or grounded or llm_plate)
    for key, val in (data.get("attributes") or {}).items():
        if val and key not in attrs:
            rejected.append(f"{key} '{val}' rejected (not stated in the question as a valid {key})")

    # Plate: explicit/OCR first, then the deterministic extractor (syntax repair), then the grounded LLM plate.
    final_plate = rules["registration_number"] or (grounded or "")
    plate_src = rules["plate_source"] if rules["registration_number"] else ("llm" if grounded else "none")
    corrected = syntax_correct_plate(final_plate) if final_plate else None
    merged_attrs = {**attrs, **{k: v for k, v in (context or {}).items() if v}}
    required: List[str] = []
    for intent in intents:
        for item in REQUIRED_INFO.get(intent, []):
            if item not in required:
                required.append(item)

    info.update(used=True, intents=intents, rejected=rejected, rules_intents=rules["intents"],
                keyword_intents_added=keyword_added)
    understanding = {
        **rules,
        "registration_number": final_plate,
        "plate_source": plate_src,
        "plate_syntax_valid": bool(final_plate) and bool(STRICT_PLATE.match(final_plate)),
        "plate_syntax_corrected": corrected if corrected and corrected != final_plate else None,
        "intents": intents,
        "intent_labels": [INTENTS.get(i, {}).get("label", "General vehicle status check") for i in intents],
        "attributes": merged_attrs,
        "required_information": required,
        "understanding_method": f"llm ({cfg['model']})",
        "llm": info,
    }
    if final_plate and not rules["ocr_variants"]:
        from matching import generate_ocr_confusion_variants
        understanding["ocr_variants"] = generate_ocr_confusion_variants(final_plate)[:8]
    return understanding


async def ollama_status(timeout: float = 2.0) -> Dict[str, Any]:
    cfg = settings()
    try:
        async with httpx.AsyncClient(timeout=timeout) as client:
            tags = (await client.get(f"{cfg['url']}/api/tags")).json()
        names = [m["name"] for m in tags.get("models", [])]
        has = any(n == cfg["model"] or n.split(":")[0] == cfg["model"].split(":")[0] for n in names)
        return {"reachable": True, "model": cfg["model"], "model_installed": has, "models": names, "mode": cfg["mode"]}
    except Exception as exc:
        return {"reachable": False, "model": cfg["model"], "error": f"{type(exc).__name__}: {exc}", "mode": cfg["mode"]}


def warm_up_model() -> None:
    """Loads the model into memory in the background so the first user query is not slowed by model loading."""
    cfg = settings()
    if cfg["mode"] not in ("auto", "on"):
        return
    try:
        payload = {"model": cfg["model"], "messages": [{"role": "user", "content": "ok"}], "stream": False,
                   "keep_alive": "30m", "options": {"num_predict": 1}}
        httpx.post(f"{cfg['url']}/api/chat", json=payload, timeout=120)
    except Exception:
        pass  # Ollama not running: the rules will be used
