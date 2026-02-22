import cloudinary
import cloudinary.uploader
import httpx
import os
from dotenv import load_dotenv

load_dotenv()

cloudinary.config(
    cloud_name=os.getenv("CLOUDINARY_CLOUD_NAME"),
    api_key=os.getenv("CLOUDINARY_API_KEY"),
    api_secret=os.getenv("CLOUDINARY_API_SECRET")
)


async def upload_twilio_image(media_url: str) -> str:
    """
    Downloads image from Twilio and uploads to Cloudinary.
    Returns a clean public Cloudinary URL.
    """
    # Download from Twilio
    async with httpx.AsyncClient(timeout=30) as client:
        response = await client.get(
            media_url,
            auth=(os.getenv("TWILIO_ACCOUNT_SID"), os.getenv("TWILIO_AUTH_TOKEN")),
            follow_redirects=True
        )
        image_bytes = response.content

    # Upload to Cloudinary
    result = cloudinary.uploader.upload(
        image_bytes,
        folder="seek-bot",
        resource_type="image"
    )

    return result["secure_url"]
