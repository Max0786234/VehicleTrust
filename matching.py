import re
from typing import Any, Dict, List, Optional, Set, Tuple

try:
    from rapidfuzz import fuzz
    HAS_RAPIDFUZZ = True
except ImportError:
    HAS_RAPIDFUZZ = False

# Character confusion mappings common in optical character recognition (OCR)
OCR_CONFUSIONS: Dict[str, List[str]] = {
    "O": ["0"],
    "0": ["O"],
    "I": ["1"],
    "1": ["I"],
    "B": ["8"],
    "8": ["B"],
    "S": ["5"],
    "5": ["S"],
    "Z": ["2"],
    "2": ["Z"],
    "G": ["6"],
    "6": ["G"],
}

INDIAN_STATES = {
    "AN", "AP", "AR", "AS", "BR", "CH", "CG", "DD", "DL", "DN", "GA", "GJ",
    "HR", "HP", "JH", "JK", "KA", "KL", "LA", "LD", "MP", "MH", "MN", "ML",
    "MZ", "NL", "OD", "PB", "PY", "RJ", "SK", "TN", "TR", "TS", "UK", "UP", "WB", "BH"
}


def normalize_plate(raw_text: Optional[str]) -> str:
    """
    Normalizes a vehicle registration plate string by converting to uppercase
    and removing spaces, hyphens, periods, and special characters.
    """
    if not raw_text:
        return ""
    cleaned = re.sub(r"[^A-Za-z0-9]", "", str(raw_text)).upper()
    return cleaned


def damerau_levenshtein_distance(s1: str, s2: str) -> int:
    """
    Computes true Damerau-Levenshtein distance between two strings,
    supporting insertion, deletion, substitution, and adjacent transposition.
    """
    len1, len2 = len(s1), len(s2)
    if len1 == 0:
        return len2
    if len2 == 0:
        return len1

    # Distance matrix
    d = [[0] * (len2 + 2) for _ in range(len1 + 2)]
    max_dist = len1 + len2
    d[0][0] = max_dist

    da: Dict[str, int] = {}

    for i in range(1, len1 + 2):
        d[i][0] = max_dist
        d[i][1] = i - 1
    for j in range(1, len2 + 2):
        d[0][j] = max_dist
        d[1][j] = j - 1

    for i in range(2, len1 + 2):
        db = 0
        for j in range(2, len2 + 2):
            k = da.get(s2[j - 2], 0)
            l = db
            cost = 0 if s1[i - 2] == s2[j - 2] else 1
            if cost == 0:
                db = j - 1

            d[i][j] = min(
                d[i - 1][j] + 1,        # deletion
                d[i][j - 1] + 1,        # insertion
                d[i - 1][j - 1] + cost,  # substitution
                d[k][l] + (i - 2 - k) + 1 + (j - 2 - l)  # transposition
            )
        da[s1[i - 2]] = i - 1

    return d[len1 + 1][len2 + 1]


def damerau_levenshtein_similarity(s1: str, s2: str) -> float:
    """Normalized Damerau-Levenshtein similarity score between 0.0 and 1.0."""
    n1 = normalize_plate(s1)
    n2 = normalize_plate(s2)
    if not n1 and not n2:
        return 1.0
    if not n1 or not n2:
        return 0.0
    max_len = max(len(n1), len(n2))
    dist = damerau_levenshtein_distance(n1, n2)
    return max(0.0, float(1.0 - (dist / max_len)))


def rapidfuzz_similarity(s1: str, s2: str) -> float:
    """Calculates RapidFuzz ratio normalized to 0.0-1.0."""
    n1 = normalize_plate(s1)
    n2 = normalize_plate(s2)
    if not n1 and not n2:
        return 1.0
    if not n1 or not n2:
        return 0.0
    if HAS_RAPIDFUZZ:
        return float(fuzz.ratio(n1, n2) / 100.0)
    # Fallback to pure python ratio if rapidfuzz is unavailable
    dist = damerau_levenshtein_distance(n1, n2)
    return max(0.0, float(1.0 - (dist / max(len(n1), len(n2)))))


