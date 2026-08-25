# HelpDesk Support Assistant — Backend

FastAPI backend for the HelpDesk Support Assistant capstone project — a
customer-support chatbot for a fictional Dubai e-commerce company, built
incrementally from basic Q&A through memory, streaming, cost tracking,
structured output, auth, caching, and production deployment.

Companion frontend repo: https://github.com/aishwarya26K/Helpdesk-Frontend

## Tech Stack
- FastAPI + Python (:8000)
- OpenAI API
- Redis (cache-aside + per-user locks)
- Docker (containerized for deploy)
- Deploy: Render (backend container) · Upstash (managed Redis) · Supabase (DB + Auth)

## Progress
| Version | Feature | Status |
|---|---|---|
| v1 | Basic Q&A | ✅ |
| v2 | Conversation memory | ✅ |
| v3 | Streaming + persona | ✅ |
| v4 | Token & cost tracking | ✅ |
| v5 | Structured JSON tickets (JSON mode + schema validation) | ✅ |
| v6 | Supabase Auth + per-user history in Postgres | ✅ |
| v7 | Redis & concurrency | ✅ |
| v8 | Production deployment | 🚧 code ready — Dockerfile, prod CORS, /health, rate limiting |

**Live:** _backend_ `<RENDER_URL>` · _frontend_ `<VERCEL_URL>` — fill in once deployed.

## Running locally

```
python -m venv venv
venv\Scripts\Activate.ps1   # Windows PowerShell
pip install -r requirements.txt
# create .env with OPENAI_API_KEY=..., SUPABASE_URL=..., SUPABASE_SERVICE_KEY=...,
#   and (v7) REDIS_URL=redis://localhost:6379
brew services start redis    # macOS; must be reachable (redis-cli ping -> PONG)
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

## v7 — Redis cache-aside + per-user locks + non-blocking I/O

A `store.py` data layer now sits in front of Postgres. `app.py`
routes call it instead of touching the DB directly.

**Cache-aside reads.** `load_history(user_id)` tries Redis first
(`GET convo:<user_id>`); on a hit it returns the JSON-decoded history
in sub-milliseconds. On a miss it loads from Postgres (the v6 loader,
still the source of truth), then `SETEX`es the result with a 30-minute
TTL (`TTL = 1800`) so the next read is a hit. Idle conversations
auto-evict when the TTL lapses and simply reload from Postgres on the
next message — cache stays bounded, no manual cleanup.

**Dual-write.** `append_turn(user_id, role, content)` writes Postgres
first (durable), then updates the Redis copy and refreshes the TTL, so
the cache never goes stale behind the DB. `trim_history()` still runs
on the cached list so it honours the v4 token budget. `/ask` calls
`append_turn` for both the user turn and the assistant reply; `/reset`
calls `invalidate(user_id)` (`DEL convo:<user_id>`) after wiping
Postgres so a cache hit can never resurrect deleted history.

Postgres remains authoritative — verified by `redis-cli FLUSHALL`
mid-conversation: the next request logged `cache miss`, reloaded from
Postgres with no data loss, and refilled the cache.

**Per-user lock (concurrency safety).** `with_user_lock(user_id)` does
`SET lock:<user_id> 1 NX EX 5` — only one caller acquires it; it
auto-expires after 5s so a dead request can't deadlock. `/ask` checks
it at entry and returns `429` if a previous message for the same user
is still in flight, so two rapid messages can't interleave and corrupt
the cached list. The key is per `user_id`, never global — different
users never block each other. Verified by firing two concurrent `/ask`
requests with the same token: one `200`, one `429`.

**Non-blocking I/O.** `/ask` is a plain `def` (not `async def`): the
OpenAI and Supabase clients are synchronous, so FastAPI runs the
handler in a threadpool. One user's long (streaming) generation blocks
only its own worker thread, not the event loop, so other users are
served concurrently. Declaring it `async def` while calling sync
clients would have captured the single event-loop thread and
serialized everyone — the opposite of the goal.

**Auth hardening (found during v7 testing).** `get_user_id` now wraps
`sb.auth.get_user(token)` in a `try/except` — the Supabase client
*raises* on an expired/invalid JWT rather than returning an empty
result, which previously surfaced as a `500`. It now returns a clean
`401` on any auth failure.

## v8 — Production deployment

Local dev is gone; the app runs as managed services reachable over the
public internet.

**Topology.**
```
browser → Vercel (Next.js frontend) → HTTPS → Render (FastAPI container)
                                                   ├── Supabase (Postgres + Auth)
                                                   └── Upstash (managed Redis, rediss:// TLS)
```

**Containerized.** A `Dockerfile` (`python:3.12-slim`) packages the
backend. `requirements.txt` is copied and installed *before* the app
code so the dependency layer stays cached across code edits. The
container listens on `0.0.0.0:${PORT:-8000}` — `0.0.0.0` so the host
can route traffic in, `$PORT` because Render injects its own. A
`.dockerignore` keeps `venv/`, `.env`, `__pycache__`, and `.git` out of
the image. Render builds the Dockerfile in its own cloud on every
`git push`; no local Docker required.

**Secrets via env, never committed.** All secrets
(`OPENAI_API_KEY`, `SUPABASE_SERVICE_KEY`, `REDIS_URL`, `FRONTEND_URL`)
live in Render's dashboard and are read with `os.environ[...]`. Only
`.env.example` (variable *names*, no values) is committed; `.env` stays
gitignored.

**Production CORS.** `allow_origins` is now
`[os.environ.get("FRONTEND_URL", "http://localhost:3000")]` — the
deployed Vercel URL in prod, localhost as the dev fallback. Wrong
origin = browser blocks every call ("works locally, blocked in prod"),
so `FRONTEND_URL` must exactly match the Vercel domain.

**Health check.** `GET /health` returns `{"ok": true}` (no auth) so
Render can poll it and auto-restart a dead container.

**Rate limiting.** `rate_limit_ok(user_id)` in `store.py` uses a Redis
fixed-window counter — `INCR rate:<user_id>`, `EXPIRE 60s` on first
hit, reject once over `RATE_LIMIT = 20` per `RATE_WINDOW = 60s`. `/ask`
returns `429` when exceeded, capping the OpenAI bill against abuse.
This is *in addition to* the v7 per-user lock (which prevents
concurrent in-flight messages corrupting the cache) — the two solve
different problems and both run at the top of `/ask`.

**Managed Redis.** `redis.from_url()` accepts the Upstash `rediss://`
URL directly; the extra `s` is TLS, handled automatically — no code
change from the v7 local `redis://`.

### Env vars (production)

| Var | Where | Notes |
|---|---|---|
| `OPENAI_API_KEY` | Render | secret |
| `SUPABASE_URL` | Render | |
| `SUPABASE_SERVICE_KEY` | Render | secret, backend-only, bypasses RLS |
| `REDIS_URL` | Render | Upstash `rediss://…` |
| `FRONTEND_URL` | Render | the Vercel domain, for CORS |
| `PORT` | Render (auto) | injected by host |

### Deploy steps

1. Push this repo to GitHub.
2. Render → New → Web Service → connect repo → Render detects the
   `Dockerfile` and builds it.
3. Set all env vars above in the Render dashboard.
4. Deploy; confirm `GET /health` returns `{"ok": true}`.
5. Set `FRONTEND_URL` to the Vercel URL, redeploy.
