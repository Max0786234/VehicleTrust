import datetime
from typing import Any, Dict, List, Optional, Tuple
import httpx
from database_common import log_cleansing_action
from matching import damerau_levenshtein_similarity, normalize_plate


def get_cleansing_audit_logs(
    limit: int = 100,
    source: Optional[str] = None,
    audit_api_url: Optional[str] = None,
) -> List[Dict[str, Any]]:
    if not audit_api_url:
        from database_common import get_audit_logs

        return get_audit_logs(limit, source)

    params: Dict[str, Any] = {"limit": limit}
    if source:
        params["source"] = source
    try:
        response = httpx.get(f"{audit_api_url.rstrip('/')}/records", params=params, timeout=5.0)
        response.raise_for_status()
    except httpx.HTTPError as exc:
        raise RuntimeError(f"Could not retrieve cleansing audit records: {exc}") from exc
    return response.json()


def _write_cleansing_audit(api_urls: Dict[str, str], entry: Dict[str, Any]) -> None:
    audit_api_url = api_urls.get("audit_log")
    if not audit_api_url:
        log_cleansing_action(**entry)
        return
    try:
        response = httpx.post(f"{audit_api_url.rstrip('/')}/records", json=entry, timeout=5.0)
        response.raise_for_status()
    except httpx.HTTPError as exc:
        raise RuntimeError(f"Could not record cleansing audit outcome: {exc}") from exc


class SchemaMapper:
    """Maps heterogeneous source database schemas to canonical fields."""

    SOURCE_MAPPINGS = {
        "vehicle_registry": {
            "plate": "registration_number",
            "make": "make",
            "model": "model",
            "colour": "colour",
            "vehicle_type": "vehicle_type",
            "registration_date": "registration_date",
            "state": "state",
        },
        "insurance_records": {
            "plate": "recorded_vehicle_number",
            "policy_number": "policy_number",
            "insurer": "insurer",
            "policy_start_date": "policy_start_date",
            "expiry_date": "expiry_date",
            "policy_status": "policy_status",
        },
        "registration_authority": {
            "plate": "plate_identifier",
            "make": "make",
            "model": "model",
            "colour": "colour",
            "registration_date": "registration_date",
            "state": "state",
            "authority_reference": "authority_reference",
        },
        "theft_scrapping": {
            "plate": "reported_plate",
            "theft_status": "theft_status",
            "report_date": "report_date",
            "scrapping_status": "scrapping_status",
        },
    }

    @classmethod
    def to_canonical(cls, source_name: str, raw_record: Dict[str, Any]) -> Dict[str, Any]:
        mapping = cls.SOURCE_MAPPINGS.get(source_name, {})
        canonical = {
            "source_system": source_name,
            "source_record_id": raw_record.get("id"),
            "raw_record": raw_record,
        }
        for canon_field, source_field in mapping.items():
            canonical[canon_field] = raw_record.get(source_field)
        if "plate" in canonical and canonical["plate"]:
            canonical["normalized_plate"] = normalize_plate(canonical["plate"])
        return canonical


