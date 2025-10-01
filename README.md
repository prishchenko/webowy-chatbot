# webowy-chatbot

Ten projekt to prosty chatbot, który czyta PDF/DOCX/TXT/CSV i treści z CMS (JSON), robi embeddingi (MiniLM), zapisuje je w Qdrant, a następnie odpowiada na pytania z czatu na bazie najbliższych semantycznie fragmentów i (opcjonalnie, jeśli ustawiono klucz Groq) skraca odpowiedź. Front to HTML/CSS/JS.

<img width="1920" height="910" alt="UI czatu" src="https://github.com/user-attachments/assets/634dad0f-be28-46b1-8a48-ce44c5232d26" />

## Linki
- **Repozytorium:** [https://github.com/prishchenko/webowy-chatbot](https://github.com/prishchenko/webowy-chatbot)
- **Frontend (live):** [https://prishchenko.github.io/webowy-chatbot/](https://prishchenko.github.io/webowy-chatbot/)  
- **Backend API (live):** [https://webowy-chatbot.onrender.com/](https://webowy-chatbot.onrender.com)  
  - Healthcheck: [https://webowy-chatbot.onrender.com/health](https://webowy-chatbot.onrender.com/health)

## Funkcje:
- Upload i parsowanie: .txt/.md, .pdf, .docx, .csv → tekst, chunkowanie, wektory. Limit pliku: 20 MB
- Import treści z CMS (JSON)
- Wektoryzacja (paraphrase-multilingual-MiniLM-L12-v2 / all-MiniLM-L6-v2 przez Hugging Face Inference API)
- Przechowywanie i wyszukiwanie w Qdrant (kolekcja chat_chunks, COSINE)
- Odpowiedzi na bazie najbliższych fragmentów
- "Polerowanie" odpowiedzi przez Groq (LLM), dzięki czemu odpowiedzi są krótsze i bardziej zwarte
- UI: historia czatów (localStorage), X-Chat-Id → separacja sesji w Qdrant, drag&drop, upload wielu plików

#### Wybór modelu embeddingów:
Domyślnie w kodzie: sentence-transformers/all-MiniLM-L6-v2 (angielski, 384).  
Opcja PL/multi: sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2 (lepiej pokrywa polski, 384).  
Oba mają wymiar 384, więc nie trzeba zmieniać kolekcji w Qdrant.  
Ustawić model można przez zmienną .env EMBED_MODEL.  

## Szybki start lokalnie (Windows / PowerShell)
#### Wymagania
- Python 3.11+
- (Opcjonalnie) Docker do Qdrant lokalnie
- Klucz HF / Groq (opcjonalnie — dla stabilniejszego działania)
##### 1) Zmienne środowiskowe
Utwórz plik backend/.env i uzupełnij własne wartości.  
`QDRANT_URL=http://localhost:6333`  
`QDRANT_API_KEY=`   
`LLM_PROVIDER=groq`   
`GROQ_API_KEY=`   
`GROQ_MODEL=llama-3.1-8b-instant`   
`HF_TOKEN=`   
`EMBED_MODEL=sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2`   
`ALLOW_ORIGINS=http://127.0.0.1:5500,http://localhost:5500,https://prishchenko.github.io`   

Oba modele embeddingów mają 384 (nie trzeba zmieniać kolekcji w Qdrant).
##### 2) Qdrant Cloud: ustaw QDRANT_URL i QDRANT_API_KEY na dane z Twojej instancji.
##### 3) Zmień w frontend/config.js
window.API_BASE = 'http://127.0.0.1:8000';
##### 4) Backend (FastAPI)
W folderze backend:
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
uvicorn app:app --reload --port 8000
##### 5) Frontend (statyczny serwer)
W drugim oknie PowerShell, w folderze project:
`cd frontend`  
`python -m http.server 5500`  
##### 6) Otwórz: http://localhost:5500/

## Deploy
**Backend (Render)**
1. Utwórz Web Service (Python 3.11+), komenda: `uvicorn app:app --host 0.0.0.0 --port $PORT`.
2. Ustaw `.env` (co najmniej: `QDRANT_URL`, `QDRANT_API_KEY`, `EMBED_MODEL`; opcj.: `HF_TOKEN`, `LLM_PROVIDER`, `GROQ_API_KEY`, `GROQ_MODEL`, `ALLOW_ORIGINS`).
3. Skopiuj URL: np. `https://webowy-chatbot.onrender.com`.

**Frontend (GitHub Pages)**
1. W `frontend/config.js` ustaw: `window.API_BASE = 'https://webowy-chatbot.onrender.com';`;
2. Opublikuj katalog frontend/ jako Pages (np. przenieś do docs/ i włącz Pages z docs/).
3. Wejdź na stronę: [https://prishchenko.github.io/webowy-chatbot/](https://prishchenko.github.io/webowy-chatbot/)

## Jak używać?
1. Wgraj plik(i) lub wyślij JSON przez **/cms** z poziomu UI (spinacz / drag&drop).
2. Zadaj pytanie w czacie. Bot znajdzie najbliższe semantycznie fragmenty i skraca odpowiedź przez Groq.

## Struktura projektu
project/  
│  
├── frontend/  
│   ├── index.html  
│   ├── styles.css  
│   ├── chatbot.js  
│   └── styles/  
│  
│  
├── backend/  
│   ├── app.py (FastAPI)  
│   ├── qdrant_utils.py  
│   ├── embeddings.py  
│   ├── document_parser.py  
│   ├── llm.py  
│   ├── .env  
│   └── requirements.txt  
│  
└── README.md  
