"""Evaluates query understanding on labelled questions: LLM (Ollama) vs rule-based parser.

Usage (Ollama running, model pulled):
    python evaluation/eval_understanding.py                 # uses OLLAMA_MODEL from .env (default llama3.2)
    python evaluation/eval_understanding.py --model qwen3:4b
    python evaluation/eval_understanding.py --rules-only

A case is CORRECT when every 'must' intent is found and every predicted intent is in must + ok.
'Right databases' means the decomposition selects every database the 'must' intents need.
Results are written to evaluation/results_<method>.json.
"""
import argparse
import asyncio
import json
import os
import statistics
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))

import config  # noqa: E402,F401  (loads .env)
from llm_understanding import understand_with_llm  # noqa: E402
from matching import normalize_plate  # noqa: E402
from query_engine import INTENT_PLAN, decompose_query, understand_query  # noqa: E402


def needed_services(must):
    services = set()
    for intent in (must or ["GENERAL_STATUS"]):
        services |= set(INTENT_PLAN.get(intent, {}))
    return services


def score(case, u):
    pred = set(u["intents"])
    must, ok = set(case["must"]), set(case["ok"])
    allowed = must | ok | ({"GENERAL_STATUS"} if not must else set())
    selected = set(decompose_query(u)["selected_services"])
    need = needed_services(case["must"])
    return {
        "plate_ok": normalize_plate(u["registration_number"]) == normalize_plate(case["plate"]),
        "intents_ok": must <= pred and pred <= allowed,
        "must_recall": (len(must & pred) / len(must)) if must else 1.0,
        "extra": sorted(pred - allowed),
        "missed": sorted(must - pred),
        "dbs_ok": need <= selected,
        "extra_dbs": sorted(selected - need),
    }


async def evaluate(method, model):
    if model:
        os.environ["OLLAMA_MODEL"] = model
    cases = json.load(open(os.path.join(HERE, "understanding_cases.json"), encoding="utf-8"))
    if method == "llm":
        from llm_understanding import warm_up_model
        warm_up_model()  # load the model first (the gateway does the same at startup) so timings reflect real use
    rows = []
    for i, case in enumerate(cases, 1):
        t0 = time.perf_counter()
        if method == "rules":
            u = understand_query(case["q"])
            u["understanding_method"] = "rules"
        else:
            u = await understand_with_llm(case["q"], use_llm=True)
        ms = round((time.perf_counter() - t0) * 1000)
        s = score(case, u)
        rows.append({"q": case["q"], "expected_plate": case["plate"], "predicted_plate": u["registration_number"],
                     "must": case["must"], "predicted": u["intents"], "method": u["understanding_method"],
                     "ms": ms, **s})
        flag = "OK " if s["intents_ok"] and s["plate_ok"] else "ERR"
        print(f"[{i:2}/{len(cases)}] {flag} {ms:>6} ms  {u['understanding_method']:<26} {u['intents']}"
              + (f"  missed={s['missed']}" if s["missed"] else "") + (f"  extra={s['extra']}" if s["extra"] else "")
              + ("" if s["plate_ok"] else f"  plate={u['registration_number']!r} (expected {case['plate']!r})"))
    n = len(rows)
    summary = {
        "method": method, "model": os.getenv("OLLAMA_MODEL", "llama3.2") if method == "llm" else None, "cases": n,
        "plate_accuracy": sum(r["plate_ok"] for r in rows) / n,
        "intent_accuracy": sum(r["intents_ok"] for r in rows) / n,
        "must_intent_recall": statistics.mean(r["must_recall"] for r in rows),
        "right_databases": sum(r["dbs_ok"] for r in rows) / n,
        "avg_extra_databases": statistics.mean(len(r["extra_dbs"]) for r in rows),
        "fell_back_to_rules": sum(r["method"].startswith("rules") for r in rows) if method == "llm" else 0,
        "median_ms": statistics.median(r["ms"] for r in rows),
    }
    out = os.path.join(HERE, f"results_{method}.json")
    json.dump({"summary": summary, "rows": rows}, open(out, "w", encoding="utf-8"), indent=1)
    return summary


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--model", default=None)
    ap.add_argument("--rules-only", action="store_true")
    args = ap.parse_args()
    results = [asyncio.run(evaluate("rules", None))]
    if not args.rules_only:
        print()
        results.append(asyncio.run(evaluate("llm", args.model)))
    print("\n" + "=" * 78)
    print(f"{'metric':<24}" + "".join(f"{r['method'] + (' (' + r['model'] + ')' if r['model'] else ''):>27}" for r in results))
    for key, fmt in [("plate_accuracy", "{:.0%}"), ("intent_accuracy", "{:.0%}"), ("must_intent_recall", "{:.0%}"),
                     ("right_databases", "{:.0%}"), ("avg_extra_databases", "{:.2f}"), ("fell_back_to_rules", "{}"),
                     ("median_ms", "{:.0f}")]:
        print(f"{key:<24}" + "".join(f"{fmt.format(r[key]):>27}" for r in results))


if __name__ == "__main__":
    main()