class CanonicalVehicleRecord:
    """Consolidated representation combining records from all four sources."""

    def __init__(self, target_plate: str):
        self.target_plate = normalize_plate(target_plate)
        self.registry_record: Optional[Dict[str, Any]] = None
        self.authority_record: Optional[Dict[str, Any]] = None
        self.insurance_records: List[Dict[str, Any]] = []
        self.theft_record: Optional[Dict[str, Any]] = None
        self.conflicts: List[Dict[str, Any]] = []
        self.confidence_tier: str = "UNKNOWN"
        self.match_score: float = 0.0

    def add_source_record(self, source_name: str, record: Dict[str, Any], score: float, confidence: str):
        self.match_score = max(self.match_score, score)
        if confidence == "HIGH" or self.confidence_tier == "UNKNOWN":
            self.confidence_tier = confidence

        canon = SchemaMapper.to_canonical(source_name, record)
        if source_name == "vehicle_registry":
            self.registry_record = canon
        elif source_name == "registration_authority":
            self.authority_record = canon
        elif source_name == "insurance_records":
            self.insurance_records.append(canon)
        elif source_name == "theft_scrapping":
            self.theft_record = canon

    def detect_conflicts(self):
        """Identifies discrepancies between registry and registration authority."""
        self.conflicts.clear()
        if not self.registry_record or not self.authority_record:
            return
        r, a = self.registry_record, self.authority_record
        for field in ["make", "model", "colour", "state"]:
            val_r, val_a = r.get(field), a.get(field)
            if val_r and val_a and str(val_r).strip().lower() != str(val_a).strip().lower():
                self.conflicts.append({
                    "field": field, "registry_val": val_r, "authority_val": val_a,
                    "description": f"{field.capitalize()} mismatch: Registry has '{val_r}', Authority has '{val_a}'",
                })

    def to_dict(self) -> Dict[str, Any]:
        self.detect_conflicts()
        return {
            "target_plate": self.target_plate,
            "match_score": self.match_score,
            "confidence_tier": self.confidence_tier,
            "has_registry": self.registry_record is not None,
            "has_authority": self.authority_record is not None,
            "insurance_count": len(self.insurance_records),
            "has_theft_record": self.theft_record is not None,
            "registry": self.registry_record,
            "authority": self.authority_record,
            "insurance": self.insurance_records,
            "theft_scrapping": self.theft_record,
            "conflicts": self.conflicts,
        }


def parse_iso_date(date_str: Optional[str]) -> Optional[datetime.date]:
    """Safely parses YYYY-MM-DD date."""
    if not date_str:
        return None
    try:
        return datetime.datetime.strptime(str(date_str).strip()[:10], "%Y-%m-%d").date()
    except (ValueError, TypeError):
        return None


