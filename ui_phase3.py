"""Phase 3 Streamlit pages (imported by app.py): federated query pipeline, schema explorer,
document repository. All data comes from the gateway REST API (GATEWAY_URL, default :8000)."""
import os
import time
from typing import Any, Dict, List

import httpx
import pandas as pd
import streamlit as st

import config
import ui_theme as ui
from ui_theme import escape

EXAMPLES = [
    "Check the complete history of vehicle DL01AB1234.",
    "Is this vehicle insured, stolen or scrapped? GJ 01 AB 7777",
    "Find the ownership history and insurance details for UP16BT9900",
    "Find vehicles with registration numbers similar to DLO1AB1234 and identify discrepancies",
    "Is WB02K0001 scrapped?",
    "Show the full history and audit trail of KA05MJ5555",
    "Is AS01BC4433 insured or stolen?",
]
PIPELINE = ["User Query", "Query Understanding", "Query Decomposition", "Federated Execution", "Local Context Discovery",
            "Context Accumulation", "Unstructured Retrieval", "Structured + Unstructured Integration", "Final Answer"]
KIND_STYLE = {
    "database_fact": ("blue", "Database fact"), "assessment": ("violet", "Assessment"),
    "document_evidence": ("green", "Document evidence"), "conflict": ("amber", "Conflict"),
    "missing": ("gray", "Missing"), "resolution": ("blue", "Entity resolution"),
}
STATUS_BADGE = {"ok": "ok", "timeout": "timeout", "unavailable": "unavailable", "error": "error",
                "not_called": "not called"}
WAVE_COLORS = ["#2a78d6", "#eb6834"]  # categorical slots 1-2 (validated adjacent pair)


def gateway() -> str:
    return st.session_state.get("gateway_url", config.gateway_url())


def _post(path: str, payload: Dict[str, Any], timeout: float = 60.0):
    resp = httpx.post(f"{gateway()}{path}", json=payload, timeout=timeout)
    resp.raise_for_status()
    return resp.json()


def _get(path: str, params=None, timeout: float = 15.0):
    resp = httpx.get(f"{gateway()}{path}", params=params, timeout=timeout)
    resp.raise_for_status()
    return resp.json()


def _fk_graph(paths: List[Dict[str, Any]]) -> str:
    lines = ['digraph G { rankdir=LR; bgcolor="transparent"; node [shape=box, style="rounded,filled", fillcolor="#ffffff", '
             'color="#9fb0c6", fontname="Helvetica", fontsize=10]; edge [fontsize=8, color="#8a99ad", fontname="Helvetica"];']
    seen = set()
    for p in paths:
        a, b = p["from"], p["to"]
        if p["direction"] == "reverse":
            a, b = b, a  # draw child -> parent, labelled with the FK column
        key = (a, b, p["fk_column"])
        if key in seen:
            continue
        seen.add(key)
        lines.append(f'"{a}" -> "{b}" [label="{p["fk_column"]}"];')
    lines.append("}")
    return "\n".join(lines)


def _pipeline_strip(result: Dict[str, Any]) -> None:
    stages = {s["stage"]: s for s in result.get("stages", [])}
    def find(prefix):
        return next((v for k, v in stages.items() if k.startswith(prefix)), None)
    mapping = {
        "User Query": {"ms": 0, "detail": result["understanding"]["original_query"][:60] or "(image / explicit plate)"},
        "Query Understanding": find("Query Understanding"),
        "Query Decomposition": find("Query Decomposition"),
        "Federated Execution": find("Federated Execution (wave 1"),
        "Local Context Discovery": find("Local Context Discovery"),
        "Context Accumulation": find("Context Accumulation"),
        "Unstructured Retrieval": find("Unstructured Retrieval"),
        "Structured + Unstructured Integration": find("Cross-Database Integration"),
        "Final Answer": find("Structured + Unstructured Integration"),
    }
    html = []
    for i, name in enumerate(PIPELINE):
        stage = mapping.get(name)
        done = stage is not None
        detail = escape(str((stage or {}).get("detail", "")).replace(",", ", ").replace(";", "; ")[:120])
        ms = f"{stage['ms']} ms" if done else "not reached"
        html.append(f"<div class='vt-step{'' if done else ' pending'}'><div class='vt-step-num'>{i + 1:02d}</div>"
                    f"<div class='vt-step-name'>{name}</div><div class='vt-step-ms'>{ms}</div>"
                    f"<div class='vt-step-detail'>{detail}</div></div>")
    st.markdown(f"<div class='vt-steps' style='--vt-cols:{len(PIPELINE)}'>" + "".join(html) + "</div>", unsafe_allow_html=True)


