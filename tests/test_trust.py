"""Vehicle Trust Score: explainable 0-100 summary of the integrated result."""
import asyncio
import datetime

import pytest

from federation import run_federated_query
from tests.federation_helpers import RouterTransport, TEST_URLS, service_apps

TODAY = datetime.date(2026, 11, 19)


@pytest.fixture(scope="module")
def apps():
    return service_apps()


def trust(query, apps, **kw):
    r = asyncio.run(run_federated_query(query, urls=TEST_URLS, transport=RouterTransport(apps, **kw),
                                        include_documents=False, today=TODAY))
    return r["trust"]


def test_clean_vehicle_scores_full_trust(apps):
    t = trust("Check the complete history of DL01AB1234", apps)
    assert t["score"] == 100 and t["band"] == "HIGH_TRUST" and t["deductions"] == [] and not t["partial"]


def test_stolen_vehicle_is_high_risk_with_explained_deductions(apps):
    t = trust("Check the complete history of GJ01AB7777", apps)
    assert t["band"] == "HIGH_RISK" and t["score"] < 50
    reasons = " | ".join(d["reason"] for d in t["deductions"])
    assert "theft status is STOLEN" in reasons and "policy_after_theft" in reasons
    assert 100 - sum(d["points"] for d in t["deductions"]) == t["score"]
    assert all(d["source"] for d in t["deductions"])


def test_scrapped_vehicle_is_high_risk(apps):
    t = trust("Check the complete history of WB02K0001", apps)
    assert t["band"] == "HIGH_RISK"
    assert any("SCRAPPED" in d["reason"] for d in t["deductions"])


def test_checks_not_queried_are_reported_not_assumed_clean(apps):
    t = trust("Is DL01AB1234 stolen?", apps)
    assert t["checks"]["insurance"] == "not checked" and t["partial"]
    assert "Not checked: insurance" in t["note"]


def test_unavailable_source_can_never_give_high_trust(apps):
    t = trust("Check the complete history of DL01AB1234", apps, down={"insurance_records"})
    assert t["checks"]["insurance"] == "unavailable"
    assert t["band"] == "REVIEW"


def test_no_match_has_no_score(apps):
    t = trust("Check the complete history of ZZ99ZZ9999", apps)
    assert t["score"] is None and t["band"] == "NO_MATCH"
