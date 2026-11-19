"""Phase 3 Streamlit pages (imported by app.py): federated query pipeline, schema explorer,
document repository. All data comes from the gateway REST API (GATEWAY_URL, default :8000)."""
from typing import Any, Dict, List

import httpx
import pandas as pd
import streamlit as st

import config

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
    "database_fact": ("🗄️", "Database fact"), "assessment": ("🛡️", "Rule-based assessment"),
    "document_evidence": ("📄", "Document evidence"), "conflict": ("⚠️", "Conflict"),
    "missing": ("❓", "Missing information"), "resolution": ("🔎", "Entity resolution"),
}
STATUS_BADGE = {"ok": "🟢 ok", "timeout": "🟠 timeout", "unavailable": "🔴 unavailable", "error": "🔴 error",
                "not_called": "⚪ not called"}
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
    lines = ['digraph G { rankdir=LR; node [shape=box, style="rounded", fontsize=10]; edge [fontsize=8];']
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
    cols = st.columns(len(PIPELINE))
    for col, name in zip(cols, PIPELINE):
        s = mapping.get(name)
        done = s is not None
        with col:
            st.markdown(
                f"<div style='border:1px solid {'#2a78d6' if done else '#bbb'};border-radius:8px;padding:6px;"
                f"min-height:118px;font-size:0.78rem'><b>{'✅' if done else '⏸️'} {name}</b><br>"
                f"<span style='opacity:.75'>{(str(s['ms']) + ' ms') if done else 'not reached'}</span><br>"
                f"<span style='opacity:.85'>{(s or {}).get('detail', '')[:95]}</span></div>",
                unsafe_allow_html=True)


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


def render_federated_query() -> None:
    st.header("🌐 Phase 3 — Federated Query Processing")
    st.caption(f"Gateway: `{gateway()}` · the gateway decomposes the query, sends subqueries to the independent "
               "database services over REST, accumulates FK-PK context and retrieves correlated documents.")

    c1, c2 = st.columns([3, 1])
    with c2:
        example = st.selectbox("Examples", ["(choose)"] + EXAMPLES)
    default_q = st.session_state.get("p3_query", EXAMPLES[0])
    if example != "(choose)":
        default_q = example
    with c1:
        query = st.text_area("Natural-language query", value=default_q, height=80)

    with st.expander("📷 Registration image / explicit plate / observed context", expanded=False):
        e1, e2 = st.columns(2)
        with e1:
            image = st.file_uploader("Upload plate image (OCR via gateway)", type=["jpg", "jpeg", "png"], key="p3_img")
            if image is not None and st.button("Run OCR on image"):
                try:
                    resp = httpx.post(f"{gateway()}/api/ocr", files={"file": (image.name, image.getvalue(), image.type)}, timeout=120)
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
            plate = st.text_input("Explicit / OCR plate (overrides plate in text)", value=st.session_state.get("p3_plate", ""))
            ctx_cols = st.columns(2)
            make = ctx_cols[0].text_input("Observed make", key="p3_make")
            model = ctx_cols[1].text_input("Observed model", key="p3_model")
            colour = ctx_cols[0].text_input("Observed colour", key="p3_colour")
            state = ctx_cols[1].text_input("Observed state", key="p3_state")
    o1, o2, o3 = st.columns([1, 1, 2])
    include_docs = o1.checkbox("Retrieve documents", value=True)
    top_k = o2.number_input("Top-k documents", 1, 15, 6)
    if o3.button("🚀 Run federated query", type="primary", width="stretch"):
        st.session_state.p3_query = query
        payload = {"query": query, "plate": plate or None,
                   "plate_source": "ocr" if plate and plate == (st.session_state.get("p3_ocr") or {}).get("normalized_plate") else None,
                   "make": make or None, "model": model or None, "colour": colour or None, "state": state or None,
                   "include_documents": include_docs, "top_k_documents": int(top_k)}
        with st.spinner("Federating subqueries..."):
            try:
                st.session_state.p3_result = _post("/api/federated-query", payload)
            except Exception as exc:
                st.error(f"Gateway request failed ({gateway()}): {exc}. Is `start_node.py machine-1` (or `all`) running?")
                return

    result = st.session_state.get("p3_result")
    if not result:
        st.info("Enter a query and press **Run federated query**.")
        return
    st.markdown("### Execution pipeline")
    _pipeline_strip(result)
    if result.get("error"):
        st.error(result["error"])
        return

    avail = result["context"]["service_availability"]
    down = [v["label"] for v in avail.values() if v["status"] not in ("ok",)]
    if down:
        st.warning("⚠️ Unavailable services (partial results): " + ", ".join(down))

    answer = result["answer"]
    st.markdown(f"### 🧾 Final answer — {answer['headline']}")
    for s in answer["statements"]:
        icon, label = KIND_STYLE.get(s["kind"], ("•", s["kind"]))
        src = f"  \n<small>sources: {', '.join(s['sources'])}</small>" if s["sources"] else ""
        st.markdown(f"{icon} **{label}:** {s['text']}{src}", unsafe_allow_html=True)
    st.caption(f"Total {result['total_ms']} ms · decision support only, not an official verification.")

    tabs = st.tabs(["1 Understanding & decomposition", "2 Federated execution", "3 Database results & FK-PK",
                    "4 Accumulated context", "5 Documents", "6 Integration, conflicts & cleansing", "Raw JSON"])
    u, d = result["understanding"], result["decomposition"]
    with tabs[0]:
        a, b = st.columns(2)
        with a:
            st.markdown("**Query understanding**")
            st.json({k: u[k] for k in ("registration_number", "plate_source", "plate_text_span", "plate_syntax_valid",
                                       "plate_syntax_corrected", "intents", "intent_labels", "attributes",
                                       "required_information", "ocr_variants")})
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
            with st.expander(f"📄 {x['doc_id']} · {x['title']} · {x['document_type']} · score {x['relevance_score']} · {x['scope']}"):
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
            with st.expander(f"⚠️ [{c['severity']}] {c['type']}: {c['description']}"):
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


def render_schema_explorer() -> None:
    st.header("🧬 Database Schemas & FK-PK Relationships")
    st.caption("Read through each service's REST API (/schema, /tables, /integrity) — works across laptops.")
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
            dot = ['digraph S { rankdir=LR; node [shape=record, fontsize=10];']
            for t in schema["tables"]:
                cols = "\\l".join(("🔑 " if c["primary_key"] else "") + c["name"] for c in t["columns"][:12])
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
    st.header("📚 Unstructured Document Repository")
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
    c4.metric("Formats", ", ".join(f"{k}:{v}" for k, v in stats["formats"].items()))
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