def exact_match(s1: str, s2: str) -> float:
    """Exact normalized equality."""
    return 1.0 if normalize_plate(s1) == normalize_plate(s2) else 0.0


def generate_ocr_confusion_variants(plate: str, max_variants: int = 16) -> List[str]:
    """
    Generates plausible alternative plate numbers based on OCR confusion rules
    and standard Indian vehicle registration syntax patterns (e.g., DL01AB1234).
    Avoids brute-force exponential explosion.
    """
    clean = normalize_plate(plate)
    if not clean:
        return []

    variants: Set[str] = {clean}

    # 1. Structural syntax-guided substitution:
    # Standard format: [2 chars State][2 digits RTO][1-2 chars Series][4 digits Number]
    chars = list(clean)
    plate_len = len(chars)

    if plate_len in (9, 10):
        # Position 0, 1 should be alphabetic state code
        for pos in (0, 1):
            if chars[pos].isdigit() and chars[pos] in OCR_CONFUSIONS:
                for alt in OCR_CONFUSIONS[chars[pos]]:
                    if alt.isalpha():
                        v = chars.copy()
                        v[pos] = alt
                        variants.add("".join(v))

        # Position 2, 3 should be numeric RTO code
        for pos in (2, 3):
            if chars[pos].isalpha() and chars[pos] in OCR_CONFUSIONS:
                for alt in OCR_CONFUSIONS[chars[pos]]:
                    if alt.isdigit():
                        v = chars.copy()
                        v[pos] = alt
                        variants.add("".join(v))

        # Position -4 to end should be numeric unique number
        num_start = plate_len - 4
        for pos in range(num_start, plate_len):
            if chars[pos].isalpha() and chars[pos] in OCR_CONFUSIONS:
                for alt in OCR_CONFUSIONS[chars[pos]]:
                    if alt.isdigit():
                        v = chars.copy()
                        v[pos] = alt
                        variants.add("".join(v))

        # Mid positions should be series letters
        for pos in range(4, num_start):
            if chars[pos].isdigit() and chars[pos] in OCR_CONFUSIONS:
                for alt in OCR_CONFUSIONS[chars[pos]]:
                    if alt.isalpha():
                        v = chars.copy()
                        v[pos] = alt
                        variants.add("".join(v))

    # 2. Single-character substitutions for any confusable char
    for i, ch in enumerate(chars):
        if ch in OCR_CONFUSIONS:
            for replacement in OCR_CONFUSIONS[ch]:
                variant = chars[:i] + [replacement] + chars[i + 1:]
                variants.add("".join(variant))
                if len(variants) >= max_variants:
                    break
        if len(variants) >= max_variants:
            break

    # 3. Transposition check for adjacent pairs
    for i in range(len(chars) - 1):
        if chars[i] != chars[i + 1]:
            transposed = chars.copy()
            transposed[i], transposed[i + 1] = transposed[i + 1], transposed[i]
            variants.add("".join(transposed))
            if len(variants) >= max_variants:
                break

    sorted_variants = sorted(
        list(variants),
        key=lambda v: (v != clean, damerau_levenshtein_distance(clean, v))
    )
    return sorted_variants[:max_variants]


def _match_string_attribute(val1: Optional[str], val2: Optional[str]) -> Tuple[float, str]:
    """
    Compares two string attributes.
    Returns (score, status):
      score: 1.0 (exact), 0.8 (fuzzy), -0.5 (contradiction), 0.0 (unknown/missing)
      status: 'SUPPORTING', 'CONFLICTING', 'UNKNOWN'
    """
    if not val1 or not val2:
        return 0.0, "UNKNOWN"

    s1 = str(val1).strip().lower()
    s2 = str(val2).strip().lower()

    if s1 == s2:
        return 1.0, "SUPPORTING"

    # Substring / partial match (e.g. "White" vs "Pearl White", "City" vs "Honda City")
    if s1 in s2 or s2 in s1:
        return 0.85, "SUPPORTING"

    if HAS_RAPIDFUZZ and fuzz.token_set_ratio(s1, s2) >= 80:
        return 0.80, "SUPPORTING"

    return -0.50, "CONFLICTING"


