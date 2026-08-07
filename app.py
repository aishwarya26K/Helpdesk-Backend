import os
from dotenv import load_dotenv
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from openai import OpenAI

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

class Question(BaseModel):
    text:str

@app.post("/ask")
async def ask(q: Question):
    history.append({"role":"user", "content":q.text})
    def generate():
        full_reply = ""
        stream = client.chat.completions.create(
            model="gpt-5.4-mini",
            messages=history,
            stream=True,
        )
        for chunk in stream:
            delta = chunk.choices[0].delta.content
            if delta:
                full_reply += delta
                yield delta
        history.append({"role": "assistant", "content": full_reply})

    return StreamingResponse(generate(), media_type="text/plain")

@app.post("/reset")
def reset():
    global history
    history = [{"role": "system", "content": (
        "You are HelpDesk, the support assistant for NoonBazaar, a Dubai online store. "
        "Be warm, concise, and professional. Answer in at most 3 sentences. "
        "If you don't know, say so and offer to raise a ticket. Never invent order details."
    )}]
    return {"status": "reset"}

# uvicorn app:app --reload
# cd frontend\helpdesk-ui> npm run dev