# webowy-chatbot

Ten projekt to prosty chatbot, który czyta PDF/DOCX/TXT/CSV i treści CMS, robi embeddingi (MiniLM-L6-v2) i zapisuje do Qdrant. Front to HTML/CSS/JS.

Co działa:
- upload plików i parsowanie do tekstu,
- embeddingi + wektorowe wyszukiwanie (Qdrant),
- pytania z czatu,
- import treści przez API (POST /cms)

---
Szybki start lokalnie (Windows / PowerShell):
1)Zainstaluj Python 3.10+ i Git.
2) Skonfiguruj zmienne środowiskowe
Utwórz plik .env w katalogu backend projektu (na podstawie poniższego wzoru) i uzupełnij swoje wartości:
QDRANT_URL=
QDRANT_API_KEY=
LLM_PROVIDER=groq
GROQ_API_KEY=
GROQ_MODEL=llama-3.1-8b-instant
HF_TOKEN=
EMBED_MODEL=sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2
3) Uruchom Qdrant poprzez ustawianie wartości QDRANT_URL i QDRANT_API_KEY.
4) W PowerShell przejdź do backendowego folderu projektu i wpisz:
python -m venv .venv
. .\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
uvicorn app:app --reload --port 8000
5) Odpal frontend (statyczny serwer w drugim oknie: python -m http.server 5500 
Otwórz przeglądarkę: http://localhost:5500/frontend/

Struktura projektu
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