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
    damerau_levenshtein_distance,
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

st.set_page_config(page_title="VehicleTrust AI — Insurance Verification", page_icon="🛡️", layout="wide")

DEFAULT_URLS = {key: config.service_url(key) for key in config.DATA_SERVICE_KEYS}
DEFAULT_AUDIT_URL = config.service_url("audit_log")

if "service_urls" not in st.session_state:
    st.session_state.service_urls = DEFAULT_URLS.copy()
if "audit_api_url" not in st.session_state:
    st.session_state.audit_api_url = DEFAULT_AUDIT_URL
if "active_plate" not in st.session_state:
    st.session_state.active_plate = "DL01AB1234"


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


st.sidebar.title("🛡️ VehicleTrust AI")
st.sidebar.caption("Distributed Vehicle Insurance Verification System")
st.sidebar.markdown("---")

section = st.sidebar.radio(
    "Navigation",
    [
        "0. Federated Query (Phase 3)",
        "1. Service Health & Network",
        "2. Plate Upload & OCR",
        "3. Fuzzy Candidate Search",
        "4. Integrated Canonical Record",
        "5. Data Cleansing Review",
        "6. Database Explorer & CRUD",
        "7. Algorithm Evaluation",
        "8. Cleansing Audit Log",
        "9. Database Schemas & FK-PK (Phase 3)",
        "10. Document Repository (Phase 3)",
    ],
)

st.sidebar.markdown("---")
st.sidebar.subheader("🌐 Laptop Node Endpoints")
for key, label in [
    ("vehicle_registry", "1. Registry (8101)"),
    ("insurance_records", "2. Insurance (8102)"),
    ("registration_authority", "3. Reg Authority (8103)"),
    ("theft_scrapping", "4. Theft/Scrapping (8104)"),
]:
    st.session_state.service_urls[key] = st.sidebar.text_input(label, st.session_state.service_urls[key])
st.session_state.audit_api_url = st.sidebar.text_input(
    "5. Audit Ledger (8105)",
    st.session_state.audit_api_url,
)
st.session_state.gateway_url = st.sidebar.text_input("Gateway (Phase 3 pages)", config.gateway_url())
st.sidebar.caption("Phase 3 pages go through the gateway, which uses the URLs in its own .env.")

if section == "0. Federated Query (Phase 3)":
    ui_phase3.render_federated_query()
elif section == "9. Database Schemas & FK-PK (Phase 3)":
    ui_phase3.render_schema_explorer()
elif section == "10. Document Repository (Phase 3)":
    ui_phase3.render_documents()


# ==============================================================================
# SECTION 1: DASHBOARD & SERVICE HEALTH
# ==============================================================================
elif section == "1. Service Health & Network":
    st.header("🖥️ Distributed Database Services & Node Monitor")
    st.markdown("Coordinates five independent SQLite databases (4-6 FK-linked tables each), split 2+3 across two laptops.")

    cols = st.columns(5)
    services_meta = [
        ("Vehicle Registry", "vehicle_registry", "Port 8101", cols[0]),
        ("Insurance Records", "insurance_records", "Port 8102", cols[1]),
        ("Registration Authority", "registration_authority", "Port 8103", cols[2]),
        ("Theft & Scrapping", "theft_scrapping", "Port 8104", cols[3]),
        ("Cleansing Audit Ledger", "audit_log", "Port 8105", cols[4]),
    ]
    all_online = True
    for name, key, port_info, col in services_meta:
        url = st.session_state.audit_api_url if key == "audit_log" else st.session_state.service_urls[key]
        is_up, latency, count, data = check_service_health(key, url)
        if not is_up:
            all_online = False
        with col:
            st.subheader(name)
            st.caption(f"{port_info} | `{url}`")
            if is_up:
                st.success(f"🟢 ONLINE ({latency} ms)")
                st.metric("Total Records", count)
            else:
                st.error("🔴 OFFLINE / UNREACHABLE")
                st.caption(data.get("error", "Refused"))

    st.markdown("---")
    if all_online:
        st.success("✅ All 5 distributed database services are active and communicating normally.")
    else:
        st.warning("⚠️ One or more database nodes are offline. Showing partial results (graceful degradation).")

    with st.expander("📡 Two-Laptop Deployment (2+3 split)", expanded=False):
        st.markdown(
            "- **Laptop 2:** `python start_node.py machine-2` → Registry 8101, Insurance 8102, Registration 8103\n"
            "- **Laptop 1:** `python start_node.py configure machine-1 --machine2-ip <LAPTOP2_IP>` then "
            "`python start_node.py machine-1` → Theft 8104, Audit 8105, Gateway 8000, Streamlit 8501\n"
            "- Verify from Laptop 1: `python start_node.py check`\n"
            "- Details: `docs/DISTRIBUTED_SETUP.md`"
        )


