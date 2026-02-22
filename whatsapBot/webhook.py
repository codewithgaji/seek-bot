from twilio.rest import Client
from fastapi import APIRouter, Request
from fastapi.responses import PlainTextResponse
import httpx
import os
import asyncio
import google.generativeai as genai
from dotenv import load_dotenv

load_dotenv()

genai.configure(api_key=os.getenv("GEMINI_API_KEY"))
model = genai.GenerativeModel("gemini-2.5-flash")

router = APIRouter()


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
        answer = await analyse_image_with_gemini(media_url)
        send_whatsapp_message(phone, answer)
        return PlainTextResponse("ok")

    # Normal text message
    send_whatsapp_message(phone, "🔍 Looking that up for you...")

    try:
        async with httpx.AsyncClient(timeout=30) as client:
            response = await client.post(
                f"{os.getenv('APP_URL')}/message",
                json={"phone": phone, "message": text}
            )
            result = response.json()

        if "answer" not in result:
            print("Error from /message:", result)
            send_whatsapp_message(phone, "Sorry, something went wrong. Please try again.")
            return PlainTextResponse("ok")

        if "chat_link" in result:
            send_whatsapp_message(phone,
                "👋 Hello! Welcome to Seek!\n\nSeek was created by 5 cracked developers to help you with all your health, food and drug questions. I'm your personal health assistant and I'm here to help! 💊🥗"
            )

        send_whatsapp_message(phone, result["answer"])

        if "chat_link" in result:
            send_whatsapp_message(phone, f"🔗 View your chat history here: {result['chat_link']}")

    except Exception as e:
        print("Webhook error:", str(e))
        send_whatsapp_message(phone, "Sorry, something went wrong. Please try again.")

    return PlainTextResponse("ok")

async def analyse_image_with_gemini(media_url: str) -> str:
    try:
        # Download image from Twilio
        async with httpx.AsyncClient(timeout=30) as client:
            image_response = await client.get(
                media_url,
                auth=(os.getenv("TWILIO_ACCOUNT_SID"), os.getenv("TWILIO_AUTH_TOKEN"))
            )
            image_bytes = image_response.content
            # Force image/jpeg regardless of what Twilio returns as e get strong head
            content_type = "image/jpeg"

        # Send image directly to Gemini
        def _analyse():
            image_part = {"mime_type": content_type, "data": image_bytes}
            prompt = """You are Seek, a health assistant. Analyse this image of a food item or drug/medication.


Identify what it is and provide:
1. What the item is
2. Key nutritional info or drug ingredients
3. Potential risks or side effects
4. A short personalised health recommendation

Keep your response concise and under 1000 characters.
End with: Want to explore more? Visit us at seekapp.com"""

            response = model.generate_content([prompt, image_part])
            return response.text

        answer = await asyncio.to_thread(_analyse)
        return answer

    except Exception as e:
        print("Image analysis error:", str(e))
        return "Sorry, I couldn't analyse that image. Please try again or type your question instead."

Identify what it is and provide:
1. What the item is
2. Key nutritional info or drug ingredients
3. Potential risks or side effects
4. A short personalised health recommendation

Keep your response concise and under 1000 characters.
End with: Want to explore more? Visit us at seekapp.com"""

            response = model.generate_content([prompt, image_part])
            return response.text

        answer = await asyncio.to_thread(_analyse)
        return answer

    except Exception as e:
        print("Image analysis error:", str(e))
        return "Sorry, I couldn't analyse that image. Please try again or type your question instead."


def send_whatsapp_message(to: str, body: str):
    client = Client(os.getenv("TWILIO_ACCOUNT_SID"), os.getenv("TWILIO_AUTH_TOKEN"))

    chunks = [body[i:i+1500] for i in range(0, len(body), 1500)]

    for chunk in chunks:
        client.messages.create(
            from_=f"whatsapp:{os.getenv('TWILIO_PHONE_NUMBER')}",
            to=f"whatsapp:{to}",
            body=chunk
        )
