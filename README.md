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
| v5 | Structured JSON tickets (JSON mode + schema validation) | ✅ |
| v6 | Supabase Auth + per-user history in Postgres | ✅ |
| v7 | Redis & concurrency | ⬜ not started |
| v8 | Production deployment | ⬜ not started |

## Running locally

```
python -m venv venv
venv\Scripts\Activate.ps1   # Windows PowerShell
pip install -r requirements.txt
# create .env with OPENAI_API_KEY=..., SUPABASE_URL=..., SUPABASE_SERVICE_KEY=...
uvicorn app:app --reload
```

## API

As of v6, every route below requires an `Authorization: Bearer <jwt>`
header — a valid Supabase Auth access token. Requests without one (or
with an invalid/expired one) get a `401` before the route body runs.

- `POST /ask` — `{ "text": string }` → `text/plain` streamed response (not JSON)
  Loads the authenticated user's conversation history from Postgres,
  includes it in the call to the model so follow-up questions retain
  context, and saves both the question and the full reply back to
  Postgres once the stream completes. The reply still streams
  token-by-token via `StreamingResponse` (`stream=True`). The system
  prompt gives the assistant a NoonBazaar support persona (warm,
  concise, ≤3 sentences, never invents order details).
- `POST /reset` — no body → `{ "status": "reset" }`
  Deletes the authenticated user's rows from the `messages` table
  (and resets the running session cost).

As of v4, every `/ask` reply ends with a footer line —
`[N tokens · $cost · session: $total]` — appended to the same text
stream, so no frontend changes were needed to display it.
- `POST /ticket` — no body → a validated `Ticket` JSON object:
  `{ category, urgency, summary, order_id }`.
  Sends the conversation so far plus a one-off instruction message
  (`role: "user"`, kept out of `history` so it doesn't pollute
  conversational memory) asking the model to summarize it as a
  support ticket. The call uses `response_format={"type": "json_object"}`
  (JSON mode) to guarantee syntactically valid JSON, then parses that
  JSON into a `Ticket` Pydantic model — `category` and `urgency` are
  `Literal` enums, so any value outside the allowed set fails
  validation. Both `json.JSONDecodeError` and Pydantic's
  `ValidationError` are caught and turned into a `422` with the
  validation detail in the response body, instead of a raw 500.
  `order_id` is `Optional[str]`, and the prompt explicitly instructs
  the model not to invent one that was never mentioned. Also requires
  auth as of v6, and loads that user's history the same way `/ask`
  does. The generated ticket itself is returned in the response but
  not persisted anywhere — no `tickets` table exists yet.

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

## Structured output — validation & rejection

`Ticket` (in `app.py`) uses `Literal["order", "refund", "technical",
"account", "other"]` for `category` and `Literal["low", "medium",
"high"]` for `urgency`. Verified directly that Pydantic rejects an
out-of-enum value:

```python
>>> Ticket(category="shipping_delay", urgency="low", summary="test", order_id=None)
pydantic_core._pydantic_core.ValidationError: 1 validation error for Ticket
category
  Input should be 'order', 'refund', 'technical', 'account' or 'other'
  [type=literal_error, input_value='shipping_delay', input_type=str]
```

That `ValidationError` is exactly what `/ticket` catches and turns
into a `422`. In practice, `gpt-5.4-mini` reliably self-corrects to a
valid category even when the prompt's enum list is loosened, so
triggering that same rejection live through the endpoint is hard to
force — the model's own output rarely strays outside the allowed set.
The direct test above is the authoritative proof that the validation
layer itself works; the endpoint's `try/except` around
`json.JSONDecodeError` and `ValidationError` is the same code path
that would fire if it ever did.

## v6 — Supabase Auth + per-user history in Postgres

The shared in-memory `history` list from v1–v5 is gone. Conversation
history now lives in a `messages` table in Postgres (Supabase),
scoped per user:

```sql
create table messages (
  id          bigint generated always as identity primary key,
  user_id     uuid not null references auth.users(id),
  role        text not null,
  content     text not null,
  created_at  timestamptz default now()
);
create index on messages (user_id, created_at);
alter table messages enable row level security;
create policy "own messages" on messages
  for all using (auth.uid() = user_id);
```

`auth.py` verifies the `Authorization: Bearer <jwt>` header on every
request via `sb.auth.get_user(token)` — the `user_id` is always
derived from the verified token server-side, never trusted from the
client. `app.py` uses `Depends(get_user_id)` on `/ask`, `/ticket`,
and `/reset` so an invalid/missing token is rejected before any route
logic runs. `load_history()` / `save_message()` replace the old list
with Postgres reads/writes, and v4's `trim_history()` token-budget
logic still runs on the loaded rows.

The backend connects with the `service_role` key (bypasses RLS,
backend-only, never exposed to the frontend) — RLS is still enabled
on the table as a defense-in-depth backstop in case application code
ever has a bug, verified directly:

```sql
set role anon;
select * from messages;
-- returns zero rows: no session, so auth.uid() matches nothing
```

**Verified:**
- Two accounts, two histories — separate `user_id`s in the table,
  confirmed no cross-contamination between accounts, both via direct
  `curl` requests and the frontend UI (after fixing a frontend bug
  where local chat state wasn't cleared on account switch)
- Durability — restarted `uvicorn` mid-conversation, history was
  still there on the next request, proving it's read from Postgres
  and not held in the Python process's memory
- RLS — confirmed the `anon` role cannot read any rows without a
  valid session, independent of the FastAPI app's own checks
