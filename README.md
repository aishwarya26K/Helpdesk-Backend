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
| v3 | Streaming + persona | ✅ |
| v4 | Token & cost tracking | ✅ |
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

- `POST /ask` — `{ "text": string }` → `text/plain` streamed response (not JSON)
  Appends to a server-side conversation history and includes the full
  history in each call to the model, so follow-up questions retain context.
  As of v3, the reply streams token-by-token via `StreamingResponse`
  (`stream=True` on the OpenAI call), and the full accumulated reply is
  appended to history only after the stream completes. The system prompt
  gives the assistant a NoonBazaar support persona (warm, concise,
  ≤3 sentences, never invents order details).
- `POST /reset` — no body → `{ "status": "reset" }`
  Clears conversation history back to just the system prompt (and the
  running session cost).

As of v4, every `/ask` reply ends with a footer line —
`[N tokens · $cost · session: $total]` — appended to the same text
stream, so no frontend changes were needed to display it.

## Cost tracking — pricing assumptions

Per-request cost is computed from OpenAI's own reported `usage`
(`prompt_tokens` / `completion_tokens`, returned on the final chunk via
`stream_options={"include_usage": True}`), **not** from `tiktoken`
estimates — `usage` is the source of truth for real dollar cost.
`tiktoken` (`o200k_base` encoding) is used only offline, to enforce the
history token budget before each request.

Pricing constants (`IN_PRICE`, `OUT_PRICE` in `app.py`), in USD per
1M tokens for `gpt-5.4-mini`:

| | Price per 1M tokens |
|---|---|
| Input (prompt) | $0.15 |
| Output (completion) | $0.60 |

⚠️ These are illustrative placeholder values, not verified against
OpenAI's current published pricing for this model — check
platform.openai.com/pricing and update the constants (and this table)
if they're off before treating `session_cost` as a real budget signal.

**History truncation:** conversation history is capped at
`MAX_HISTORY_TOKENS = 3000` tokens (configurable in `app.py`). The
system prompt is always preserved; the oldest user/assistant turns are
dropped first once the budget is exceeded, so long conversations keep
working instead of hitting a context-length error — verified manually
with a 35-request stress test (steady token growth, then a stable
plateau once trimming engaged, no errors).
