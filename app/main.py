"""
QueryMind API.

Run with:  uvicorn app.main:app --reload
Docs at:   http://127.0.0.1:8000/docs
"""
import json
import sqlite3
import time
import uuid
from pathlib import Path
from typing import Optional, List

from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
from sqlalchemy import text
from cryptography.fernet import Fernet

from app.config import ENCRYPTION_KEY, MAX_ROWS_RETURNED, MAX_CONVERSATION_TURNS_IN_CONTEXT
from app.database import init_db, get_session, build_target_engine
from app.db_models import User, Connection, SchemaEntry, Query, QueryResult, SavedQuery
from app.schema_analyzer import extract_schema, select_relevant_tables, schema_to_prompt
from app.sql_validator import validate_sql, enforce_row_limit
from app.llm_service import generate_sql
from app.viz_selector import choose_visualization

app = FastAPI(title="QueryMind", description="Natural Language -> SQL -> Visualization")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

_fernet = Fernet(ENCRYPTION_KEY.encode()) if ENCRYPTION_KEY else None

# In-memory cache of live target-DB engines, keyed by connection_id, so we
# don't reconnect on every single query. Fine for a demo/single-process app.
_engine_cache = {}
_DEMO_USER_ID = "demo-user"
_UPLOAD_DIR = Path(__file__).resolve().parent.parent / "sample_data" / "uploads"
_MAX_UPLOAD_BYTES = 50 * 1024 * 1024
_SAMPLE_DATABASES = [
    {
        "id": "company",
        "name": "Company Operations",
        "path": "sample_data/sample_company.db",
        "description": "Explore teams, employee salaries, and sales performance.",
        "tables": ["departments", "employees", "sales"],
        "examples": ["What is the average salary in each department?", "Show total sales by product category", "Which employees have the highest salary?"],
    },
    {
        "id": "university",
        "name": "University Campus",
        "path": "sample_data/sample_university.db",
        "description": "Analyze students, programs, courses, enrollment, and academic outcomes.",
        "tables": ["departments", "programs", "students", "instructors", "courses", "enrollments"],
        "examples": ["What is the average GPA by program?", "Show student enrollment by program", "Which courses have the most enrollments?"],
    },
    {
        "id": "retail",
        "name": "Retail & Orders",
        "path": "sample_data/sample_retail.db",
        "description": "Review product categories, customer segments, orders, and revenue.",
        "tables": ["customers", "products", "orders", "order_items"],
        "examples": ["Show revenue by product category", "Which are the top selling products?", "Show sales by category"],
    },
]


# ---------------------------------------------------------------- startup --

@app.on_event("startup")
def on_startup():
    init_db()
    with get_session() as db:
        if not db.get(User, _DEMO_USER_ID):
            db.add(User(
                user_id=_DEMO_USER_ID,
                name="Demo User",
                email="demo@querymind.local",
                password_hash="not-used-in-demo",
                role="admin",
            ))


# --------------------------------------------------------------- schemas --

class ConnectRequest(BaseModel):
    name: str
    database_type: str  # 'sqlite' | 'postgresql'
    database_name: str  # file path for sqlite, db name for postgres
    host: Optional[str] = None
    username: Optional[str] = None
    password: Optional[str] = None
    port: Optional[int] = 5432


class QueryRequest(BaseModel):
    connection_id: str
    question: str
    conversation_id: Optional[str] = None  # omit to start a new conversation


class SavedQueryRequest(BaseModel):
    connection_id: str
    name: str
    question: str
    generated_sql: Optional[str] = None


@app.get("/api/db/catalog")
def get_database_catalog():
    samples = [
        {**sample, "available": (Path(__file__).resolve().parent.parent / sample["path"]).is_file()}
        for sample in _SAMPLE_DATABASES
    ]
    with get_session() as db:
        connections = db.query(Connection).filter_by(user_id=_DEMO_USER_ID).order_by(Connection.created_at.desc()).all()
        existing = [{
            "connection_id": row.connection_id,
            "name": row.name,
            "database_type": row.database_type,
            "database_name": row.database_name,
            "created_at": row.created_at.isoformat(),
        } for row in connections]
    return {"samples": samples, "connections": existing}


