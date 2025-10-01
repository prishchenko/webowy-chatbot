import os
import re
import unicodedata
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
from fastapi.exceptions import RequestValidationError
from qdrant_utils import delete_session



def _env_list(name: str, default: str) -> List[str]:
    return [o.strip().rstrip("/") for o in os.getenv(name, default).split(",") if o.strip()]
MIN_SIM = float(os.getenv("MIN_SIM", "0.10"))
app = FastAPI(title="Chatbot API (Qdrant Cloud)", description="Czat + upload + embeddingi + CMS")
ALLOW_ORIGINS = _env_list(
    "ALLOW_ORIGINS",
    "http://127.0.0.1:5500,http://localhost:5500,https://prishchenko.github.io"
)

ALLOW_CREDENTIALS = False

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



@app.exception_handler(RequestValidationError)
async def pydantic_422(request: Request, exc: RequestValidationError):
    path = request.url.path
    if path == "/cms":
        detail = "Nieprawidłowy JSON. Dla /cms oczekuję: { items: [ { id?: string, text: string }, ... ] }"
    elif path == "/ask":
        detail = "Nieprawidłowy JSON. Dla /ask oczekuję: { \"question\": \"...\" }"
    else:
        detail = "Nieprawidłowy JSON w żądaniu."
    return JSONResponse({"detail": detail, "errors": exc.errors()}, status_code=422)



MAX_BYTES = 20 * 1024 * 1024

@app.middleware("http")
async def limit_body(request: Request, call_next):
    if request.url.path in ("/upload", "/cms"):
        cl = request.headers.get("content-length")
        if cl and cl.isdigit():
            if int(cl) > MAX_BYTES:
                return JSONResponse({"detail": f"Payload za duży (max {MAX_BYTES // (1024*1024)} MB)"},
                                    status_code=413)
    return await call_next(request)


QDRANT_URL = os.getenv("QDRANT_URL", "http://localhost:6333")
QDRANT_API_KEY = os.getenv("QDRANT_API_KEY")
VECTOR_DIM = int(os.getenv("VECTOR_DIM", "0"))
if not VECTOR_DIM:
    try:
        VECTOR_DIM = len(encode(["__probe__"])[0])
    except Exception:
        VECTOR_DIM = 384

client = connect(QDRANT_URL, QDRANT_API_KEY)
ensure_collection(client, dim=VECTOR_DIM)
ensure_payload_indexes(client)

@app.delete("/purge")
def purge(x_chat_id: Optional[str] = Header(default=None, alias="X-Chat-Id")):
    if not x_chat_id:
        raise HTTPException(status_code=400, detail="Brak X-Chat-Id")
    try:
        delete_session(client, x_chat_id)
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"Qdrant purge failed: {e}")
    return {"ok": True, "purged_session": x_chat_id}

def preprocess_text(text: str) -> str:
    if not text:
        return text
    text = text.replace("\u200b", "").replace("\ufeff", "")
    text = text.replace("\u00ad", "").replace("\u2011", "-")
    text = re.sub(r"(\w)-\s+(\w)", r"\1\2", text)
    text = text.replace("„", "\"").replace("”", "\"").replace("‚","'").replace("’","'")
    text = unicodedata.normalize("NFKC", text)
    return text

def _overlap_bonus(question: str, text: str) -> int:
    q = {w for w in re.findall(r"\w+", (question or "").lower()) if len(w) >= 3}
    t = set(re.findall(r"\w+", (text or "").lower()))
    return len(q & t)

def _exact_phrase_bonus(question: str, text: str) -> float:
    q_words = [w for w in re.findall(r"\w+", (question or "").lower()) if len(w) >= 3]
    if len(q_words) < 3:
        return 0.0
    low = re.sub(r"\s+", " ", (text or "").lower())
    for win in range(7, 2, -1):
        for i in range(0, len(q_words) - win + 1):
            frag = " ".join(q_words[i:i+win])
            if frag in low:
                return 0.35
    return 0.0

