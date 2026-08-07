# HelpDesk Support Assistant — Backend

FastAPI backend for the HelpDesk Support Assistant capstone project — a
customer-support chatbot for a fictional Dubai e-commerce company, built
incrementally from basic Q&A through memory, streaming, cost tracking,
structured output, auth, caching, and production deployment.

Companion frontend repo: https://github.com/aishwarya26K/Helpdesk-Frontend

## Tech Stack
- FastAPI + Python (:8000)
- OpenAI API

## Progress
| Version | Feature | Status |
|---|---|---|
| v1 | Basic Q&A | ✅ |
| v2 | Conversation memory | ✅ |
| v3 | Streaming + persona | ⬜ not started |
| v4 | Token & cost tracking | ⬜ not started |
| v5 | Structured output | ⬜ not started |
| v6 | Auth & per-user history | ⬜ not started |
| v7 | Redis & concurrency | ⬜ not started |
| v8 | Production deployment | ⬜ not started |

## Running locally

```
python -m venv venv
venv\Scripts\Activate.ps1   # Windows PowerShell
pip install -r requirements.txt
# create .env with OPENAI_API_KEY=...
uvicorn app:app --reload
```

## API

- `POST /ask` — `{ "text": string }` → `{ "answer": string }`
  Appends to a server-side conversation history and includes the full
  history in each call to the model, so follow-up questions retain context.
- `POST /reset` — no body → `{ "status": "reset" }`
  Clears conversation history back to just the system prompt.
