from fastapi import APIRouter, Depends, HTTPException, UploadFile, File
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

load_dotenv()

GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")
APP_URL = os.getenv("APP_URL", "http://localhost:8000")
SEEK_WEB_URL = os.getenv("SEEK_WEB_URL", "https://seekapp.com")

if not GEMINI_API_KEY:
    raise ValueError("GEMINI_API_KEY not found in environment") # Incase of no API KEY, so i can debug

genai.configure(api_key=GEMINI_API_KEY)
model = genai.GenerativeModel("gemini-2.5-flash")

router = APIRouter()

async def get_db():
    async with SessionLocal() as session:
        yield session # Providing a database session for the endpoints that need to interact with the database.

class IncomingMessage(BaseModel):
    phone: str
    message: str # I"m using this model to define the expected structure of incoming messages to the /message endpoint, which will be called from the webhook when a new message is received on WhatsApp.


@router.post("/message")
async def receive_message(data: IncomingMessage, db: AsyncSession = Depends(get_db)):

    user = None
    try:
        result = await asyncio.wait_for(
            db.execute(text("SELECT * FROM users WHERE phone_number = :phone"), {"phone": data.phone}), # accesing the users table to find a user with the matching phone number from the incoming message, so i can link the message to the correct user and maintain conversation history for that user.
            timeout=2
        )
        user = result.mappings().first()
        print("User found:", user["firstName"] if user else "No user found")
    except Exception as e:
        print("User lookup error:", str(e)) # Debugging sake, railway needs it alot if i want to see the logs of the database queries and errors.

    user_id = user["id"] if user else None
    chat_token = None
    is_new_user = False
    conversation_history = ""

    if user_id:
        token_result = await db.execute(
            select(Message.token).where(Message.user_id == user_id).limit(1)
        ) # Verifying if there's an existing chat token for this user, which indicates they have an existing conversation history. If not, it means this is a new user and I will generate a new chat token for them.
        chat_token = token_result.scalar_one_or_none()
        is_new_user = chat_token is None
        if not chat_token:
            chat_token = uuid.uuid4()

        history_result = await db.execute(
            select(Message)
            .where(Message.user_id == user_id)
            .order_by(Message.created_at.desc())
            .limit(5)
        )
        history = list(reversed(history_result.scalars().all()))
        for msg in history:
            role = "User" if msg.role == "user" else "Seek"
            conversation_history += f"{role}: {msg.content}\n"

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

Previous conversation:
{conversation_history}

Now answer this: {data.message}

At the end of your answer always add:
Want to explore more? Visit us at {SEEK_WEB_URL}"""
    else:
        prompt = f"""You are Seek, a friendly AI health assistant created by 5 cracked developers.
You help people with questions about food, drugs, nutrition and wellness.
Only answer health related questions.
If asked something unrelated, politely say you can only help with health topics.

Ensure your response is engaging, friendly, informative and not more than 3000 characters.
Now answer this: {data.message}

At the end of your answer always add:
Want to explore more? Visit us at {SEEK_WEB_URL}"""

    if user_id:
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


@router.get("/chat/{token}") # This endpoint is for the web app to retrieve the chat history for a user based on their unique chat token, which is generated when they first interact with the bot and stored in the database.
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


@router.post("/test") # I'm testing with swagger the connection to Gemini and the response format, to make sure everything is working before i connect it to the webhook and start handling real user messages.
async def test_bot(data: IncomingMessage):
    try:
        print("Calling Gemini for test...")
        gemini_response = await asyncio.to_thread(
            model.generate_content,
            f"""You are Seek, a friendly health assistant created by 5 cracked developers.
You ONLY answer questions related to health, food, drugs, nutrition or wellness.
If asked something unrelated, politely redirect them.

Answer this: {data.message}

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
async def test_image(file: UploadFile = File(...)):
    try:
        image_bytes = await file.read()
        image_b64 = base64.b64encode(image_bytes).decode("utf-8")

        def _analyse():
            image_part = {
                "inline_data": {
                    "mime_type": file.content_type or "image/jpeg",
                    "data": image_b64
                }
            }
            prompt = """You are Seek, a health assistant. Analyse this image of a food item or drug/medication.

Identify what it is and provide:
1. What the item is
2. Key nutritional info or drug ingredients
3. Potential risks or side effects
4. A short health recommendation

End with: Want to explore more? Visit us at seekapp.com"""

            response = model.generate_content([prompt, image_part])
            return response.text

        answer = await asyncio.to_thread(_analyse)
        return {
            "filename": file.filename,
            "analysis": answer
        }

    except Exception as e:
        print("Image test error:", str(e))
        raise HTTPException(status_code=500, detail=f"Image analysis failed: {str(e)}")
