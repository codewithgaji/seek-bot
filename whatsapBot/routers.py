from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, text
from pydantic import BaseModel
from database import SessionLocal
from models import Message
import os
import uuid
import asyncio
import base64
import httpx
from dotenv import load_dotenv
import google.generativeai as genai
from typing import Optional

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

class ImageTest(BaseModel):
    image_url: str  # paste any public image URL to test


@router.post("/message")
async def receive_message(data: IncomingMessage, db: AsyncSession = Depends(get_db)):

    user = None
    try:
        result = await asyncio.wait_for(
            db.execute(text("SELECT * FROM users WHERE phone_number = :phone"), {"phone": data.phone}),
            timeout=2
        )
        user = result.mappings().first()
        print("User found:", user["firstName"] if user else "No user found")
    except Exception as e:
        print("User lookup error:", str(e))

    if user:
        prompt = f"""You are Seek, a friendly health assistant created by 5 cracked developers.
You ONLY answer questions related to health, food, drugs, nutrition or wellness.
If the user asks something unrelated, politely redirect them to {SEEK_WEB_URL}.

Here is what you know about this user:
- Name: {user["firstName"]}
- Age/DOB: {user["dateOfBirth"]}
- Gender: {user["gender"]}
- Diet type: {user["dietType"]}
- Allergies: {user["allergies"]}
- Health goals: {user["userGoals"]}
- Height: {user["height"]}
- Weight: {user["weight"]}

Use this information to give personalised answers. Answer this: {data.message}

Keep your answer concise and under 1000 characters.
At the end of your answer always add:
Want to explore more? Visit us at {SEEK_WEB_URL}"""
    else:
        prompt = f"""You are Seek, a friendly AI health assistant created by 5 cracked developers.
You help people with questions about food, drugs, nutrition and wellness.
Only answer health related questions.
If asked something unrelated, politely say you can only help with health topics.

Answer this: {data.message}

Keep your answer concise and under 1000 characters.
At the end of your answer always add:
Want to explore more? Visit us at {SEEK_WEB_URL}"""

    user_id = user["id"] if user else None
    chat_token = None
    is_new_user = False

    if user_id:
        token_result = await db.execute(
            select(Message.token).where(Message.user_id == user_id).limit(1)
        )
        chat_token = token_result.scalar_one_or_none()
        is_new_user = chat_token is None
        if not chat_token:
            chat_token = uuid.uuid4()

        user_message = Message(
            user_id=user_id,
            phone_number=data.phone,
            token=chat_token,
            role="user",
            content=data.message
        )
        db.add(user_message)
        await db.commit()

    try:
        print("Calling Gemini...")
        gemini_response = await asyncio.to_thread(model.generate_content, prompt)
        answer = gemini_response.text
        print("Gemini responded successfully")
    except Exception as e:
        print("Gemini error:", str(e))
        raise HTTPException(status_code=500, detail="AI service failed")

    if user_id:
        bot_message = Message(
            user_id=user_id,
            phone_number=data.phone,
            token=chat_token,
            role="bot",
            content=answer
        )
        db.add(bot_message)
        await db.commit()

    if user_id and is_new_user:
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
        print("Calling Gemini for test...")
        gemini_response = await asyncio.to_thread(
            model.generate_content,
            f"""You are Seek, a friendly health assistant created by 5 cracked developers.
You ONLY answer questions related to health, food, drugs, nutrition or wellness.
If asked something unrelated, politely redirect them.

Answer this: {data.message}

Keep your answer concise and under 1000 characters.
At the end always add:
Want to explore more? Visit us at {SEEK_WEB_URL}"""
        )
        answer = gemini_response.text
        print("Gemini test responded successfully")
    except Exception as e:
        print("Gemini test error:", str(e))
        raise HTTPException(status_code=500, detail="AI service failed")

    return {
        "you_sent": data.message,
        "seek_replied": answer
    }


@router.post("/test/image")
async def test_image(data: ImageTest):
    try:
        # Download image from the URL
        async with httpx.AsyncClient(timeout=30) as client:
            image_response = await client.get(data.image_url, follow_redirects=True)
            image_bytes = image_response.content
            image_b64 = base64.b64encode(image_bytes).decode("utf-8")

        def _analyse():
            image_part = {
                "inline_data": {
                    "mime_type": "image/jpeg",
                    "data": image_b64
                }
            }
            prompt = """You are Seek, a health assistant. Analyse this image of a food item or drug/medication.

Identify what it is and provide:
1. What the item is
2. Key nutritional info or drug ingredients
3. Potential risks or side effects
4. A short health recommendation

Keep your response concise and under 1000 characters.
End with: Want to explore more? Visit us at seekapp.com"""

            response = model.generate_content([prompt, image_part])
            return response.text

        answer = await asyncio.to_thread(_analyse)
        return {
            "image_url": data.image_url,
            "analysis": answer
        }

    except Exception as e:
        print("Image test error:", str(e))
