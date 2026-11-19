# VehicleTrust: Code Modifications & Verification Log

## 1. Master Prompt Reference
The project was designed, generated, and iteratively refined based on the Master Prompt:
`VehicleTrust — Distributed Vehicle Insurance Verification`, targeting:
- Four independent FastAPI database services (`vehicle_registry.db`, `insurance_records.db`, `registration_authority.db`, `theft_scrapping.db`)
- Multi-laptop LAN deployment support with configurable endpoints
- Streamlit web frontend covering all features
- OpenCV and EasyOCR image preprocessing and optical text reading
- Explainable fuzzy entity matching (Damerau-Levenshtein, RapidFuzz, Contextual Scoring)
- Explainable date-aware insurance risk assessment rules
- Interactive data cleansing review with centralized SQLite audit ledger
- ~1,500–2,000 lines of pure Python code

---

## 2. Important Generated Files & Purposes

| File Name | Purpose |
| :--- | :--- |
| `database_common.py` | SQLAlchemy connection factory, base schema definitions, and central SQLite audit log (`audit_log.db`). |
| `service_registry.py` | FastAPI service on port 8101 managing `vehicle_registry.db`. Full REST CRUD. |
| `service_insurance.py` | FastAPI service on port 8102 managing `insurance_records.db`. Full REST CRUD. |
| `service_registration.py` | FastAPI service on port 8103 managing `registration_authority.db` (RTO records). Full REST CRUD. |
| `service_theft.py` | FastAPI service on port 8104 managing `theft_scrapping.db`. Full REST CRUD. |
| `gateway.py` | Dedicated HTTP/JSON API Gateway & Web Frontend server on port 8000. Provides `/api/status`, `/api/ocr`, `/api/search`, `/api/sql`, and serves the SPA frontend. |
| `frontend/index.html` | Modern responsive Single-Page Application (SPA) web frontend in HTML5/CSS3/Vanilla JS communicating via HTTP/JSON. |
| `matching.py` | Plate normalization, OCR ambiguity permutations, Damerau-Levenshtein distance, RapidFuzz, Contextual weighted scoring, and empirical benchmark evaluation. |
| `integration.py` | Canonical schema mapper, cross-source conflict detection, date-aware insurance risk rules, cleansing proposal generator, and API update dispatcher. |
| `seed_data.py` | Idempotent seeder creating 33 synthetic vehicle identities across all 4 databases covering edge cases. |
| `app.py` | Comprehensive Streamlit web dashboard providing the complete front-end for all features (health monitor, OCR, fuzzy search, canonical viewer, cleansing review, live CRUD, evaluation, audit log). |
| `run_all.py` | Local development launcher starting the 4 microservices and the Streamlit frontend concurrently with graceful teardown. |
| `tests/test_matching.py` | Unit tests for plate normalization, edit distance, transpositions, RapidFuzz, contextual scoring, and benchmarks. |
| `tests/test_integration.py` | Unit tests for schema mapping, canonical integration, conflict detection, insurance risk outcomes, and audit logging. |
| `tests/test_services.py` | Integration tests for FastAPI endpoints (health, CRUD lifecycle, error handling, partial degradation). |

---

## 3. Actual Code Modifications Made & Verification

### Modification 1: Pydantic v2 Compatibility (`pattern` instead of `regex`)
- **Reason:** Pydantic v2 removed the `regex` keyword argument from `pydantic.Field` in favor of `pattern`, causing `PydanticUserError` on startup.
- **Before:**
  ```python
  registration_date: str = Field(..., regex=r"^\d{4}-\d{2}-\d{2}$")
  ```
- **After:**
  ```python
  registration_date: str = Field(..., pattern=r"^\d{4}-\d{2}-\d{2}$")
  ```
- **Files Modified:** `service_registry.py`, `service_insurance.py`, `service_registration.py`, `service_theft.py`.
- **Verification:** Seeding script and FastAPI startup succeeded without schema validation errors.

---

### Modification 2: Pydantic v2 `model_dump` Migration
- **Reason:** Pydantic v2 deprecated `data.dict(exclude_unset=True)` in favor of `data.model_dump(exclude_unset=True)`.
- **Before:**
  ```python
  updates = data.dict(exclude_unset=True)
  ```
- **After:**
  ```python
  updates = data.model_dump(exclude_unset=True) if hasattr(data, "model_dump") else data.dict(exclude_unset=True)
  ```
