import os
from dotenv import load_dotenv
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from openai import OpenAI
import tiktoken
import json
from typing import Literal, Optional
from pydantic import ValidationError
from fastapi import HTTPException

load_dotenv()

app = FastAPI()
client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3000"],
    allow_methods=["*"],
    allow_headers=["*"]
)

history = [{"role": "system", "content": (
    "You are HelpDesk, the support assistant for NoonBazaar, a Dubai online store. "
    "Be warm, concise, and professional. Answer in at most 3 sentences. "
    "If you don't know, say so and offer to raise a ticket. Never invent order details."
)}]

IN_PRICE  = 0.15             # $ per 1M input/prompt tokens — check OpenAI's actual pricing for gpt-5.4-mini
OUT_PRICE = 0.60              # $ per 1M output/completion tokens
session_cost = 0.0

enc = tiktoken.get_encoding("o200k_base")
MAX_HISTORY_TOKENS = 3000

def count_tokens(messages):
    return sum(len(enc.encode(m["content"])) for m in messages)

def trim_history(history):
    system, rest = history[0], history[1:]
    while rest and count_tokens(rest) > MAX_HISTORY_TOKENS:
        rest.pop(0)
    return [system] + rest

class Question(BaseModel):
    text:str

class Ticket(BaseModel):
    category: Literal["order", "refund", "technical", "account", "other"]
    urgency: Literal["low", "medium", "high"]
    summary: str
    order_id: Optional[str] = None

@app.post("/ask")
async def ask(q: Question):
    history.append({"role":"user", "content":q.text})
    history[:] = trim_history(history)

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

        history.append({"role": "assistant", "content": full_reply})

    return StreamingResponse(generate(), media_type="text/plain")

@app.post("/ticket")
def create_ticket():
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
def reset():
    global history, session_cost
    history = [{"role": "system", "content": (
        "You are HelpDesk, the support assistant for NoonBazaar, a Dubai online store. "
        "Be warm, concise, and professional. Answer in at most 3 sentences. "
        "If you don't know, say so and offer to raise a ticket. Never invent order details."
    )}]
    session_cost = 0.0
    return {"status": "reset"}

# uvicorn app:app --reload
# cd frontend\helpdesk-ui> npm run dev