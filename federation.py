"""Phase 3 — Federated query execution, context accumulation and integration.

Pipeline (each stage is timed and returned so the UI can show it):

  1 understanding      query_engine.understand_query
  2 decomposition      query_engine.decompose_query (only relevant databases)
  3 wave 1             parallel async POST /federated/query to the selected services;
                       each service fuzzy-matches locally and expands its own FK-PK graph
  4 entity resolution  consensus registration number across sources (OCR-noise tolerant)
  5 wave 2             context-dependent subqueries: audit log (needs record ids from wave 1)
                       + re-query of services that missed the resolved plate
  6 accumulation       matched/related entities, relationship paths, attributes with provenance,
                       service availability; unrelated candidates filtered out with reasons
  7 integration        Phase 2 CanonicalVehicleRecord + insurance rules + cleansing proposals,
                       plus cross-database conflict rules (never silently resolved)
  8 retrieval          documents retrieved with the accumulated structured context
  9 final answer       statements tagged as DB fact / document evidence / conflict / missing

Cross-machine communication is HTTP only; no SQLite file is ever opened here.
"""
import asyncio
import datetime
import time
from typing import Any, Dict, List, Optional, Tuple

import httpx

import config
from integration import CanonicalVehicleRecord, evaluate_insurance_risk, generate_cleansing_proposals
from matching import damerau_levenshtein_similarity, normalize_plate
from query_engine import decompose_query, understand_query

try:
    from rapidfuzz import fuzz
except ImportError:  # pragma: no cover
    fuzz = None

PLATE_FIELD = {
    "vehicle_registry": "registration_number",
    "insurance_records": "recorded_vehicle_number",
    "registration_authority": "plate_identifier",
    "theft_scrapping": "reported_plate",
}
LABELS = {key: spec["label"] for key, spec in config.SERVICES.items()}
CLUSTER_SIMILARITY = 0.90  # one edit in a 10-character plate


# =============================================================================
# Execution
# =============================================================================
async def _call_service(client: httpx.AsyncClient, service: str, base_url: str, payload: Dict[str, Any],
                        wave: int, t0: float, purpose: str) -> Dict[str, Any]:
    url = f"{base_url.rstrip('/')}/federated/query"
    started = time.perf_counter()
    call = {"service": service, "label": LABELS.get(service, service), "url": url, "wave": wave, "purpose": purpose,
            "payload": payload, "started_ms": round((started - t0) * 1000, 1)}
    try:
        # Overall per-call deadline: httpx timeouts only cover socket I/O, so a service that
        # accepts the request but stalls would otherwise block the whole federated query.
        resp = await asyncio.wait_for(client.post(url, json=payload), timeout=client.timeout.read)
        call["http_status"] = resp.status_code
        if resp.status_code == 200:
            call["status"], call["result"] = "ok", resp.json()
        else:
            call["status"], call["error"] = "error", f"HTTP {resp.status_code}: {resp.text[:200]}"
    except (httpx.TimeoutException, asyncio.TimeoutError):
        call["status"], call["error"] = "timeout", f"No response within {client.timeout.read}s"
    except httpx.RequestError as exc:
        call["status"], call["error"] = "unavailable", f"{type(exc).__name__}: {exc}"
    ended = time.perf_counter()
    call["latency_ms"] = round((ended - started) * 1000, 1)
    call["ended_ms"] = round((ended - t0) * 1000, 1)
    result = call.get("result") or {}
    call["match_count"] = result.get("match_count", 0)
    call["tables_touched"] = result.get("tables_touched", [])
    return call


_SSL_CONTEXT = None


def _ssl_context():
    """Built once: creating a CA bundle per AsyncClient costs ~0.5 s on Windows."""
    global _SSL_CONTEXT
    if _SSL_CONTEXT is None:
        import ssl
        try:
            import certifi
            _SSL_CONTEXT = ssl.create_default_context(cafile=certifi.where())
        except ImportError:  # pragma: no cover
            _SSL_CONTEXT = ssl.create_default_context()
    return _SSL_CONTEXT


def _client(timeout: float, transport: Optional[httpx.AsyncBaseTransport]) -> httpx.AsyncClient:
    return httpx.AsyncClient(timeout=httpx.Timeout(timeout), transport=transport, verify=_ssl_context())


async def _run_wave(client: httpx.AsyncClient, calls: List[Tuple[str, Dict[str, Any], str]], urls: Dict[str, str],
                    wave: int) -> Tuple[List[Dict[str, Any]], float]:
    """Runs one wave of subqueries concurrently (asyncio.gather) and returns them with wall time."""
    t0 = time.perf_counter()
    if not calls:
        return [], 0.0
    results = await asyncio.gather(*[
        _call_service(client, svc, urls[svc], payload, wave, t0, purpose) for svc, payload, purpose in calls])
    return list(results), round((time.perf_counter() - t0) * 1000, 1)


# =============================================================================
# Entity resolution
# =============================================================================
def _record_plate(service: str, record: Dict[str, Any]) -> str:
    return normalize_plate(record.get(PLATE_FIELD.get(service, ""), ""))


