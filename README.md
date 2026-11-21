# VehicleTrust 🛡️
### Federated vehicle-record integration across independent databases

VehicleTrust answers questions such as *"Check the complete history of DL01AB1234"* or
*"Is this vehicle insured, stolen or scrapped?"*. The information needed lives in **five independent
databases** owned by different organisations and running on **two machines**. The system finds the
vehicle in every database even when the registration number is noisy (for example read by OCR as
`DLO1AB1234`), discovers related information through each database's own relationships, combines it,
reports where the sources disagree, and adds supporting evidence from documents.

Developed as the course project for *Information Integration* (Phase 2: noisy plate matching and data
cleansing; Phase 3: relational databases, federated query processing, unstructured data integration).

> All vehicles, people and documents in this repository are **synthetic demonstration data**.
> Query understanding can optionally use a local LLM (Ollama); everything after it — decomposition, federation,
> matching, integration and retrieval — is deterministic and explainable.

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

**Highlights**
- **LLM query understanding (local, optional):** a model served by Ollama reads free-form questions such as
  *"my friend is selling me UP 16 BT 9900 — is he really the registered owner and is it still covered?"* and
  returns the plate, intents and attributes as schema-validated JSON. The output is grounded (a plate or
  attribute not present in the question is rejected) and the rule-based parser takes over automatically if
  Ollama is off, slow or returns invalid output.
- **Vehicle Trust Score (0–100):** one explainable score per query built from theft / scrapping status, insurance
  outcome, RC status, cross-database conflicts, missing data and match confidence. Every deduction lists its reason
  and source record, and checks that were not performed are reported, never assumed clean.
- **Fleet Data-Quality Scan:** one click federates the complete-history query over every registered vehicle and
  ranks the whole fleet by trust score, with conflict types, insurance / theft / scrapping status and service
  availability (33 vehicles across five databases in a few seconds).

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
Ollama + llama3.2 (optional) · OpenCV · EasyOCR (optional) · pytest

---

## Quick start (one machine, all five databases)

```powershell
python -m pip install -r requirements.txt
python -m pip install -r requirements-ocr.txt      # optional: plate-image OCR (installs PyTorch)
python start_node.py all
```

- Dashboard: **http://127.0.0.1:8501** → *Overview*, then *Federated query*
- Gateway web UI: http://127.0.0.1:8000 · API docs: http://127.0.0.1:8000/docs

Databases are created and seeded automatically on first start (non-destructive afterwards).

**Optional local LLM** (machine running the gateway): install Ollama from https://ollama.com, then
```powershell
ollama pull llama3.2
python start_node.py check      # shows "LLM (Ollama) llama3.2 ready"
```
Settings in `.env`: `LLM_UNDERSTANDING=auto|on|off`, `OLLAMA_URL`, `OLLAMA_MODEL`, `LLM_TIMEOUT`. Without Ollama
the rule-based parser is used and everything else works the same.
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

## Hosted demo

The online demo runs on **Streamlit Community Cloud** from this repository with main file `streamlit_app.py`. That
file starts the five database services and the gateway as separate background processes on localhost; they still
talk only over HTTP. It then renders the normal dashboard. Demo mode turns off plate OCR (EasyOCR/PyTorch is too
large for the free tier) and the local LLM, and makes record editing read-only. Databases are seeded fresh whenever
the app restarts.

The same single-host setup is also available as a `Dockerfile` (port 7860) for container platforms;
`python start_node.py package space` builds an upload folder for a Hugging Face Docker Space.

## Example queries

| Query | What it shows |
|---|---|
| `Check the complete history of vehicle DL01AB1234.` | all five databases, FK context, documents |
| `Find vehicles with registration numbers similar to DLO1AB1234` | noisy plate resolved to DL01AB1234 |
| `Find the ownership history and insurance details for UP16BT9900` | registry owner vs RTO transfer conflict |
| `Is this vehicle insured, stolen or scrapped? GJ 01 AB 7777` | theft report, policy renewed after theft |
| `Is WB02K0001 scrapped?` | scrapped vehicle whose RC is still valid |
| `Show the full history and audit trail of KA05MJ5555` | colour conflict, RTO explanation, cleansing proposal |

## Query-understanding evaluation

`evaluation/eval_understanding.py` scores 45 labelled questions (formal, casual, Hinglish, typos, spaced and
OCR-noisy plates, multi-intent, no plate). Latest run with `llama3.2` on a CPU-only laptop:

| Metric | Rule-based parser | LLM (llama3.2) + safeguards |
|---|---|---|
| Registration number extracted correctly | 100% | 100% |
| All required intents found | 89% | 100% |
| Right databases selected | 89% | 98% |
| Exactly the expected intents | 80% | 87% |
| Extra databases queried (average) | 0.16 | 0.22 |
| Median understanding time | 1 ms | ~10 s |

Safeguards: JSON-schema output, grounding of plates and attributes in the question, cue checks for the
look-alike and discrepancy intents, explicit keyword intents from the rule parser are always kept, and automatic
fallback to the rules on any error or timeout. Run it yourself with `python evaluation/eval_understanding.py`.

## Tests

```powershell
python -m pytest -q
```

142 tests: matching and cleansing regression, schemas / FK enforcement / migration, federation (parallelism,
timeouts, outages, conflicts), document retrieval, trust score, LLM understanding with fallback (Ollama mocked), launcher, and a real-process simulation of the two-machine split.

---

## Project structure

```
config.py              topology, ports, URLs, database paths (reads .env)
start_node.py          launcher: machine-1 | machine-2 | all | frontend | init | check | configure | package [space]
run_all.py             shortcut for 'start_node.py all'
databases/             the five database modules (models, migration, FK expansion) + service factory
service_*.py           the five FastAPI database services
gateway.py             API gateway + HTML web UI (frontend/index.html)
query_engine.py        rule-based query understanding and decomposition
llm_understanding.py   optional LLM query understanding (Ollama) with validation and rule fallback
federation.py          federated execution, entity resolution, context accumulation, integration, answer
retrieval.py           document processing, BM25 index, context-driven retrieval
matching.py            plate normalisation, OCR variants, Damerau-Levenshtein, contextual scoring, benchmark
integration.py         canonical record, insurance rules, cleansing proposals and decisions
seed_data.py           synthetic data for all five databases
app.py, ui_phase3.py   Streamlit dashboard (ui_theme.py: styling, .streamlit/: theme)
streamlit_app.py       hosted-demo entry point (starts the services, then app.py)
documents/             synthetic document repository + generate_documents.py
Dockerfile, deploy/     single-container hosted demo (Hugging Face Space)
docs/                  DISTRIBUTED_SETUP.md, MATCHING_JUSTIFICATION.md, CODE_MODIFICATIONS.md
evaluation/            labelled questions + evaluation script for query understanding
tests/                 pytest suite
```

## Known limitations

- Without the optional LLM, query understanding uses keyword rules; unusual wording falls back to a general status check.
- LLM understanding on a CPU-only laptop takes a few seconds per question (the Fleet Scan always uses the rules).
- Fuzzy matching scans each database's vehicle table — suitable for the demonstration dataset, not for millions of rows.
- Document retrieval is lexical (BM25); scanned image-only PDFs are not OCR'd.
- Services trust the local network (no authentication between services).
