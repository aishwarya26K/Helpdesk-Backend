import os, json, redis
import tiktoken
from auth import sb  # reuse the Supabase client from v6

r = redis.from_url(os.environ["REDIS_URL"])
TTL = 1800  # 30 min

RATE_LIMIT = 20        # max requests
RATE_WINDOW = 60       # per 60 sec

def rate_limit_ok(user_id: str) -> bool:
    key = f"rate:{user_id}"
    n = r.incr(key)
    if n == 1:
        r.expire(key, RATE_WINDOW)
    return n <= RATE_LIMIT

SYSTEM_PROMPT = {"role": "system", "content": (
    "You are HelpDesk, the support assistant for NoonBazaar, a Dubai online store. "
    "Be warm, concise, and professional. Answer in at most 3 sentences. "
    "If you don't know, say so and offer to raise a ticket. Never invent order details."
)}

enc = tiktoken.get_encoding("o200k_base")
MAX_HISTORY_TOKENS = 3000


def count_tokens(messages):
    return sum(len(enc.encode(m["content"])) for m in messages)


def trim_history(history):
    system, rest = history[0], history[1:]
    while rest and count_tokens(rest) > MAX_HISTORY_TOKENS:
        rest.pop(0)
    return [system] + rest


def cache_key(user_id):
    return f"convo:{user_id}"


# --- Postgres helpers (the v6 loader/writer, source of truth) ---

def load_from_postgres(user_id: str):
    rows = (sb.table("messages").select("role, content")
              .eq("user_id", user_id).order("created_at")
              .execute().data)
    history = [SYSTEM_PROMPT] + [{"role": row["role"], "content": row["content"]} for row in rows]
    return trim_history(history)


def save_to_postgres(user_id: str, role: str, content: str):
    sb.table("messages").insert({
        "user_id": user_id,
        "role": role,
        "content": content,
    }).execute()


# --- Cache-aside API ---

def load_history(user_id: str):
    cached = r.get(cache_key(user_id))
    if cached:
        print("cache hit")
        return json.loads(cached)                       # fast path: Redis hit
    print("cache miss")
    history = load_from_postgres(user_id)               # slow path: Postgres (source of truth)
    r.setex(cache_key(user_id), TTL, json.dumps(history))
    return history


def append_turn(user_id: str, role: str, content: str):
    save_to_postgres(user_id, role, content)            # durable write first
    key = cache_key(user_id)
    history = json.loads(r.get(key) or "null") or load_from_postgres(user_id)
    history.append({"role": role, "content": content})
    history = trim_history(history)                      # keep cache within token budget
    r.setex(key, TTL, json.dumps(history))              # refresh cache + TTL


def invalidate(user_id: str):
    r.delete(cache_key(user_id))                         # drop cache on /reset


def with_user_lock(user_id: str):
    # True if this caller acquired the lock; auto-expires after 5s so a
    # dead process can never deadlock. Per-user key -> users never block each other.
    return r.set(f"lock:{user_id}", "1", nx=True, ex=5)