# ==============================================================================
# SECTION 2: PLATE UPLOAD & OCR
# ==============================================================================
elif section == "2. Plate Upload & OCR":
    st.header("📷 Indian Registration Plate Image Upload & OCR")
    st.markdown("Preprocesses plate images with OpenCV (Grayscale, Resize, Gaussian Blur, Otsu Threshold) before EasyOCR text reading.")

    col1, col2 = st.columns([1, 1])
    with col1:
        uploaded_file = st.file_uploader("Upload Plate Image", type=["jpg", "jpeg", "png"])
        manual_override = st.text_input("Or Enter Plate Manually", value=st.session_state.active_plate)
        if st.button("Use Manual Plate for Search"):
            st.session_state.active_plate = normalize_plate(manual_override)
            st.success(f"Active plate updated to: {st.session_state.active_plate}")

    with col2:
        if uploaded_file is not None:
            import cv2
            file_bytes = np.asarray(bytearray(uploaded_file.read()), dtype=np.uint8)
            img = cv2.imdecode(file_bytes, cv2.IMREAD_COLOR)
            st.image(cv2.cvtColor(img, cv2.COLOR_BGR2RGB), caption="Uploaded Plate Image", width="stretch")

            gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
            resized = cv2.resize(gray, None, fx=2.0, fy=2.0, interpolation=cv2.INTER_CUBIC)
            blurred = cv2.GaussianBlur(resized, (5, 5), 0)
            _, thresh = cv2.threshold(blurred, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)

            with st.expander("🔬 OpenCV Preprocessing Pipeline", expanded=False):
                p1, p2, p3 = st.columns(3)
                p1.image(gray, caption="1. Grayscale")
                p2.image(blurred, caption="2. Gaussian Blur")
                p3.image(thresh, caption="3. Otsu Threshold")

            reader = get_ocr_reader()
            if reader is None:
                st.warning("EasyOCR is unavailable. Use manual plate entry.")
            else:
                with st.spinner("Extracting text with EasyOCR..."):
                    results = reader.readtext(thresh)
                    if results:
                        raw_combined = " ".join([r[1] for r in results])
                        avg_conf = float(np.mean([r[2] for r in results]))
                        norm = normalize_plate(raw_combined)
                        st.session_state.active_plate = norm
                        st.success(f"Recognized Plate: **{norm}**")
                        st.info(f"Raw Output: `{raw_combined}` | Confidence: `{avg_conf * 100:.1f}%`")
                    else:
                        st.warning("No readable plate text found. Please enter manually.")

    st.markdown("---")
    st.subheader("💡 OCR Confusion Alternatives")
    variants = generate_ocr_confusion_variants(st.session_state.active_plate)
    st.write([f"`{v}`" for v in variants])


# ==============================================================================
# SECTION 3: FUZZY CANDIDATE SEARCH
# ==============================================================================
elif section == "3. Fuzzy Candidate Search":
    st.header("🔍 Fuzzy Entity Candidate Search & Ranking")
    scol1, scol2, scol3 = st.columns([2, 1, 1])
    with scol1:
        search_query = st.text_input("Registration Plate Query", value=st.session_state.active_plate)
    with scol2:
        threshold = st.slider("Similarity Threshold", 0.20, 0.95, 0.50, 0.05)
    with scol3:
        st.write("")
        st.write("")
        search_btn = st.button("🚀 Search Databases", width="stretch")

    with st.expander("🎯 Contextual Clues (Make, Model, Colour, State)", expanded=False):
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
        st.warning(f"⚠️ Services offline: {', '.join(offline_services)}. Showing partial results.")

    candidates = search_and_rank_candidates(search_query, all_source_records, query_context, threshold)
    st.subheader(f"Candidates Found: {len(candidates)}")

    if candidates:
        rows = []
        for idx, c in enumerate(candidates):
            badge = "🟢 HIGH" if c["confidence"] == "HIGH" else "🟡 MEDIUM" if c["confidence"] == "MEDIUM" else "🔴 LOW"
            rows.append({
                "Rank": idx + 1, "Plate": c["recorded_registration_number"], "Source": c["source_database"],
                "ID": c["record_id"], "Score": f"{c['combined_score']:.3f}", "Conf": badge,
                "Distance": c["edit_distance"], "RapidFuzz": f"{c['plate_similarity']:.2f}",
                "DL": f"{c['dl_similarity']:.2f}", "Context": f"{c['contextual_score']:.2f}",
                "Method": c["matching_method"], "Supporting": ", ".join(c["supporting_attributes"]) or "-",
                "Conflicting": ", ".join(c["conflicting_attributes"]) or "-",
            })
        st.dataframe(pd.DataFrame(rows), width="stretch")

        selected_plate = st.selectbox("Select Candidate to Inspect:", [c["recorded_registration_number"] for c in candidates])
        if st.button("Open in Integrated Record"):
            st.session_state.active_plate = selected_plate
            st.success(f"Selected {selected_plate}! Switch to '4. Integrated Canonical Record'.")


