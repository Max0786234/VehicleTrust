import os
import sys
import time
import datetime
import numpy as np
import pandas as pd
import streamlit as st
import httpx
from dotenv import load_dotenv

sys.path.insert(0, os.path.dirname(__file__))

from matching import (
    normalize_plate,
    generate_ocr_confusion_variants,
    search_and_rank_candidates,
    rank_candidate_record,
    evaluate_algorithms,
)
from integration import (
    CanonicalVehicleRecord,
    evaluate_insurance_risk,
    generate_cleansing_proposals,
    apply_cleansing_decision,
    get_cleansing_audit_logs,
)

load_dotenv(os.path.join(os.path.dirname(os.path.abspath(__file__)), ".env"))
import config  # noqa: E402
import ui_phase3  # noqa: E402
import ui_theme as ui  # noqa: E402

st.set_page_config(page_title="VehicleTrust", page_icon=":material/verified_user:", layout="wide",
                   initial_sidebar_state="expanded")
ui.inject()

DEMO = config.DEMO_MODE
REPO_URL = os.getenv("PROJECT_REPO_URL", "https://github.com/Max0786234/VehicleTrust")
DEFAULT_URLS = {key: config.service_url(key) for key in config.DATA_SERVICE_KEYS}
DEFAULT_AUDIT_URL = config.service_url("audit_log")
OCR_DEMO_REASON = ("Plate OCR uses EasyOCR on PyTorch (about 2 GB of model and runtime), which does not fit the free "
                   "hosting tier. It runs in the local installation; here, type the plate instead. Everything after "
                   "OCR (normalisation, OCR-confusion variants, fuzzy matching) works the same.")

if "service_urls" not in st.session_state:
    st.session_state.service_urls = DEFAULT_URLS.copy()
if "audit_api_url" not in st.session_state:
    st.session_state.audit_api_url = DEFAULT_AUDIT_URL
if "active_plate" not in st.session_state:
    st.session_state.active_plate = "DL01AB1234"
if "gateway_url" not in st.session_state:
    st.session_state.gateway_url = config.gateway_url()


@st.cache_resource
def get_ocr_reader():
    try:
        import easyocr
        return easyocr.Reader(["en"], gpu=False)
    except Exception:
        return None


def check_service_health(service_key: str, base_url: str):
    try:
        start = time.time()
        resp = httpx.get(f"{base_url.rstrip('/')}/health", timeout=2.5)
        latency = round((time.time() - start) * 1000, 1)
        if resp.status_code == 200:
            data = resp.json()
            return True, latency, data.get("record_count", 0), data
        return False, latency, 0, {"error": f"Status {resp.status_code}"}
    except Exception as e:
        return False, 0.0, 0, {"error": str(e)}


def fetch_service_records(service_key: str, base_url: str):
    try:
        resp = httpx.get(f"{base_url.rstrip('/')}/records", timeout=3.0)
        return (True, resp.json()) if resp.status_code == 200 else (False, [])
    except Exception:
        return False, []


SERVICE_META = [
    ("Vehicle Registry", "vehicle_registry", 8101),
    ("Insurance Records", "insurance_records", 8102),
    ("Registration Authority", "registration_authority", 8103),
    ("Theft & Scrapping", "theft_scrapping", 8104),
    ("Cleansing Audit Log", "audit_log", 8105),
]


def service_url_for(key: str) -> str:
    return st.session_state.audit_api_url if key == "audit_log" else st.session_state.service_urls[key]


def render_service_cards(show_errors: bool = True) -> bool:
    """Live status card per database service; returns True when all five are online."""
    cards, all_online = [], True
    for name, key, port in SERVICE_META:
        url = service_url_for(key)
        is_up, latency, count, data = check_service_health(key, url)
        all_online &= is_up
        machine = config.SERVICES[key]["machine"].replace("machine-", "Laptop ")
        status = ui.pill(f"Online · {latency:.0f} ms", "green") if is_up else ui.pill("Unreachable", "red")
        body = (f"<div class='vt-svc-num'>{count}</div><div class='vt-svc-sub'>"
                f"{'records · ' + str(data.get('table_count', '-')) + ' tables' if is_up else ''}</div>")
        if not is_up and show_errors:
            body = f"<div class='vt-svc-sub'>{ui.escape(str(data.get('error', ''))[:120])}</div>"
        where = "single host" if DEMO else machine
        cards.append(f"<div class='vt-svc'><div class='vt-svc-name'>{name}</div>"
                     f"<div class='vt-svc-meta'>:{port} · {where}</div>{status}<div style='margin-top:10px'>{body}</div></div>")
    st.markdown(f"<div class='vt-grid' style='grid-template-columns:repeat(auto-fit,minmax(200px,1fr))'>{''.join(cards)}</div>",
                unsafe_allow_html=True)
    return all_online


