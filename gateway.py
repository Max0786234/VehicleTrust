import os
import sys
import time
import sqlite3
import datetime
from typing import Any, Dict, List, Optional
import numpy as np
import httpx
from fastapi import FastAPI, File, UploadFile, HTTPException, Query, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse, JSONResponse
from pydantic import BaseModel
from starlette.concurrency import run_in_threadpool
from dotenv import load_dotenv

sys.path.insert(0, os.path.dirname(__file__))
load_dotenv(os.path.join(os.path.dirname(os.path.abspath(__file__)), ".env"))
import config  # noqa: E402

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

app = FastAPI(title="VehicleTrust — HTTP/JSON API Gateway & Web Frontend", version="1.0.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

FRONTEND_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "frontend")
os.makedirs(FRONTEND_DIR, exist_ok=True)

DEFAULT_URLS = {key: config.service_url(key) for key in config.DATA_SERVICE_KEYS}
AUDIT_API_URL = config.service_url("audit_log")

# SQL console: database file name -> service key (paths resolved through config / env vars)
VALID_DBS = {config.SERVICES[key]["db_default"]: key for key in config.ALL_SERVICE_KEYS}

_ocr_reader = None


def get_reader():
    global _ocr_reader
    if _ocr_reader is None:
        try:
            import easyocr
            _ocr_reader = easyocr.Reader(["en"], gpu=False)
        except Exception:
            _ocr_reader = None
    return _ocr_reader


@app.get("/api/status")
def get_system_status():
    results = {}
    for key, base_url in DEFAULT_URLS.items():
        try:
            start = time.time()
            resp = httpx.get(f"{base_url.rstrip('/')}/health", timeout=2.0)
            latency = round((time.time() - start) * 1000, 1)
            if resp.status_code == 200:
                data = resp.json()
                results[key] = {"online": True, "latency_ms": latency, "record_count": data.get("record_count", 0), "url": base_url,
                                "table_count": data.get("table_count"), "machine": data.get("machine")}
            else:
                results[key] = {"online": False, "latency_ms": latency, "record_count": 0, "url": base_url, "error": f"HTTP {resp.status_code}"}
        except Exception as e:
            results[key] = {"online": False, "latency_ms": 0, "record_count": 0, "url": base_url, "error": str(e)}
    try:
        start = time.time()
        response = httpx.get(f"{AUDIT_API_URL}/health", timeout=2.0)
        latency = round((time.time() - start) * 1000, 1)
        if response.status_code == 200:
            data = response.json()
            results["audit_log"] = {
                "online": True,
                "latency_ms": latency,
                "record_count": data.get("record_count", 0),
                "url": AUDIT_API_URL,
                "table_count": data.get("table_count"),
                "machine": data.get("machine"),
            }
        else:
            results["audit_log"] = {
                "online": False,
                "latency_ms": latency,
                "record_count": 0,
                "url": AUDIT_API_URL,
                "error": f"HTTP {response.status_code}",
            }
    except httpx.RequestError as exc:
        results["audit_log"] = {
            "online": False,
            "latency_ms": 0,
            "record_count": 0,
            "url": AUDIT_API_URL,
            "error": str(exc),
        }
    return {"status": "ok", "timestamp": datetime.datetime.now(datetime.timezone.utc).isoformat(), "services": results}


def get_service_url(service_key: str) -> str:
    service_url = DEFAULT_URLS.get(service_key)
    if not service_url:
        raise HTTPException(status_code=404, detail=f"Unknown database service: {service_key}")
    return service_url.rstrip("/")


def forward_service_request(method: str, service_key: str, path: str = "", payload: Optional[Dict[str, Any]] = None):
    url = f"{get_service_url(service_key)}/records{path}"
    try:
        response = httpx.request(method, url, json=payload, timeout=5.0)
    except httpx.RequestError as exc:
        raise HTTPException(status_code=502, detail=f"Could not contact {service_key} service: {exc}") from exc

    try:
        body = response.json()
    except ValueError:
        body = {"detail": response.text}
    if not response.is_success:
        detail = body.get("detail", body) if isinstance(body, dict) else body
        raise HTTPException(status_code=response.status_code, detail=detail)
    return JSONResponse(status_code=response.status_code, content=body)