@app.post("/api/db/upload")
async def upload_database(request: Request, filename: str):
    safe_name = filename.replace("\\", "/").rsplit("/", 1)[-1].strip()
    suffix = Path(safe_name).suffix.lower()
    if suffix not in {".db", ".sqlite", ".sqlite3"}:
        raise HTTPException(400, "Choose a SQLite database file (.db, .sqlite, or .sqlite3).")

    content_length = request.headers.get("content-length")
    if content_length and content_length.isdigit() and int(content_length) > _MAX_UPLOAD_BYTES:
        raise HTTPException(413, "Database files must be 50 MB or smaller.")

    chunks = []
    total_bytes = 0
    async for chunk in request.stream():
        total_bytes += len(chunk)
        if total_bytes > _MAX_UPLOAD_BYTES:
            raise HTTPException(413, "Database files must be 50 MB or smaller.")
        chunks.append(chunk)
    file_bytes = b"".join(chunks)
    if not file_bytes.startswith(b"SQLite format 3\x00"):
        raise HTTPException(400, "The selected file is not a SQLite database.")

    _UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
    upload_path = _UPLOAD_DIR / f"{uuid.uuid4().hex}{suffix}"
    upload_path.write_bytes(file_bytes)
    try:
        db_file = sqlite3.connect(f"file:{upload_path.as_posix()}?mode=ro", uri=True)
        integrity = db_file.execute("PRAGMA quick_check").fetchone()
        tables = db_file.execute(
            "SELECT name FROM sqlite_master WHERE type = 'table' AND name NOT LIKE 'sqlite_%'"
        ).fetchall()
        db_file.close()
        if not integrity or integrity[0] != "ok" or not tables:
            raise ValueError("The SQLite database is invalid or has no user tables.")
    except (sqlite3.Error, ValueError) as exc:
        upload_path.unlink(missing_ok=True)
        raise HTTPException(400, str(exc)) from exc

    relative_path = upload_path.relative_to(Path(__file__).resolve().parent.parent).as_posix()
    display_name = Path(safe_name).stem or "Uploaded SQLite database"
    return {
        "name": display_name,
        "database_name": relative_path,
        "table_count": len(tables),
        "size_bytes": total_bytes,
    }


@app.post("/api/db/reconnect/{connection_id}")
def reconnect_database(connection_id: str):
    with get_session() as db:
        connection = db.get(Connection, connection_id)
        if not connection:
            raise HTTPException(404, "Saved database connection not found.")
        credentials = {}
        if _fernet and connection.encrypted_credentials:
            credentials = json.loads(_fernet.decrypt(connection.encrypted_credentials.encode()).decode())
        try:
            engine = build_target_engine(
                connection.database_type, connection.database_name, connection.host, credentials
            )
            with engine.connect() as target:
                target.execute(text("SELECT 1"))
        except Exception as exc:
            raise HTTPException(400, f"Could not reconnect to database: {exc}")
        _engine_cache[connection_id] = engine
        table_count = db.query(SchemaEntry.table_name).filter_by(connection_id=connection_id).distinct().count()
        return {
            "connection_id": connection_id,
            "table_count": table_count,
            "name": connection.name,
            "database_type": connection.database_type,
            "database_name": connection.database_name,
        }


@app.post("/api/db/disconnect/{connection_id}")
def disconnect_database(connection_id: str):
    with get_session() as db:
        if not db.get(Connection, connection_id):
            raise HTTPException(404, "Saved database connection not found.")
        target_engine = _engine_cache.pop(connection_id, None)
        if target_engine:
            target_engine.dispose()
    return {"disconnected": True, "connection_id": connection_id}


# ------------------------------------------------------------ db/connect --

@app.post("/api/db/connect")
def connect_database(req: ConnectRequest):
    credentials = {"username": req.username, "password": req.password, "port": req.port}

    try:
        engine = build_target_engine(req.database_type, req.database_name, req.host, credentials)
        with engine.connect() as conn:
            conn.execute(text("SELECT 1"))
    except Exception as e:
        raise HTTPException(400, f"Could not connect to database: {e}")

    encrypted = _fernet.encrypt(json.dumps(credentials).encode()).decode() if _fernet else None

    with get_session() as db:
        connection = Connection(
            user_id=_DEMO_USER_ID,
            name=req.name,
            database_type=req.database_type,
            host=req.host,
            database_name=req.database_name,
            encrypted_credentials=encrypted,
        )
        db.add(connection)
        db.flush()
        connection_id = connection.connection_id

        # Extract + persist schema immediately so /api/db/schema is fast later.
        tables = extract_schema(engine)
        for table in tables.values():
            for col in table.columns:
                db.add(SchemaEntry(
                    connection_id=connection_id,
                    table_name=table.name,
                    column_name=col.name,
                    data_type=col.data_type,
                    is_primary_key=int(col.is_primary_key),
                    is_foreign_key=int(col.is_foreign_key),
                    foreign_key_ref=col.foreign_key_ref,
                ))

    _engine_cache[connection_id] = engine
    return {"connection_id": connection_id, "table_count": len(tables)}