def evaluate_insurance_risk(
    insurance_records: List[Dict[str, Any]],
    theft_record: Optional[Dict[str, Any]] = None,
    evaluation_date: Optional[datetime.date] = None,
    plate_confidence: str = "HIGH",
    insurance_service_available: bool = True,
) -> Dict[str, Any]:
    """
    Evaluates insurance compliance and risk status based on explicit date rules.
    Possible outcomes:
      CURRENT, EXPIRED, NOT_FOUND, CONFLICTING, UNVERIFIED, FUTURE_POLICY
    Theft and scrapping statuses are evaluated separately.
    """
    today = evaluation_date or datetime.date.today()

    # If the insurance service was unreachable, status is UNVERIFIED
    if not insurance_service_available:
        return {
            "status": "UNVERIFIED",
            "status_label": "Unverified (Insurance Service Offline)",
            "risk_level": "WARNING",
            "evaluation_date": today.isoformat(),
            "policy_details": None,
            "theft_status": theft_record.get("theft_status", "UNKNOWN") if theft_record else "UNKNOWN",
            "scrapping_status": theft_record.get("scrapping_status", "UNKNOWN") if theft_record else "UNKNOWN",
            "recommended_action": "Retry query once the Insurance database service is online.",
            "disclaimer": "Decision-support assessment only; not an official government verification certificate.",
        }

    # If matching confidence is low, do not assert insurance absence
    if plate_confidence == "LOW":
        return {
            "status": "UNVERIFIED",
            "status_label": "Unverified (Low Plate Confidence)",
            "risk_level": "INFO",
            "evaluation_date": today.isoformat(),
            "policy_details": None,
            "theft_status": theft_record.get("theft_status", "UNKNOWN") if theft_record else "UNKNOWN",
            "scrapping_status": theft_record.get("scrapping_status", "UNKNOWN") if theft_record else "UNKNOWN",
            "recommended_action": "Verify registration number manually before evaluating insurance compliance.",
            "disclaimer": "Decision-support assessment only; not an official government verification certificate.",
        }

    # No policies found
    if not insurance_records:
        return {
            "status": "NOT_FOUND",
            "status_label": "No Policy Found",
            "risk_level": "HIGH_RISK",
            "evaluation_date": today.isoformat(),
            "policy_details": None,
            "theft_status": theft_record.get("theft_status", "UNKNOWN") if theft_record else "NOT_RECORDED",
            "scrapping_status": theft_record.get("scrapping_status", "UNKNOWN") if theft_record else "NOT_RECORDED",
            "recommended_action": "Request physical or digital insurance certificate from owner; issue inquiry notice.",
            "disclaimer": "Decision-support assessment only; not an official government verification certificate.",
        }

    # Check for conflicting policies
    active_policies = []
    expired_policies = []
    future_policies = []

    for item in insurance_records:
        rec = item.get("raw_record", item)
        start_d = parse_iso_date(rec.get("policy_start_date"))
        end_d = parse_iso_date(rec.get("expiry_date"))
        status_str = str(rec.get("policy_status", "")).upper()

        if not start_d or not end_d:
            continue

        if start_d > today:
            future_policies.append((rec, start_d, end_d))
        elif end_d < today or status_str == "EXPIRED":
            expired_policies.append((rec, start_d, end_d))
        elif start_d <= today <= end_d and status_str == "ACTIVE":
            active_policies.append((rec, start_d, end_d))
        else:
            # Policy marked active but dates expired or vice versa
            expired_policies.append((rec, start_d, end_d))

    theft_st = theft_record.get("theft_status", "UNKNOWN") if theft_record else "NOT_RECORDED"
    scrap_st = theft_record.get("scrapping_status", "UNKNOWN") if theft_record else "NOT_RECORDED"

    # Evaluation logic
    if len(active_policies) > 1:
        # Check if multiple active policies have conflicting insurers
        insurers = {p[0].get("insurer") for p in active_policies}
        if len(insurers) > 1:
            return {
                "status": "CONFLICTING",
                "status_label": "Conflicting Active Policies",
                "risk_level": "WARNING",
                "evaluation_date": today.isoformat(),
                "policy_details": [p[0] for p in active_policies],
                "theft_status": theft_st,
                "scrapping_status": scrap_st,
                "recommended_action": "Investigate concurrent insurance policies across multiple underwriting entities.",
                "disclaimer": "Decision-support assessment only; not an official government verification certificate.",
            }

    if active_policies:
        primary = active_policies[0][0]
        return {
            "status": "CURRENT",
            "status_label": "Insurance Valid & Current",
            "risk_level": "CLEAR",
            "evaluation_date": today.isoformat(),
            "policy_details": primary,
            "theft_status": theft_st,
            "scrapping_status": scrap_st,
            "recommended_action": "No action required. Coverage verified active.",
            "disclaimer": "Decision-support assessment only; not an official government verification certificate.",
        }

    if future_policies and not expired_policies:
        primary = future_policies[0][0]
        return {
            "status": "FUTURE_POLICY",
            "status_label": "Future Policy (Not Yet Active)",
            "risk_level": "WARNING",
            "evaluation_date": today.isoformat(),
            "policy_details": primary,
            "theft_status": theft_st,
            "scrapping_status": scrap_st,
            "recommended_action": "Check current policy coverage until new policy inception date.",
            "disclaimer": "Decision-support assessment only; not an official government verification certificate.",
        }

    if expired_policies:
        # Sort by expiry date descending to get the most recently expired
        expired_policies.sort(key=lambda x: x[2], reverse=True)
        primary = expired_policies[0][0]
        days_expired = (today - expired_policies[0][2]).days
        return {
            "status": "EXPIRED",
            "status_label": f"Insurance Expired ({days_expired} days ago)",
            "risk_level": "HIGH_RISK",
            "evaluation_date": today.isoformat(),
            "policy_details": primary,
            "theft_status": theft_st,
            "scrapping_status": scrap_st,
            "recommended_action": "Issue Section 196 Motor Vehicles Act challan / notice for uninsured operation.",
            "disclaimer": "Decision-support assessment only; not an official government verification certificate.",
        }

    return {
        "status": "UNVERIFIED",
        "status_label": "Unverified Policy Data",
        "risk_level": "WARNING",
        "evaluation_date": today.isoformat(),
        "policy_details": None,
        "theft_status": theft_st,
        "scrapping_status": scrap_st,
        "recommended_action": "Manual document review required.",
        "disclaimer": "Decision-support assessment only; not an official government verification certificate.",
    }