def render_service_list() -> None:
    rows = []
    for name, key, port in SERVICE_META:
        is_up, latency, count, _ = check_service_health(key, service_url_for(key))
        status = ui.pill(f"{latency:.0f} ms", "green") if is_up else ui.pill("down", "red")
        rows.append(f"<div class='vt-svc-row'><div><b>{name}</b> <span class='vt-mono'>:{port}</span></div>"
                    f"<div>{'<span class=vt-mono>' + str(count) + ' rows</span> ' if is_up else ''}{status}</div></div>")
    st.markdown(f"<div class='vt-card' style='padding:4px 16px'>{''.join(rows)}</div>", unsafe_allow_html=True)


ARCH_DOT = """
digraph A {
  rankdir=LR; bgcolor="transparent"; nodesep=0.18; ranksep=0.5; size="11,3.6";
  node [shape=box, style="rounded,filled", fillcolor="#ffffff", color="#c9d3e0", fontname="Helvetica", fontsize=10, margin="0.18,0.08"];
  edge [color="#8a99ad", arrowsize=0.6, fontname="Helvetica", fontsize=8, fontcolor="#5b6678"];
  user [label="User\\nquestion / plate", shape=oval, fillcolor="#eaf0ff", color="#1d4ed8", fontcolor="#1d4ed8"];
  subgraph cluster_m1 { label="%s"; fontname="Helvetica"; fontsize=10; fontcolor="#5b6678"; style="rounded,dashed"; color="#c9d3e0";
    ui [label="Streamlit dashboard\\n:8501"];
    gw [label="Gateway  :8000\\nunderstand · decompose\\nfederate · integrate", fillcolor="#1d4ed8", color="#1d4ed8", fontcolor="#ffffff"];
    docs [label="Document index\\nBM25 · 37 docs"];
    theft [label="Theft & Scrapping\\n:8104 · 6 tables"];
    audit [label="Audit Log\\n:8105 · 5 tables"];
  }
  subgraph cluster_m2 { label="%s"; fontname="Helvetica"; fontsize=10; fontcolor="#5b6678"; style="rounded,dashed"; color="#c9d3e0";
    reg [label="Vehicle Registry\\n:8101 · 5 tables"];
    ins [label="Insurance\\n:8102 · 5 tables"];
    rto [label="Registration (RTO)\\n:8103 · 5 tables"];
  }
  user -> ui -> gw;
  gw -> reg [label="wave 1"]; gw -> ins; gw -> rto; gw -> theft;
  gw -> audit [label="wave 2"];
  gw -> docs [label="context"];
}
"""


