from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
import json

app = FastAPI()

# Allow all origins (for your frontend)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ---- MODELS ----
class VideoRequest(BaseModel):
    prompt: str
    duration: int
    plan: str
    user_email: str

class AudioRequest(BaseModel):
    text: str
    voice: str
    user_email: str

class ImageRequest(BaseModel):
    prompt: str
    style: str
    user_email: str

# ---- ROUTES ----
@app.get("/")
def home():
    return {"message": "Kairah Studio Backend Running ✅"}

@app.post("/api/generate-video")
def generate_video(data: VideoRequest):
    return {
        "status": "success",
        "video_url": f"https://kairah.vercel.app/demo-videos/{data.prompt.replace(' ', '_')}.mp4",
        "plan_used": data.plan
    }

@app.post("/api/generate-audio")
def generate_audio(data: AudioRequest):
    return {
        "status": "success",
        "audio_url": f"https://kairah.vercel.app/demo-audios/{data.voice}_{data.text[:10]}.mp3"
    }

@app.post("/api/generate-image")
def generate_image(data: ImageRequest):
    return {
        "status": "success",
        "image_url": f"https://kairah.vercel.app/demo-images/{data.style}_{data.prompt.replace(' ', '_')}.png"
    }

@app.post("/api/payment/webhook")
async def payment_webhook(request: Request):
    body = await request.json()
    print("Received webhook:", json.dumps(body, indent=2))
    return {"status": "received"}

@app.get("/api/plans")
def plans():
    return {
        "plans": [
            {"name": "Free", "price": "$0", "limit": "1 short HD video"},
            {"name": "Pro", "price": "$19/month", "limit": "Unlimited HD videos"},
            {"name": "Diamond", "price": "$49/month", "limit": "Unlimited 4K videos + audio + image tools"}
        ]
    }

@app.get("/api/support")
def support():
    return {
        "email": "support@kairahstudio.com",
        "message": "We reply within 24 hours."
    }
