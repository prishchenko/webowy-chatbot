import os, time, requests

def _clean(s: str) -> str:
    return (s or "").strip().strip('"').strip("'")

PROVIDER = _clean(os.getenv("LLM_PROVIDER") or "groq").lower()

GROQ_BASE = "https://api.groq.com/openai/v1"
def _groq_key() -> str:
    return _clean(os.getenv("GROQ_API_KEY"))
GROQ_MODEL = _clean(os.getenv("GROQ_MODEL") or "llama-3.1-8b-instant")
LLM_TIMEOUT = int(os.getenv("HF_LLM_TIMEOUT", "90"))

SYS_PROMPT = (
    "Przepisz podany fragment na 1–2 naturalne zdania po polsku, "
    "ODPOWIADAJĄC WYŁĄCZNIE NA PYTANIE. Nie dodawaj nowych faktów. "
    "Zachowaj liczby/kwoty/jednostki. Jeśli fragment nie zawiera odpowiedzi: "
    "'Nie mam tego w danych.'"
)

def _build_user_prompt(question: str, contexts: list[dict]) -> str:
    cand = ((contexts or [{}])[0].get("text") or "").strip()
    if len(cand) > 900:
        cand = cand[:900] + "…"
    return (
        f"PYTANIE: {question}\n"
        f"FRAGMENT:\n---\n{cand}\n---\n\n"
        f"ODPOWIEDŹ (1–2 zdania):"
    )

def generate_answer(question: str, contexts: list[dict]) -> str:
    assert PROVIDER == "groq", "This llm.py is configured for Groq provider."
    key = _groq_key()
    if not key:
        raise RuntimeError("Brak GROQ_API_KEY w .env")

    headers = {
        "Authorization": f"Bearer {key}",
        "Content-Type": "application/json",
    }
    payload = {
        "model": GROQ_MODEL,
        "messages": [
            {"role": "system", "content": SYS_PROMPT},
            {"role": "user", "content": _build_user_prompt(question, contexts)},
        ],
        "temperature": 0.1,
        "max_tokens": 120,
        "stream": False,
    }
    r = requests.post(f"{GROQ_BASE}/chat/completions", headers=headers, json=payload, timeout=LLM_TIMEOUT)
    if r.status_code >= 400:
        raise RuntimeError(f"[LLM] {r.status_code} @ {GROQ_BASE}/chat/completions -> {r.text[:200]}")

    data = r.json()
    try:
        return (data["choices"][0]["message"]["content"] or "").strip()
    except Exception:
        return str(data)

def llm_ready(timeout_sec: int = 8) -> bool:
    try:
        key = _groq_key()
        if not key:
            return False
        r = requests.get(f"{GROQ_BASE}/models", headers={"Authorization": f"Bearer {key}"}, timeout=timeout_sec)
        return r.status_code == 200
    except Exception:
        return False

def llm_healthcheck() -> dict:
    t0 = time.time()
    try:
        key = _groq_key()
        if not key:
            return {"ok": False, "status": 0, "model": GROQ_MODEL, "error": "Brak GROQ_API_KEY"}
        r = requests.post(
            f"{GROQ_BASE}/chat/completions",
            headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"},
            json={
                "model": GROQ_MODEL,
                "messages": [
                    {"role": "system", "content": "Powtórz słowo: test."},
                    {"role": "user", "content": "test"},
                ],
                "max_tokens": 2,
                "temperature": 0.0,
                "stream": False,
            },
            timeout=min(LLM_TIMEOUT, 20),
        )
        ms = round((time.time() - t0) * 1000)
        return {"ok": r.status_code == 200, "status": r.status_code, "ms": ms, "model": GROQ_MODEL, "preview": r.text[:200]}
    except Exception as e:
        ms = round((time.time() - t0) * 1000)
        return {"ok": False, "status": 0, "ms": ms, "model": GROQ_MODEL, "error": str(e)}