def resolve_entity(query_plate: str, calls: List[Dict[str, Any]]) -> Dict[str, Any]:
    """Chooses the registration number the sources agree on, and the plate variants that belong
    to the same vehicle. A variant only joins the cluster if no single database holds records for
    both plates (if one DB has both, they are two different vehicles)."""
    candidates: Dict[str, Dict[str, Any]] = {}
    plates_per_service: Dict[str, set] = {}
    for call in calls:
        if call["status"] != "ok" or call["service"] not in PLATE_FIELD:
            continue
        for m in call["result"]["matches"]:
            plate = _record_plate(call["service"], m["record"])
            plates_per_service.setdefault(call["service"], set()).add(plate)
            c = candidates.setdefault(plate, {"plate": plate, "sources": {}, "dl_similarity": m["match"]["dl_similarity"],
                                              "exact_query_match": plate == normalize_plate(query_plate)})
            c["sources"][call["service"]] = max(c["sources"].get(call["service"], 0), m["match"]["combined_score"])
    if not candidates:
        return {"registration_number": None, "query_plate": normalize_plate(query_plate), "cluster": [],
                "candidates": [], "confidence": "NONE", "match_score": 0.0, "sources_agreeing": [],
                "method": "No database returned a candidate above the similarity threshold"}

    from query_engine import PREFERRED_PLATE

    def rank(c):
        authoritative = "registration_authority" in c["sources"] or "vehicle_registry" in c["sources"]
        return (len(c["sources"]), bool(PREFERRED_PLATE.match(c["plate"])), authoritative,
                c["exact_query_match"], max(c["sources"].values()), c["dl_similarity"])

    ordered = sorted(candidates.values(), key=rank, reverse=True)
    anchor = ordered[0]
    cluster = [anchor["plate"]]
    for c in ordered[1:]:
        if damerau_levenshtein_similarity(anchor["plate"], c["plate"]) < CLUSTER_SIMILARITY:
            continue
        if any(anchor["plate"] in ps and c["plate"] in ps for ps in plates_per_service.values()):
            continue  # one database holds both plates -> distinct vehicles
        cluster.append(c["plate"])
    best_score = max(anchor["sources"].values())
    dl = damerau_levenshtein_similarity(query_plate, anchor["plate"]) if query_plate else 0.0
    confidence = "HIGH" if dl >= 0.9 and best_score >= 0.85 else "MEDIUM" if dl >= 0.8 else "LOW"
    sources = sorted({s for p in cluster for s in candidates[p]["sources"]})
    if anchor["exact_query_match"]:
        method = "Exact registration match"
    else:
        method = f"Fuzzy resolution: query '{normalize_plate(query_plate)}' ≈ '{anchor['plate']}' (DL similarity {dl:.2f})"
    return {
        "registration_number": anchor["plate"], "query_plate": normalize_plate(query_plate), "cluster": cluster,
        "candidates": [{"plate": c["plate"], "sources": c["sources"], "dl_similarity_to_query": round(
            damerau_levenshtein_similarity(query_plate, c["plate"]), 4), "in_entity": c["plate"] in cluster}
            for c in ordered],
        "confidence": confidence, "match_score": round(best_score, 4), "query_similarity": round(dl, 4),
        "sources_agreeing": sources, "method": method,
    }


# =============================================================================
# Context accumulation
# =============================================================================
def _fact(attrs: Dict[str, Any], name: str, value: Any, source: str, ref: str, overwrite: bool = False) -> None:
    if value in (None, "", []):
        return
    if name not in attrs:
        attrs[name] = {"value": value, "source": source, "record": ref, "alternatives": []}
    elif overwrite:
        prev = attrs[name]
        attrs[name] = {"value": value, "source": source, "record": ref,
                       "alternatives": prev["alternatives"] + [{"value": prev["value"], "source": prev["source"], "record": prev["record"]}]}
    elif str(attrs[name]["value"]).strip().lower() != str(value).strip().lower():
        attrs[name]["alternatives"].append({"value": value, "source": source, "record": ref})


