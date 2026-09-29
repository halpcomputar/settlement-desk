"""Private, loopback-only settlement review dashboard."""
import csv
import hashlib
import io
import json
import os
import secrets
import sqlite3
import threading
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Literal
from urllib.parse import urlparse
from uuid import UUID

import httpx
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import HTMLResponse, Response
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field
from starlette.middleware.trustedhost import TrustedHostMiddleware
from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parent
load_dotenv(ROOT / ".env", override=False)
DB = Path(os.environ.get("SETTLEMENT_DB", "data/settlements.sqlite3")).expanduser()
if not DB.is_absolute():
    DB = ROOT / DB
SCRAPER_ID = os.environ.get("PARSE_SCRAPER_ID", "").strip()
if SCRAPER_ID:
    SCRAPER_ID = str(UUID(SCRAPER_ID))
API_URL = f"https://api.parse.bot/scraper/{SCRAPER_ID}/list_settlements"
PORT = int(os.environ.get("SETTLEMENT_PORT", "8765"))
LOAD_SAMPLE = os.environ.get("SETTLEMENT_LOAD_SAMPLE", "false").lower() in ("1", "true", "yes")
TOKEN = secrets.token_urlsafe(32)
REFRESH_LOCK = threading.Lock()
app = FastAPI(docs_url=None, redoc_url=None, openapi_url=None)
app.add_middleware(TrustedHostMiddleware, allowed_hosts=["127.0.0.1", "localhost", "testserver"])


@contextmanager
def connect():
    db = sqlite3.connect(DB, timeout=10)
    db.row_factory = sqlite3.Row
    try:
        with db:
            yield db
    finally:
        db.close()


def safe_url(value):
    value = str(value or "")
    parsed = urlparse(value)
    return value if parsed.scheme in ("http", "https") and parsed.hostname and not parsed.username else ""


def store_rows(db, rows, fetched_at):
    valid = []
    for item in rows:
        if not isinstance(item, dict) or not item.get("object_id") or not item.get("name"):
            continue
        row = {key: item.get(key) for key in ("object_id", "name", "description", "claim_deadline", "payout_amount", "proof_required", "official_website", "is_active")}
        for key in row:
            if key != "is_active":
                row[key] = str(row[key] or "")
        row["official_website"] = safe_url(row["official_website"])
        row["last_checked"] = fetched_at
        row["deadline_iso"] = None
        try:
            row["deadline_iso"] = datetime.strptime(row["claim_deadline"], "%m/%d/%Y").date().isoformat()
        except ValueError:
            pass
        title = row["name"].lower()
        row["category"] = "Data breach" if "data breach" in title else "Privacy" if "privacy" in title else "Consumer" if any(word in title for word in ("return", "refund", "product")) else "Uncategorized"
        row["category_inferred"] = True
        valid.append(row)
    if not valid:
        raise ValueError("No usable settlement records returned; your saved data has been kept.")
    for row in valid:
        db.execute("INSERT INTO settlements(id, payload) VALUES (?, ?) ON CONFLICT(id) DO UPDATE SET payload=excluded.payload", (row["object_id"], json.dumps(row)))
    return len(valid)


def meta_set(db, key, value):
    db.execute("INSERT INTO metadata(key,value) VALUES (?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value", (key, json.dumps(value)))


def initialize():
    DB.parent.mkdir(parents=True, exist_ok=True)
    with connect() as db:
        db.executescript("CREATE TABLE IF NOT EXISTS settlements(id TEXT PRIMARY KEY,payload TEXT NOT NULL); CREATE TABLE IF NOT EXISTS reviews(id TEXT PRIMARY KEY,status TEXT NOT NULL DEFAULT 'unreviewed',notes TEXT NOT NULL DEFAULT ''); CREATE TABLE IF NOT EXISTS metadata(key TEXT PRIMARY KEY,value TEXT NOT NULL);")
        if not db.execute("SELECT 1 FROM metadata WHERE key='initialized'").fetchone():
            sample = None
            if LOAD_SAMPLE:
                sample = json.loads((ROOT / "sample/settlements.json").read_text(encoding="utf-8"))
                store_rows(db, sample["settlements"], sample["fetched_at_utc"])
            for key, value in {"initialized": True, "sample_only": bool(sample), "last_refresh": sample["fetched_at_utc"] if sample else None}.items():
                meta_set(db, key, value)