def _timeline_chart(calls: List[Dict[str, Any]]) -> None:
    import altair as alt
    rows = []
    for c in calls:
        rows.append({"service": c["label"], "wave": f"Wave {c['wave']}", "start": c["started_ms"],
                     "end": max(c["ended_ms"], c["started_ms"] + 1), "latency_ms": c["latency_ms"],
                     "status": c["status"], "purpose": c["purpose"]})
    if not rows:
        return
    df = pd.DataFrame(rows)
    chart = alt.Chart(df).mark_bar(cornerRadius=4, height=14).encode(
        x=alt.X("start:Q", title="ms since wave start"), x2="end:Q",
        y=alt.Y("service:N", title=None, sort=None),
        color=alt.Color("wave:N", scale=alt.Scale(domain=["Wave 1", "Wave 2"], range=WAVE_COLORS),
                        legend=alt.Legend(title=None, orient="top")),
        tooltip=["service", "wave", "status", "latency_ms", "purpose"],
    ).properties(height=36 * len(rows) + 30)
    st.altair_chart(chart, width="stretch")
    st.caption("Each wave starts at 0 ms. Overlapping wave-1 bars show the subqueries ran concurrently (asyncio.gather).")


def _llm_disabled() -> bool:
    return os.getenv("LLM_UNDERSTANDING", "auto").strip().lower() == "off"


