# webowy-chatbot

Ten projekt to prosty chatbot, który czyta PDF/DOCX/TXT/CSV i treści z API, robi embeddingi (MiniLM) i zapisuje do Qdrant. Front to HTML/CSS/JS.

## Co działa:
- upload plików i parsowanie do tekstu,
- embeddingi + wektorowe wyszukiwanie (Qdrant),
- pytania z czatu,
- import treści przez API (POST /cms)

#### Wybór modelu embeddingów:
Domyślnie w kodzie: sentence-transformers/all-MiniLM-L6-v2 (angielski, 384).
Opcja PL/multi: sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2 (lepsze pokrywa PL, 384).
Oba mają wymiar 384, więc nie trzeba zmieniać kolekcji w Qdrant.
Ustawić model można przez zmienną .env EMBED_MODEL.

## Szybki start lokalnie (Windows / PowerShell)
##### 1) Zmienne środowiskowe
Utwórz plik backend/.env i uzupełnij własne wartości.
QDRANT_URL=http://localhost:6333
QDRANT_API_KEY=
LLM_PROVIDER=groq
GROQ_API_KEY=
GROQ_MODEL=llama-3.1-8b-instant
HF_TOKEN=
EMBED_MODEL=sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2
##### 2) Qdrant Cloud: ustaw QDRANT_URL i QDRANT_API_KEY na dane z Twojej instancji.
##### 3) Backend (FastAPI)
W folderze backend:
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
uvicorn app:app --reload --port 8000
#### 4) Frontend (statyczny serwer)
W drugim oknie PowerShell, w folderze project:
python -m http.server 5500
##### 5) Otwórz: http://localhost:5500/frontend/

## Struktura projektu
project/
│
├── frontend/
│   ├── index.html
│   ├── styles.css
│   ├── chatbot.js
│   └── styles/
│
├── backend/
│   ├── app.py
│   ├── qdrant_utils.py
│   ├── embeddings.py
│   ├── document_parser.py
│   ├── llm.py
│   ├── requirements.txt
│   └── .env   (lokalne, nie commitować)
│
└── README.md
