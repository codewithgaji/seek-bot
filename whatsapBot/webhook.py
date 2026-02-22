from sqlalchemy import text
from twilio.rest import Client
from fastapi import APIRouter, Request
from fastapi.responses import PlainTextResponse
import httpx
import os
import asyncio
import google.generativeai as genai
from dotenv import load_dotenv
from cloudinary_service import upload_twilio_image

load_dotenv()

genai.configure(api_key=os.getenv("GEMINI_API_KEY"))
model = genai.GenerativeModel("gemini-2.5-flash") # Apparently 1.5 has been deprecated, hence my change of model.

router = APIRouter()



# this webook endpoint is what Twilio will call when a new message is received on the WhatsApp number. It processes the incoming message, checks if there's media attached, and responds accordingly. If it's a text message, it forwards it to the /message endpoint for processing. If it's an image, it sends an immediate response to the user and then processes the image with Gemini before sending back the analysis.
@router.post("/webhook")
async def receive_whatsapp_message(request: Request):
    form = await request.form() # Twilio sends data as form-data

    phone = form.get("From").replace("whatsapp:", "")
    text = form.get("Body")
    media_url = form.get("MediaUrl0") # Twilio sending my mail.
    num_media = form.get("NumMedia", "0")

    if int(num_media) > 0 and media_url:
        send_whatsapp_message(phone, "🔍 Analysing your image, give me a second...") # I'm sending this to let the user know it is doing the analysis behind the scenes
        answer = await analyse_image_with_gemini(media_url)
        send_whatsapp_message(phone, answer)
        return PlainTextResponse("ok")

    send_whatsapp_message(phone, "🔍 Looking that up for you...") # same thing here.

    try:
        async with httpx.AsyncClient(timeout=30) as client:
            response = await client.post(
                f"{os.getenv('APP_URL')}/message",
                json={"phone": phone, "message": text}
            )
            print("Status from /message:", response.status_code)
            print("Response text:", response.text)
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

        if "chat_link" in result: # chat_link is generated only for new users, so if it's present it means this is a new user and i want to send them the link to view their chat history on the web app.
            send_whatsapp_message(phone, f"🔗 View your chat history here: {result['chat_link']}")

    except Exception as e:
        print("Webhook error:", str(e))
        send_whatsapp_message(phone, "Sorry, something went wrong. Please try again.")

    return PlainTextResponse("ok")


async def analyse_image_with_gemini(media_url: str) -> str:
    try:
        import base64

        # Upload to Cloudinary first to get a clean URL
        clean_url = await upload_twilio_image(media_url)
        print("Cloudinary URL:", clean_url)

        # Download clean image from Cloudinary
        async with httpx.AsyncClient(timeout=30) as client:
            image_response = await client.get(clean_url, follow_redirects=True)
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

You can be friendly and engaging in your response.
End with: Want to explore more? Visit us at seekapp.com"""

            response = model.generate_content([prompt, image_part])
            return response.text

        answer = await asyncio.to_thread(_analyse)
        return answer

    except Exception as e:
        print("Image analysis error:", str(e))
        return "Sorry, I couldn't analyse that image. Please try again or type your question instead."
    

def send_whatsapp_message(to: str, body: str):
    client = Client(os.getenv("TWILIO_ACCOUNT_SID"), os.getenv("TWILIO_AUTH_TOKEN")) # This is so I can send messages back to the user through Twilio's API.

    chunks = [body[i:i+1500] for i in range(0, len(body), 1500)]# WhatsApp has a message limit of 1600 characters, so I'm splitting the message into chunks to avoid errors when sending long responses from Gemini.

    for chunk in chunks:
        client.messages.create(
            from_=f"whatsapp:{os.getenv('TWILIO_PHONE_NUMBER')}",
            to=f"whatsapp:{to}", # I'm using the "to" parameter to specify the recipient's phone number, which I extracted from the incoming message data.
            body=chunk # Response broken into chunks to avoid WhatsApp message length limits
        )