def render_federated_query() -> None:
    ui.page_header(
        "Federated query",
        "Ask about a vehicle in plain English. The gateway understands the question, sends subqueries only to the "
        "relevant databases, runs them in parallel, accumulates foreign-key context, retrieves correlated documents and "
        "integrates everything into one sourced answer.", eyebrow="Federated querying")

    llm_off = _llm_disabled()
    autorun = st.session_state.pop("p3_autorun", False)
    if autorun:
        st.session_state.p3_question = st.session_state.get("p3_query", EXAMPLES[0])
        st.session_state.p3_example_pill = None
    if "p3_question" not in st.session_state:
        st.session_state.p3_question = st.session_state.get("p3_query", EXAMPLES[0])

    def _use_example():
        if st.session_state.get("p3_example_pill"):
            st.session_state.p3_question = st.session_state.p3_example_pill

    with st.container(border=True):
        st.pills("Examples", EXAMPLES, selection_mode="single", key="p3_example_pill", on_change=_use_example)
        query = st.text_area("Question", key="p3_question", height=78,
                             placeholder="e.g. Is GJ01AB7777 insured, stolen or scrapped?")

        with st.expander("Plate image, explicit plate and observed vehicle details", expanded=False):
            e1, e2 = st.columns(2)
            with e1:
                if config.DEMO_MODE:
                    ui.demo_notice("Image OCR", "EasyOCR needs PyTorch (about 2 GB), which does not fit the free hosting "
                                                "tier; it runs in the local installation. Type the plate on the right "
                                                "instead - it goes through the same normalisation and matching.")
                    image = None
                else:
                    image = st.file_uploader("Plate image (OCR through the gateway)", type=["jpg", "jpeg", "png"],
                                             key="p3_img")
                if image is not None and st.button("Read plate from image"):
                    try:
                        resp = httpx.post(f"{gateway()}/api/ocr", files={"file": (image.name, image.getvalue(), image.type)},
                                          timeout=120)
                        resp.raise_for_status()
                        ocr = resp.json()
                        st.session_state.p3_ocr = ocr
                        if ocr.get("normalized_plate"):
                            st.session_state.p3_plate = ocr["normalized_plate"]
                    except Exception as exc:
                        st.error(f"OCR failed: {exc}")
                ocr = st.session_state.get("p3_ocr")
                if ocr:
                    st.write(f"OCR text `{ocr.get('raw_text')}` → plate **{ocr.get('normalized_plate') or '-'}** "
                             f"(confidence {ocr.get('confidence')})")
                    if ocr.get("ocr_variants"):
                        st.caption("OCR confusion variants: " + ", ".join(ocr["ocr_variants"][:8]))
                    if ocr.get("message"):
                        st.warning(ocr["message"])
            with e2:
                plate = st.text_input("Explicit plate (overrides the plate in the question)",
                                      value=st.session_state.get("p3_plate", ""))
                ctx_cols = st.columns(2)
                make = ctx_cols[0].text_input("Observed make", key="p3_make")
                model = ctx_cols[1].text_input("Observed model", key="p3_model")
                colour = ctx_cols[0].text_input("Observed colour", key="p3_colour")
                state = ctx_cols[1].text_input("Observed state", key="p3_state")

        o1, o2, o3, o4 = st.columns([1.1, 0.9, 1.3, 1.5], vertical_alignment="center")
        include_docs = o1.toggle("Retrieve documents", value=True)
        top_k = o2.number_input("Top-k documents", 1, 15, 6, help="Number of documents to retrieve")
        if llm_off:
            use_llm = o3.toggle("LLM understanding", value=False, disabled=True,
                                help="The local Ollama model is not enabled here; the rule-based parser reads the "
                                     "question and the rest of the pipeline is identical.")
        else:
            use_llm = o3.toggle("LLM understanding", value=st.session_state.get("p3_use_llm", True),
                                help="A local Ollama model reads the question; the rule-based parser is used if it is "
                                     "unavailable or returns invalid output.")
            st.session_state.p3_use_llm = use_llm
        run = o4.button("Run federated query", type="primary", width="stretch", icon=":material/play_arrow:")

    if run or autorun:
        st.session_state.p3_query = query
        payload = {"query": query, "plate": plate or None,
                   "plate_source": "ocr" if plate and plate == (st.session_state.get("p3_ocr") or {}).get("normalized_plate") else None,
                   "make": make or None, "model": model or None, "colour": colour or None, "state": state or None,
                   "include_documents": include_docs, "top_k_documents": int(top_k), "use_llm": use_llm}
        with st.spinner("Understanding the question and federating subqueries..."):
            try:
                st.session_state.p3_result = _post("/api/federated-query", payload, timeout=120)
            except Exception as exc:
                st.error(f"Gateway request failed ({gateway()}): {exc}. Is the gateway running?")
                return

    result = st.session_state.get("p3_result")
    if not result:
        ui.note("Pick an example or type a question, then press <b>Run federated query</b>.")
        return
    oq = result["understanding"]["original_query"] or "(explicit plate)"
    ui.section("Execution pipeline", f"Total {result['total_ms']} ms · “{oq[:140]}”")
    _pipeline_strip(result)
    if result.get("error"):
        st.error(result["error"])
        return

    avail = result["context"]["service_availability"]
    down = [v["label"] for v in avail.values() if v["status"] not in ("ok",)]
    if down:
        ui.note("<b>Partial result.</b> Unavailable: " + escape(", ".join(down)) +
                ". Their checks are reported as missing, never as clear.", tone="amber")

    answer = result["answer"]
    trust = result.get("trust") or {}
    t_col, a_col = st.columns([1, 2.7])
    with t_col:
        render_trust_card(trust, compact=True)
    with a_col:
        rows = []
        for s in answer["statements"]:
            tone, label = KIND_STYLE.get(s["kind"], ("gray", s["kind"]))
            src = f"<div class='vt-stmt-src'>Sources: {escape(', '.join(s['sources']))}</div>" if s["sources"] else ""
            rows.append(f"<div class='vt-stmt'><div>{ui.pill(label, tone)}</div>"
                        f"<div><div class='vt-stmt-text'>{escape(s['text'])}</div>{src}</div></div>")
        st.markdown(f"<div class='vt-eyebrow' style='margin-top:2px'>Answer</div>"
                    f"<div style='font-size:1.12rem;font-weight:650;margin:0 0 8px 0;color:#0f172a'>"
                    f"{escape(answer['headline'])}</div><div class='vt-answer'>{''.join(rows)}</div>",
                    unsafe_allow_html=True)
        st.caption("Decision support only, not an official verification.")
    if trust.get("score") is not None:
        with st.expander(f"How the Trust Score was computed ({len(trust.get('deductions', []))} deduction(s))"):
            _trust_deductions(trust)

    st.write("")
    tabs = st.tabs(["Understanding & decomposition", "Federated execution", "Database results & FK-PK",
                    "Accumulated context", "Documents", "Conflicts & cleansing", "Raw JSON"])
    u, d = result["understanding"], result["decomposition"]
    with tabs[0]:
        llm = u.get("llm") or {}
        method = u.get("understanding_method", "rules")
        if llm.get("used"):
            st.success(f"Understood by **{method}** in {llm.get('latency_ms')} ms — {llm.get('reasoning', '')}")
            st.caption(f"Rule-based parser would have chosen: {', '.join(llm.get('rules_intents') or [])}"
                       + (f" · Rejected (not in the question): {'; '.join(llm['rejected'])}" if llm.get("rejected") else ""))
        else:
            st.info(f"Understood by **{method}**" + (f" — {llm.get('fallback_reason')}" if llm.get("fallback_reason") else ""))
        st.markdown(f"<div style='margin:4px 0 12px 0'><span class='vt-label'>Plate</span>&nbsp; "
                    f"<code>{escape(str(u.get('registration_number') or '-'))}</code> &nbsp;&nbsp;"
                    f"<span class='vt-label'>Intents</span>&nbsp; "
                    + " ".join(ui.pill(x, "blue") for x in (u.get("intent_labels") or u.get("intents") or []))
                    + "</div>", unsafe_allow_html=True)
        a, b = st.columns(2)
        with a:
            st.markdown("**Query understanding**")
            st.json({k: u[k] for k in ("registration_number", "plate_source", "plate_text_span", "plate_syntax_valid",
                                       "plate_syntax_corrected", "intents", "intent_labels", "attributes",
                                       "required_information", "ocr_variants")}, expanded=1)
        with b:
            st.markdown("**Decomposition — subqueries**")
            st.dataframe(pd.DataFrame([{"database": config.SERVICES[s["service"]]["label"], "wave": s["wave"],
                                        "mode": s["payload"].get("mode"), "FK relations to traverse": ", ".join(s["payload"]["include"]),
                                        "reason": s["reason"]} for s in d["subqueries"]]), width="stretch", hide_index=True)
            if d["skipped"]:
                st.markdown("**Not queried**")
                st.dataframe(pd.DataFrame([{"database": config.SERVICES[s["service"]]["label"], "reason": s["reason"]}
                                           for s in d["skipped"]]), width="stretch", hide_index=True)
    with tabs[1]:
        calls = result["context"]["subqueries"]
        st.dataframe(pd.DataFrame([{"database": c["label"], "wave": c["wave"], "url": c["url"],
                                    "status": STATUS_BADGE.get(c["status"], c["status"]), "latency ms": c["latency_ms"],
                                    "start ms": c["started_ms"], "end ms": c["ended_ms"], "matches": c["match_count"],
                                    "tables touched": ", ".join(c["tables_touched"]), "purpose": c["purpose"],
                                    "error": c.get("error") or ""} for c in calls]), width="stretch", hide_index=True)
        for wave in (1, 2):
            wave_calls = [c for c in calls if c["wave"] == wave]
            if wave_calls:
                st.markdown(f"**Wave {wave} timeline**")
                _timeline_chart(wave_calls)
    with tabs[2]:
        results = result["context"]["database_results"]
        if not results:
            st.info("No database returned a record for the resolved vehicle.")
        for svc, matches in results.items():
            with st.expander(f"{config.SERVICES[svc]['label']} — {len(matches)} matched record(s)", expanded=True):
                st.dataframe(pd.DataFrame([{**m["record"], "score": m["match"].get("combined_score"),
                                            "method": m["match"].get("matching_method") or m["match"].get("matched_by")}
                                           for m in matches]), width="stretch", hide_index=True)
                paths = [p for m in matches for p in m["relationship_paths"]]
                g1, g2 = st.columns([1, 1])
                with g1:
                    st.markdown("**Related entities discovered through local FK-PK joins**")
                    for m in matches:
                        st.json(m["related"], expanded=False)
                with g2:
                    if paths:
                        st.markdown("**FK-PK traversal (child → parent, edge = FK column)**")
                        st.graphviz_chart(_fk_graph(paths))
    with tabs[3]:
        ctx = result["context"]
        ent = ctx["resolved_entity"]
        st.markdown(f"**Resolved entity:** `{ent.get('registration_number')}` · confidence **{ent.get('confidence')}** · {ent.get('method')}")
        if ent.get("candidates"):
            st.dataframe(pd.DataFrame([{"plate": c["plate"], "in entity": c["in_entity"],
                                        "sources": ", ".join(f"{k} ({v:.2f})" for k, v in c["sources"].items()),
                                        "DL similarity to query": c["dl_similarity_to_query"]} for c in ent["candidates"]]),
                         width="stretch", hide_index=True)
        st.markdown("**Accumulated attributes (with provenance)**")
        st.dataframe(pd.DataFrame([{"attribute": k, "value": str(v["value"]), "source": v["source"], "record": v["record"],
                                    "other sources disagree": "; ".join(f"{a['value']} ({a['source']})" for a in v["alternatives"])}
                                   for k, v in ctx["attributes"].items()]), width="stretch", hide_index=True)
        st.markdown("**Relationship paths**")
        st.dataframe(pd.DataFrame([{"database": p["source"], "relation": p["relation"], "path": p["label"]}
                                   for p in ctx["relationship_paths"]]), width="stretch", hide_index=True)
        if ctx["similar_vehicles"]:
            st.markdown("**Similar registration numbers (different vehicles)**")
            st.dataframe(pd.DataFrame([{"plate": s["plate"], "database": s["source"], "score": s["match"]["combined_score"],
                                        "DL": s["match"]["dl_similarity"], "make": s["record"].get("make"),
                                        "model": s["record"].get("model"), "colour": s["record"].get("colour")}
                                       for s in ctx["similar_vehicles"]]), width="stretch", hide_index=True)
        if ctx["filtered_out"]:
            st.markdown("**Filtered out as unrelated to the query**")
            st.dataframe(pd.DataFrame([{"plate": f["plate"], "database": f["source"], "reason": f["reason"]}
                                       for f in ctx["filtered_out"]]), width="stretch", hide_index=True)
        st.markdown("**Service availability**")
        st.dataframe(pd.DataFrame([{"database": v["label"], "status": STATUS_BADGE.get(v["status"], v["status"]),
                                    "url": v.get("url", ""), "latency ms": v.get("latency_ms"), "error": v.get("error") or ""}
                                   for v in avail.values()]), width="stretch", hide_index=True)
    with tabs[4]:
        docs = result["documents"]
        rc = docs.get("context_used", {})
        st.markdown("**Retrieval context derived from the structured results**")
        st.json({"plate": rc.get("plate"), "facts": rc.get("facts"), "identifiers": rc.get("identifiers"),
                 "names": rc.get("names"), "organisations": rc.get("organisations"), "dates": rc.get("dates"),
                 "expected_document_types": docs.get("expected_document_types")}, expanded=False)
        if not docs.get("documents"):
            st.info("No vehicle-specific document matched. Absence of documents neither confirms nor refutes any status.")
        else:
            st.dataframe(pd.DataFrame([{"document": x["doc_id"], "type": x["document_type"], "score": x["relevance_score"],
                                        **{k: v for k, v in x["score_breakdown"].items()}} for x in docs["documents"]]),
                         width="stretch", hide_index=True,
                         column_config={k: st.column_config.ProgressColumn(k, min_value=0.0, max_value=1.0, format="%.2f")
                                        for k in ("score", "plate", "identifiers", "bm25", "doc_type", "date", "context")})
        for x in docs.get("documents", []) + docs.get("general_documents", []):
            with st.expander(f"{x['doc_id']} · {x['title']} · {x['document_type']} · score {x['relevance_score']} · {x['scope']}"):
                st.markdown("**Why relevant:** " + " · ".join(x["reasons"]))
                st.markdown(f"**Best matching chunk:** {x['snippet']}")
                checks = [c for c in x["evidence_checks"]]
                if checks:
                    st.markdown("**Document vs database**")
                    st.dataframe(pd.DataFrame(checks), width="stretch", hide_index=True)
                m = x["metadata"]
                st.json({k: m.get(k) for k in ("doc_id", "document_type", "document_type_source", "registration_numbers",
                                               "noisy_plate_mentions", "date", "issuer", "associated_entity", "source",
                                               "format", "identifiers", "keywords", "synthetic")}, expanded=False)
                st.text(x["extracted_text"])
        if docs.get("rejected"):
            st.markdown("**Rejected by structured context**")
            st.dataframe(pd.DataFrame(docs["rejected"]), width="stretch", hide_index=True)
    with tabs[5]:
        integ = result["integration"]
        risk = integ["insurance_risk"]
        st.markdown(f"**Insurance rule outcome:** {risk.get('status_label')} (`{risk.get('status')}`, {risk.get('risk_level')})")
        if risk.get("recommended_action"):
            st.caption(risk["recommended_action"])
        st.markdown(f"**Conflicts ({len(integ['conflicts'])})** — none are auto-resolved")
        for c in integ["conflicts"]:
            with st.expander(f"[{c['severity']}] {c['type']}: {c['description']}"):
                if c.get("explanation"):
                    st.info(c["explanation"])
                st.dataframe(pd.DataFrame(c["evidence"]), width="stretch", hide_index=True)
                st.caption(c["resolution"])
        st.markdown("**Missing information**")
        if result["missing_information"]:
            st.dataframe(pd.DataFrame(result["missing_information"]), width="stretch", hide_index=True)
        else:
            st.write("Nothing required by the query is missing.")
        props = integ["cleansing_proposals"]
        st.markdown(f"**Cleansing proposals ({len(props)})** — Phase 2 review workflow")
        for i, p in enumerate(props):
            st.write(f"`{p['field_label']}`: registry `{p['current_value']}` → RTO `{p['proposed_value']}` (registry record #{p['record_id']})")
            reason = st.text_input("Reviewer note", value=p["reason"], key=f"p3_reason_{i}")
            b1, b2, b3 = st.columns(3)
            for col, decision in ((b1, "ACCEPTED"), (b2, "REJECTED"), (b3, "UNRESOLVED")):
                if col.button(decision.title(), key=f"p3_{decision}_{i}"):
                    try:
                        out = _post("/api/cleansing/decide", {"proposal": p, "decision": decision, "reason": reason})
                        (st.success if out["success"] else st.error)(out["message"])
                    except Exception as exc:
                        st.error(str(exc))
        with st.expander("Phase 2 canonical record"):
            st.json(integ["canonical_record"], expanded=False)
    with tabs[6]:
        st.json(result, expanded=False)


