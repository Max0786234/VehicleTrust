import pytest
from matching import (
    normalize_plate,
    damerau_levenshtein_distance,
    damerau_levenshtein_similarity,
    rapidfuzz_similarity,
    exact_match,
    generate_ocr_confusion_variants,
    calculate_contextual_score,
    rank_candidate_record,
    evaluate_algorithms,
)


def test_plate_normalization():
    assert normalize_plate("dl 01 ab 1234") == "DL01AB1234"
    assert normalize_plate("MH-12-DE-1432") == "MH12DE1432"
    assert normalize_plate("  up.16_bt 9900  ") == "UP16BT9900"
    assert normalize_plate("") == ""
    assert normalize_plate(None) == ""


def test_damerau_levenshtein_transposition():
    # Adjacent transposition AZ -> ZA should have distance 1 in Damerau-Levenshtein
    # (whereas standard Levenshtein gives distance 2)
    s1 = "TN09AZ4321"
    s2 = "TN09ZA4321"
    assert damerau_levenshtein_distance(s1, s2) == 1
    sim = damerau_levenshtein_similarity(s1, s2)
    assert sim == 0.9  # 1.0 - 1/10


def test_damerau_levenshtein_single_edits():
    assert damerau_levenshtein_distance("DL01AB1234", "DL01AB1234") == 0
    assert damerau_levenshtein_distance("DL01AB1234", "DL01AB123") == 1  # Deletion
    assert damerau_levenshtein_distance("DL01AB1234", "DL01AB12345") == 1  # Insertion
    assert damerau_levenshtein_distance("DL01AB1234", "DL01AB1239") == 1  # Substitution


def test_rapidfuzz_similarity():
    sim_exact = rapidfuzz_similarity("DL01AB1234", "DL01AB1234")
    assert sim_exact == 1.0
    sim_close = rapidfuzz_similarity("DL01AB1234", "DL01AB1239")
    assert 0.85 <= sim_close < 1.0
    sim_diff = rapidfuzz_similarity("DL01AB1234", "KA05MJ5555")
    assert sim_diff < 0.40


def test_exact_match():
    assert exact_match("DL01AB1234", "dl-01-ab-1234") == 1.0
    assert exact_match("DL01AB1234", "DL01AB1235") == 0.0


def test_ocr_confusion_variants():
    # O in digit slot (RTO 01) should generate 0
    variants = generate_ocr_confusion_variants("DLO1AB1234")
    assert "DL01AB1234" in variants

    # I in digit slot should generate 1
    variants_i = generate_ocr_confusion_variants("DL0IAB1234")
    assert "DL01AB1234" in variants_i

    # S in number slot should generate 5
    variants_s = generate_ocr_confusion_variants("KA05MJSSSS")
    assert any("5" in v for v in variants_s)


def test_contextual_scoring_supporting():
    rec = {
        "make": "Honda",
        "model": "City",
        "colour": "White",
        "state": "Delhi",
        "registration_date": "2020-05-15",
    }
    ctx = {
        "make": "Honda",
        "model": "City",
        "colour": "Pearl White",  # substring match
        "state": "Delhi",
        "registration_date": "2020-01-01",  # same year
    }
    score, breakdown = calculate_contextual_score(rec, ctx)
    assert score > 0.80
    assert "Make (Honda)" in breakdown["supporting_attributes"]
    assert "Model (City)" in breakdown["supporting_attributes"]


def test_contextual_scoring_conflicting():
    rec = {
        "make": "Honda",
        "model": "City",
        "colour": "White",
        "state": "Delhi",
    }
    ctx = {
        "make": "Hyundai",
        "model": "Creta",
        "colour": "Black",
        "state": "Karnataka",
    }
    score, breakdown = calculate_contextual_score(rec, ctx)
    assert score < 0.0
    assert len(breakdown["conflicting_attributes"]) >= 3


def test_contextual_scoring_missing_unknown():
    rec = {
        "make": "Honda",
        "model": "City",
    }
    # Query has no colour, state, or reg date
    ctx = {
        "make": "Honda",
        "model": "City",
    }
    score, breakdown = calculate_contextual_score(rec, ctx)
    assert score > 0.0
    assert "Colour" in breakdown["unknown_attributes"]
    assert "State" in breakdown["unknown_attributes"]


def test_rank_candidate_record():
    rec = {
        "id": 1,
        "registration_number": "DL01AB1234",
        "make": "Honda",
        "model": "City",
        "colour": "White",
    }
    # Exact query
    res_exact = rank_candidate_record("DL01AB1234", rec, "vehicle_registry", 1)
    assert res_exact["combined_score"] == 1.0
    assert res_exact["confidence"] == "HIGH"

    # Noisy OCR query
    res_noisy = rank_candidate_record("DLO1AB1234", rec, "vehicle_registry", 1, query_context={"make": "Honda"})
    assert res_noisy["combined_score"] >= 0.85
    assert res_noisy["confidence"] == "HIGH"


def test_algorithm_evaluation_benchmark():
    metrics = evaluate_algorithms()
    assert "Exact Matching" in metrics
    assert "RapidFuzz" in metrics
    assert "Damerau-Levenshtein" in metrics
    assert "Combined Contextual" in metrics

    # RapidFuzz and Damerau-Levenshtein and Combined should achieve higher recall than exact matching
    assert metrics["Combined Contextual"]["Recall"] > metrics["Exact Matching"]["Recall"]
    assert metrics["Damerau-Levenshtein"]["Recall"] > metrics["Exact Matching"]["Recall"]
    assert metrics["Combined Contextual"]["Top-1 Accuracy"] >= 0.90