def accumulate_context(understanding, decomposition, calls, entity) -> Dict[str, Any]:
    cluster = set(entity.get("cluster") or [])
    similar_mode = "SIMILARITY" in understanding["intents"]
    selected: Dict[str, List[Dict[str, Any]]] = {}
    matched, related, paths, filtered, similar = [], [], [], [], []
    availability: Dict[str, Dict[str, Any]] = {}

    for call in calls:
        svc = call["service"]
        prev = availability.get(svc)
        if prev is None or call["status"] == "ok":
            availability[svc] = {"label": LABELS.get(svc, svc), "status": call["status"], "url": call["url"],
                                 "latency_ms": call["latency_ms"], "error": call.get("error"), "wave": call["wave"]}
        if call["status"] != "ok":
            continue
        for m in call["result"]["matches"]:
            if svc == "audit_log":
                keep = True
            else:
                plate = _record_plate(svc, m["record"])
                keep = plate in cluster
                if not keep:
                    item = {"source": svc, "plate": plate, "record_id": m["record_id"], "match": m["match"],
                            "record": m["record"],
                            "reason": f"{plate} is not the resolved vehicle {entity.get('registration_number')}"}
                    (similar if similar_mode else filtered).append(item)
                    continue
            bucket = selected.setdefault(svc, [])
            if any(x["record_id"] == m["record_id"] for x in bucket):
                continue  # same record returned by a retry
            bucket.append(m)
            matched.append({"source": svc, "label": LABELS.get(svc, svc), "table": m["table"],
                            "record_id": m["record_id"], "ref": f"{svc}:{m['table']}#{m['record_id']}",
                            "plate": m["record"].get(PLATE_FIELD.get(svc, "vehicle_plate")), "match": m["match"],
                            "record": m["record"]})
            for rel_name, value in m["related"].items():
                related.append({"source": svc, "relation": rel_name, "parent": f"{m['table']}#{m['record_id']}",
                                "count": len(value) if isinstance(value, list) else 1, "data": value})
            for p in m["relationship_paths"]:
                paths.append({"source": svc, **p})

    for svc in decomposition["selected_services"]:
        availability.setdefault(svc, {"label": LABELS.get(svc, svc), "status": "not_called"})

    attrs: Dict[str, Any] = {}
    reg = (selected.get("vehicle_registry") or [None])[0]
    rto = (selected.get("registration_authority") or [None])[0]
    theft = (selected.get("theft_scrapping") or [None])[0]
    policies = selected.get("insurance_records") or []
    audits = selected.get("audit_log") or []

    if reg:
        r, ref = reg["record"], f"vehicles#{reg['record_id']}"
        for k in ("make", "model", "colour", "vehicle_type", "registration_date", "state", "chassis_number"):
            _fact(attrs, k, r.get(k), "vehicle_registry", ref)
        _fact(attrs, "owner", r.get("owner_name"), "vehicle_registry", ref)
        owner = reg["related"].get("owner")
        if owner:
            _fact(attrs, "owner_city", owner.get("city"), "vehicle_registry", f"vehicle_owners#{owner['id']}")
        others = reg["related"].get("owner_other_vehicles") or []
        if others:
            _fact(attrs, "owner_other_vehicles", [o["registration_number"] for o in others], "vehicle_registry",
                  f"vehicle_owners#{r.get('owner_id')}")
    if rto:
        r, ref = rto["record"], f"rto_registrations#{rto['record_id']}"
        for k in ("make", "model", "colour", "registration_date", "state"):
            _fact(attrs, k, r.get(k), "registration_authority", ref)
        _fact(attrs, "authority_reference", r.get("authority_reference"), "registration_authority", ref)
        office = rto["related"].get("office")
        if office:
            _fact(attrs, "rto_office", office.get("office_name"), "registration_authority", f"rto_offices#{office['id']}")
        certs = rto["related"].get("certificates") or []
        if certs:
            c = sorted(certs, key=lambda x: x["issue_date"])[-1]
            _fact(attrs, "rc_number", c["rc_number"], "registration_authority", f"registration_certificates#{c['id']}")
            _fact(attrs, "rc_status", c["rc_status"], "registration_authority", f"registration_certificates#{c['id']}")
            _fact(attrs, "rc_valid_until", c["valid_until"], "registration_authority", f"registration_certificates#{c['id']}")
            _fact(attrs, "rto_registered_owner", c.get("registered_owner"), "registration_authority",
                  f"registration_certificates#{c['id']}")
        transfers = rto["related"].get("transfers") or []
        if transfers:
            t = transfers[-1]
            _fact(attrs, "rto_registered_owner", t["new_owner"], "registration_authority", f"ownership_transfers#{t['id']}")
    if theft:
        r, ref = theft["record"], f"theft_scrapping_records#{theft['record_id']}"
        _fact(attrs, "theft_status", r.get("theft_status"), "theft_scrapping", ref)
        _fact(attrs, "scrapping_status", r.get("scrapping_status"), "theft_scrapping", ref)
    if policies:
        for p in policies:
            _fact(attrs, "insurers", [x["record"].get("insurer") for x in policies], "insurance_records",
                  f"insurance_policies#{p['record_id']}")
            break

    return {
        "original_query": understanding["original_query"],
        "subqueries": [{k: v for k, v in c.items() if k != "result"} for c in calls],
        "resolved_entity": entity,
        "selected": selected,
        "matched_entities": matched,
        "related_entities": related,
        "relationship_paths": paths,
        "attributes": attrs,
        "filtered_out": filtered,
        "similar_vehicles": similar,
        "service_availability": availability,
        "audit_entries": [a["record"] for a in audits],
    }


# =============================================================================
# Integration: Phase 2 canonical record + Phase 3 cross-database conflict rules
# =============================================================================
def _names_match(a: Optional[str], b: Optional[str]) -> bool:
    if not a or not b:
        return True
    a, b = a.strip().lower(), b.strip().lower()
    return a == b or bool(fuzz and fuzz.token_sort_ratio(a, b) >= 90)


def _conflict(kind, severity, description, evidence, explanation=None):
    return {"type": kind, "severity": severity, "description": description, "evidence": evidence,
            "explanation": explanation, "resolution": "UNRESOLVED - requires reviewer decision"}


