import os
from dotenv import load_dotenv
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
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

class Question(BaseModel):
    text:str

@app.post("/ask")
def ask(q: Question):
    resp = client.chat.completions.create(
        model="gpt-5.4-mini",
        messages=[{"role":"user", "content":q.text}]
    )
    return {"answer":resp.choices[0].message.content}

# uvicorn app:app --reload
# cd frontend\helpdesk-ui> npm run dev