@app.get("/api/services/{service_key}/records")
def get_remote_records(service_key: str):
    return forward_service_request("GET", service_key)


@app.post("/api/services/{service_key}/records")
def create_remote_record(service_key: str, payload: Dict[str, Any]):
    return forward_service_request("POST", service_key, payload=payload)


@app.delete("/api/services/{service_key}/records/{record_id}")
def delete_remote_record(service_key: str, record_id: int):
    return forward_service_request("DELETE", service_key, f"/{record_id}")


@app.put("/api/services/{service_key}/records/{record_id}")
def update_remote_record(service_key: str, record_id: int, payload: Dict[str, Any]):
    return forward_service_request("PUT", service_key, f"/{record_id}", payload=payload)


@app.post("/api/ocr")
async def process_ocr_image(file: UploadFile = File(...)):
    contents = await file.read()
    if not contents:
        raise HTTPException(status_code=400, detail="The uploaded image is empty.")
    try:
        return await run_in_threadpool(_process_ocr_image, contents)
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Image processing error: {str(e)}")


def _process_ocr_image(contents: bytes) -> Dict[str, Any]:
    import cv2

    nparr = np.frombuffer(contents, np.uint8)
    img = cv2.imdecode(nparr, cv2.IMREAD_COLOR)
    if img is None:
        raise HTTPException(status_code=400, detail="Invalid image file format.")

    gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
    resized = cv2.resize(gray, None, fx=2.0, fy=2.0, interpolation=cv2.INTER_CUBIC)
    blurred = cv2.GaussianBlur(resized, (5, 5), 0)
    _, thresh = cv2.threshold(blurred, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)

    reader = get_reader()
    if reader is None:
        return {
            "raw_text": "",
            "normalized_plate": "",
            "confidence": 0.0,
            "ocr_variants": [],
            "message": "EasyOCR model could not be loaded. Check the server log or enter the plate manually.",
        }

    ocr_res = reader.readtext(thresh)
    raw_combined = " ".join(result[1] for result in ocr_res) if ocr_res else ""
    avg_conf = float(np.mean([result[2] for result in ocr_res])) if ocr_res else 0.0
    normalized = normalize_plate(raw_combined)
    return {
        "raw_text": raw_combined,
        "normalized_plate": normalized,
        "confidence": round(avg_conf, 4),
        "ocr_variants": generate_ocr_confusion_variants(normalized),
        "message": "No text was detected. Try a clearer, closer image or enter the plate manually." if not raw_combined else "",
    }


class SearchRequest(BaseModel):
    query_plate: str
    make: Optional[str] = None
    model: Optional[str] = None
    colour: Optional[str] = None
    state: Optional[str] = None
    threshold: float = 0.50