def integrate(understanding, ctx, today: Optional[datetime.date] = None) -> Dict[str, Any]:
    today = today or datetime.date.today()
    sel = ctx["selected"]
    avail = ctx["service_availability"]
    entity = ctx["resolved_entity"]
    reg = (sel.get("vehicle_registry") or [None])[0]
    rto = (sel.get("registration_authority") or [None])[0]
    theft = (sel.get("theft_scrapping") or [None])[0]
    policies = sel.get("insurance_records") or []

    canonical = CanonicalVehicleRecord(entity.get("registration_number") or understanding["registration_number"])
    for svc in ("vehicle_registry", "registration_authority", "insurance_records", "theft_scrapping"):
        for m in sel.get(svc, []):
            canonical.add_source_record(svc, m["record"], m["match"]["dl_similarity"], m["match"]["confidence"])
            if svc in ("vehicle_registry", "registration_authority", "theft_scrapping"):
                break
    canon = canonical.to_dict()

    insurance_queried = "insurance_records" in avail
    if insurance_queried:
        risk = evaluate_insurance_risk(canon.get("insurance", []), canon.get("theft_scrapping"), today,
                                       entity.get("confidence", "HIGH") if entity.get("registration_number") else "LOW",
                                       avail["insurance_records"]["status"] == "ok")
    else:
        risk = {"status": "NOT_QUERIED", "status_label": "Insurance not requested by this query", "risk_level": "INFO"}
    proposals = generate_cleansing_proposals(canon)

    conflicts: List[Dict[str, Any]] = []
    events = (rto or {}).get("related", {}).get("events") or []
    for c in canon.get("conflicts", []):
        explanation = None
        for e in events:
            if c["field"] in (e.get("event_type") or "").lower() or c["field"] in (e.get("description") or "").lower():
                explanation = f"RTO event registration_events#{e['id']} ({e['event_date']} {e['event_type']}): {e['description']}"
        conflicts.append(_conflict("attribute_mismatch", "MEDIUM", c["description"], [
            {"source": "vehicle_registry", "record": f"vehicles#{reg['record_id']}", "field": c["field"], "value": c["registry_val"]},
            {"source": "registration_authority", "record": f"rto_registrations#{rto['record_id']}", "field": c["field"], "value": c["authority_val"]},
        ], explanation))

    for svc, items in sel.items():
        if svc in PLATE_FIELD:
            for m in items:
                plate = _record_plate(svc, m["record"])
                if plate != entity.get("registration_number"):
                    conflicts.append(_conflict("plate_variant", "HIGH",
                        f"{LABELS[svc]} stores '{plate}' for the vehicle the other sources record as '{entity['registration_number']}'",
                        [{"source": svc, "record": f"{m['table']}#{m['record_id']}", "field": PLATE_FIELD[svc], "value": plate}]))

    attrs = ctx["attributes"]
    reg_owner = (attrs.get("owner") or {}).get("value")
    rto_owner = (attrs.get("rto_registered_owner") or {}).get("value")
    if reg_owner and rto_owner and not _names_match(reg_owner, rto_owner):
        transfers = (rto or {}).get("related", {}).get("transfers") or []
        last = transfers[-1] if transfers else None
        conflicts.append(_conflict("owner_mismatch", "HIGH",
            f"Registry owner '{reg_owner}' differs from RTO registered owner '{rto_owner}'",
            [{"source": "vehicle_registry", "record": attrs["owner"]["record"], "field": "owner", "value": reg_owner},
             {"source": "registration_authority", "record": attrs["rto_registered_owner"]["record"], "field": "registered_owner", "value": rto_owner}],
            f"RTO transfer on {last['transfer_date']} from {last['previous_owner']} to {last['new_owner']} is not reflected in the registry" if last else None))

    theft_rec = (theft or {}).get("record") or {}
    scrap = str(theft_rec.get("scrapping_status", "")).upper()
    theft_st = str(theft_rec.get("theft_status", "")).upper()
    rc_status = str((attrs.get("rc_status") or {}).get("value", "")).upper()
    if scrap == "SCRAPPED" and rc_status == "VALID":
        conflicts.append(_conflict("scrapped_but_rc_valid", "HIGH",
            "Theft & Scrapping DB records the vehicle as SCRAPPED, but the RTO certificate is still VALID",
            [{"source": "theft_scrapping", "record": f"theft_scrapping_records#{theft['record_id']}", "field": "scrapping_status", "value": scrap},
             {"source": "registration_authority", "record": attrs["rc_status"]["record"], "field": "rc_status", "value": rc_status}]))
    if theft_st == "STOLEN" and rc_status == "VALID":
        conflicts.append(_conflict("stolen_but_rc_valid", "HIGH", "Vehicle is reported STOLEN but its RC is VALID",
            [{"source": "theft_scrapping", "record": f"theft_scrapping_records#{theft['record_id']}", "field": "theft_status", "value": theft_st},
             {"source": "registration_authority", "record": attrs["rc_status"]["record"], "field": "rc_status", "value": rc_status}]))

    reports = (theft or {}).get("related", {}).get("theft_reports") or []
    theft_dates = [r["report_date"] for r in reports if r.get("report_status") == "OPEN"]
    current_holder_names = []
    for p in policies:
        rec, ref = p["record"], f"insurance_policies#{p['record_id']}"
        active = rec.get("policy_status") == "ACTIVE" and rec.get("policy_start_date", "") <= today.isoformat() <= rec.get("expiry_date", "")
        if active and scrap == "SCRAPPED":
            conflicts.append(_conflict("scrapped_but_insured", "MEDIUM",
                f"Policy {rec['policy_number']} is active for a vehicle recorded as SCRAPPED",
                [{"source": "insurance_records", "record": ref, "field": "policy_status", "value": rec["policy_status"]},
                 {"source": "theft_scrapping", "record": f"theft_scrapping_records#{theft['record_id']}", "field": "scrapping_status", "value": scrap}]))
        for t_date in theft_dates:
            if theft_st == "STOLEN" and rec.get("policy_start_date", "") > t_date:
                conflicts.append(_conflict("policy_after_theft", "HIGH",
                    f"Policy {rec['policy_number']} started {rec['policy_start_date']}, after the open theft report of {t_date}",
                    [{"source": "insurance_records", "record": ref, "field": "policy_start_date", "value": rec["policy_start_date"]},
                     {"source": "theft_scrapping", "record": "theft_reports", "field": "report_date", "value": t_date}]))
        if active:
            current_holder_names.append((rec.get("holder_name"), ref, rec["policy_number"]))
        for claim in p["related"].get("claims") or []:
            if claim.get("claim_type") == "THEFT" and "theft_scrapping" in avail and avail["theft_scrapping"]["status"] == "ok" and not reports:
                conflicts.append(_conflict("theft_claim_without_report", "HIGH",
                    f"Theft claim {claim['claim_number']} exists but no theft report is recorded",
                    [{"source": "insurance_records", "record": f"insurance_claims#{claim['id']}", "field": "claim_type", "value": "THEFT"}]))
    owner_now = rto_owner or reg_owner
    for holder, ref, number in current_holder_names:
        if holder and owner_now and not _names_match(holder, owner_now):
            conflicts.append(_conflict("policy_holder_mismatch", "MEDIUM",
                f"Active policy {number} is held by '{holder}', but the current owner is '{owner_now}'",
                [{"source": "insurance_records", "record": ref, "field": "holder_name", "value": holder}]))
    if risk.get("status") == "CONFLICTING":
        conflicts.append(_conflict("concurrent_policies", "MEDIUM", "More than one active policy from different insurers",
            [{"source": "insurance_records", "record": f"insurance_policies#{p['record_id']}", "field": "insurer",
              "value": p["record"].get("insurer")} for p in policies]))

    return {"canonical_record": canon, "insurance_risk": risk, "cleansing_proposals": proposals, "conflicts": conflicts}