@app.get("/api/db/schema")
def get_schema(connection_id: str):
    with get_session() as db:
        entries = db.query(SchemaEntry).filter_by(connection_id=connection_id).all()
        if not entries:
            raise HTTPException(404, "No schema found for this connection_id.")

        tables = {}
        for e in entries:
            tables.setdefault(e.table_name, []).append({
                "column": e.column_name,
                "type": e.data_type,
                "primary_key": bool(e.is_primary_key),
                "foreign_key": e.foreign_key_ref if e.is_foreign_key else None,
            })
        return {"connection_id": connection_id, "tables": tables}


# -------------------------------------------------------------- /api/query --

@app.post("/api/query")
def run_query(req: QueryRequest):
    """
    The main endpoint: natural language question in, validated SQL +
    results + chosen visualization out. Also persists the turn so
    follow-up questions in the same conversation_id have context.
    """
    connection_id = req.connection_id
    engine = _engine_cache.get(connection_id)

    with get_session() as db:
        conn_row = db.get(Connection, connection_id)
        if not conn_row:
            raise HTTPException(404, "Unknown connection_id. Call /api/db/connect first.")

        if engine is None:
            creds = {}
            if _fernet and conn_row.encrypted_credentials:
                creds = json.loads(_fernet.decrypt(conn_row.encrypted_credentials.encode()).decode())
            engine = build_target_engine(conn_row.database_type, conn_row.database_name, conn_row.host, creds)
            _engine_cache[connection_id] = engine

        dialect = "postgres" if conn_row.database_type == "postgresql" else "sqlite"

        # ---- 1. Schema retrieval (relevant tables only, not the whole DB) ----
        all_tables = extract_schema(engine)
        relevant_tables = select_relevant_tables(req.question, all_tables)
        schema_text = schema_to_prompt(relevant_tables)

        # ---- 2. Conversation history for multi-turn follow-ups ----
        conversation_id = req.conversation_id or str(uuid.uuid4())
        history = []
        if req.conversation_id:
            past = (
                db.query(Query)
                .filter_by(conversation_id=conversation_id, status="success")
                .order_by(Query.created_at.asc())
                .all()
            )
            history = [{"question": q.natural_language_query, "sql": q.generated_sql}
                       for q in past[-MAX_CONVERSATION_TURNS_IN_CONTEXT:]]

        query_row = Query(
            user_id=_DEMO_USER_ID,
            connection_id=connection_id,
            conversation_id=conversation_id,
            natural_language_query=req.question,
            status="pending",
        )
        db.add(query_row)
        db.flush()
        query_id = query_row.query_id

        # ---- 3. LLM: NL -> SQL ----
        try:
            llm_result = generate_sql(req.question, schema_text, history)
        except Exception as e:
            query_row.status = "error"
            query_row.error_message = str(e)
            raise HTTPException(502, f"SQL generation failed: {e}")

        generated_sql = llm_result["sql"]
        explanation = llm_result.get("explanation", "")
        query_row.generated_sql = generated_sql

        # ---- 4. Validate (the critical security layer) ----
        validation = validate_sql(generated_sql, dialect=dialect)
        if not validation.is_safe:
            query_row.status = "rejected"
            query_row.error_message = validation.reason
            return {
                "query_id": query_id,
                "conversation_id": conversation_id,
                "status": "rejected",
                "reason": validation.reason,
                "attempted_sql": generated_sql,
            }

        safe_sql = enforce_row_limit(validation.normalized_sql, dialect, MAX_ROWS_RETURNED)

        # ---- 5. Execute against the (ideally read-only-role) connection ----
        start = time.perf_counter()
        try:
            with engine.connect() as conn:
                result = conn.execute(text(safe_sql))
                columns = list(result.keys())
                rows = [dict(zip(columns, r)) for r in result.fetchall()]
        except Exception as e:
            query_row.status = "error"
            query_row.error_message = str(e)
            raise HTTPException(400, f"Query execution failed: {e}")
        elapsed = time.perf_counter() - start

        query_row.status = "success"
        query_row.execution_time = elapsed

        # ---- 6. Choose a visualization ----
        viz = choose_visualization(columns, rows)

        db.add(QueryResult(
            query_id=query_id,
            result_data=json.dumps(rows, default=str),
            row_count=len(rows),
            chart_type=viz.chart_type,
            chart_config=json.dumps(viz.config),
        ))

        return {
            "query_id": query_id,
            "conversation_id": conversation_id,
            "status": "success",
            "generated_sql": safe_sql,
            "explanation": explanation,
            "columns": columns,
            "rows": rows,
            "row_count": len(rows),
            "execution_time": round(elapsed, 4),
            "chart_type": viz.chart_type,
            "chart_config": viz.config,
        }