@app.post("/api/search")
def search_records(req: SearchRequest):
    all_source_records = []
    offline = []
    ins_available = True

    for s_name, s_url in DEFAULT_URLS.items():
        try:
            resp = httpx.get(f"{s_url.rstrip('/')}/records", timeout=2.5)
            if resp.status_code == 200:
                all_source_records.append((s_name, resp.json()))
            else:
                offline.append(s_name)
                if s_name == "insurance_records":
                    ins_available = False
        except Exception:
            offline.append(s_name)
            if s_name == "insurance_records":
                ins_available = False

    query_ctx = {
        "make": req.make.strip() if req.make else None,
        "model": req.model.strip() if req.model else None,
        "colour": req.colour.strip() if req.colour else None,
        "state": req.state.strip() if req.state else None,
    }

    candidates = search_and_rank_candidates(req.query_plate, all_source_records, query_ctx, req.threshold)

    # Build canonical record
    canonical = CanonicalVehicleRecord(req.query_plate)
    for s_name, records in all_source_records:
        ranked = [
            rank_candidate_record(
                req.query_plate,
                record,
                s_name,
                record.get("id", 0),
                query_ctx,
            )
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

    canon_dict = canonical.to_dict()
    risk = evaluate_insurance_risk(
        canon_dict.get("insurance", []),
        canon_dict.get("theft_scrapping"),
        datetime.date.today(),
        canon_dict.get("confidence_tier", "HIGH"),
        ins_available,
    )
    proposals = generate_cleansing_proposals(canon_dict)

    return {
        "query_plate": req.query_plate,
        "normalized_plate": normalize_plate(req.query_plate),
        "candidates_count": len(candidates),
        "candidates": candidates,
        "canonical_record": canon_dict,
        "insurance_risk": risk,
        "cleansing_proposals": proposals,
        "offline_services": offline,
    }


class SqlQueryRequest(BaseModel):
    database: str
    query: str


@app.post("/api/sql")
def execute_sql_query(req: SqlQueryRequest):
    """Read-only SQL console over the SQLite files that live on THIS (gateway) machine."""
    db_name = os.path.basename(req.database.strip())
    if db_name not in VALID_DBS:
        raise HTTPException(status_code=400, detail=f"Invalid database. Allowed: {list(VALID_DBS.keys())}")
    db_path = config.db_path(VALID_DBS[db_name])
    if not os.path.exists(db_path):
        raise HTTPException(status_code=404, detail=(
            f"Database file {db_name} is not on this machine. In the two-laptop deployment it is owned by "
            f"another node; inspect it through the Schema Explorer (REST) instead."))

    clean_query = req.query.strip()
    disallowed = ["DROP", "ALTER", "ATTACH", "DETACH", "PRAGMA"]
    for word in disallowed:
        if word in clean_query.upper().split():
            raise HTTPException(status_code=403, detail=f"Operation '{word}' is restricted in the interactive console.")

    start_t = time.time()
    try:
        # mode=ro: SQLite itself rejects INSERT/UPDATE/DELETE, so the console is genuinely read-only.
        uri_path = db_path.replace("\\", "/")
        conn = sqlite3.connect(f"file:{uri_path}?mode=ro", uri=True)
        try:
            cursor = conn.cursor()
            cursor.execute(clean_query)
            columns = [d[0] for d in cursor.description] if cursor.description else []
            rows = cursor.fetchmany(300) if cursor.description else []
        finally:
            conn.close()
        elapsed_ms = round((time.time() - start_t) * 1000, 2)
        return {
            "database": db_name,
            "columns": columns,
            "rows": rows,
            "row_count": len(rows),
            "execution_time_ms": elapsed_ms,
        }
    except sqlite3.OperationalError as e:
        if "readonly" in str(e).lower():
            raise HTTPException(status_code=403, detail="The SQL console is read-only; use the CRUD API to modify data.")
        raise HTTPException(status_code=400, detail=f"SQL Execution Error: {str(e)}")
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"SQL Execution Error: {str(e)}")


class CleansingDecisionRequest(BaseModel):
    proposal: Dict[str, Any]
    decision: str
    reason: str


@app.post("/api/cleansing/decide")
def submit_cleansing_decision(req: CleansingDecisionRequest):
    api_urls = {**DEFAULT_URLS, "audit_log": AUDIT_API_URL}
    ok, msg = apply_cleansing_decision(req.proposal, req.decision, req.reason, api_urls)
    return {"success": ok, "message": msg}


@app.get("/api/audit-logs")
def fetch_audit_logs(limit: int = 100, source: Optional[str] = None):
    return get_cleansing_audit_logs(limit, source, AUDIT_API_URL)


@app.get("/api/benchmark")
def get_algorithm_benchmark():
    return evaluate_algorithms()


# =============================================================================
# PHASE 3 — federated query processing, schema inspection, document retrieval
# =============================================================================
def _warm_up() -> None:
    """Builds the document index and TLS context once at startup so the first query is not slow."""
    try:
        from federation import _ssl_context
        from retrieval import get_store
        _ssl_context()
        get_store()
    except Exception as exc:  # never block startup; the error resurfaces on use
        print(f"[Gateway] warm-up skipped: {exc}")


app.router.on_startup.append(_warm_up)


def _all_service_urls() -> Dict[str, str]:
    return {**DEFAULT_URLS, "audit_log": AUDIT_API_URL}


