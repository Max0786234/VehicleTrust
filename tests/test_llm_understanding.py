"""LLM query understanding (Ollama) with the rule-based fallback. Ollama is mocked: tests are deterministic."""
import asyncio
import json

import httpx
import pytest

from llm_understanding import understand_with_llm


def ollama(reply=None, status=200, raise_exc=None, raw=None):
    """Mock Ollama /api/chat returning `reply` (dict) as the model's JSON content."""
    seen = {}

    def handler(request: httpx.Request):
        seen["payload"] = json.loads(request.content)
        if raise_exc:
            raise raise_exc
        content = raw if raw is not None else json.dumps(reply)
        return httpx.Response(status, json={"message": {"role": "assistant", "content": content}})
    return httpx.MockTransport(handler), seen


def run(text, transport, plate=None, use_llm=True):
    return asyncio.run(understand_with_llm(text, plate=plate, use_llm=use_llm, transport=transport))


def reply(plate="", intents=("INSURANCE",), make="", model="", colour="", state=""):
    return {"registration_number": plate, "intents": list(intents),
            "attributes": {"make": make, "model": model, "colour": colour, "state": state}, "reasoning": "test"}


def test_llm_intents_are_used_for_human_phrasing():
    q = "Was GJ 01 AB 7777 ever taken off the road for good or reported missing?"
    t, seen = ollama(reply("GJ 01 AB 7777", ["SCRAPPING", "THEFT"]))
    u = run(q, t)
    assert u["understanding_method"].startswith("llm")
    assert u["intents"] == ["SCRAPPING", "THEFT"] and u["registration_number"] == "GJ01AB7777"
    assert u["llm"]["rules_intents"] == ["THEFT"]            # rules missed 'taken off the road for good'
    assert "enum" in json.dumps(seen["payload"]["format"])   # structured output schema is sent
    assert seen["payload"]["options"]["temperature"] == 0


def test_invented_plate_and_attributes_are_rejected():
    q = "is my white car insured?"
    t, _ = ollama(reply("DL01AB1234", ["INSURANCE"], make="Honda", colour="white"))
    u = run(q, t)
    assert u["registration_number"] == ""                   # plate not in the question -> rejected
    assert u["attributes"] == {"colour": "White"}           # 'Honda' not in the question -> rejected
    assert any("DL01AB1234" in r for r in u["llm"]["rejected"])


def test_unknown_intents_dropped_and_empty_falls_back_to_rules():
    t, _ = ollama(reply("KA05MJ5555", ["SOMETHING_ELSE"]))
    u = run("is KA05MJ5555 stolen?", t)
    assert u["understanding_method"] == "rules (LLM output invalid)" and u["intents"] == ["THEFT"]


@pytest.mark.parametrize("transport_kw,expected", [
    ({"raise_exc": httpx.ConnectError("refused")}, "rules (LLM unavailable)"),
    ({"raise_exc": httpx.ReadTimeout("slow")}, "rules (LLM unavailable)"),
    ({"raw": "not json at all"}, "rules (LLM unavailable)"),
    ({"status": 500, "reply": {}}, "rules (LLM unavailable)"),
])
def test_errors_fall_back_to_rules(transport_kw, expected):
    t, _ = ollama(**transport_kw)
    u = run("Check the complete history of DL01AB1234", t)
    assert u["understanding_method"] == expected
    assert u["intents"] == ["FULL_HISTORY"] and u["registration_number"] == "DL01AB1234"
    assert u["llm"]["fallback_reason"]


def test_disabled_uses_rules_without_calling_ollama():
    t, seen = ollama(reply())
    u = run("is DL01AB1234 insured?", t, use_llm=False)
    assert u["understanding_method"] == "rules" and "payload" not in seen


def test_model_name_in_make_field_is_corrected_and_similarity_needs_a_cue():
    q = "My dad wants the grey Innova UP16BT9900, is the seller the owner and is it covered?"
    t, _ = ollama(reply("UP16BT9900", ["OWNERSHIP", "INSURANCE", "SIMILARITY"], make="Innova", colour="grey"))
    u = run(q, t)
    assert u["attributes"] == {"model": "Innova", "colour": "Grey"}
    assert u["intents"] == ["OWNERSHIP", "INSURANCE"]       # no 'similar' cue in the question


def test_explicit_ocr_plate_wins():
    t, _ = ollama(reply("", ["THEFT"]))
    u = run("is this one stolen?", t, plate="DLO1AB1234")
    assert u["registration_number"] == "DLO1AB1234" and u["plate_syntax_corrected"] == "DL01AB1234"


def test_pipeline_runs_with_llm_understanding():
    from federation import run_federated_query
    from tests.federation_helpers import RouterTransport, TEST_URLS, service_apps
    t, _ = ollama(reply("GJ 01 AB 7777", ["SCRAPPING", "THEFT"]))
    r = asyncio.run(run_federated_query("Was GJ 01 AB 7777 ever taken off the road for good or reported missing?",
                                        urls=TEST_URLS, transport=RouterTransport(service_apps()),
                                        include_documents=False, use_llm=True, llm_transport=t))
    assert r["understanding"]["understanding_method"].startswith("llm")
    assert "theft_scrapping" in r["decomposition"]["selected_services"]
    assert "registration_authority" in r["decomposition"]["selected_services"]  # SCRAPPING needs RC + events
    assert "REPORTED STOLEN" in r["answer"]["headline"]
    assert r["stages"][0]["detail"].startswith("[llm")


def test_plate_fragments_and_junk_are_not_accepted_as_attributes():
    q = "my friend is selling his Toyota UP 16 BT 9900, is it insured? it's from uttar pradesh"
    t, _ = ollama(reply("UP 16 BT 9900", ["INSURANCE"], make="Toyota", model="UP", colour="selling", state="Uttar Pradesh"))
    u = run(q, t)
    assert u["attributes"] == {"make": "Toyota", "state": "Uttar Pradesh"}


def test_discrepancy_needs_a_doubt_cue():
    t, _ = ollama(reply("AS01BC4433", ["THEFT", "DISCREPANCY"]))
    assert run("was AS01BC4433 ever reported missing to the police?", t)["intents"] == ["THEFT"]
    t, _ = ollama(reply("KA05MJ5555", ["DISCREPANCY"]))
    kept = run("something feels off about KA05MJ5555, the colour doesn't match", t)["intents"]
    assert "DISCREPANCY" in kept  # ('colour' also adds VEHICLE_DETAILS through the explicit-keyword merge)