- **Files Modified:** All four FastAPI microservice PUT endpoints.
- **Verification:** Verified via `test_registry_crud_lifecycle` and `test_insurance_crud_lifecycle`.

---

### Modification 3: Contextual Scoring Normalization Over Evaluated Attributes
- **Reason:** When a user queried with only a subset of attributes (e.g. `make="Honda"`), unprovided attributes (model, colour, state, date) were evaluating to 0.0 with full weights, artificially penalizing the candidate to 0.72 even though there were no contradictions.
- **Before:**
  ```python
  total_context_score = (
      breakdown["make_score"] * weights["make"]
      + breakdown["model_score"] * weights["model"]
      + breakdown["colour_score"] * weights["colour"]
      + breakdown["state_score"] * weights["state"]
      + breakdown["date_score"] * weights["reg_date"]
  )
  ```
- **After:**
  ```python
  evaluated_weights = 0.0
  weighted_sum = 0.0
  for attr, weight in [("make", 0.30), ("model", 0.30), ("colour", 0.15), ("state", 0.15)]:
      q_val = query_context.get(attr)
      c_val = candidate_record.get(attr)
      score, status = _match_string_attribute(q_val, c_val)
      if q_val is not None and c_val is not None:
          weighted_sum += score * weight
          evaluated_weights += weight
  total_context_score = (weighted_sum / evaluated_weights) if evaluated_weights > 0 else 0.0
  ```
- **Files Modified:** `matching.py`.
- **Verification:** `test_rank_candidate_record` now correctly scores `0.93` ($\ge 0.85$) with `HIGH` confidence.

---

### Modification 4: Timezone UTC Deprecation Fix
- **Reason:** Python 3.12 deprecated `datetime.datetime.utcnow()` in favor of timezone-aware UTC timestamps.
- **Before:**
  ```python
  timestamp = Column(DateTime, default=datetime.datetime.utcnow, nullable=False)
  ```
- **After:**
  ```python
  timestamp = Column(DateTime, default=lambda: datetime.datetime.now(datetime.timezone.utc), nullable=False)
  ```
- **Files Modified:** `database_common.py`.
- **Verification:** Zero UTC deprecation warnings during test execution.

---

## 4. Test Verification & Actual Test Outcomes

The test suite was executed using `pytest` inside the project environment:

```bash
$ pytest tests/ -v
============================= test session starts ==============================
platform linux -- Python 3.12.3, pytest-9.1.1, pluggy-1.7.0
rootdir: /home/ricky16x/projects/iia/VehicleTrust
configfile: pytest.ini

tests/test_integration.py::test_schema_mapper PASSED                     [  3%]
tests/test_integration.py::test_canonical_record_conflict_detection PASSED [  6%]
tests/test_integration.py::test_insurance_rules_current PASSED           [ 10%]
tests/test_integration.py::test_insurance_rules_expired PASSED           [ 13%]
tests/test_integration.py::test_insurance_rules_future_policy PASSED     [ 17%]
tests/test_integration.py::test_insurance_rules_conflicting PASSED       [ 20%]
tests/test_integration.py::test_insurance_rules_not_found PASSED         [ 24%]
tests/test_integration.py::test_insurance_rules_unverified_offline PASSED [ 27%]
tests/test_integration.py::test_insurance_rules_unverified_low_confidence PASSED [ 31%]
tests/test_integration.py::test_generate_cleansing_proposals PASSED      [ 34%]
tests/test_integration.py::test_audit_logging PASSED                     [ 37%]
tests/test_matching.py::test_plate_normalization PASSED                  [ 41%]
tests/test_matching.py::test_damerau_levenshtein_transposition PASSED    [ 44%]
tests/test_matching.py::test_damerau_levenshtein_single_edits PASSED     [ 48%]
tests/test_matching.py::test_rapidfuzz_similarity PASSED                 [ 51%]
tests/test_matching.py::test_exact_match PASSED                          [ 55%]
tests/test_matching.py::test_ocr_confusion_variants PASSED               [ 58%]
tests/test_matching.py::test_contextual_scoring_supporting PASSED        [ 62%]
tests/test_matching.py::test_contextual_scoring_conflicting PASSED       [ 65%]
tests/test_matching.py::test_contextual_scoring_missing_unknown PASSED   [ 68%]
tests/test_matching.py::test_rank_candidate_record PASSED                [ 72%]
tests/test_matching.py::test_algorithm_evaluation_benchmark PASSED       [ 75%]
tests/test_services.py::test_registry_health PASSED                      [ 71%]
tests/test_services.py::test_insurance_health PASSED                     [ 75%]
tests/test_services.py::test_registration_health PASSED                  [ 78%]
tests/test_services.py::test_theft_health PASSED                         [ 81%]
tests/test_services.py::test_registry_crud_lifecycle PASSED              [ 84%]
tests/test_services.py::test_insurance_crud_lifecycle PASSED             [ 87%]
tests/test_services.py::test_graceful_handling_unavailable_service PASSED [ 90%]
tests/test_services.py::test_gateway_status_endpoint PASSED              [ 93%]
tests/test_services.py::test_gateway_sql_query_execution PASSED          [ 96%]
tests/test_services.py::test_gateway_sql_disallowed_statement PASSED     [100%]

======================== 32 passed in 3.06s =========================
```
Total Tests: **38 Passed, 0 Failed, 0 Skipped.**