# ============================================================================== pages
def page_overview():
    ui.page_header(
        "Trustworthy vehicle answers from five independent databases",
        "Ask about a vehicle in plain English. VehicleTrust works out which databases are relevant, queries them in "
        "parallel over REST, follows foreign-key relationships inside each one, resolves the vehicle across sources "
        "despite noisy plates, retrieves supporting documents, and returns an answer in which every statement is "
        "tagged as a database fact, document evidence, a conflict or missing information.",
        eyebrow="Information integration · federated query processing")
    if DEMO:
        ui.note("<b>Hosted demo.</b> All five database services, the gateway and this dashboard run as separate "
                "processes in one container and talk over HTTP. In the full setup they are split across two laptops "
                "(2 + 3). Data is synthetic and resets when the demo restarts. Plate OCR and the local LLM run in the "
                "local installation only.")

    ui.stat_cards([
        ("Independent databases", "5", "separate SQLite services"),
        ("Relational tables", "26", "linked by foreign keys"),
        ("Synthetic documents", "37", "TXT · PDF · Markdown"),
        ("Automated tests", "142", "pytest, incl. multi-process"),
    ])

    c1, c2 = st.columns([1.5, 1], gap="large")
    with c1:
        ui.section("Try a question", "Each opens the federated query page and runs it straight away.")
        examples = [
            ("Complete history", "Check the complete history of vehicle DL01AB1234."),
            ("Stolen and re-insured", "Is this vehicle insured, stolen or scrapped? GJ 01 AB 7777"),
            ("Ownership mismatch", "Find the ownership history and insurance details for UP16BT9900"),
            ("Noisy OCR plate", "Find vehicles with registration numbers similar to DLO1AB1234 and identify discrepancies"),
            ("Scrapped but RC valid", "Is WB02K0001 scrapped?"),
            ("Audit trail", "Show the full history and audit trail of KA05MJ5555"),
        ]
        grid = st.columns(2)
        for i, (label, q) in enumerate(examples):
            with grid[i % 2]:
                if st.button(label, key=f"ov_ex_{i}", width="stretch", help=q):
                    st.session_state.p3_query = q
                    st.session_state.p3_autorun = True
                    st.switch_page(PAGES["query"])
    with c2:
        ui.section("Live services", "Health check of each database service, right now.")
        render_service_list()

    ui.section("Architecture", "Two-laptop deployment: Laptop 1 hosts the gateway, dashboard, Theft and Audit; Laptop 2 "
                               "hosts Registry, Insurance and Registration" + (". This demo runs all of it on one host."
                                                                              if DEMO else "."))
    with st.container(border=True):
        st.graphviz_chart(ARCH_DOT % ("Laptop 1", "Laptop 2"), width="content")

    ui.section("How a question is answered")
    steps = [
        ("Understand", "Plate, intents and attributes from the question (rules, or a local LLM with grounding)."),
        ("Decompose", "Only the relevant databases get a subquery; skipped ones are listed with a reason."),
        ("Federate", "Subqueries run in parallel with per-call deadlines; outages give partial results."),
        ("Expand locally", "Each service follows its own FK-PK joins (owner, policies, claims, RTO events...)."),
        ("Resolve & accumulate", "Noisy plates are matched; attributes keep their source and alternatives."),
        ("Retrieve documents", "Structured context drives hybrid BM25 retrieval and rejects look-alike plates."),
        ("Integrate & answer", "Conflicts are flagged, never auto-resolved; an explainable Trust Score is computed."),
    ]
    st.markdown("<div class='vt-steps'>" + "".join(
        f"<div class='vt-step'><div class='vt-step-num'>STEP {i + 1}</div><div class='vt-step-name'>{t}</div>"
        f"<div class='vt-step-detail'>{d}</div></div>" for i, (t, d) in enumerate(steps)) + "</div>",
        unsafe_allow_html=True)

    ui.section("Where to look")
    ui.info_cards([
        ("Federated query", "The full pipeline for one question: decomposition, parallel execution timeline, FK-PK "
                            "graphs, accumulated context, documents and conflicts."),
        ("Fleet scan", "Runs the pipeline for all 33 vehicles and ranks them by Trust Score - integration at fleet scale."),
        ("Noisy plate matching", "Damerau-Levenshtein, RapidFuzz and OCR-confusion variants combined with "
                                 "make/model/colour context; benchmark included."),
        ("Cleansing with audit", "Registry vs RTO discrepancies become proposals; every accept/reject is "
                                 "evidence-checked and written to an append-only audit log."),
        ("Schemas & FK-PK", "Live schema, FK constraints, integrity check and table rows of each database."),
        ("Documents", "37 synthetic reports, notices and certificates with extracted metadata and BM25 search."),
    ])
    ui.section("Built with")
    ui.chips(["Python", "FastAPI", "Uvicorn", "SQLAlchemy 2", "SQLite", "httpx (async)", "RapidFuzz",
              "Damerau-Levenshtein", "BM25", "pypdf", "Streamlit", "Altair", "Ollama (local LLM)", "OpenCV / EasyOCR",
              "pytest"])