def rerank_hits(question: str, hits, top_k: int = 8):
    scored = []
    for h in hits:
        base = float(getattr(h, "score", 0.0))
        txt  = h.payload.get("text", "")
        score = base + 0.06 * _overlap_bonus(question, txt) + _exact_phrase_bonus(question, txt)
        scored.append((score, h))
    scored.sort(key=lambda x: x[0], reverse=True)
    return [h for _, h in scored[:top_k]]



def _cleanup_span(s: str, max_chars: int = 220) -> str:
    s = re.sub(r"\s+", " ", s).strip()
    s = re.sub(r"\s+([,\.:\;\!\?])", r"\1", s)
    if len(s) > max_chars:
        m = re.search(r"^(.{80,}?[\.\!\?])(.*)$", s)
        s = m.group(1) if m else (s[:max_chars-1] + "…")
    return s[0].upper() + s[1:] if s else s

def norm_for_embed(s: str) -> str:
    s = unicodedata.normalize('NFC', s or '')
    s = re.sub(r'\s+', ' ', s).strip()
    return s.lower()

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


    clean = [c for c in cands if len(c) >= 20]

    seen, uniq = set(), []
    for c in clean:
        if c not in seen:
            seen.add(c); uniq.append(c)
    return uniq

def _norm_text(s: str) -> str:
    return re.sub(r"\s+", " ", (s or "")).strip().lower()

def pick_best_answer_span(question: str, fragments: Iterable[str], q_vec: Optional[List[float]] = None,
                          max_chars: int = 220) -> tuple[Optional[str], Optional[int]]:
    candidates: List[str] = []
    origins: List[int] = []

    for i, frag in enumerate(fragments):
        spans = _candidate_spans_from_fragment(frag, max_chars=max_chars)
        candidates.extend(spans)
        origins.extend([i] * len(spans))

    if not candidates:
        return None, None

    if len(candidates) > 80:
        candidates = candidates[:80]
        origins = origins[:80]

    if q_vec is None:
        q_vec = encode([norm_for_embed(question)])[0]

    win_vecs = encode([norm_for_embed(c) for c in candidates])

    def _norm(v):
        v = np.asarray(v, dtype=np.float32)
        n = np.linalg.norm(v)
        return v if n == 0 else v / n

    qv = _norm(q_vec)
    scores = [float(np.dot(qv, _norm(w))) for w in win_vecs]
    best_idx = int(np.argmax(scores))
    best_span = _cleanup_span(candidates[best_idx], max_chars=max_chars)
    return best_span, origins[best_idx]


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
        "reranker": True
    }

@app.post("/upload")
async def upload(file: UploadFile = File(...), x_chat_id: Optional[str] = Header(default=None, alias="X-Chat-Id")):
    if not file.filename:
        raise HTTPException(status_code=400, detail="Brak pliku")

    ext = file.filename.rsplit('.', 1)[-1].lower()
    if ext not in {"txt", "md", "pdf", "docx", "csv"}:
        raise HTTPException(status_code=415, detail=f"Nieobsługiwany typ pliku: .{ext}")

    raw = await file.read()
    if len(raw) > MAX_BYTES:
        raise HTTPException(status_code=413, detail="Plik za duży (max 20 MB)")

    try:
        text = preprocess_text(parse_bytes(file.filename, raw))
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Nie udało się odczytać pliku: {e}")

    chunks = split(text)
    if not chunks:
        return {"ok": True, "filename": file.filename, "chunks": 0}

    norm_chunks = [norm_for_embed(c) for c in chunks]
    vecs = await to_thread.run_sync(encode, norm_chunks)
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
async def cms_import(
    body: CMSBody,
    request: Request,
    x_chat_id: Optional[str] = Header(default=None, alias="X-Chat-Id"),
):
    if "application/json" not in (request.headers.get("content-type") or "").lower():
        raise HTTPException(status_code=415, detail="Użyj Content-Type: application/json")

    session_id = x_chat_id or "default"
    total_len = sum(len((it.text or "")) for it in body.items)
    if total_len > 5_000_000:
        raise HTTPException(status_code=413, detail="Za duży JSON (limit ~5 MB tekstu)")

    all_chunks: List[str] = []
    payloads = []
    for it in body.items:
        t = (it.text or "").strip()
        if not t:
            continue
        cs = split(preprocess_text(t))
        all_chunks.extend(cs)
        payloads.extend([{
            "text": c,
            "source": (it.id or "cms"),
            "file_type": "cms",
            "chunk_id": i,
            "session_id": session_id,
        } for i, c in enumerate(cs)])

    if not all_chunks:
        return {"ok": True, "count": 0}

    norm_chunks = [norm_for_embed(c) for c in all_chunks]
    vecs = await to_thread.run_sync(encode, norm_chunks)
    await to_thread.run_sync(upsert_chunks, client, vecs, payloads)
    return {"ok": True, "count": len(all_chunks)}