BAND_STYLE = {"HIGH_TRUST": ("green", "#0f7b4f"), "REVIEW": ("amber", "#b86e00"), "HIGH_RISK": ("red", "#b42323"),
              "NO_MATCH": ("gray", "#64748b")}


def _trust_deductions(trust: Dict[str, Any]) -> None:
    if trust.get("deductions"):
        st.dataframe(pd.DataFrame([{"points": -d["points"], "reason": d["reason"], "source": d["source"]}
                                   for d in trust["deductions"]]), width="stretch", hide_index=True)
    else:
        st.write("No deductions: every check that was performed came back clean.")
    st.caption(trust.get("note", "") + " Score = 100 minus the listed deductions (rules in federation.TRUST_RULES).")


def render_trust_card(trust: Dict[str, Any], compact: bool = False) -> None:
    """Explainable Vehicle Trust Score: 100 minus listed deductions, with the checks it covers."""
    if not trust or trust.get("score") is None:
        return
    tone, color = BAND_STYLE.get(trust["band"], ("gray", "#64748b"))
    score = int(trust["score"])
    n = len(trust.get("deductions") or [])
    st.markdown(
        f"<div class='vt-trust'><div class='vt-trust-label'>Vehicle Trust Score</div>"
        f"<div class='vt-trust-score' style='color:{color}'>{score}</div>"
        f"<div class='vt-trust-bar'><div style='width:{max(2, min(100, score))}%;background:{color}'></div></div>"
        f"{ui.pill(trust['label'], tone)}"
        f"<div class='vt-stmt-src' style='margin-top:10px'>{n} deduction(s) · 100 minus listed risks</div></div>",
        unsafe_allow_html=True)
    if not compact:
        _trust_deductions(trust)