def page_service_health():
    ui.page_header("System status",
                   "Health of the five independent database services. Each owns its SQLite file; the gateway "
                   "reaches them only over HTTP.", eyebrow="Infrastructure")
    all_online = render_service_cards()
    if all_online:
        ui.note("All five database services are online.", tone="green")
    else:
        ui.note("One or more services are unreachable. Queries still run and report those sources as unavailable "
                "(partial results, never treated as 'clear').", tone="amber")
    try:
        topo = httpx.get(f"{st.session_state.gateway_url}/api/topology", timeout=3).json()
        with st.expander("Gateway topology (GET /api/topology)"):
            st.json(topo, expanded=False)
    except Exception:
        pass
    with st.expander("Two-laptop deployment (2 + 3 split)"):
        st.markdown(
            "- **Laptop 2:** `python start_node.py machine-2` → Registry 8101, Insurance 8102, Registration 8103\n"
            "- **Laptop 1:** `python start_node.py configure machine-1 --machine2-ip <LAPTOP2_IP>`, then "
            "`python start_node.py machine-1` → Theft 8104, Audit 8105, Gateway 8000, dashboard 8501\n"
            "- Verify: `python start_node.py check` · details in `docs/DISTRIBUTED_SETUP.md`")


def page_plate_input():
    ui.page_header("Plate input & OCR",
                   "Plate images are pre-processed with OpenCV (grayscale, resize, Gaussian blur, Otsu threshold) and "
                   "read with EasyOCR. The recognised text is normalised and expanded into OCR-confusion variants.",
                   eyebrow="Noisy plate matching")
    col1, col2 = st.columns([1, 1])
    with col1:
        if DEMO:
            ui.demo_notice("Image OCR", OCR_DEMO_REASON)
            uploaded_file = None
        else:
            uploaded_file = st.file_uploader("Upload plate image", type=["jpg", "jpeg", "png"])
        manual_override = st.text_input("Enter plate manually", value=st.session_state.active_plate)
        if st.button("Use this plate", type="primary"):
            st.session_state.active_plate = normalize_plate(manual_override)
            st.success(f"Active plate: {st.session_state.active_plate}")

    with col2:
        if uploaded_file is not None:
            import cv2
            file_bytes = np.asarray(bytearray(uploaded_file.read()), dtype=np.uint8)
            img = cv2.imdecode(file_bytes, cv2.IMREAD_COLOR)
            st.image(cv2.cvtColor(img, cv2.COLOR_BGR2RGB), caption="Uploaded plate image", width="stretch")

            gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
            resized = cv2.resize(gray, None, fx=2.0, fy=2.0, interpolation=cv2.INTER_CUBIC)
            blurred = cv2.GaussianBlur(resized, (5, 5), 0)
            _, thresh = cv2.threshold(blurred, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)

            with st.expander("OpenCV pre-processing", expanded=False):
                p1, p2, p3 = st.columns(3)
                p1.image(gray, caption="1. Grayscale")
                p2.image(blurred, caption="2. Gaussian blur")
                p3.image(thresh, caption="3. Otsu threshold")

            reader = get_ocr_reader()
            if reader is None:
                st.warning("EasyOCR is not installed on this machine. Use manual plate entry.")
            else:
                with st.spinner("Reading the plate with EasyOCR..."):
                    results = reader.readtext(thresh)
                    if results:
                        raw_combined = " ".join([r[1] for r in results])
                        avg_conf = float(np.mean([r[2] for r in results]))
                        norm = normalize_plate(raw_combined)
                        st.session_state.active_plate = norm
                        st.success(f"Recognised plate: **{norm}**")
                        st.info(f"Raw output: `{raw_combined}` · confidence {avg_conf * 100:.1f}%")
                    else:
                        st.warning("No readable plate text found. Please enter it manually.")

    ui.section("OCR-confusion variants",
               f"Look-alike characters (0/O, 1/I, 8/B, 5/S ...) of {st.session_state.active_plate} - used to find records "
               "that were mistyped or misread.")
    variants = generate_ocr_confusion_variants(st.session_state.active_plate)
    ui.chips(variants)