def _service_base(service_key: str) -> str:
    urls = _all_service_urls()
    if service_key not in urls:
        raise HTTPException(status_code=404, detail=f"Unknown database service: {service_key}")
    return urls[service_key].rstrip("/")


class FederatedQueryRequest(BaseModel):
    query: str = ""
    plate: Optional[str] = None
    plate_source: Optional[str] = None  # "ocr" | "explicit"
    make: Optional[str] = None
    model: Optional[str] = None
    colour: Optional[str] = None
    state: Optional[str] = None
    include_documents: bool = True
    top_k_documents: int = 6
    timeout: Optional[float] = None


@app.post("/api/federated-query")
async def federated_query(req: FederatedQueryRequest):
    from federation import run_federated_query
    context = {k: getattr(req, k).strip() for k in ("make", "model", "colour", "state") if getattr(req, k)}
    return await run_federated_query(
        req.query, plate=req.plate, context=context, plate_source=req.plate_source,
        urls=_all_service_urls(), timeout=req.timeout, include_documents=req.include_documents,
        top_k_documents=max(1, min(req.top_k_documents, 15)))


@app.post("/api/query/understand")
def understand(req: FederatedQueryRequest):
    from query_engine import decompose_query, understand_query
    context = {k: getattr(req, k) for k in ("make", "model", "colour", "state") if getattr(req, k)}
    u = understand_query(req.query, req.plate, context, req.plate_source)
    return {"understanding": u, "decomposition": decompose_query(u)}


@app.get("/api/topology")
def topology():
    return {"service_urls": _all_service_urls(), "machine_groups": config.MACHINE_GROUPS,
            "services": {k: {"label": v["label"], "machine": v["machine"], "port": config.service_port(k)}
                         for k, v in config.SERVICES.items()},
            "documents_dir": config.DOCUMENTS_DIR}


def _proxy_get(service_key: str, path: str, params: Optional[Dict[str, Any]] = None):
    url = f"{_service_base(service_key)}{path}"
    try:
        response = httpx.get(url, params=params, timeout=5.0)
    except httpx.RequestError as exc:
        raise HTTPException(status_code=502, detail=f"Could not contact {service_key} service: {exc}") from exc
    if not response.is_success:
        raise HTTPException(status_code=response.status_code, detail=response.text[:300])
    return response.json()


@app.get("/api/services/{service_key}/schema")
def service_schema(service_key: str):
    return _proxy_get(service_key, "/schema")


@app.get("/api/services/{service_key}/tables/{table}")
def service_table(service_key: str, table: str, limit: int = 100):
    return _proxy_get(service_key, f"/tables/{table}", {"limit": limit})


@app.get("/api/services/{service_key}/integrity")
def service_integrity(service_key: str):
    return _proxy_get(service_key, "/integrity")


class DocumentSearchRequest(BaseModel):
    query: str
    document_type: Optional[str] = None
    registration_number: Optional[str] = None
    top_k: int = 5


@app.get("/api/documents")
def list_documents():
    from retrieval import get_store
    store = get_store()
    return {"stats": store.stats(), "documents": store.list_documents()}


@app.get("/api/documents/{doc_id}")
def get_document(doc_id: str):
    from retrieval import get_store
    doc = get_store().get(doc_id)
    if not doc:
        raise HTTPException(status_code=404, detail=f"Document {doc_id} not found")
    return doc


@app.post("/api/documents/search")
def search_documents(req: DocumentSearchRequest):
    from retrieval import get_store
    return get_store().search(req.query, req.top_k, req.document_type, req.registration_number)


@app.post("/api/documents/reindex")
def reindex_documents():
    from retrieval import get_store
    return get_store(rebuild=True).stats()


# Serve Single Page Application frontend
@app.get("/")
def serve_index():
    index_file = os.path.join(FRONTEND_DIR, "index.html")
    if os.path.exists(index_file):
        return FileResponse(index_file)
    return {"message": "Frontend index.html is being prepared."}


app.mount("/static", StaticFiles(directory=FRONTEND_DIR), name="static")

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