def generate_cleansing_proposals(canonical_record: Dict[str, Any]) -> List[Dict[str, Any]]:
    proposals: List[Dict[str, Any]] = []
    reg = (canonical_record.get("registry") or {}).get("raw_record", {})
    auth = (canonical_record.get("authority") or {}).get("raw_record", {})
    if not reg or not auth:
        return proposals

    target_plate = normalize_plate(canonical_record.get("target_plate"))
    registry_plate = normalize_plate(reg.get("registration_number"))
    authority_plate = normalize_plate(auth.get("plate_identifier"))
    if not target_plate or not registry_plate or not authority_plate:
        return proposals
    if min(
        damerau_levenshtein_similarity(target_plate, registry_plate),
        damerau_levenshtein_similarity(target_plate, authority_plate),
        damerau_levenshtein_similarity(registry_plate, authority_plate),
    ) < 0.80:
        return proposals

    fields = ["registration_number", "make", "model", "colour", "state"]
    for f_key in fields:
        registry_field = "registration_number" if f_key == "registration_number" else f_key
        authority_field = "plate_identifier" if f_key == "registration_number" else f_key
        curr_val, prop_val = reg.get(registry_field), auth.get(authority_field)
        if prop_val is None or not str(prop_val).strip():
            continue
        values_match = (
            normalize_plate(curr_val) == normalize_plate(prop_val)
            if f_key == "registration_number"
            else str(curr_val or "").strip().casefold() == str(prop_val).strip().casefold()
        )
        if not values_match:
            label = "Registration Number" if f_key == "registration_number" else f_key.capitalize()
            proposals.append({
                "field_name": f_key,
                "field_label": label,
                "target_source": "vehicle_registry",
                "record_id": reg.get("id"),
                "current_value": curr_val,
                "proposed_value": prop_val,
                "proposed_by": "registration_authority",
                "source_record_id": auth.get("id"),
                "source_plate": auth.get("plate_identifier"),
                "registry_plate": reg.get("registration_number"),
                "reason": f"Review {label} against the registration authority record for the same likely vehicle.",
            })
    return proposals