@app.get("/api/query/history")
def query_history(
    connection_id: Optional[str] = None,
    conversation_id: Optional[str] = None,
    search: Optional[str] = None,
    status: Optional[str] = None,
    offset: int = 0,
    limit: int = 100,
):
    with get_session() as db:
        q = db.query(Query, QueryResult).outerjoin(QueryResult, QueryResult.query_id == Query.query_id)
        if connection_id:
            q = q.filter(Query.connection_id == connection_id)
        if conversation_id:
            q = q.filter(Query.conversation_id == conversation_id)
        if search:
            pattern = f"%{search.strip()}%"
            q = q.filter((Query.natural_language_query.ilike(pattern)) | (Query.generated_sql.ilike(pattern)))
        if status:
            q = q.filter(Query.status == status)
        total = q.count()
        rows = q.order_by(Query.created_at.desc()).offset(max(offset, 0)).limit(min(max(limit, 1), 500)).all()
        return {
            "total": total,
            "items": [{
                "query_id": query.query_id,
                "conversation_id": query.conversation_id,
                "natural_language_query": query.natural_language_query,
                "generated_sql": query.generated_sql,
                "status": query.status,
                "error_message": query.error_message,
                "execution_time": query.execution_time,
                "created_at": query.created_at.isoformat(),
                "row_count": result.row_count if result else None,
                "chart_type": result.chart_type if result else None,
            } for query, result in rows],
        }


@app.get("/api/dashboard")
def dashboard(connection_id: Optional[str] = None):
    with get_session() as db:
        query = db.query(Query)
        if connection_id:
            query = query.filter(Query.connection_id == connection_id)
        all_queries = query.all()
        total = len(all_queries)
        success = sum(row.status == "success" for row in all_queries)
        rejected = sum(row.status == "rejected" for row in all_queries)
        errored = sum(row.status == "error" for row in all_queries)
        avg_time_row = [row for row in all_queries if row.execution_time is not None]
        avg_time = (
            sum(r.execution_time for r in avg_time_row) / len(avg_time_row)
            if avg_time_row else 0
        )
        results = (
            db.query(QueryResult, Query.created_at)
            .join(Query, Query.query_id == QueryResult.query_id)
        )
        if connection_id:
            results = results.filter(Query.connection_id == connection_id)
        chart_counts = {}
        for result, _ in results.all():
            chart_counts[result.chart_type or "unknown"] = chart_counts.get(result.chart_type or "unknown", 0) + 1

        today = time.strftime("%Y-%m-%d", time.gmtime())
        daily_counts = {}
        for row in all_queries:
            day = row.created_at.strftime("%Y-%m-%d")
            daily_counts[day] = daily_counts.get(day, 0) + 1
        from datetime import date, timedelta
        today_date = date.fromisoformat(today)
        activity = [
            {"date": (today_date - timedelta(days=offset)).isoformat(),
             "queries": daily_counts.get((today_date - timedelta(days=offset)).isoformat(), 0)}
            for offset in range(6, -1, -1)
        ]
        return {
            "total_queries": total,
            "successful": success,
            "rejected_unsafe": rejected,
            "errored": errored,
            "success_rate": round(success / total, 3) if total else 0,
            "avg_execution_time_seconds": round(avg_time, 4),
            "activity": activity,
            "chart_breakdown": chart_counts,
        }


@app.get("/api/saved-queries")
def list_saved_queries(connection_id: str):
    with get_session() as db:
        rows = (db.query(SavedQuery).filter_by(user_id=_DEMO_USER_ID, connection_id=connection_id)
                .order_by(SavedQuery.created_at.desc()).all())
        return [{
            "saved_query_id": row.saved_query_id,
            "name": row.name,
            "question": row.question,
            "generated_sql": row.generated_sql,
            "created_at": row.created_at.isoformat(),
        } for row in rows]


@app.post("/api/saved-queries")
def save_query(req: SavedQueryRequest):
    with get_session() as db:
        if not db.get(Connection, req.connection_id):
            raise HTTPException(404, "Unknown connection_id.")
        row = SavedQuery(
            user_id=_DEMO_USER_ID,
            connection_id=req.connection_id,
            name=req.name.strip() or req.question[:80],
            question=req.question.strip(),
            generated_sql=req.generated_sql,
        )
        db.add(row)
        db.flush()
        return {"saved_query_id": row.saved_query_id, "name": row.name}


@app.delete("/api/saved-queries/{saved_query_id}")
def delete_saved_query(saved_query_id: str):
    with get_session() as db:
        row = db.query(SavedQuery).filter_by(
            saved_query_id=saved_query_id, user_id=_DEMO_USER_ID
        ).first()
        if not row:
            raise HTTPException(404, "Saved query not found.")
        db.delete(row)
        return {"deleted": True}


# Serve the simple frontend at / (mounted last so it doesn't shadow /api routes)
app.mount("/", StaticFiles(directory="frontend", html=True), name="frontend")