def render_fleet_scan() -> None:
    """Runs the full-history federated query for every vehicle in the registry and summarises data quality."""
    ui.page_header("Fleet data-quality scan",
                   "Runs the complete-history federated query for every registered vehicle - all five databases, "
                   "wave 1 and the audit wave - and ranks the fleet by Trust Score, conflicts and statuses. "
                   "Documents and the LLM are skipped for speed.", eyebrow="Federated querying")
    if st.button("Scan all vehicles", type="primary", icon=":material/play_arrow:"):
        try:
            vehicles = _get("/api/services/vehicle_registry/records")
        except Exception as exc:
            st.error(f"Vehicle Registry unavailable through the gateway: {exc}")
            return
        rows, started = [], time.time()
        bar = st.progress(0.0, text="Scanning...")
        for i, v in enumerate(vehicles):
            plate = v["registration_number"]
            try:
                r = _post("/api/federated-query", {"query": f"Check the complete history of {plate}",
                                                   "include_documents": False, "use_llm": False}, timeout=30)
                t, attrs, risk = r.get("trust") or {}, r["context"]["attributes"], r["integration"]["insurance_risk"]
                rows.append({"plate": plate, "vehicle": f"{v.get('make', '')} {v.get('model', '')}".strip(),
                             "trust score": t.get("score"), "band": t.get("label"),
                             "conflicts": len(r["integration"]["conflicts"]),
                             "conflict types": ", ".join(sorted({c["type"] for c in r["integration"]["conflicts"]})) or "-",
                             "insurance": risk.get("status"),
                             "theft": (attrs.get("theft_status") or {}).get("value", "not recorded"),
                             "scrapping": (attrs.get("scrapping_status") or {}).get("value", "not recorded"),
                             "RC": (attrs.get("rc_status") or {}).get("value", "-"),
                             "unavailable": ", ".join(k for k, s in r["context"]["service_availability"].items()
                                                      if s["status"] != "ok") or "-"})
            except Exception as exc:
                rows.append({"plate": plate, "vehicle": "", "trust score": None, "band": f"error: {exc}"})
            bar.progress((i + 1) / max(1, len(vehicles)), text=f"Scanned {i + 1}/{len(vehicles)}: {plate}")
        st.session_state.fleet_scan = {"rows": rows, "seconds": round(time.time() - started, 1)}
    scan = st.session_state.get("fleet_scan")
    if not scan:
        ui.note("Press <b>Scan all vehicles</b>. Each vehicle triggers one federated query; the whole fleet takes "
                "a few seconds.")
        return
    df = pd.DataFrame(scan["rows"])
    scored = df[df["trust score"].notna()]
    m1, m2, m3, m4, m5 = st.columns(5)
    m1.metric("Vehicles scanned", len(df))
    m2.metric("Average trust", f"{scored['trust score'].mean():.0f}" if len(scored) else "-")
    m3.metric("High risk", int((scored["band"] == "High risk").sum()) if len(scored) else 0)
    m4.metric("With conflicts", int((df.get("conflicts", 0) > 0).sum()) if "conflicts" in df else 0)
    m5.metric("Scan time", f"{scan['seconds']} s")
    if len(scored):
        import altair as alt
        bands = ["High trust", "Review advised", "High risk"]
        chart = alt.Chart(scored).mark_bar(cornerRadiusEnd=3, height=14).encode(
            x=alt.X("trust score:Q", scale=alt.Scale(domain=[0, 100]), title="Vehicle Trust Score"),
            y=alt.Y("plate:N", sort="x", title=None, axis=alt.Axis(labelOverlap=False, labelFontSize=11)),
            color=alt.Color("band:N", scale=alt.Scale(domain=bands, range=["#1baf7a", "#eda100", "#d03b3b"]),
                            legend=alt.Legend(title=None, orient="top")),
            tooltip=["plate", "vehicle", "trust score", "band", "conflicts", "insurance", "theft", "scrapping"],
        ).properties(height=22 * len(scored) + 50)
        st.altair_chart(chart, width="stretch")
    st.dataframe(df.sort_values("trust score", na_position="first"), width="stretch", hide_index=True,
                 column_config={"trust score": st.column_config.ProgressColumn("trust score", min_value=0, max_value=100,
                                                                               format="%d")})
    conflict_counts = {}
    for types in df.get("conflict types", []):
        for t in str(types).split(", "):
            if t and t != "-":
                conflict_counts[t] = conflict_counts.get(t, 0) + 1
    if conflict_counts:
        ui.section("Conflict types across the fleet")
        st.dataframe(pd.DataFrame(sorted(conflict_counts.items(), key=lambda x: -x[1]), columns=["conflict type", "vehicles"]),
                     width="stretch", hide_index=True)


