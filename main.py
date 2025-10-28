# main.py
from fastapi import FastAPI, Request, HTTPException, Depends
from fastapi.middleware.cors import CORSMiddleware
import os
import requests
from typing import Optional

# ------------------------------
# Environment Variables
# ------------------------------
WISE_ACCOUNT_NAME = os.getenv("WISE_ACCOUNT_NAME", "Eunice Muema Mueni")
WISE_ACCOUNT_NUMBER = os.getenv("WISE_ACCOUNT_NUMBER", "12345678")
WISE_ROUTING_NUMBER = os.getenv("WISE_ROUTING_NUMBER", "020123456")

PAYPAL_EMAIL = os.getenv("PAYPAL_EMAIL", "eunicemueni1009@gmail.com")

PAYSTACK_PUBLIC_KEY = os.getenv("PAYSTACK_PUBLIC_KEY", "pk_test_d3297a9a8fe29af2c3f012b77ea38d7df9f00480")
PAYSTACK_SECRET_KEY = os.getenv("PAYSTACK_SECRET_KEY", "sk_test_b0e3fdb6e346294f423e174557e25321bf9d855e")
PAYSTACK_CURRENCY = os.getenv("PAYSTACK_CURRENCY", "KES")

FREE_VIDEO_LIMIT = 1

# ------------------------------
# Dummy DB (Replace with PostgreSQL/SQLite)
# ------------------------------
USERS_DB = {}  # {firebase_uid: {role: "Free/Pro/Diamond", videos_generated: int}}

# ------------------------------
# Firebase Token Verification Placeholder
# ------------------------------
def verify_firebase_token(token: str) -> str:
    """
    Placeholder function for Firebase Auth verification.
    Return firebase_uid if valid, raise HTTPException if invalid.
    """
    if not token:
        raise HTTPException(status_code=401, detail="Missing token")
    # TODO: Implement Firebase Admin SDK verification here
    firebase_uid = token  # For placeholder, token = uid
    if firebase_uid not in USERS_DB:
        USERS_DB[firebase_uid] = {"role": "Free", "videos_generated": 0}
    return firebase_uid

# ------------------------------
# FastAPI App Setup
# ------------------------------
app = FastAPI()
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ------------------------------
# Home Route
# ------------------------------
@app.get("/")
def home():
    return {"message": "Kairah Studio Backend Running 💫"}

# ------------------------------
# Payment Info Endpoints
# ------------------------------
@app.get("/api/wise-info")
def wise_info():
    return {
        "account_name": WISE_ACCOUNT_NAME,
        "account_number": WISE_ACCOUNT_NUMBER,
        "routing_number": WISE_ROUTING_NUMBER,
        "currency": "USD"
    }

@app.get("/api/paypal-info")
def paypal_info():
    return {
        "paypal_email": PAYPAL_EMAIL,
        "currency": "USD",
        "type": "personal"
    }

@app.post("/api/paystack/init")
async def paystack_init(request: Request):
    data = await request.json()
    email = data.get("email")
    amount = data.get("amount")
    if not email or not amount:
        raise HTTPException(status_code=400, detail="Missing email or amount")

    headers = {
        "Authorization": f"Bearer {PAYSTACK_SECRET_KEY}",
        "Content-Type": "application/json"
    }
    body = {
        "email": email,
        "amount": int(amount) * 100,  # Paystack uses kobo
        "currency": PAYSTACK_CURRENCY,
        "callback_url": "https://kairah.vercel.app/payment-success"
    }
    response = requests.post("https://api.paystack.co/transaction/initialize", headers=headers, json=body)
    return response.json()

@app.post("/api/paystack-webhook")
async def paystack_webhook(request: Request):
    event = await request.json()
    print("🔔 Paystack Event Received:", event)
    return {"status": "success"}

@app.post("/api/wise-webhook")
async def wise_webhook(request: Request):
    event = await request.json()
    print("🔔 Wise Event Received:", event)
    return {"status": "received"}

# ------------------------------
# User Dependency
# ------------------------------
def get_current_user(token: Optional[str] = None):
    return verify_firebase_token(token)

# ------------------------------
# Content Generation Endpoints (Placeholders)
# ------------------------------
@app.post("/api/generate/video")
async def generate_video(request: Request, firebase_uid: str = Depends(get_current_user)):
    user = USERS_DB[firebase_uid]
    if user["role"] == "Free" and user["videos_generated"] >= FREE_VIDEO_LIMIT:
        raise HTTPException(status_code=403, detail="Free user video limit reached")
    
    data = await request.json()
    prompt = data.get("prompt", "Default prompt")
    style = data.get("style", "cinematic")  # e.g., cinematic, viral, image-to-video
    length = data.get("length", 6)  # seconds

    # ----------------------
    # Placeholder AI Engine Call
    # ----------------------
    video_url = f"https://kairah.fakecdn.com/videos/{firebase_uid}_video.mp4"

    # Update usage
    user["videos_generated"] += 1

    return {
        "video_url": video_url,
        "prompt": prompt,
        "style": style,
        "length": length,
        "role": user["role"]
    }

@app.post("/api/generate/audio")
async def generate_audio(request: Request, firebase_uid: str = Depends(get_current_user)):
    data = await request.json()
    prompt = data.get("prompt", "Default audio prompt")

    # Placeholder AI engine call
    audio_url = f"https://kairah.fakecdn.com/audios/{firebase_uid}_audio.mp3"

    return {"audio_url": audio_url, "prompt": prompt}

@app.post("/api/generate/image")
async def generate_image(request: Request, firebase_uid: str = Depends(get_current_user)):
    data = await request.json()
    prompt = data.get("prompt", "Default image prompt")

    # Placeholder AI engine call
    image_url = f"https://kairah.fakecdn.com/images/{firebase_uid}_image.png"

    return {"image_url": image_url, "prompt": prompt}

# ------------------------------
# Run Local (for testing)
# ------------------------------
if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=int(os.getenv("PORT", 3000)))
