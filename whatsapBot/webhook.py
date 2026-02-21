from twilio.rest import Client
from fastapi import APIRouter, Request
from fastapi.responses import PlainTextResponse
import httpx
import os

router = APIRouter()


@router.post("/webhook")
async def receive_whatsapp_message(request: Request):
    form = await request.form()

    phone = form.get("From").replace("whatsapp:", "")
    text = form.get("Body")

    async with httpx.AsyncClient() as client:
        response = await client.post(
            f"{os.getenv('APP_URL')}/message",
            json={"phone": phone, "message": text}
        )
        result = response.json()

    # If new user, send welcome message first
    if "chat_link" in result:
        send_whatsapp_message(phone,
            "👋 Hello! Welcome to Seek!\n\nSeek was created by 5 cracked developers to help you with all your health, food and drug questions. I'm your personal health assistant and I'm here to help! 💊🥗"
        )

    # Send the actual answer
    send_whatsapp_message(phone, result["answer"])

    # Send chat link for new users
    if "chat_link" in result:
        send_whatsapp_message(phone, f"🔗 View your chat history here: {result['chat_link']}")

    return PlainTextResponse("ok")


def send_whatsapp_message(to: str, text: str):
    client = Client(os.getenv("TWILIO_ACCOUNT_SID"), os.getenv("TWILIO_AUTH_TOKEN"))
    client.messages.create(
        from_=f"whatsapp:{os.getenv('TWILIO_PHONE_NUMBER')}",
        to=f"whatsapp:{to}",
        body=text
    )