def calculate_contextual_score(
    candidate_record: Dict[str, Any],
    query_context: Optional[Dict[str, Any]] = None
) -> Tuple[float, Dict[str, Any]]:
    """
    Calculates contextual match score based on make, model, colour, state, and registration date.
    Weights:
      make: 0.30
      model: 0.30
      colour: 0.15
      state: 0.15
      reg_date: 0.10
    Missing values are treated as UNKNOWN (neutral, no penalty).
    Contradictions reduce confidence.
    """
    breakdown: Dict[str, Any] = {
        "make_score": 0.0,
        "model_score": 0.0,
        "colour_score": 0.0,
        "state_score": 0.0,
        "date_score": 0.0,
        "supporting_attributes": [],
        "conflicting_attributes": [],
        "unknown_attributes": [],
    }

    if not query_context:
        return 0.0, breakdown

    weights = {
        "make": 0.30,
        "model": 0.30,
        "colour": 0.15,
        "state": 0.15,
        "reg_date": 0.10,
    }

    weighted_sum = 0.0
    evaluated_weights = 0.0

    for attr, weight in [("make", 0.30), ("model", 0.30), ("colour", 0.15), ("state", 0.15)]:
        q_val = query_context.get(attr)
        c_val = candidate_record.get(attr)
        score, status = _match_string_attribute(q_val, c_val)
        breakdown[f"{attr}_score"] = score
        label = attr.capitalize()
        if status == "SUPPORTING":
            breakdown["supporting_attributes"].append(f"{label} ({c_val})")
        elif status == "CONFLICTING":
            breakdown["conflicting_attributes"].append(f"{label} ({c_val} vs {q_val})")
        else:
            breakdown["unknown_attributes"].append(label)
        if q_val is not None and c_val is not None:
            weighted_sum += score * weight
            evaluated_weights += weight

    q_date, c_date = query_context.get("registration_date"), candidate_record.get("registration_date")
    d_score = 0.0
    if q_date and c_date:
        d_score = 1.0 if str(q_date)[:4] == str(c_date)[:4] else -0.30
        if d_score > 0:
            breakdown["supporting_attributes"].append(f"Year ({str(c_date)[:4]})")
        else:
            breakdown["conflicting_attributes"].append(f"Reg Year ({c_date} vs {q_date})")
        weighted_sum += d_score * weights["reg_date"]
        evaluated_weights += weights["reg_date"]
    else:
        breakdown["unknown_attributes"].append("Reg Date")
    breakdown["date_score"] = d_score

    breakdown["evaluated_weight"] = round(evaluated_weights, 4)
    total_context_score = (weighted_sum / evaluated_weights) if evaluated_weights > 0 else 0.0
    return max(-1.0, min(1.0, round(total_context_score, 4))), breakdown