# ==============================================================================
# SECTION 4: INTEGRATED CANONICAL RECORD
# ==============================================================================
elif section == "4. Integrated Canonical Record":
    st.header("📋 Integrated Canonical Vehicle Record")
    target_plate = st.text_input("Active Vehicle Plate", value=st.session_state.active_plate)

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

    status_display = {
        "CURRENT": (st.success, "🛡️"), "EXPIRED": (st.error, "⚠️"), "NOT_FOUND": (st.error, "❌"),
        "CONFLICTING": (st.warning, "⚠️"), "FUTURE_POLICY": (st.info, "ℹ️"), "UNVERIFIED": (st.warning, "❓")
    }
    fn, icon = status_display.get(risk["status"], (st.warning, "❓"))
    fn(f"### {icon} INSURANCE STATUS: {risk['status_label']}")

    rc1, rc2 = st.columns([2, 1])
    with rc1:
        st.markdown(f"**Action Required:** {risk['recommended_action']}")
        st.caption(f"Disclaimer: {risk['disclaimer']}")
    with rc2:
        t_stat, s_stat = risk["theft_status"], risk["scrapping_status"]
        st.markdown(f"**Theft Status:** `{'🔴 ' + t_stat if t_stat == 'STOLEN' else '🟢 ' + t_stat}`")
        st.markdown(f"**Scrapping Status:** `{'🔴 ' + s_stat if s_stat == 'SCRAPPED' else '🟢 ' + s_stat}`")

    st.markdown("---")
    tab1, tab2, tab3, tab4 = st.tabs(["1. Vehicle Registry", "2. Registration Authority", "3. Insurance Policies", "4. Theft & Scrapping"])
    with tab1:
        st.json(data["registry"]["raw_record"] if data.get("registry") else {"status": "No record"})
    with tab2:
        st.json(data["authority"]["raw_record"] if data.get("authority") else {"status": "No record"})
    with tab3:
        st.json([p["raw_record"] for p in data["insurance"]] if data.get("insurance") else {"status": "No record"})
    with tab4:
        st.json(data["theft_scrapping"]["raw_record"] if data.get("theft_scrapping") else {"status": "No record"})

    if data.get("conflicts"):
        st.warning("⚠️ Discrepancies detected between source databases!")
        st.table(pd.DataFrame(data["conflicts"]))