def page_candidate_search():
    ui.page_header("Fuzzy candidate search",
                   "Ranks records from all four vehicle databases against a possibly noisy plate: 0.7 × plate "
                   "similarity (Damerau-Levenshtein, RapidFuzz, OCR variants) + 0.3 × context agreement.",
                   eyebrow="Noisy plate matching")
    scol1, scol2, scol3 = st.columns([2, 1, 1], vertical_alignment="bottom")
    with scol1:
        search_query = st.text_input("Registration plate", value=st.session_state.active_plate)
    with scol2:
        threshold = st.slider("Similarity threshold", 0.20, 0.95, 0.50, 0.05)
    with scol3:
        st.button("Search databases", width="stretch", type="primary")

    with st.expander("Contextual clues (make, model, colour, state)", expanded=False):
        cc1, cc2, cc3, cc4 = st.columns(4)
        c_make = cc1.text_input("Make", value="")
        c_model = cc2.text_input("Model", value="")
        c_colour = cc3.text_input("Colour", value="")
        c_state = cc4.text_input("State", value="")

    query_context = {"make": c_make.strip() or None, "model": c_model.strip() or None,
                     "colour": c_colour.strip() or None, "state": c_state.strip() or None}

    all_source_records = []
    offline_services = []
    for s_name, s_url in st.session_state.service_urls.items():
        ok, records = fetch_service_records(s_name, s_url)
        if ok:
            all_source_records.append((s_name, records))
        else:
            offline_services.append(s_name)

    if offline_services:
        st.warning(f"Services offline: {', '.join(offline_services)}. Showing partial results.")

    candidates = search_and_rank_candidates(search_query, all_source_records, query_context, threshold)
    ui.section(f"{len(candidates)} candidate(s)")

    if candidates:
        rows = []
        for idx, c in enumerate(candidates):
            rows.append({
                "Rank": idx + 1, "Plate": c["recorded_registration_number"], "Source": c["source_database"],
                "ID": c["record_id"], "Score": round(c["combined_score"], 3), "Confidence": c["confidence"],
                "Edit distance": c["edit_distance"], "RapidFuzz": round(c["plate_similarity"], 2),
                "Damerau-Lev.": round(c["dl_similarity"], 2), "Context": round(c["contextual_score"], 2),
                "Method": c["matching_method"], "Supporting": ", ".join(c["supporting_attributes"]) or "-",
                "Conflicting": ", ".join(c["conflicting_attributes"]) or "-",
            })
        st.dataframe(pd.DataFrame(rows), width="stretch", hide_index=True,
                     column_config={"Score": st.column_config.ProgressColumn("Score", min_value=0.0, max_value=1.0,
                                                                             format="%.3f")})

        s1, s2 = st.columns([2, 1], vertical_alignment="bottom")
        selected_plate = s1.selectbox("Inspect candidate", [c["recorded_registration_number"] for c in candidates])
        if s2.button("Open integrated record", width="stretch"):
            st.session_state.active_plate = selected_plate
            st.switch_page(PAGES["record"])


def page_integrated_record():
    ui.page_header("Integrated canonical record",
                   "Combines the best match from each database into one canonical vehicle record, evaluates insurance "
                   "with date rules and lists attribute conflicts between the registry and the RTO.",
                   eyebrow="Integration")
    target_plate = st.text_input("Vehicle plate", value=st.session_state.active_plate)

    canonical = CanonicalVehicleRecord(target_plate)
    ins_available = True
    for s_name, s_url in st.session_state.service_urls.items():
        ok, records = fetch_service_records(s_name, s_url)
        if not ok:
            if s_name == "insurance_records":
                ins_available = False
            continue
        ranked = [
            rank_candidate_record(target_plate, record, s_name, record.get("id", 0))
            for record in records
        ]
        matches = [candidate for candidate in ranked if candidate["dl_similarity"] >= 0.80]
        if matches:
            best = max(matches, key=lambda candidate: (candidate["combined_score"], candidate["dl_similarity"]))
            canonical.add_source_record(
                s_name,
                best["raw_record"],
                best["dl_similarity"],
                best["confidence"],
            )

    data = canonical.to_dict()
    risk = evaluate_insurance_risk(data.get("insurance", []), data.get("theft_scrapping"), datetime.date.today(),
                                   data.get("confidence_tier", "HIGH"), ins_available)

    tone = {"CURRENT": "green", "EXPIRED": "red", "NOT_FOUND": "red", "CONFLICTING": "amber",
            "FUTURE_POLICY": "blue", "UNVERIFIED": "amber"}.get(risk["status"], "amber")
    t_stat, s_stat = risk["theft_status"], risk["scrapping_status"]
    st.markdown(
        "<div class='vt-card'><div class='vt-label'>Insurance status</div>"
        f"<div style='margin:6px 0 10px 0'>{ui.pill(risk['status_label'], tone)} "
        f"{ui.pill('Theft: ' + t_stat, 'red' if t_stat == 'STOLEN' else 'green')} "
        f"{ui.pill('Scrapping: ' + s_stat, 'red' if s_stat == 'SCRAPPED' else 'green')}</div>"
        f"<p><b>Recommended action:</b> {ui.escape(risk['recommended_action'])}</p>"
        f"<p style='margin-top:6px;font-size:0.78rem'>{ui.escape(risk['disclaimer'])}</p></div>",
        unsafe_allow_html=True)

    st.write("")
    tab1, tab2, tab3, tab4 = st.tabs(["Vehicle Registry", "Registration Authority", "Insurance policies", "Theft & Scrapping"])
    with tab1:
        st.json(data["registry"]["raw_record"] if data.get("registry") else {"status": "No record"})
    with tab2:
        st.json(data["authority"]["raw_record"] if data.get("authority") else {"status": "No record"})
    with tab3:
        st.json([p["raw_record"] for p in data["insurance"]] if data.get("insurance") else {"status": "No record"})
    with tab4:
        st.json(data["theft_scrapping"]["raw_record"] if data.get("theft_scrapping") else {"status": "No record"})

    if data.get("conflicts"):
        ui.section("Discrepancies between source databases")
        st.dataframe(pd.DataFrame(data["conflicts"]), width="stretch", hide_index=True)