def render_schema_explorer() -> None:
    ui.page_header("Schemas & FK-PK relationships",
                   "Live schema of each database service, read over its REST API (/schema, /tables, /integrity): "
                   "tables, primary and foreign keys, an orphan-row integrity check and the rows themselves.",
                   eyebrow="Data")
    keys = config.ALL_SERVICE_KEYS
    tabs = st.tabs([config.SERVICES[k]["label"] for k in keys])
    for key, tab in zip(keys, tabs):
        with tab:
            try:
                schema = _get(f"/api/services/{key}/schema")
                integrity = _get(f"/api/services/{key}/integrity")
            except Exception as exc:
                st.error(f"{config.SERVICES[key]['label']} unavailable: {exc}")
                continue
            m1, m2, m3, m4 = st.columns(4)
            m1.metric("Tables", len(schema["tables"]))
            m2.metric("FK constraints", sum(len(t["foreign_keys"]) for t in schema["tables"]))
            m3.metric("FK enforcement", "ON" if integrity["foreign_keys_enabled"] else "OFF")
            m4.metric("Orphan rows", len(integrity["violations"]))
            st.caption(f"Database file on its own machine: `{schema['database']}` · views: {', '.join(schema['views']) or 'none'}")
            dot = ['digraph S { rankdir=LR; bgcolor="transparent"; node [shape=record, fontsize=10, fontname="Helvetica", '
                   'style=filled, fillcolor="#ffffff", color="#9fb0c6"]; edge [color="#8a99ad", fontname="Helvetica"];']
            for t in schema["tables"]:
                cols = "\\l".join(("PK  " if c["primary_key"] else "") + c["name"] for c in t["columns"][:12])
                dot.append(f'"{t["table"]}" [label="{{{t["table"]} ({t["row_count"]})|{cols}\\l}}"];')
                for fk in t["foreign_keys"]:
                    dot.append(f'"{t["table"]}" -> "{fk["references_table"]}" [label="{fk["column"]}", fontsize=8];')
            dot.append("}")
            st.graphviz_chart("\n".join(dot))
            st.dataframe(pd.DataFrame([{"table": t["table"], "rows": t["row_count"], "primary key": ", ".join(t["primary_key"]),
                                        "foreign keys": ", ".join(f"{f['column']} → {f['references_table']}.{f['references_column']}"
                                                                  for f in t["foreign_keys"]) or "-",
                                        "indexes": len(t["indexes"])} for t in schema["tables"]]),
                         width="stretch", hide_index=True)
            table = st.selectbox("Inspect table rows", [t["table"] for t in schema["tables"]] + schema["views"], key=f"tbl_{key}")
            try:
                rows = _get(f"/api/services/{key}/tables/{table}", {"limit": 100})
                st.dataframe(pd.DataFrame(rows["rows"]), width="stretch", hide_index=True)
            except Exception as exc:
                st.error(str(exc))