# ==============================================================================
# SECTION 5: DATA CLEANSING REVIEW
# ==============================================================================
elif section == "5. Data Cleansing Review":
    st.header("⚖️ Data Cleansing & Discrepancy Resolution")
    st.markdown("Use the scanned/entered plate and observed vehicle details to find likely records. Review proposed corrections against the registration authority before applying them.")

    target_plate = st.text_input("Inspect Plate for Cleansing", value=st.session_state.active_plate)
    with st.expander("Observed Vehicle Details (from image)", expanded=False):
        obs1, obs2, obs3, obs4 = st.columns(4)
        observed_context = {
            "make": obs1.text_input("Observed Make", key="clean_make").strip() or None,
            "model": obs2.text_input("Observed Model", key="clean_model").strip() or None,
            "colour": obs3.text_input("Observed Colour", key="clean_colour").strip() or None,
            "state": obs4.text_input("Observed State", key="clean_state").strip() or None,
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
        st.success("✅ No attribute discrepancies detected for this vehicle.")
    else:
        st.info(f"Found {len(proposals)} proposed cleansing actions.")
        for idx, p in enumerate(proposals):
            st.markdown(f"#### Proposal #{idx + 1}: `{p['field_label']}` Discrepancy")
            p1, p2, p3 = st.columns(3)
            p1.metric("Current Registry Value", p["current_value"])
            p2.metric("Proposed Value (from RTO)", p["proposed_value"])
            p3.write(f"Target: `{p['target_source']}` (ID #{p['record_id']})")

            reason = st.text_input(f"Reviewer Note #{idx + 1}", value=p["reason"], key=f"r_{idx}")
            b1, b2, b3, _ = st.columns([1, 1, 1, 3])
            with b1:
                if st.button("✅ Accept", key=f"a_{idx}"):
                    ok, msg = apply_cleansing_decision(
                        p,
                        "ACCEPTED",
                        reason,
                        {**st.session_state.service_urls, "audit_log": st.session_state.audit_api_url},
                    )
                    if ok:
                        st.success(msg)
                    else:
                        st.error(msg)
                    st.rerun()
            with b2:
                if st.button("❌ Reject", key=f"rj_{idx}"):
                    apply_cleansing_decision(
                        p,
                        "REJECTED",
                        reason,
                        {**st.session_state.service_urls, "audit_log": st.session_state.audit_api_url},
                    )
                    st.warning("Rejected.")
                    st.rerun()
            with b3:
                if st.button("❓ Unresolved", key=f"u_{idx}"):
                    apply_cleansing_decision(
                        p,
                        "UNRESOLVED",
                        reason,
                        {**st.session_state.service_urls, "audit_log": st.session_state.audit_api_url},
                    )
                    st.info("Marked unresolved.")
                    st.rerun()
            st.markdown("---")


# ==============================================================================
# SECTION 6: DATABASE EXPLORER & CRUD
# ==============================================================================
elif section == "6. Database Explorer & CRUD":
    st.header("🗄️ Database Explorer & Live CRUD Management")
    st.markdown("Live REST CRUD on the four vehicle databases (flat Phase 2 view; the services resolve the normalized FK tables). The audit ledger is append-only.")

    tabs = st.tabs(["1. Vehicle Registry", "2. Insurance Records", "3. Reg Authority", "4. Theft & Scrapping"])
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
                st.dataframe(pd.DataFrame(records), width="stretch")
            else:
                st.warning(f"Could not load records from {url}")

            with st.expander(f"➕ Insert Record into {s_key}"):
                with st.form(f"add_{s_key}"):
                    payload = {f: st.text_input(f, key=f"in_{s_key}_{f}") for f in fields}
                    if st.form_submit_button("Submit to API"):
                        try:
                            resp = httpx.post(f"{url.rstrip('/')}/records", json=payload, timeout=3.0)
                            if resp.status_code == 201:
                                st.success(f"Created: {resp.json().get('id')}")
                            else:
                                st.error(resp.text)
                            st.rerun()
                        except Exception as e:
                            st.error(str(e))

            with st.expander(f"✏️ Modify / Update Record in {s_key}"):
                with st.form(f"edit_{s_key}"):
                    edit_id = st.number_input("Record ID to Update", 1, step=1, key=f"edit_id_{s_key}")
                    edit_payload = {f: st.text_input(f"New {f} (leave blank to keep current)", key=f"edit_{s_key}_{f}") for f in fields}
                    if st.form_submit_button("Submit Update to API"):
                        try:
                            filtered_updates = {k: v.strip() for k, v in edit_payload.items() if v.strip()}
                            if not filtered_updates:
                                st.warning("Please enter at least one field to update.")
                            else:
                                resp = httpx.put(f"{url.rstrip('/')}/records/{edit_id}", json=filtered_updates, timeout=3.0)
                                if resp.status_code == 200:
                                    st.success(f"Updated record #{edit_id} in {s_key}")
                                else:
                                    st.error(resp.text)
                                st.rerun()
                        except Exception as e:
                            st.error(str(e))

            with st.expander(f"🗑️ Delete Record from {s_key}"):
                del_id = st.number_input("Record ID to Delete", 1, step=1, key=f"del_id_{s_key}")
                if st.button(f"Confirm Delete #{del_id}", key=f"btn_del_{s_key}"):
                    try:
                        resp = httpx.delete(f"{url.rstrip('/')}/records/{del_id}", timeout=3.0)
                        if resp.status_code == 200:
                            st.success(f"Deleted #{del_id}")
                        else:
                            st.error(resp.text)
                        st.rerun()
                    except Exception as e:
                        st.error(str(e))


# ==============================================================================
# SECTION 7: ALGORITHM EVALUATION
# ==============================================================================
elif section == "7. Algorithm Evaluation":
    st.header("📊 Matching Algorithm Empirical Benchmark")
    eval_results = evaluate_algorithms()
    st.dataframe(pd.DataFrame(eval_results).T, width="stretch")
    st.markdown(
        """
        - **Exact Matching:** 50.0% Recall (misses any OCR glyph substitution, space, or hyphen).
        - **RapidFuzz:** 91.67% Recall and 100% Top-1 Accuracy across character permutations.
        - **Damerau-Levenshtein:** Detects adjacent character transpositions (`AZ` -> `ZA`) with edit cost 1.
        - **Combined Contextual (Selected):** Combines normalized plate similarity (70%) with Make, Model, Colour, State, Year signals (30%).
        """
    )


# ==============================================================================
# SECTION 8: CLEANSING AUDIT LOG
# ==============================================================================
elif section == "8. Cleansing Audit Log":
    st.header("📜 Cleansing Audit Trail & Review Decisions")
    source_filter = st.selectbox("Filter Source", ["ALL", "vehicle_registry", "registration_authority", "insurance_records"])
    logs = get_cleansing_audit_logs(
        200,
        None if source_filter == "ALL" else source_filter,
        st.session_state.audit_api_url,
    )
    if logs:
        st.dataframe(pd.DataFrame(logs), width="stretch")
    else:
        st.info("No audit logs recorded yet.")
