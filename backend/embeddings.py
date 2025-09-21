import os, requests, numpy as np

def _model():
    return (os.getenv("EMBED_MODEL") or "sentence-transformers/all-MiniLM-L6-v2").strip()

def _headers():
    tok = (os.getenv("HF_TOKEN") or "").strip()
    h = {"Content-Type": "application/json"}
    if tok: h["Authorization"] = f"Bearer {tok}"
    return h

BATCH = int(os.getenv("EMBED_BATCH", "16"))
TIMEOUT = int(os.getenv("HF_TIMEOUT", "90"))

def _post(url, payload):
    r = requests.post(url, headers=_headers(), json=payload, timeout=TIMEOUT)
    try:
        data = r.json()
    except Exception:
        data = r.text
    if r.status_code >= 400:
        raise RuntimeError(f"HF {r.status_code} @ {url} -> {data}")
    return data

def _l2(v):
    v = np.asarray(v, dtype="float32"); n = np.linalg.norm(v)
    return (v if n == 0 else v / n).tolist()

def _pool(x):
    x = np.asarray(x, dtype="float32")
    if x.ndim == 2: x = x.mean(axis=0)
    else:           x = x.reshape(-1)
    return _l2(x)

def encode(texts):
    m = _model()
    urls = [
        f"https://router.huggingface.co/hf-inference/models/{m}/pipeline/feature-extraction",
        f"https://api-inference.huggingface.co/pipeline/feature-extraction/{m}",
    ]

    out = []
    for i in range(0, len(texts), BATCH):
        batch = texts[i:i+BATCH]
        payload = {"inputs": batch, "options": {"wait_for_model": True}}

        last_err = None
        for url in urls:
            try:
                data = _post(url, payload)
                break
            except RuntimeError as e:
                last_err = e
                continue
        else:
            msg = str(last_err)
            if "SentenceSimilarityPipeline" in msg:
                raise RuntimeError(
                    f"Model '{m}' działa jako sentence-similarity. "
                    f"Użyj endpointu 'pipeline/feature-extraction' (patrz router HF) lub zmień model."
                )
            raise last_err

        for item in data:
            if isinstance(item, list) and item and isinstance(item[0], (float, int)):
                out.append(_l2(item))
            else:
                out.append(_pool(item))
    return out