def page_cleansing():
    ui.page_header("Data cleansing review",
                   "Discrepancies between the registry and the registration authority become correction proposals. "
                   "A reviewer accepts, rejects or leaves each one unresolved; every decision is evidence-checked and "
                   "written to the append-only audit log.", eyebrow="Contextual cleansing")
    target_plate = st.text_input("Plate to inspect", value=st.session_state.active_plate)
    with st.expander("Observed vehicle details (e.g. from the image)", expanded=False):
        obs1, obs2, obs3, obs4 = st.columns(4)
        observed_context = {
            "make": obs1.text_input("Observed make", key="clean_make").strip() or None,
            "model": obs2.text_input("Observed model", key="clean_model").strip() or None,
            "colour": obs3.text_input("Observed colour", key="clean_colour").strip() or None,
            "state": obs4.text_input("Observed state", key="clean_state").strip() or None,
        }

    canonical = CanonicalVehicleRecord(target_plate)
    has_context = any(observed_context.values())
    min_plate_similarity = 0.80
    min_combined_score = 0.65 if has_context else 0.80
    for s_name in ["vehicle_registry", "registration_authority"]:
        ok, records = fetch_service_records(s_name, st.session_state.service_urls[s_name])
        if ok:
            ranked = [
                rank_candidate_record(
                    target_plate,
                    record,
                    s_name,
                    record.get("id", 0),
                    observed_context,
                )
                for record in records
            ]
            matches = [
                item for item in ranked
                if item["dl_similarity"] >= min_plate_similarity
                and item["combined_score"] >= min_combined_score
            ]
            if matches:
                best = max(matches, key=lambda item: (item["combined_score"], item["dl_similarity"]))
                canonical.add_source_record(
                    s_name,
                    best["raw_record"],
                    best["dl_similarity"],
                    best["confidence"],
                )

    proposals = generate_cleansing_proposals(canonical.to_dict())
    if not proposals:
        ui.note("No attribute discrepancies between the registry and the RTO for this vehicle. "
                "Try <b>KA05MJ5555</b> (colour changed after a repaint).", tone="green")
        return
    ui.section(f"{len(proposals)} proposed correction(s)")
    urls = {**st.session_state.service_urls, "audit_log": st.session_state.audit_api_url}
    for idx, p in enumerate(proposals):
        with st.container(border=True):
            st.markdown(f"**{p['field_label']}** discrepancy · target `{p['target_source']}` record #{p['record_id']}")
            p1, p2 = st.columns(2)
            p1.metric("Current registry value", p["current_value"])
            p2.metric("Proposed value (from RTO)", p["proposed_value"])
            reason = st.text_input("Reviewer note", value=p["reason"], key=f"r_{idx}")
            b1, b2, b3, _ = st.columns([1, 1, 1, 3])
            if b1.button("Accept", key=f"a_{idx}", type="primary", width="stretch"):
                ok, msg = apply_cleansing_decision(p, "ACCEPTED", reason, urls)
                (st.success if ok else st.error)(msg)
                st.rerun()
            if b2.button("Reject", key=f"rj_{idx}", width="stretch"):
                apply_cleansing_decision(p, "REJECTED", reason, urls)
                st.rerun()
            if b3.button("Unresolved", key=f"u_{idx}", width="stretch"):
                apply_cleansing_decision(p, "UNRESOLVED", reason, urls)
                st.rerun()