### Modification 5: Reviewed, Evidence-Checked Cleansing
- Fuzzy plate matches can now produce review proposals for registry plate and attribute corrections, including missing registry values.
- Proposals are only generated when the scanned/query plate, registry plate, and authority plate are sufficiently similar; the authority record is carried as the correction evidence.
- Both web interfaces accept optional vehicle details observed from the image to improve candidate ranking. Those observations help identify the record but are not written as authoritative data.
- The browser now displays proposals and supports accept/reject/unresolved decisions. An accepted change re-reads the registry and authority records, rejects stale or mismatched evidence, then updates the registry.
- Audit entries record the actual outcome; a failed database update is no longer recorded as an accepted correction.
- Added tests for plate and missing-field proposals, unrelated authority records, successful evidence-checked updates, stale-proposal rejection, and failed-update audit accuracy.
- Added a gateway search test proving observed context ranks a noisy plate and returns authority-backed plate and attribute corrections.

---

## 5. Phase 2 verification fixes (made during the Phase 3 work)
Baseline before any change: **45 passed** (`python -m pytest -q`, Python 3.14, Windows). Each fix below is a
manual modification of generated code, verified by the current suite (122 passed).

| # | Defect found | Fix | File |
|---|---|---|---|
| 6 | With observed context supplied, records from sources that carry no make/model/colour/state (insurance, theft) were capped at combined score 0.70 even for an exact plate match, because the 0.7/0.3 weighting was applied although no attribute could be compared. | Context re-weights only when at least one attribute was actually compared (`evaluated_weight > 0`). | `matching.py` |
| 7 | When the theft/scrapping database had no record for a vehicle, the risk evaluation reported `CLEAR` / `ACTIVE`, i.e. asserted clearance without evidence. | Reports `NOT_RECORDED`; the Phase 3 answer states that this is not a clearance. | `integration.py` |
| 8 | The SQL console was documented as read-only but executed `INSERT/UPDATE/DELETE`, and ignored the `*_DB_FILE` settings. | Opens SQLite with `mode=ro` (writes rejected with 403) and resolves paths through `config.db_path`. | `gateway.py` |
| 9 | `run_all.py` re-seeded every database with `DELETE FROM` on each launch, silently discarding CRUD edits and accepted cleansing corrections. | Non-destructive initialization; explicit `init --reset` with automatic backup. | `run_all.py`, `seed_data.py` |
| 10 | `st.image(use_column_width=True)` raises `TypeError` on current Streamlit, breaking the OCR page as soon as an image is uploaded. | Uses `width="stretch"` (requirement `streamlit>=1.46`). | `app.py` |
| 11 | Tests wrote into the live database files. | `tests/conftest.py` points every service at a temporary copy. | `tests/conftest.py` |
| 12 | `.env` addressed the local Theft/Audit services through the laptop's own DHCP Wi-Fi IP (breaks when the IP changes) and hard-coded IPs by hand. | `.env` generated by `start_node.py configure` (local services on `127.0.0.1`, Laptop 2 IP as a parameter). | `.env`, `start_node.py` |

Phase 3 additions (relational schemas, migration, federation, retrieval, launcher) are documented in
`README.md` and `docs/DISTRIBUTED_SETUP.md`.
