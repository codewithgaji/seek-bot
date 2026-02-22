from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, text
from pydantic import BaseModel
from database import SessionLocal
from models import Message
import os
import uuid
import asyncio
from dotenv import load_dotenv
import google.generativeai as genai

load_dotenv()

GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")
APP_URL = os.getenv("APP_URL", "http://localhost:8000")
SEEK_WEB_URL = os.getenv("SEEK_WEB_URL", "https://seekapp.com")

if not GEMINI_API_KEY:
    raise ValueError("GEMINI_API_KEY not found in environment")

genai.configure(api_key=GEMINI_API_KEY)
model = genai.GenerativeModel("gemini-2.5-flash")

router = APIRouter()

async def get_db():
    async with SessionLocal() as session:
        yield session

class IncomingMessage(BaseModel):
    phone: str
    message: str


@router.post("/message")
async def receive_message(data: IncomingMessage, db: AsyncSession = Depends(get_db)):

    # Look up user from the frontend's users table by phone number
    result = await db.execute(
        text("SELECT * FROM users WHERE phone_number = :phone"),
        {"phone": data.phone}
    )
    user = result.mappings().first()

    if not user:
        raise HTTPException(status_code=404, detail="User not found. Please register on Seek first.")

    # Check if they already have a chat token in messages table
    token_result = await db.execute(
        select(Message.token).where(Message.user_id == user["id"]).limit(1)
    )
    existing_token = token_result.scalar_one_or_none()
    is_new_user = existing_token is None
    chat_token = existing_token if existing_token else uuid.uuid4()

    # Save the user's message
    user_message = Message(
        user_id=user["id"],
        phone_number=data.phone,
        token=chat_token,
        role="user",
        content=data.message
    )
    db.add(user_message)
    await db.commit()

    # Build personalised Gemini prompt using their real profile data
    try:
        gemini_response = await asyncio.to_thread(
            model.generate_content,
            f"""You are Seek, a friendly health assistant that answers questions about food and drugs.

You ONLY answer questions related to health, food, drugs, nutrition or wellness.
If the user asks something unrelated, politely say you can only help with health topics and suggest they visit {SEEK_WEB_URL} for more.

Here is what you know about this user:
- Name: {user["firstName"]}
- Age/DOB: {user["dateOfBirth"]}
- Gender: {user["gender"]}
- Diet type: {user["dietType"]}
- Allergies: {user["allergies"]}
- Health goals: {user["userGoals"]}
- Height: {user["height"]}
- Weight: {user["weight"]}

Use this information to give personalised answers. Answer this question: {data.message}

At the end of your answer always add:
Want to explore more? Visit us at {SEEK_WEB_URL}"""
        )
        answer = gemini_response.text
    except Exception as e:
        print("Gemini error:", e)
        raise HTTPException(status_code=500, detail="AI service failed")

    # Save the bot's reply
    bot_message = Message(
        user_id=user["id"],
        phone_number=data.phone,
        token=chat_token,
        role="bot",
        content=answer
    )
    db.add(bot_message)
    await db.commit()

    if is_new_user:
        return {
            "answer": answer,
            "chat_link": f"{APP_URL}/chat/{chat_token}"
        }

    return {"answer": answer}


@router.get("/chat/{token}")
async def get_chat_history(token: str, db: AsyncSession = Depends(get_db)):

    try:
        user_uuid = uuid.UUID(token)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid token format")

    result = await db.execute(
        select(Message).where(Message.token == user_uuid).order_by(Message.created_at)
    )
    messages = result.scalars().all()

    if not messages:
        raise HTTPException(status_code=404, detail="Invalid token")

    return {
        "messages": [
            {"role": m.role, "content": m.content, "time": m.created_at} for m in messages
        ]
    }


@router.post("/test")
async def test_bot(data: IncomingMessage):
    try:
        gemini_response = await asyncio.to_thread(
            model.generate_content,
            f"""You are Seek, a friendly health assistant that answers questions about food and drugs.

You ONLY answer questions related to health, food, drugs, nutrition or wellness.
Depending on how a person greets you, respond in a similar tone. If they are formal, be formal. If they are casual, be casual.
If the user asks something unrelated, politely say you can only help with health topics.

Answer this question: {data.message}

At the end of your answer always add:
Want to explore more? Visit us at {SEEK_WEB_URL}"""
    )
        answer = gemini_response.text
    except Exception as e:
        print("Gemini error:", e)
        raise HTTPException(status_code=500, detail="AI service failed")

    return {
        "you_sent": data.message,
        "seek_replied": answer
    }