def page_crud():
    ui.page_header("Records (CRUD)",
                   "Live REST access to the four vehicle databases through their flat record contract; each service "
                   "resolves the normalised FK tables behind it. The audit log is append-only.",
                   eyebrow="Data")
    if DEMO:
        ui.demo_notice("Editing records", "The public demo is read-only so every visitor sees the same data. Insert, "
                                          "update and delete work in the local installation.")

    tabs = st.tabs(["Vehicle Registry", "Insurance Records", "Registration Authority", "Theft & Scrapping"])
    configs = [
        ("vehicle_registry", tabs[0], "registration_number", "make", "model", "colour", "vehicle_type", "registration_date", "state"),
        ("insurance_records", tabs[1], "policy_number", "recorded_vehicle_number", "insurer", "policy_start_date", "expiry_date", "policy_status"),
        ("registration_authority", tabs[2], "plate_identifier", "make", "model", "colour", "registration_date", "state", "authority_reference"),
        ("theft_scrapping", tabs[3], "reported_plate", "theft_status", "report_date", "scrapping_status"),
    ]

    for s_key, tab, *fields in configs:
        with tab:
            url = st.session_state.service_urls[s_key]
            ok, records = fetch_service_records(s_key, url)
            if ok and records:
                st.dataframe(pd.DataFrame(records), width="stretch", hide_index=True)
            else:
                st.warning(f"Could not load records from {url}")
            if DEMO:
                continue

            with st.expander("Insert record"):
                with st.form(f"add_{s_key}"):
                    payload = {f: st.text_input(f, key=f"in_{s_key}_{f}") for f in fields}
                    if st.form_submit_button("Create"):
                        try:
                            resp = httpx.post(f"{url.rstrip('/')}/records", json=payload, timeout=3.0)
                            if resp.status_code == 201:
                                st.success(f"Created: {resp.json().get('id')}")
                            else:
                                st.error(resp.text)
                            st.rerun()
                        except Exception as e:
                            st.error(str(e))

            with st.expander("Update record"):
                with st.form(f"edit_{s_key}"):
                    edit_id = st.number_input("Record ID", 1, step=1, key=f"edit_id_{s_key}")
                    edit_payload = {f: st.text_input(f"New {f} (blank = keep)", key=f"edit_{s_key}_{f}") for f in fields}
                    if st.form_submit_button("Update"):
                        try:
                            filtered_updates = {k: v.strip() for k, v in edit_payload.items() if v.strip()}
                            if not filtered_updates:
                                st.warning("Enter at least one field to update.")
                            else:
                                resp = httpx.put(f"{url.rstrip('/')}/records/{edit_id}", json=filtered_updates, timeout=3.0)
                                if resp.status_code == 200:
                                    st.success(f"Updated record #{edit_id} in {s_key}")
                                else:
                                    st.error(resp.text)
                                st.rerun()
                        except Exception as e:
                            st.error(str(e))

            with st.expander("Delete record"):
                del_id = st.number_input("Record ID", 1, step=1, key=f"del_id_{s_key}")
                if st.button(f"Delete #{del_id}", key=f"btn_del_{s_key}"):
                    try:
                        resp = httpx.delete(f"{url.rstrip('/')}/records/{del_id}", timeout=3.0)
                        if resp.status_code == 200:
                            st.success(f"Deleted #{del_id}")
                        else:
                            st.error(resp.text)
                        st.rerun()
                    except Exception as e:
                        st.error(str(e))