@app.middleware("http")
async def local_security(request: Request, call_next):
    if request.method not in ("GET", "HEAD", "OPTIONS"):
        if not secrets.compare_digest(request.headers.get("x-desk-token", ""), TOKEN):
            return Response("Request denied", status_code=403)
        origin = request.headers.get("origin")
        if origin and origin != str(request.base_url).rstrip("/"):
            return Response("Origin denied", status_code=403)
    response = await call_next(request)
    response.headers["Cache-Control"] = "no-store"
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["Referrer-Policy"] = "no-referrer"
    response.headers["Content-Security-Policy"] = "default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self' data:; connect-src 'self'; frame-ancestors 'none'; base-uri 'none'; form-action 'self'"
    return response


@app.get("/", response_class=HTMLResponse)
def home():
    return (ROOT / "static/index.html").read_text(encoding="utf-8").replace("__DESK_TOKEN__", TOKEN)


def read_records():
    with connect() as db:
        rows = db.execute("SELECT s.payload, COALESCE(r.status,'unreviewed') status, COALESCE(r.notes,'') notes FROM settlements s LEFT JOIN reviews r ON r.id=s.id").fetchall()
        metadata = {row["key"]: json.loads(row["value"]) for row in db.execute("SELECT * FROM metadata WHERE key IN ('initialized', 'sample_only', 'last_refresh')")}
    return [{**json.loads(row["payload"]), "review_status": row["status"], "notes": row["notes"]} for row in rows], metadata


def discovery_state(db):
    saved = {row["key"]: json.loads(row["value"]) for row in db.execute(
        "SELECT key, value FROM metadata WHERE key IN ('discovery', 'last_refresh', 'sample_only')")}
    # Existing installations already fetched page 0; sample-only/empty ones have not.
    default_page = 1 if saved.get("last_refresh") and not saved.get("sample_only") else 0
    if "discovery" in saved:
        return saved["discovery"]
    signatures = {}
    if default_page:
        ids = sorted(row["id"] for row in db.execute("SELECT id FROM settlements"))
        if ids and len(ids) <= 50:
            signatures["0"] = hashlib.sha256(json.dumps(ids).encode()).hexdigest()
    return {"next_page": default_page, "stop_reason": None, "signatures": signatures}


@app.get("/api/settlements")
def settlements():
    rows, metadata = read_records()
    with connect() as db:
        progress = discovery_state(db)
    return {"settlements": rows, "metadata": metadata,
            "discovery": {key: progress[key] for key in ("next_page", "stop_reason")}, "api_configured": bool(os.environ.get("PARSE_API_KEY", "").strip() and SCRAPER_ID)}


@app.get("/api/health")
def health():
    return {"app": "settlement-desk", "status": "ok"}


class Review(BaseModel):
    status: Literal["unreviewed", "maybe", "not_applicable", "claimed"]
    notes: str = Field(default="", max_length=5000)


@app.put("/api/reviews/{record_id}")
def update_review(record_id: str, review: Review):
    with connect() as db:
        if not db.execute("SELECT 1 FROM settlements WHERE id=?", (record_id,)).fetchone():
            raise HTTPException(404, "Settlement not found")
        db.execute("INSERT INTO reviews(id,status,notes) VALUES (?,?,?) ON CONFLICT(id) DO UPDATE SET status=excluded.status,notes=excluded.notes", (record_id, review.status, review.notes))
    return {"saved": True}


@app.post("/api/refresh")
def refresh():
    return fetch_listings(find_more=False)


