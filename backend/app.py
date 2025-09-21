import os
import re
from anyio import to_thread
from typing import Iterable, List, Optional
from llm import generate_answer, llm_ready, llm_healthcheck
import numpy as np
from dotenv import load_dotenv
from pathlib import Path
load_dotenv(dotenv_path=Path(__file__).with_name(".env"), override=True)
from fastapi import FastAPI, UploadFile, File, HTTPException, Request, Header
from fastapi.middleware.cors import CORSMiddleware
from starlette.responses import JSONResponse
from pydantic import BaseModel
from document_parser import parse_bytes
from embeddings import encode
from qdrant_utils import (
    connect, ensure_collection, ensure_payload_indexes,
    upsert_chunks, search as qsearch, COLLECTION
)

app = FastAPI(title="Chatbot API (Qdrant Cloud)", description="Czat + upload + embeddingi + CMS")
ALLOW_ORIGINS = [o.strip() for o in os.getenv("ALLOW_ORIGINS","http://localhost:5500,http://127.0.0.1:5500").split(",") if o.strip()]
ALLOW_CREDENTIALS = not ("*" in ALLOW_ORIGINS)

app.add_middleware(
    CORSMiddleware,
    allow_origins=ALLOW_ORIGINS,
    allow_credentials=ALLOW_CREDENTIALS,
    allow_methods=["*"],
    allow_headers=["*"],
)
@app.get("/llm-health")
async def llm_health():
    return llm_healthcheck()


MAX_BYTES = 20 * 1024 * 1024

@app.middleware("http")
async def limit_body(request: Request, call_next):
    if request.url.path == "/upload":
        cl = request.headers.get("content-length")
        if cl and cl.isdigit() and int(cl) > MAX_BYTES:
            return JSONResponse({"detail": "Plik za duży (max 20 MB)"}, status_code=413)

        body = await request.body()
        if len(body) > MAX_BYTES:
            return JSONResponse({"detail": "Plik za duży (max 20 MB)"}, status_code=413)
        request._body = body
    return await call_next(request)


QDRANT_URL = os.getenv("QDRANT_URL", "http://localhost:6333")
QDRANT_API_KEY = os.getenv("QDRANT_API_KEY")
VECTOR_DIM = 384

client = connect(QDRANT_URL, QDRANT_API_KEY)
ensure_collection(client, dim=VECTOR_DIM)
ensure_payload_indexes(client)

def rerank_hits(question: str, hits, top_k: int = 5):
    return hits[:top_k]

def _cleanup_span(s: str, max_chars: int = 220) -> str:
    s = re.sub(r"\s+", " ", s).strip()
    s = re.sub(r"\s+([,\.:\;\!\?])", r"\1", s)
    s = re.sub(r"(\d)\s*z(\s|[,\.])", r"\1 zł\2", s)
    if len(s) > max_chars:
        m = re.search(r"^(.{80,}?[\.\!\?])(.*)$", s)
        s = m.group(1) if m else (s[:max_chars-1] + "…")
    return s[0].upper() + s[1:] if s else s