# =============================================================================
# Missing information & retrieval context
# =============================================================================
def missing_information(understanding, ctx, integration) -> List[Dict[str, str]]:
    sel, avail = ctx["selected"], ctx["service_availability"]

    def down(svc):
        return svc in avail and avail[svc]["status"] != "ok"

    rto = (sel.get("registration_authority") or [None])[0]
    reg = (sel.get("vehicle_registry") or [None])[0]
    theft = (sel.get("theft_scrapping") or [None])[0]
    policies = sel.get("insurance_records") or []
    missing = []
    for svc, info in avail.items():
        if info["status"] != "ok":
            missing.append({"item": f"{info['label']} results", "reason": f"Service {info['status']}: {info.get('error') or ''}".strip()})
    for item in understanding["required_information"]:
        reason = None
        if item == "vehicle identity" and not reg and not rto:
            reason = "No matching vehicle in Vehicle Registry or Registration Authority"
        elif item == "current owner" and not (ctx["attributes"].get("owner") or ctx["attributes"].get("rto_registered_owner")):
            reason = "No owner recorded in the queried sources"
        elif item in ("insurance status", "policy validity dates", "insurer", "coverage", "claims"):
            if down("insurance_records"):
                reason = "Insurance Records service unavailable"
            elif not policies and "insurance_records" in avail:
                reason = ("No policy for this vehicle in Insurance Records (a database finding, not proof "
                          "that the vehicle is uninsured elsewhere)") if item == "insurance status" else None
            elif item == "claims" and policies and not any(p["related"].get("claims") for p in policies):
                reason = None  # empty claims list is an answer, not missing data
        elif item in ("theft status", "scrapping status", "theft reports"):
            if down("theft_scrapping"):
                reason = "Theft & Scrapping service unavailable — status cannot be confirmed"
            elif not theft and "theft_scrapping" in avail:
                reason = ("Vehicle not present in Theft & Scrapping DB: status NOT_RECORDED, which is "
                          "not a clearance") if item != "theft reports" else None
        elif item in ("registration certificate status", "ownership transfers", "rto events"):
            if down("registration_authority"):
                reason = "Registration Authority service unavailable"
            elif not rto and "registration_authority" in avail:
                reason = "No RTO registration found for this vehicle"
            elif item == "registration certificate status" and rto and not rto["related"].get("certificates"):
                reason = "RTO registration has no certificate row"
        elif item == "audit history" and down("audit_log"):
            reason = "Audit Log service unavailable"
        if reason:
            missing.append({"item": item, "reason": reason})
    return missing


def retrieval_context(understanding, ctx, integration) -> Dict[str, Any]:
    attrs, sel = ctx["attributes"], ctx["selected"]
    facts = {k: v["value"] for k, v in attrs.items() if not isinstance(v["value"], list)}
    risk = integration["insurance_risk"]
    if risk.get("status") not in (None, "NOT_QUERIED"):
        facts["insurance_status"] = risk["status"]
    identifiers = {"policy_numbers": [], "claim_numbers": [], "fir_numbers": [], "rc_numbers": [], "certificate_numbers": []}
    names, orgs, dates = set(), set(), set()
    for p in sel.get("insurance_records", []):
        rec = p["record"]
        identifiers["policy_numbers"].append(rec.get("policy_number"))
        orgs.add(rec.get("insurer") or "")
        names.add(rec.get("holder_name") or "")
        dates.update([rec.get("policy_start_date"), rec.get("expiry_date")])
        facts.setdefault("policy_status", rec.get("policy_status"))
        facts.setdefault("policy_holder", rec.get("holder_name"))
        for c in p["related"].get("claims") or []:
            identifiers["claim_numbers"].append(c["claim_number"])
            dates.add(c["claim_date"])
    for r in sel.get("registration_authority", []):
        for c in r["related"].get("certificates") or []:
            identifiers["rc_numbers"].append(c["rc_number"])
        for t in r["related"].get("transfers") or []:
            names.update([t["previous_owner"], t["new_owner"]])
            dates.add(t["transfer_date"])
        for e in r["related"].get("events") or []:
            if e["event_type"] != "NEW_REGISTRATION":
                dates.add(e["event_date"])
        office = r["related"].get("office")
        if office:
            orgs.add(office["office_name"])
    for t in sel.get("theft_scrapping", []):
        for rep in t["related"].get("theft_reports") or []:
            identifiers["fir_numbers"].append(rep["fir_number"])
            dates.add(rep["report_date"])
            if rep.get("station"):
                orgs.add(rep["station"]["station_name"])
        for s in t["related"].get("scrapping_records") or []:
            if s.get("certificate_number"):
                identifiers["certificate_numbers"].append(s["certificate_number"])
            dates.update([s.get("application_date"), s.get("scrap_date")])
    if facts.get("owner"):
        names.add(facts["owner"])
    alternatives: Dict[str, List[Dict[str, Any]]] = {
        k: [{"value": a["value"], "source": a["source"]} for a in v["alternatives"]]
        for k, v in attrs.items() if v.get("alternatives")}
    if attrs.get("rto_registered_owner"):
        alternatives.setdefault("owner", []).append({"value": attrs["rto_registered_owner"]["value"],
                                                     "source": "registration_authority"})
    return {
        "plate": ctx["resolved_entity"].get("registration_number") or understanding["registration_number"],
        "intents": understanding["intents"], "intent_terms": understanding["intent_labels"],
        "facts": facts, "fact_alternatives": alternatives, "identifiers": {k: sorted({x for x in v if x}) for k, v in identifiers.items()},
        "names": sorted(n for n in names if n), "organisations": sorted(o for o in orgs if o),
        "dates": sorted(d for d in dates if d),
    }