def render_documents() -> None:
    ui.page_header("Document repository",
                   "Synthetic police reports, insurer letters, RTO notices and certificates (TXT, PDF, Markdown). Each "
                   "is cleaned, its metadata extracted (plates incl. OCR-noisy ones, identifiers, dates, type) and "
                   "indexed as overlapping chunks with BM25.", eyebrow="Unstructured data")
    try:
        data = _get("/api/documents")
    except Exception as exc:
        st.error(f"Gateway unavailable: {exc}")
        return
    stats = data["stats"]
    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Documents", stats["documents"])
    c2.metric("Chunks indexed", stats["chunks"])
    c3.metric("Vocabulary", stats["vocabulary"])
    c4.metric("Formats", " · ".join(k.upper() for k in stats["formats"]),
              help=", ".join(f"{k}: {v}" for k, v in stats["formats"].items()))
    st.caption("All documents are SYNTHETIC demonstration data (marked in each file). Index: BM25 over overlapping "
               f"word chunks + metadata. Indexed at {stats['indexed_at']}.")
    if st.button("Re-index documents folder"):
        _post("/api/documents/reindex", {})
        st.rerun()
    s1, s2, s3 = st.columns([2, 1, 1])
    q = s1.text_input("Keyword search", "theft claim rejected")
    dtype = s2.selectbox("Type filter", ["(any)"] + sorted(stats["document_types"]))
    plate = s3.text_input("Registration filter", "")
    if q:
        hits = _post("/api/documents/search", {"query": q, "document_type": None if dtype == "(any)" else dtype,
                                               "registration_number": plate or None, "top_k": 8})
        for h in hits:
            st.markdown(f"**{h['doc_id']}** · {h['metadata']['document_type']} · BM25 {h['bm25']} — {h['snippet'][:220]}...")
    st.markdown("**All documents (extracted metadata)**")
    st.dataframe(pd.DataFrame([{"doc_id": m["doc_id"], "type": m["document_type"], "type source": m["document_type_source"],
                                "registration": ", ".join(m["registration_numbers"]),
                                "noisy plate": ", ".join(n["raw"] for n in m["noisy_plate_mentions"]),
                                "date": m["date"], "issuer": m["issuer"], "format": m["format"], "chunks": m["chunks"],
                                "keywords": ", ".join(m["keywords"][:5]), "source": m["source"]} for m in data["documents"]]),
                 width="stretch", hide_index=True)