def page_benchmark():
    ui.page_header("Matching benchmark",
                   "Precision, recall and F1 of four matching strategies on 15 labelled noisy-plate cases.",
                   eyebrow="Noisy plate matching")
    eval_results = evaluate_algorithms()
    st.dataframe(pd.DataFrame(eval_results).T, width="stretch")
    ui.info_cards([
        ("Exact matching", "50% recall: misses any OCR glyph substitution, space or hyphen."),
        ("RapidFuzz", "Robust to character permutations; strong recall and top-1 accuracy."),
        ("Damerau-Levenshtein", "Counts an adjacent transposition (AZ → ZA) as a single edit."),
        ("Combined contextual (selected)", "70% plate similarity + 30% make, model, colour, state and year agreement."),
    ])


def page_audit_log():
    ui.page_header("Cleansing audit trail",
                   "Every review decision with reviewer, session, evidence and before/after values. Append-only: "
                   "the service exposes no update or delete.", eyebrow="Contextual cleansing")
    source_filter = st.selectbox("Source", ["ALL", "vehicle_registry", "registration_authority", "insurance_records"])
    logs = get_cleansing_audit_logs(
        200,
        None if source_filter == "ALL" else source_filter,
        st.session_state.audit_api_url,
    )
    if logs:
        st.dataframe(pd.DataFrame(logs), width="stretch", hide_index=True)
    else:
        st.info("No audit entries recorded yet.")


# ============================================================================== navigation
PAGES = {
    "overview": st.Page(page_overview, title="Overview", icon=":material/space_dashboard:", url_path="overview", default=True),
    "status": st.Page(page_service_health, title="System status", icon=":material/dns:", url_path="status"),
    "query": st.Page(ui_phase3.render_federated_query, title="Federated query", icon=":material/hub:", url_path="query"),
    "fleet": st.Page(ui_phase3.render_fleet_scan, title="Fleet scan", icon=":material/leaderboard:", url_path="fleet"),
    "plate": st.Page(page_plate_input, title="Plate input & OCR", icon=":material/photo_camera:", url_path="plate"),
    "search": st.Page(page_candidate_search, title="Candidate search", icon=":material/manage_search:", url_path="search"),
    "record": st.Page(page_integrated_record, title="Integrated record", icon=":material/merge_type:", url_path="record"),
    "cleansing": st.Page(page_cleansing, title="Cleansing review", icon=":material/rule:", url_path="cleansing"),
    "audit": st.Page(page_audit_log, title="Audit trail", icon=":material/history:", url_path="audit"),
    "benchmark": st.Page(page_benchmark, title="Matching benchmark", icon=":material/analytics:", url_path="benchmark"),
    "schema": st.Page(ui_phase3.render_schema_explorer, title="Schemas & FK-PK", icon=":material/schema:", url_path="schema"),
    "documents": st.Page(ui_phase3.render_documents, title="Documents", icon=":material/description:", url_path="documents"),
    "crud": st.Page(page_crud, title="Records (CRUD)", icon=":material/table_view:", url_path="records"),
}

ui.sidebar_brand()
nav = st.navigation({
    "Start": [PAGES["overview"], PAGES["status"]],
    "Federated querying": [PAGES["query"], PAGES["fleet"]],
    "Matching & cleansing": [PAGES["plate"], PAGES["search"], PAGES["record"], PAGES["cleansing"], PAGES["audit"],
                             PAGES["benchmark"]],
    "Data": [PAGES["schema"], PAGES["documents"], PAGES["crud"]],
}, expanded=True)

with st.sidebar:
    if not DEMO:
        with st.expander("Connection settings"):
            for key, label in [
                ("vehicle_registry", "Registry (8101)"),
                ("insurance_records", "Insurance (8102)"),
                ("registration_authority", "Registration (8103)"),
                ("theft_scrapping", "Theft & Scrapping (8104)"),
            ]:
                st.session_state.service_urls[key] = st.text_input(label, st.session_state.service_urls[key])
            st.session_state.audit_api_url = st.text_input("Audit log (8105)", st.session_state.audit_api_url)
            st.session_state.gateway_url = st.text_input("Gateway", st.session_state.gateway_url)
            st.caption("Federated pages go through the gateway, which uses the URLs in its own .env.")
    st.markdown(
        "<div class='vt-footer'>All data is synthetic. Decision support only, not an official verification."
        f"<br><a href='{REPO_URL}' target='_blank'>Source code</a></div>", unsafe_allow_html=True)

nav.run()