@app.post("/api/find-more")
def find_more():
    return fetch_listings(find_more=True)


def fetch_listings(*, find_more):
    key = os.environ.get("PARSE_API_KEY", "").strip()
    if not key or not SCRAPER_ID:
        raise HTTPException(503, "Set PARSE_API_KEY and PARSE_SCRAPER_ID in your local .env file, then restart the dashboard.")
    if not REFRESH_LOCK.acquire(blocking=False):
        raise HTTPException(409, "A listing request is already in progress.")
    try:
        with connect() as db:
            progress = discovery_state(db)
        if find_more and progress["stop_reason"]:
            raise HTTPException(409, "The previous search reached an empty or repeated page. Refresh listings before searching again.")
        page = progress["next_page"] if find_more else 0
        with httpx.Client(timeout=45, follow_redirects=False) as client:
            response = client.get(API_URL, params={"page": page, "limit": 50}, headers={"X-API-Key": key})
        if response.status_code != 200:
            message = {401: "Parse did not accept the saved key.", 402: "Parse reports no available credits.", 429: "Parse is rate limiting requests. Please try again later."}.get(response.status_code, "Parse could not complete this refresh. Your saved data is unchanged.")
            raise HTTPException(502, message)
        payload = response.json()
        data = payload.get("data", payload) if isinstance(payload, dict) else {}
        rows = data.get("settlements") if isinstance(data, dict) else None
        if (not isinstance(rows, list) or len(rows) > 50 or
                any(not isinstance(row, dict) or not row.get("object_id") or not row.get("name") for row in rows)):
            raise HTTPException(502, "The API response format changed. Your saved data and search position are unchanged.")
        ids = sorted({str(row["object_id"]) for row in rows})
        signature = hashlib.sha256(json.dumps(ids).encode()).hexdigest()
        repeated = find_more and signature in progress["signatures"].values()
        stop_reason = "empty" if not rows else "repeated" if repeated else None
        now = datetime.now(timezone.utc).isoformat()
        with connect() as db:
            before = db.execute("SELECT COUNT(*) FROM settlements").fetchone()[0]
            count = store_rows(db, rows, now) if rows and not repeated else 0
            added = db.execute("SELECT COUNT(*) FROM settlements").fetchone()[0] - before
            if not find_more and progress["stop_reason"]:
                progress = {"next_page": 1, "stop_reason": None, "signatures": {}}
            progress["signatures"][str(page)] = signature
            progress["next_page"] = page + 1 if find_more else max(1, progress["next_page"])
            progress["stop_reason"] = stop_reason
            meta_set(db, "discovery", progress)
            meta_set(db, "last_refresh", now)
            meta_set(db, "sample_only", False)
        if find_more:
            return {"added": added, "existing": len(ids) - added, "checked": len(ids),
                    "page": page, "stop_reason": stop_reason}
        return {"updated": count}
    except (httpx.HTTPError, ValueError) as error:
        # Do not expose transport objects, request headers, or credentials.
        raise HTTPException(502, "Refresh did not return usable data. Your saved records and notes are kept.") from None
    finally:
        REFRESH_LOCK.release()


@app.get("/api/export")
def export():
    rows, _ = read_records()
    fields = ["name", "description", "claim_deadline", "payout_amount", "proof_required", "official_website", "review_status", "notes", "last_checked"]
    output = io.StringIO(newline="")
    writer = csv.DictWriter(output, fieldnames=fields)
    writer.writeheader()
    for row in rows:
        writer.writerow({key: ("'" + str(row.get(key, "")) if str(row.get(key, "")).lstrip().startswith(("=", "+", "-", "@")) else row.get(key, "")) for key in fields})
    return Response("\ufeff" + output.getvalue(), media_type="text/csv; charset=utf-8", headers={"Content-Disposition": 'attachment; filename="settlement-review.csv"'})


app.mount("/static", StaticFiles(directory=ROOT / "static"), name="static")
initialize()

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="127.0.0.1", port=PORT, access_log=False)