def _candidate_spans_from_fragment(frag: str, max_chars: int = 220) -> List[str]:
    text = re.sub(r"\s+", " ", frag).strip()
    if not text:
        return []
    cands: List[str] = []
    sents = re.split(r"(?<=[\.\!\?])\s+", text)
    buf = ""
    for s in sents:
        if not buf:
            buf = s
        elif len(buf) + 1 + len(s) <= max_chars:
            buf = f"{buf} {s}"
        else:
            cands.append(buf); buf = s
    if buf: cands.append(buf)
    step = max(40, max_chars // 2)
    for i in range(0, max(1, len(text) - max_chars + 1), step):
        cands.append(text[i:i + max_chars])
    clean = []
    for c in cands:
        cap_ratio = sum(ch.isupper() for ch in c if ch.isalpha()) / max(1, sum(ch.isalpha() for ch in c))
        if len(c) >= 30 and cap_ratio < 0.6:
            clean.append(c)
    seen, uniq = set(), []
    for c in clean:
        if c not in seen:
            seen.add(c); uniq.append(c)
    return uniq
def _norm_text(s: str) -> str:
    return re.sub(r"\s+", " ", (s or "")).strip().lower()

def pick_best_answer_span(question: str, fragments: Iterable[str], q_vec: Optional[List[float]] = None,
                          max_chars: int = 220) -> Optional[str]:
    candidates: List[str] = []
    for frag in fragments:
        candidates.extend(_candidate_spans_from_fragment(frag, max_chars=max_chars))
    if not candidates:
        return None

    if len(candidates) > 80:
        candidates = candidates[:80]

    if q_vec is None:
        from embeddings import encode
        q_vec = encode([question])[0]
    from embeddings import encode
    win_vecs = encode(candidates)
    def _norm(v):
        v = np.asarray(v, dtype=np.float32)
        n = np.linalg.norm(v)
        return v if n == 0 else v / n
    qv = _norm(q_vec)
    scores = [float(np.dot(qv, _norm(w))) for w in win_vecs]
    best = candidates[int(np.argmax(scores))]
    return _cleanup_span(best, max_chars=max_chars)

def split(text: str, size=800, overlap=120) -> List[str]:
    text = re.sub(r"\s+", " ", text).strip()
    parts: List[str] = []
    start = 0
    while start < len(text):
        end = min(start + size, len(text))
        parts.append(text[start:end])
        if end == len(text): break
        start = end - overlap
    return parts

class AskRequest(BaseModel):
    question: str

class CMSItem(BaseModel):
    id: str | None = None
    text: str

class CMSBody(BaseModel):
    items: List[CMSItem]

def _file_type(name: str) -> str:
    return name.rsplit('.', 1)[-1].lower() if '.' in name else 'unknown'

def polish_answer(text: str, max_len: int = 220) -> str:
    text = re.sub(r"\s+", " ", text).strip()
    if len(text) > max_len:
        m = re.search(r"^(.{80,}?[\.\!\?])(.*)$", text)
        text = m.group(1) if m else (text[:max_len-1] + "…")
    if text:
        text = text[0].upper() + text[1:]
    return text
def _near_identical(a: str, b: str) -> bool:
    na, nb = _norm_text(a), _norm_text(b)
    return not na or na == nb or na in nb or nb in na

def _extract_email(text: str) -> Optional[str]:
    m = re.search(r'[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}', text or '')
    return m.group(0) if m else None

def _one_sentence_from_span(span: str, question: str, max_chars: int = 160) -> str:
    sents = re.split(r'(?<=[\.\!\?])\s+', _cleanup_span(span or "", max_chars=220))
    q_words = {w for w in re.findall(r'\w+', question.lower()) if len(w) > 2}
    best = max(sents, key=lambda s: sum(1 for w in q_words if w in s.lower()), default=span or "")
    return _cleanup_span(best, max_chars=max_chars)


@app.get("/health")
async def health():
    return {
        "ok": True,
        "backend": "qdrant-cloud",
        "collection": COLLECTION,
        "vector_dim": VECTOR_DIM,
        "reranker": False
    }

@app.post("/upload")
async def upload(file: UploadFile = File(...), x_chat_id: Optional[str] = Header(default=None, alias="X-Chat-Id")):
    if not file.filename:
        raise HTTPException(status_code=400, detail="Brak pliku")

    ext = file.filename.rsplit('.', 1)[-1].lower()
    if ext not in {"txt", "md", "pdf", "docx", "csv"}:
        raise HTTPException(status_code=415, detail=f"Nieobsługiwany typ pliku: .{ext}")

    raw = await file.read()
    try:
        text = parse_bytes(file.filename, raw)
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Nie udało się odczytać pliku: {e}")

    chunks = split(text)
    if not chunks:
        return {"ok": True, "filename": file.filename, "chunks": 0}

    vecs = await to_thread.run_sync(encode, chunks)
    ftype = _file_type(file.filename)
    session_id = x_chat_id or "default"
    payloads = [{
        "text": c,
        "source": file.filename,
        "file_type": ftype,
        "chunk_id": i,
        "session_id": session_id,
    } for i, c in enumerate(chunks)]

    await to_thread.run_sync(upsert_chunks, client, vecs, payloads)
    return {"ok": True, "filename": file.filename, "size_bytes": len(raw), "chunks": len(chunks)}

@app.post("/cms")
async def cms_import(body: CMSBody, x_chat_id: Optional[str] = Header(default=None, alias="X-Chat-Id")):
    session_id = x_chat_id or "default"
    all_chunks: List[str] = []
    payloads = []
    for it in body.items:
        cs = split(it.text)
        all_chunks.extend(cs)
        payloads.extend([{
            "text": c,
            "source": it.id or "cms",
            "file_type": "cms",
            "chunk_id": i,
            "session_id": session_id,
        } for i, c in enumerate(cs)])
    if not all_chunks:
        return {"ok": True, "count": 0}
    vecs = await to_thread.run_sync(encode, all_chunks)
    await to_thread.run_sync(upsert_chunks, client, vecs, payloads)
    return {"ok": True, "count": len(all_chunks)}

@app.post("/ask")
def ask(payload: AskRequest, x_chat_id: Optional[str] = Header(default=None, alias="X-Chat-Id")):
    session_id = x_chat_id or "default"

    qv = encode([payload.question])[0]

    hits = qsearch(client, qv, k=8, session_id=session_id)
    if not hits:
        return {
            "answer": "Brak danych w tym czacie. Wgraj plik lub zaimportuj CMS i spróbuj ponownie.",
            "sources": []
        }

    hits = rerank_hits(payload.question, hits, top_k=5)
    contexts = [{
        "text": h.payload.get("text", ""),
        "source": h.payload.get("source", "unknown")
    } for h in hits]
    best_texts = [c["text"] for c in contexts]
    span = pick_best_answer_span(payload.question, best_texts, q_vec=qv, max_chars=140)

    if not span and best_texts:
        span = best_texts[0]

    chosen_source = contexts[0]["source"] if contexts else "unknown"
    chosen_score = float(getattr(hits[0], "score", 0.0)) if hits else 0.0

    if span:
        ns = _norm_text(span)
        for h in hits:
            txt = h.payload.get("text", "")
            if ns and ns in _norm_text(txt):
                chosen_source = h.payload.get("source", chosen_source)
                chosen_score = float(getattr(h, "score", chosen_score))
                break

    candidate_contexts = [{"text": span or "", "source": chosen_source}]
    try:
        if not llm_ready():
            raise RuntimeError("LLM not ready")

        raw = (generate_answer(payload.question, candidate_contexts) or "").strip()


        if _near_identical(raw, span or ""):
            answer = _one_sentence_from_span(span or "", payload.question)
        else:
            answer = polish_answer(raw)

    except Exception:
        best_texts = [c["text"] for c in contexts[:3]]
        span2 = pick_best_answer_span(payload.question, best_texts, q_vec=qv, max_chars=140)
        answer = polish_answer(span2 or span or "Nie mam tego w danych.")


    sources = [f'{chosen_source} (score {chosen_score:.2f})']


    return {"answer": answer, "sources": sources}
