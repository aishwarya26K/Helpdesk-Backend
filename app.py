import os
from fastapi import FastAPI, Depends, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, ValidationError
from openai import OpenAI
import json
from typing import Literal, Optional

from dotenv import load_dotenv
from store import load_history, append_turn, invalidate, with_user_lock, rate_limit_ok

# module import
from auth import get_user_id, sb

load_dotenv()

app = FastAPI()
client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))

app.add_middleware(
    CORSMiddleware,
    allow_origins=[
    os.environ.get("FRONTEND_URL", "http://localhost:3000"),
    ],
    allow_methods=["*"],
    allow_headers=["*"]
)

IN_PRICE  = 0.15             # $ per 1M input/prompt tokens — check OpenAI's actual pricing for gpt-5.4-mini
OUT_PRICE = 0.60              # $ per 1M output/completion tokens
session_cost = 0.0

class Question(BaseModel):
    text:str

class Ticket(BaseModel):
    category: Literal["order", "refund", "technical", "account", "other"]
    urgency: Literal["low", "medium", "high"]
    summary: str
    order_id: Optional[str] = None

@app.post("/ask")
def ask(q: Question, user_id: str = Depends(get_user_id)):
    if not with_user_lock(user_id):
        raise HTTPException(429, "Slow down — previous message still processing")
    if not rate_limit_ok(user_id):
        raise HTTPException(429, "Rate limit exceeded — try again in a minute")
    append_turn(user_id,"user",q.text)
    history = load_history(user_id)

    def generate():
        global session_cost
        full_reply = ""
        stream = client.chat.completions.create(
            model="gpt-5.4-mini",
            messages=history,
            stream=True,
            stream_options={"include_usage": True}      # ask for a final usage chunk
        )
        for chunk in stream:
            if chunk.choices and chunk.choices[0].delta.content:
                delta = chunk.choices[0].delta.content
                full_reply += delta
                yield delta

            if chunk.usage:     # arrives on the last chunk
                cost = (chunk.usage.prompt_tokens / 1e6) * IN_PRICE + \
                       (chunk.usage.completion_tokens / 1e6) * OUT_PRICE
                session_cost += cost
                footer = (
                    f"\n\n[{chunk.usage.total_tokens} tokens · "
                    f"${cost:.6f} · session: ${session_cost:.6f}]"
                )
                yield footer

        append_turn(user_id,"assistant",full_reply)

    return StreamingResponse(generate(), media_type="text/plain")

@app.post("/ticket")
def create_ticket(user_id: str = Depends(get_user_id)):
    history = load_history(user_id)
    ticket_instruction = {
        "role":"user",
        "content":(
            "Based only on the conversation so far, produce a support ticket as JSON "
            "with exactly these keys: category (one of order, refund, technical, account, "
            "other), urgency (one of low, medium, high), summary (one sentence), and "
            "order_id (the order id if the customer mentioned one, otherwise null). "
            "Do not invent an order_id that was never mentioned."
        )
    }

    resp = client.chat.completions.create(
            model="gpt-5.4-mini",
            messages=history + [ticket_instruction],
            response_format={"type": "json_object"}
    )

    raw = resp.choices[0].message.content

    try:
        parsed = json.loads(raw)
        ticket = Ticket(**parsed)
    except (json.JSONDecodeError, ValidationError) as e:
        raise HTTPException(status_code=422, detail=str(e))
    return ticket


@app.post("/reset")
def reset(user_id: str = Depends(get_user_id)):
    global session_cost
    sb.table("messages").delete().eq("user_id", user_id).execute()
    invalidate(user_id)
    session_cost = 0.0
    return {"status": "reset"}

@app.get("/health")
def health():
    return {"ok": True}