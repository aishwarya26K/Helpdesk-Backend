import os
from dotenv import load_dotenv
from fastapi import Header, HTTPException
from supabase import create_client

load_dotenv()

sb = create_client(
    os.environ["SUPABASE_URL"],
    os.environ["SUPABASE_SERVICE_KEY"]
)

def get_user_id(authorization: str = Header(...)) -> str:
    token = authorization.removeprefix("Bearer ").strip()
    res = sb.auth.get_user(token)
    if not res or not res.user:
        raise HTTPException(401, "Invalid or expired token")
    return res.user.id