# =============================================================================
# Final answer
# =============================================================================
def compose_answer(understanding, ctx, integ, docs, missing) -> Dict[str, Any]:
    attrs, sel = ctx["attributes"], ctx["selected"]
    entity = ctx["resolved_entity"]
    plate = entity.get("registration_number")
    intents = set(understanding["intents"])
    statements: List[Dict[str, Any]] = []

    def fact(text, sources):
        statements.append({"kind": "database_fact", "text": text, "sources": sources})

    if not plate:
        headline = "No vehicle in the queried databases matches this registration number."
        return {"headline": headline, "statements": [{"kind": "missing", "text": headline, "sources": []}]}

    if entity["registration_number"] != entity["query_plate"] and entity["query_plate"]:
        statements.append({"kind": "resolution", "text": f"Query plate '{entity['query_plate']}' was resolved to "
                           f"{plate} ({entity['method']}; confidence {entity['confidence']}).",
                           "sources": entity["sources_agreeing"]})
    v = {k: (attrs.get(k) or {}).get("value") for k in ("make", "model", "colour", "vehicle_type", "state", "registration_date", "owner")}
    if v["make"]:
        src = attrs["make"]["source"]
        fact(f"{plate} is a {v['colour'] or ''} {v['make']} {v['model'] or ''}"
             f"{' (' + v['vehicle_type'] + ')' if v['vehicle_type'] else ''} registered in {v['state']} on "
             f"{v['registration_date']}{', owned by ' + v['owner'] if v['owner'] else ''}.".replace("  ", " "),
             [f"{src}:{attrs['make']['record']}"])
    others = (attrs.get("owner_other_vehicles") or {}).get("value")
    if others and intents & {"OWNERSHIP", "FULL_HISTORY"}:
        fact(f"The same owner also owns: {', '.join(others)}.", [f"vehicle_registry:{attrs['owner_other_vehicles']['record']}"])

    risk = integ["insurance_risk"]
    if risk.get("status") != "NOT_QUERIED":
        policies = sel.get("insurance_records") or []
        pol_txt = "; ".join(f"{p['record']['policy_number']} ({p['record']['insurer']}, {p['record']['policy_start_date']} "
                            f"to {p['record']['expiry_date']}, {p['record']['policy_status']})" for p in policies)
        statements.append({"kind": "assessment", "text": f"Insurance: {risk['status_label']}."
                           + (f" Policies: {pol_txt}." if pol_txt else ""),
                           "sources": [f"insurance_records:insurance_policies#{p['record_id']}" for p in policies]})
        claims = [c for p in policies for c in (p["related"].get("claims") or [])]
        if claims and intents & {"INSURANCE", "FULL_HISTORY", "THEFT"}:
            fact("Claims: " + "; ".join(f"{c['claim_number']} {c['claim_type']} on {c['claim_date']} — {c['claim_status']}" for c in claims) + ".",
                 [f"insurance_records:insurance_claims#{c['id']}" for c in claims])

    rto = (sel.get("registration_authority") or [None])[0]
    if rto:
        certs = rto["related"].get("certificates") or []
        if certs:
            c = certs[-1]
            fact(f"RC {c['rc_number']} is {c['rc_status']} (valid until {c['valid_until']}), issued by "
                 f"{(rto['related'].get('office') or {}).get('office_name', 'the RTO')}.",
                 [f"registration_authority:registration_certificates#{c['id']}"])
        transfers = rto["related"].get("transfers") or []
        if intents & {"OWNERSHIP", "FULL_HISTORY"}:
            if transfers:
                fact("Ownership transfers: " + "; ".join(f"{t['transfer_date']} {t['previous_owner']} → {t['new_owner']} ({t['transfer_reason']})"
                                                       for t in transfers) + ".",
                     [f"registration_authority:ownership_transfers#{t['id']}" for t in transfers])
            elif "transfers" in (rto.get("related") or {}):
                fact("No ownership transfer is recorded by the RTO.", [f"registration_authority:rto_registrations#{rto['record_id']}"])

    theft = (sel.get("theft_scrapping") or [None])[0]
    avail = ctx["service_availability"]
    if theft:
        r = theft["record"]
        reports = theft["related"].get("theft_reports") or []
        text = f"Theft & Scrapping DB: theft status {r['theft_status']}, scrapping status {r['scrapping_status']}."
        if reports:
            text += " " + "; ".join(f"FIR {t['fir_number']} ({t['report_date']}, {t['station']['station_name']}) — {t['report_status']}" for t in reports) + "."
        scraps = theft["related"].get("scrapping_records") or []
        if scraps:
            text += " " + "; ".join(f"Scrapping: {s['scrap_status']} at {s['facility_name']}" + (f", certificate {s['certificate_number']}" if s.get("certificate_number") else "") for s in scraps) + "."
        fact(text, [f"theft_scrapping:theft_scrapping_records#{theft['record_id']}"])
    elif "theft_scrapping" in avail:
        statements.append({"kind": "missing", "text": "Theft/scrapping status could not be confirmed (no record or service unavailable); this is NOT a clearance.", "sources": []})

    audits = ctx["audit_entries"]
    if "audit_log" in avail:
        if audits:
            fact(f"{len(audits)} previous cleansing decision(s); latest: {audits[0]['field_name']} → {audits[0]['reviewer_decision']} "
                 f"by {audits[0].get('reviewer') or 'unknown'} ({(audits[0].get('timestamp') or '')[:10]}).",
                 [f"audit_log:cleansing_audit_log#{a['id']}" for a in audits])
        elif avail["audit_log"]["status"] == "ok":
            fact("No previous cleansing decisions are recorded for this vehicle.", ["audit_log"])

    for d in docs.get("documents", [])[:4]:
        checks = [c for c in d["evidence_checks"] if c["status"] != "DOCUMENT_ONLY"]
        check_txt = ", ".join(
            f"{c['field']} {c['status'].lower().replace('_alternative', ' ' + c.get('supported_source', '') + ' value')} "
            f"({c['document_value']})" for c in checks[:4])
        statements.append({"kind": "document_evidence", "text": f"{d['doc_id']} — {d['title']} ({d['document_type']}, "
                           f"{d['metadata'].get('date')}){': ' + check_txt if check_txt else ''}.",
                           "sources": [f"document:{d['source']}"]})
    if not docs.get("documents"):
        statements.append({"kind": "document_evidence", "text": "No vehicle-specific document was found in the repository. "
                           "Absence of documents neither confirms nor refutes any status.", "sources": []})
    for c in integ["conflicts"]:
        statements.append({"kind": "conflict", "text": c["description"] + (f" — {c['explanation']}" if c.get("explanation") else ""),
                           "sources": [f"{e['source']}:{e['record']}" for e in c["evidence"]]})
    for m in missing:
        statements.append({"kind": "missing", "text": f"Missing: {m['item']} — {m['reason']}", "sources": []})

    flags = []
    if theft and theft["record"]["theft_status"] == "STOLEN":
        flags.append("REPORTED STOLEN")
    if theft and theft["record"]["scrapping_status"] in ("SCRAPPED", "PENDING_SCRAP"):
        flags.append(theft["record"]["scrapping_status"])
    if risk.get("status") not in (None, "NOT_QUERIED"):
        flags.append(f"insurance {risk['status']}")
    if integ["conflicts"]:
        flags.append(f"{len(integ['conflicts'])} conflict(s)")
    headline = f"{plate}: " + (", ".join(flags) if flags else "records found") + "."
    return {"headline": headline, "statements": statements}