VOWELS = set("aeiouyąęóAEIOUYĄĘÓ")

def likely_gibberish(s: str) -> bool:
    s = (s or "").strip()
    letters = [ch for ch in s if ch.isalpha()]
    if len(letters) < 2:
        return True
    v = sum(ch in VOWELS for ch in letters)
    return (v / len(letters)) < 0.2

@app.post("/ask")
def ask(payload: AskRequest, x_chat_id: Optional[str] = Header(default=None, alias="X-Chat-Id")):
    session_id = x_chat_id or "default"

    q = (payload.question or "").strip()
    if likely_gibberish(q):
        return {
            "answer": "Nie rozumiem pytania. Napisz je proszę pełnym zdaniem.",
            "sources": []
        }
    try:
        qv = encode([norm_for_embed(q)])[0]
    except Exception:
        raise HTTPException(status_code=502, detail="Embedding service unavailable (HF). Spróbuj ponownie za chwilę.")
    try:
        hits_raw = qsearch(client, qv, k=64, session_id=session_id)
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"Błąd zapytania do Qdrant: {e}")
    if not hits_raw:
        return {
            "answer": "Brak danych w tym czacie. Wgraj plik lub zaimportuj CMS i spróbuj ponownie.",
            "sources": []
        }

    raw_best_hit = max(hits_raw, key=lambda h: float(getattr(h, "score", 0.0)))
    best_raw = float(getattr(raw_best_hit, "score", 0.0))

    hits = rerank_hits(q, hits_raw, top_k=8)
    if not hits:
        return {"answer": "Nie mam tego w danych.", "sources": []}

    top_txt = hits[0].payload.get("text", "")
    lex_ok = (_overlap_bonus(q, top_txt) >= 2) or (_exact_phrase_bonus(q, top_txt) > 0)
    if (best_raw < MIN_SIM) and not lex_ok:
        return {
            "answer": "Nie mam tego w danych.",
            "sources": [f"{raw_best_hit.payload.get('source', 'unknown')} (score {best_raw:.2f})"]
        }

    best_texts = [h.payload.get("text", "") for h in hits]
    span, origin_idx = pick_best_answer_span(q, best_texts, q_vec=qv, max_chars=140)
    if origin_idx is None:
        origin_idx = 0
    if not span:
        span = best_texts[origin_idx] if best_texts else ""

    chosen_hit = hits[origin_idx]

    chosen_source = chosen_hit.payload.get("source", "unknown")
    chosen_score = float(getattr(chosen_hit, "score", 0.0))
    chosen_chunk = int(chosen_hit.payload.get("chunk_id", -1))
    chosen_type = chosen_hit.payload.get("file_type", "unknown")
    sources = [f"{chosen_source} (score {chosen_score:.2f})"]

    candidate_contexts = [{
        "text": chosen_hit.payload.get("text", ""),
        "source": chosen_source
    }]
    sources_meta = [{
        "source": chosen_source,
        "chunk_id": chosen_chunk,
        "file_type": chosen_type,
        "score": round(chosen_score, 4),
    }]
    if not llm_ready():
        answer = _one_sentence_from_span(span or (best_texts[0] if best_texts else ""), q)
    else:
        try:
            raw_ans = (generate_answer(q, candidate_contexts) or "").strip()
            if _near_identical(raw_ans, span or ""):
                answer = _one_sentence_from_span(span or "", q)
            else:
                answer = polish_answer(raw_ans)
        except Exception:
            answer = _one_sentence_from_span(span or (best_texts[0] if best_texts else ""), q)

    return {"answer": answer, "sources": sources, "sources_meta": sources_meta}