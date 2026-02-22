from twilio.rest import Client
from fastapi import APIRouter, Request
from fastapi.responses import PlainTextResponse
import httpx
import os

router = APIRouter()

SEEK_API = "https://seek-1-6el7.onrender.com/api/v1/imageScan"


@router.post("/webhook")
async def receive_whatsapp_message(request: Request):
    form = await request.form()

    phone = form.get("From").replace("whatsapp:", "")
    text = form.get("Body")
    media_url = form.get("MediaUrl0")
    num_media = form.get("NumMedia", "0")

    # If user sent an image
    if int(num_media) > 0 and media_url:
        send_whatsapp_message(phone, "🔍 Analysing your image, give me a second...")
        answer = await analyse_image(media_url)
        send_whatsapp_message(phone, answer)
        return PlainTextResponse("ok")

    # Normal text message
    send_whatsapp_message(phone, "🔍 Looking that up for you...")

    async with httpx.AsyncClient(timeout=30) as client:
        response = await client.post(
            f"{os.getenv('APP_URL')}/message",
            json={"phone": phone, "message": text}
        )
        result = response.json()

    if "chat_link" in result:
        send_whatsapp_message(phone,
            "👋 Hello! Welcome to Seek!\n\nSeek was created by 5 cracked developers to help you with all your health, food and drug questions. I'm your personal health assistant and I'm here to help! 💊🥗"
        )

    send_whatsapp_message(phone, result["answer"])

    if "chat_link" in result:
        send_whatsapp_message(phone, f"🔗 View your chat history here: {result['chat_link']}")

    return PlainTextResponse("ok")


async def analyse_image(media_url: str) -> str:
    try:
        async with httpx.AsyncClient(timeout=30) as client:
            image_response = await client.get(
                media_url,
                auth=(os.getenv("TWILIO_ACCOUNT_SID"), os.getenv("TWILIO_AUTH_TOKEN"))
            )
            image_bytes = image_response.content
            content_type = image_response.headers.get("content-type", "image/jpeg")

        async with httpx.AsyncClient(timeout=30) as client:
            response = await client.post(
                SEEK_API,
                files={"image": ("image.jpg", image_bytes, content_type)}
            )
            data = response.json()
            print("Image API response:", data)  # <-- this shows exactly what comes back

        return format_image_response(data)

    except Exception as e:
        print("Image analysis error:", str(e))
        return "Sorry, I couldn't analyse that image. Please try again or type your question instead."


def format_image_response(data: dict) -> str:
    try:
        r = data["response"]
        item_type = r.get("item_type", "Item")
        name = r.get("identified_name", "Unknown")

        msg = f"🔎 *{item_type}: {name}*\n\n"

        risks = r.get("risk_assessment", [])
        if risks:
            msg += "⚠️ *Risk Assessment:*\n"
            for risk in risks:
                severity = risk.get("severity", "")
                effect = risk.get("ailment_or_side_effect", "")
                trigger = risk.get("trigger", "")
                msg += f"• {effect} ({trigger}) — {severity}\n"

        recommendations = r.get("personalized_recommendations", [])
        if recommendations:
            msg += "\n💡 *Recommendations:*\n"
            for rec in recommendations[:2]:  # limit to 2 to stay under char limit
                issue = rec.get("original_issue", "")
                suggestion = rec.get("suggestion", "")[:200]  # cap length
                msg += f"• {issue}: {suggestion}...\n"

        msg += f"\n\nWant to explore more? Visit us at {os.getenv('SEEK_WEB_URL', 'https://seekapp.com')}"
        return msg

    except Exception as e:
        print("Format error:", e)
        return "Received a response but couldn't format it. Please try again."


def send_whatsapp_message(to: str, body: str):
    client = Client(os.getenv("TWILIO_ACCOUNT_SID"), os.getenv("TWILIO_AUTH_TOKEN"))

    chunks = [body[i:i+1500] for i in range(0, len(body), 1500)]

    for chunk in chunks:
        client.messages.create(
            from_=f"whatsapp:{os.getenv('TWILIO_PHONE_NUMBER')}",
            to=f"whatsapp:{to}",
            body=chunk
        )