def apply_cleansing_decision(
    proposal: Dict[str, Any],
    decision: str,  # ACCEPTED, REJECTED, UNRESOLVED
    reason: str,
    api_urls: Dict[str, str],
) -> Tuple[bool, str]:
    """Validates and applies a reviewed registry correction, then records its outcome."""
    source = proposal.get("target_source", "")
    rec_id = proposal.get("record_id")
    field = proposal.get("field_name", "")
    old_val = proposal.get("current_value")
    new_val = proposal.get("proposed_value")
    decision = decision.strip().upper()
    valid_decisions = {"ACCEPTED", "REJECTED", "UNRESOLVED"}
    valid_fields = {"registration_number", "make", "model", "colour", "state"}
    if decision not in valid_decisions:
        return False, f"Unsupported cleansing decision: {decision}"
    if source != "vehicle_registry" or field not in valid_fields:
        return False, "Cleansing is restricted to supported vehicle registry fields."
    if not isinstance(rec_id, int) or rec_id <= 0:
        return False, "The target registry record ID is invalid."
    if (old_val is not None and not isinstance(old_val, str)) or not isinstance(new_val, str) or not new_val.strip():
        return False, "The proposal must contain a valid current value and non-empty proposed value."
    if proposal.get("proposed_by") != "registration_authority":
        return False, "The proposed correction must be backed by a registration authority record."

    def record_outcome(outcome: str, new_value: Optional[str], detail: str) -> None:
        _write_cleansing_audit(api_urls, {
            "affected_source": source,
            "record_id": rec_id,
            "field_name": field,
            "old_value": old_val,
            "new_value": new_value,
            "reviewer_decision": outcome,
            "reason": "; ".join(part for part in (reason.strip(), detail) if part),
            # Phase 3: cross-DB identifier + evidence rows (audit_evidence / data_change_history)
            "vehicle_plate": normalize_plate(proposal.get("registry_plate")) or None,
            "evidence": {
                "source": proposal.get("proposed_by"),
                "record_id": proposal.get("source_record_id"),
                "field": "plate_identifier" if field == "registration_number" else field,
                "value": new_val,
                "plate_similarity": round(damerau_levenshtein_similarity(
                    proposal.get("registry_plate") or "", proposal.get("source_plate") or ""), 4),
                "description": "Registration authority record backing the proposed correction",
            },
        })

    if decision != "ACCEPTED":
        record_outcome(decision, None, "")
        return True, f"Cleansing proposal marked {decision}. Audit log updated."

    authority_id = proposal.get("source_record_id")
    if not isinstance(authority_id, int) or authority_id <= 0:
        return False, "The proposal is missing its registration authority record ID."
    registry_url = api_urls.get("vehicle_registry")
    authority_url = api_urls.get("registration_authority")
    if not registry_url or not authority_url:
        return False, "Both vehicle registry and registration authority endpoints are required."

    registry_record_url = f"{registry_url.rstrip('/')}/records/{rec_id}"
    authority_record_url = f"{authority_url.rstrip('/')}/records/{authority_id}"
    authority_field = "plate_identifier" if field == "registration_number" else field

    try:
        with httpx.Client(timeout=5.0) as client:
            registry_response = client.get(registry_record_url)
            authority_response = client.get(authority_record_url)
            if registry_response.status_code != 200 or authority_response.status_code != 200:
                detail = (
                    f"Unable to verify current registry/authority records "
                    f"(HTTP {registry_response.status_code}/{authority_response.status_code})."
                )
                record_outcome("FAILED", None, detail)
                return False, detail

            current_registry = registry_response.json()
            current_authority = authority_response.json()
            current_value = current_registry.get(field)
            authority_plate = normalize_plate(current_authority.get("plate_identifier"))
            registry_plate = normalize_plate(current_registry.get("registration_number"))
            expected_authority_plate = normalize_plate(proposal.get("source_plate"))
            expected_registry_plate = normalize_plate(proposal.get("registry_plate"))

            if current_value != old_val or registry_plate != expected_registry_plate:
                detail = "The registry record changed after this proposal was generated; refresh and review it again."
                record_outcome("STALE", None, detail)
                return False, detail
            if authority_plate != expected_authority_plate or current_authority.get(authority_field) != new_val:
                detail = "The registration authority evidence no longer matches this proposal."
                record_outcome("FAILED", None, detail)
                return False, detail
            if damerau_levenshtein_similarity(registry_plate, authority_plate) < 0.80:
                detail = "The registry and authority plates are not a sufficiently close vehicle match."
                record_outcome("FAILED", None, detail)
                return False, detail

            update_response = client.put(
                registry_record_url,
                json={field: new_val.strip()},
            )
            if update_response.status_code not in (200, 204):
                detail = f"Registry update failed (HTTP {update_response.status_code}): {update_response.text}"
                record_outcome("FAILED", None, detail)
                return False, detail
    except httpx.HTTPError as exc:
        detail = f"Failed to contact a vehicle data service: {exc}"
        record_outcome("FAILED", None, detail)
        return False, detail

    record_outcome("ACCEPTED", new_val.strip(), "Registry update succeeded.")
    return True, f"Successfully updated {field} in vehicle_registry (Record #{rec_id}) to '{new_val.strip()}'."