# =============================================================================
# Orchestrator
# =============================================================================
async def run_federated_query(query: str, plate: Optional[str] = None, context: Optional[Dict[str, Any]] = None,
                              plate_source: Optional[str] = None, *, urls: Optional[Dict[str, str]] = None,
                              timeout: Optional[float] = None, transport: Optional[httpx.AsyncBaseTransport] = None,
                              include_documents: bool = True, top_k_documents: int = 6, store=None,
                              today: Optional[datetime.date] = None) -> Dict[str, Any]:
    urls = urls or config.service_urls()
    timeout = timeout or config.FEDERATION_TIMEOUT
    stages: List[Dict[str, Any]] = []
    t_all = time.perf_counter()

    def stage(name, started, detail):
        stages.append({"stage": name, "ms": round((time.perf_counter() - started) * 1000, 1), "detail": detail})

    t = time.perf_counter()
    understanding = understand_query(query, plate, context, plate_source)
    stage("Query Understanding", t, f"plate={understanding['registration_number'] or '-'}; intents={', '.join(understanding['intents'])}")
    t = time.perf_counter()
    decomposition = decompose_query(understanding)
    stage("Query Decomposition", t, f"{len(decomposition['subqueries'])} subqueries: {', '.join(decomposition['selected_services'])}")

    base = {"understanding": understanding, "decomposition": decomposition, "stages": stages}
    if not understanding["registration_number"] and not understanding["attributes"]:
        base.update({"error": "No registration number found. Type a plate in the query, upload a plate image, or enter it explicitly.",
                     "answer": {"headline": "No registration number in the query.", "statements": []}})
        return base

    t = time.perf_counter()
    wave1 = [(s["service"], s["payload"], "local match + FK-PK expansion") for s in decomposition["subqueries"] if s["wave"] == 1]
    client = _client(timeout, transport)
    try:
        calls1, wave1_ms = await _run_wave(client, wave1, urls, 1)
    except Exception:
        await client.aclose()
        raise
    ok1 = sum(c["status"] == "ok" for c in calls1)
    stage("Federated Execution (wave 1, parallel)", t, f"{ok1}/{len(calls1)} services answered in {wave1_ms} ms wall time")

    t = time.perf_counter()
    entity = resolve_entity(understanding["registration_number"], calls1)
    if not understanding["registration_number"] and entity["registration_number"]:
        # attribute-only query: the registry matched candidates by make/model/colour/state
        reg_call = next((c for c in calls1 if c["service"] == "vehicle_registry" and c["status"] == "ok"), None)
        n = len(reg_call["result"]["matches"]) if reg_call else 0
        entity["method"] = (f"Attribute search {understanding['attributes']}: {n} registry candidate(s); "
                            f"best {entity['registration_number']}")
        entity["confidence"] = "MEDIUM" if n == 1 else "LOW"
    stage("Local Context Discovery + Entity Resolution", t, f"resolved={entity['registration_number'] or 'none'} "
          f"({entity['confidence']}); sources agreeing: {', '.join(entity['sources_agreeing']) or '-'}")

    t = time.perf_counter()
    wave2: List[Tuple[str, Dict[str, Any], str]] = []
    resolved = entity.get("registration_number")
    if resolved:
        for c in calls1:
            if c["status"] == "ok" and c["service"] in PLATE_FIELD and resolved != understanding["registration_number"]:
                found = {_record_plate(c["service"], m["record"]) for m in c["result"]["matches"]}
                if resolved not in found:
                    wave2.append((c["service"], {**c["payload"], "plate": resolved, "mode": "lookup"},
                                  f"re-query with resolved plate {resolved}"))
        audit_sub = next((s for s in decomposition["subqueries"] if s["service"] == "audit_log"), None)
        if audit_sub:
            refs = []
            for c in calls1:
                if c["status"] == "ok" and c["service"] in PLATE_FIELD:
                    refs += [{"source": c["service"], "record_id": m["record_id"]} for m in c["result"]["matches"]
                             if _record_plate(c["service"], m["record"]) in entity["cluster"]]
            wave2.append(("audit_log", {**audit_sub["payload"], "plate": resolved, "record_refs": refs},
                          f"audit lookup for {len(refs)} record reference(s) discovered in wave 1"))
    try:
        calls2, wave2_ms = await _run_wave(client, wave2, urls, 2)
    finally:
        await client.aclose()
    stage("Federated Execution (wave 2, context-dependent)", t,
          f"{len(calls2)} subqueries ({', '.join(c['service'] for c in calls2) or 'none'}) in {wave2_ms} ms")

    t = time.perf_counter()
    ctx = accumulate_context(understanding, decomposition, calls1 + calls2, entity)
    stage("Context Accumulation", t, f"{len(ctx['matched_entities'])} matched, {len(ctx['related_entities'])} related groups, "
          f"{len(ctx['relationship_paths'])} FK paths, {len(ctx['filtered_out'])} filtered out")

    t = time.perf_counter()
    integ = integrate(understanding, ctx, today)
    stage("Cross-Database Integration", t, f"insurance={integ['insurance_risk'].get('status')}; {len(integ['conflicts'])} conflict(s); "
          f"{len(integ['cleansing_proposals'])} cleansing proposal(s)")

    t = time.perf_counter()
    rctx = retrieval_context(understanding, ctx, integ)
    docs: Dict[str, Any] = {"documents": [], "general_documents": [], "rejected": [], "context_used": rctx}
    if include_documents and resolved:
        if store is None:
            from retrieval import get_store
            store = get_store()
        docs = {**store.retrieve_for_context(rctx, top_k=top_k_documents), "context_used": rctx}
        for d in docs["documents"]:
            for check in d["evidence_checks"]:
                if check["status"] == "SUPPORTS_ALTERNATIVE":
                    # Attach the document as evidence to the existing DB-vs-DB conflict; never auto-resolve it.
                    for c in integ["conflicts"]:
                        if any(e.get("value") == check["supported_value"] for e in c["evidence"]):
                            c["evidence"].append({"source": "document", "record": d["source"], "field": check["field"],
                                                  "value": check["document_value"],
                                                  "note": f"supports {check['supported_source']}"})
                if check["status"] == "CONFLICTS":
                    integ["conflicts"].append(_conflict("document_vs_database", "LOW",
                        f"{d['doc_id']} states {check['field']} '{check['document_value']}' but the database has '{check['database_value']}'",
                        [{"source": "document", "record": d["source"], "field": check["field"], "value": check["document_value"]}]))
    stage("Unstructured Retrieval", t, f"{len(docs['documents'])} vehicle documents, {len(docs.get('general_documents', []))} general, "
          f"{len(docs.get('rejected', []))} rejected by context")

    t = time.perf_counter()
    missing = missing_information(understanding, ctx, integ)
    answer = compose_answer(understanding, ctx, integ, docs, missing)
    stage("Structured + Unstructured Integration → Final Answer", t, answer["headline"])

    ctx["database_results"] = ctx.pop("selected")  # per-service matched records with related rows + FK paths
    return {**base, "context": ctx, "integration": integ, "documents": docs, "missing_information": missing,
            "answer": answer, "total_ms": round((time.perf_counter() - t_all) * 1000, 1),
            "executed_at": datetime.datetime.now(datetime.timezone.utc).isoformat()}
