# VehicleTrust AI 🛡️
### Federated vehicle-record integration across independent databases

VehicleTrust AI answers questions such as *"Check the complete history of DL01AB1234"* or
*"Is this vehicle insured, stolen or scrapped?"*. The information needed lives in **five independent
databases** owned by different organisations and running on **two machines**. The system finds the
vehicle in every database even when the registration number is noisy (for example read by OCR as
`DLO1AB1234`), discovers related information through each database's own relationships, combines it,
reports where the sources disagree, and adds supporting evidence from documents.

Developed as the course project for *Information Integration* (Phase 2: noisy plate matching and data
cleansing; Phase 3: relational databases, federated query processing, unstructured data integration).

> All vehicles, people and documents in this repository are **synthetic demonstration data**.
> The system is deterministic and explainable: edit-distance matching, rules and BM25 ranking.

---

## Features

**Noisy plate matching and cleansing**
- Plate image upload → OpenCV preprocessing → EasyOCR (optional)
- Plate normalisation and OCR-confusion variants (`O/0`, `I/1`, `B/8`, `S/5`, `Z/2`, `G/6`)
- Damerau-Levenshtein + RapidFuzz similarity, contextual scoring with make / model / colour / state / year
- Canonical vehicle record, date-based insurance evaluation, conflict detection
- Cleansing proposals backed by the Registration Authority; accept / reject / unresolved with stale-check and audit trail

**Federated integration**
- Five normalised SQLite databases (5–6 tables each) with enforced foreign keys and safe, id-preserving migration
- Natural-language query understanding and decomposition to only the relevant databases
- Parallel subqueries over REST with per-call deadlines and partial results when a service is down
- Each database discovers related context through its own FK-PK relationships and returns the paths it followed
- Cross-source entity resolution, context accumulation with provenance, cross-database conflict rules
- Document repository (TXT / PDF / Markdown / HTML): extraction, metadata, chunking, BM25 index, and retrieval
  driven by the facts found in the databases, with document-vs-database evidence checks
- Streamlit dashboard showing every pipeline stage; two-machine launcher with health checks and packaging

---

## Architecture

```
                 Machine 1                                          Machine 2
 ┌──────────────────────────────────────────┐        ┌─────────────────────────────────┐
 │ Streamlit :8501 ──► Gateway :8000        │  REST  │ Vehicle Registry       :8101    │
 │   understanding · decomposition          │◄──────►│ Insurance Records      :8102    │
 │   federation · context · retrieval       │  LAN   │ Registration Authority :8103    │
 │ Theft & Scrapping :8104  Audit Log :8105 │        │ (own SQLite files)              │
 │ documents/ (document repository)         │        └─────────────────────────────────┘
 └──────────────────────────────────────────┘
```

**Query pipeline:** user query → query understanding → query decomposition → parallel federated execution →
local FK-PK context discovery → entity resolution → audit subquery → context accumulation →
structured integration and conflict detection → context-driven document retrieval → final answer with sources.

| Database | Service | Port | Tables |
|---|---|---|---|
| Vehicle Registry | `service_registry.py` | 8101 | vehicles, vehicle_models, manufacturers, vehicle_categories, vehicle_owners |
| Insurance Records | `service_insurance.py` | 8102 | insurance_policies, insurance_providers, policy_holders, coverage_details, insurance_claims |
| Registration Authority | `service_registration.py` | 8103 | rto_registrations, rto_offices, registration_certificates, ownership_transfers, registration_events |
| Theft & Scrapping | `service_theft.py` | 8104 | theft_scrapping_records, theft_reports, police_stations, investigation_details, recovery_records, scrapping_records |
| Cleansing Audit Log | `service_audit.py` | 8105 | cleansing_audit_log, reviewers, audit_sessions, audit_evidence, data_change_history |

Foreign keys connect tables **inside** each database. Databases are linked to each other only through shared
identifiers (registration number, record ids, policy / FIR / RC numbers) over HTTP — never by opening another
machine's database file.

---

## Technology

Python · FastAPI · Uvicorn · SQLAlchemy 2 · SQLite · httpx (async) · RapidFuzz · pypdf · Streamlit · pandas ·
OpenCV · EasyOCR (optional) · pytest

---

## Quick start (one machine, all five databases)

```powershell
python -m pip install -r requirements.txt
python -m pip install -r requirements-ocr.txt      # optional: plate-image OCR (installs PyTorch)
python start_node.py all
```

- Dashboard: **http://127.0.0.1:8501** → *0. Federated Query*
- Gateway web UI: http://127.0.0.1:8000 · API docs: http://127.0.0.1:8000/docs

Databases are created and seeded automatically on first start (non-destructive afterwards).
`python start_node.py init all --reset` recreates them from the seed data after taking a backup.

## Two machines

```powershell
# Machine 2
python start_node.py init machine-2
python start_node.py machine-2

# Machine 1
python start_node.py configure machine-1 --machine2-ip <MACHINE2_IP>
python start_node.py check
python start_node.py machine-1
```

`python start_node.py package machine-2` creates a clean copy of the project for the second machine.
Firewall rules, troubleshooting and the optional dashboard on machine 2 are described in
[`docs/DISTRIBUTED_SETUP.md`](docs/DISTRIBUTED_SETUP.md).

## Example queries

| Query | What it shows |
|---|---|
| `Check the complete history of vehicle DL01AB1234.` | all five databases, FK context, documents |
| `Find vehicles with registration numbers similar to DLO1AB1234` | noisy plate resolved to DL01AB1234 |
| `Find the ownership history and insurance details for UP16BT9900` | registry owner vs RTO transfer conflict |
| `Is this vehicle insured, stolen or scrapped? GJ 01 AB 7777` | theft report, policy renewed after theft |
| `Is WB02K0001 scrapped?` | scrapped vehicle whose RC is still valid |
| `Show the full history and audit trail of KA05MJ5555` | colour conflict, RTO explanation, cleansing proposal |

## Tests

```powershell
python -m pytest -q
```

122 tests: matching and cleansing regression, schemas / FK enforcement / migration, federation (parallelism,
timeouts, outages, conflicts), document retrieval, launcher, and a real-process simulation of the two-machine split.

---

## Project structure

```
config.py              topology, ports, URLs, database paths (reads .env)
start_node.py          launcher: machine-1 | machine-2 | all | frontend | init | check | configure | package
run_all.py             shortcut for 'start_node.py all'
databases/             the five database modules (models, migration, FK expansion) + service factory
service_*.py           the five FastAPI database services
gateway.py             API gateway + HTML web UI (frontend/index.html)
query_engine.py        query understanding and decomposition
federation.py          federated execution, entity resolution, context accumulation, integration, answer
retrieval.py           document processing, BM25 index, context-driven retrieval
matching.py            plate normalisation, OCR variants, Damerau-Levenshtein, contextual scoring, benchmark
integration.py         canonical record, insurance rules, cleansing proposals and decisions
seed_data.py           synthetic data for all five databases
app.py, ui_phase3.py   Streamlit dashboard
documents/             synthetic document repository + generate_documents.py
docs/                  DISTRIBUTED_SETUP.md, MATCHING_JUSTIFICATION.md, CODE_MODIFICATIONS.md
tests/                 pytest suite
```

## Known limitations

- Query understanding uses keyword rules; unusual wording falls back to a general status check.
- Fuzzy matching scans each database's vehicle table — suitable for the demonstration dataset, not for millions of rows.
- Document retrieval is lexical (BM25); scanned image-only PDFs are not OCR'd.
- Services trust the local network (no authentication between services).