def rank_candidate_record(
    query_plate: str,
    record: Dict[str, Any],
    source_database: str,
    record_id: int,
    query_context: Optional[Dict[str, Any]] = None,
    plate_weight: float = 0.70,
    context_weight: float = 0.30,
) -> Dict[str, Any]:
    """
    Computes all similarity metrics and the combined score for a single candidate record.
    """
    # Extract target plate string from whatever key the source database uses
    target_plate = (
        record.get("registration_number")
        or record.get("recorded_vehicle_number")
        or record.get("plate_identifier")
        or record.get("reported_plate")
        or ""
    )

    norm_query = normalize_plate(query_plate)
    norm_target = normalize_plate(target_plate)

    exact = exact_match(norm_query, norm_target)
    rf_sim = rapidfuzz_similarity(norm_query, norm_target)
    dl_dist = damerau_levenshtein_distance(norm_query, norm_target)
    dl_sim = damerau_levenshtein_similarity(norm_query, norm_target)

    # Plate score is the best combination of edit distance and token ratio
    plate_score = max(rf_sim, dl_sim)
    if exact == 1.0:
        plate_score = 1.0

    context_score, breakdown = calculate_contextual_score(record, query_context)

    # Combine plate and contextual scores
    # Context only re-weights the score when at least one attribute could actually be
    # compared. (Phase 3 fix: insurance/theft records carry no make/model/colour/state, so
    # an exact plate match there was previously capped at 0.70 whenever context was given.)
    if query_context and any(query_context.values()) and breakdown.get("evaluated_weight", 0) > 0:
        # When comparable context is present, combine
        combined_score = (plate_score * plate_weight) + (max(0.0, context_score) * context_weight)
        # Apply penalty if there are direct contradictions
        if context_score < 0:
            combined_score = max(0.0, combined_score + (context_score * 0.20))
    else:
        combined_score = plate_score

    combined_score = round(max(0.0, min(1.0, combined_score)), 4)

    # Determine confidence tier
    if combined_score >= 0.85:
        confidence = "HIGH"
    elif combined_score >= 0.65:
        confidence = "MEDIUM"
    else:
        confidence = "LOW"

    # Identify primary matching method
    if exact == 1.0:
        method = "Exact Match"
    elif dl_sim > rf_sim:
        method = "Damerau-Levenshtein (Transposition aware)"
    elif rf_sim > dl_sim:
        method = "RapidFuzz Similarity"
    else:
        method = "Hybrid Levenshtein/RapidFuzz"

    return {
        "recorded_registration_number": target_plate,
        "source_database": source_database,
        "record_id": record_id,
        "exact_match": exact,
        "plate_similarity": round(rf_sim, 4),
        "edit_distance": dl_dist,
        "dl_similarity": round(dl_sim, 4),
        "plate_score": round(plate_score, 4),
        "contextual_score": round(context_score, 4),
        "combined_score": combined_score,
        "confidence": confidence,
        "matching_method": method,
        "supporting_attributes": breakdown.get("supporting_attributes", []),
        "conflicting_attributes": breakdown.get("conflicting_attributes", []),
        "unknown_attributes": breakdown.get("unknown_attributes", []),
        "raw_record": record,
    }


def search_and_rank_candidates(
    query_plate: str,
    all_source_records: List[Tuple[str, List[Dict[str, Any]]]],
    query_context: Optional[Dict[str, Any]] = None,
    threshold: float = 0.50,
) -> List[Dict[str, Any]]:
    """
    Searches all database records and returns candidates ranked by combined score.
    all_source_records is a list of (source_name, records_list).
    """
    candidates: List[Dict[str, Any]] = []

    for source_name, records in all_source_records:
        for rec in records:
            rec_id = rec.get("id", 0)
            res = rank_candidate_record(
                query_plate=query_plate,
                record=rec,
                source_database=source_name,
                record_id=rec_id,
                query_context=query_context,
            )
            if res["combined_score"] >= threshold or res["exact_match"] == 1.0:
                candidates.append(res)

    # Sort descending by combined_score, then dl_similarity
    candidates.sort(key=lambda c: (c["combined_score"], c["dl_similarity"]), reverse=True)
    return candidates


# Labeled evaluation test suite for algorithm benchmarking
LABELED_TEST_CASES = [
    ("DL01AB1234", {"make": "Honda", "model": "City"}, "DL01AB1234", True),
    ("DLO1AB1234", {"make": "Honda", "model": "City"}, "DL01AB1234", True),
    ("DL0IAB1234", {"make": "Honda", "model": "City"}, "DL01AB1234", True),
    ("TN09AZ4321", {"make": "Hyundai", "model": "Creta"}, "TN09AZ4321", True),
    ("TN09ZA4321", {"make": "Hyundai", "model": "Creta"}, "TN09AZ4321", True),
    ("MH12DE1432", {"make": "Tata", "model": "Nexon"}, "MH12DE1432", True),
    ("MH12DF1432", {"make": "Tata", "model": "Nexon"}, "MH12DE1432", True),
    ("KA05MJ5555", {"make": "Maruti", "model": "Swift"}, "KA05MJ5555", True),
    ("KA05MJSSSS", {"make": "Maruti", "model": "Swift"}, "KA05MJ5555", True),
    ("UP16BT9900", {"make": "Toyota", "model": "Innova"}, "UP16BT9900", True),
    ("UP 16-BT-9900", {"make": "Toyota", "model": "Innova"}, "UP16BT9900", True),
    ("HR26DK839", {"make": "Kia", "model": "Seltos"}, "HR26DK8392", True),
    ("GJ01XY9999", {}, "DL01AB1234", False),
    ("WB02K0001", {"make": "BMW"}, "MH12DE1432", False),
    ("RJ14CD5555", {}, "TN09AZ4321", False),
]


def evaluate_algorithms(labeled_data: Optional[List[Tuple]] = None) -> Dict[str, Dict[str, float]]:
    """
    Evaluates Exact Match, RapidFuzz, Damerau-Levenshtein, and Combined contextual matching.
    Calculates actual Precision, Recall, F1-Score, Top-1 Accuracy, and Top-3 Accuracy.
    """
    cases = labeled_data or LABELED_TEST_CASES
    # Pool of candidate plates
    candidate_pool = list({c[2] for c in cases})

    algorithms = ["Exact Matching", "RapidFuzz", "Damerau-Levenshtein", "Combined Contextual"]
    results: Dict[str, Dict[str, float]] = {alg: {"tp": 0, "fp": 0, "fn": 0, "tn": 0, "top1": 0, "top3": 0, "total": 0} for alg in algorithms}

    for query, ctx, true_plate, is_match in cases:
        # Score against all candidates in candidate pool
        scored = []
        for cand in candidate_pool:
            rec = {"registration_number": cand, **(ctx or {})}
            exact = exact_match(query, cand)
            rf = rapidfuzz_similarity(query, cand)
            dl = damerau_levenshtein_similarity(query, cand)
            c_score, _ = calculate_contextual_score(rec, ctx)
            comb = (max(rf, dl) * 0.70) + (max(0.0, c_score) * 0.30)
            scored.append({
                "plate": cand,
                "exact": exact,
                "rf": rf,
                "dl": dl,
                "comb": comb,
            })

        for alg, key in [
            ("Exact Matching", "exact"),
            ("RapidFuzz", "rf"),
            ("Damerau-Levenshtein", "dl"),
            ("Combined Contextual", "comb"),
        ]:
            results[alg]["total"] += 1
            # Sort descending by metric
            ranked = sorted(scored, key=lambda x: x[key], reverse=True)
            top1_item = ranked[0]
            top3_plates = [r["plate"] for r in ranked[:3]]

            # Decision threshold for binary classification
            thresh = 1.0 if key == "exact" else 0.70
            predicted_positive = top1_item[key] >= thresh and (top1_item["plate"] == true_plate)

            if is_match:
                if top1_item["plate"] == true_plate and top1_item[key] >= thresh:
                    results[alg]["tp"] += 1
                else:
                    results[alg]["fn"] += 1

                if top1_item["plate"] == true_plate:
                    results[alg]["top1"] += 1
                if true_plate in top3_plates:
                    results[alg]["top3"] += 1
            else:
                if top1_item[key] >= thresh and top1_item["plate"] != true_plate:
                    results[alg]["fp"] += 1
                else:
                    results[alg]["tn"] += 1

    # Compute final metrics
    metrics: Dict[str, Dict[str, float]] = {}
    total_positives = sum(1 for c in cases if c[3])

    for alg in algorithms:
        tp = results[alg]["tp"]
        fp = results[alg]["fp"]
        fn = results[alg]["fn"]
        precision = tp / (tp + fp) if (tp + fp) > 0 else 0.0
        recall = tp / (tp + fn) if (tp + fn) > 0 else 0.0
        f1 = (2 * precision * recall) / (precision + recall) if (precision + recall) > 0 else 0.0
        top1_acc = results[alg]["top1"] / total_positives if total_positives > 0 else 0.0
        top3_acc = results[alg]["top3"] / total_positives if total_positives > 0 else 0.0

        metrics[alg] = {
            "Precision": round(precision, 4),
            "Recall": round(recall, 4),
            "F1-Score": round(f1, 4),
            "Top-1 Accuracy": round(top1_acc, 4),
            "Top-3 Accuracy": round(top3_acc, 4),
        }

    return metrics

