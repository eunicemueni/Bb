# main.py
import os
import subprocess
import sys

# Auto-install required packages if missing
packages = ["fastapi", "uvicorn", "requests", "stripe", "python-dotenv", "pydantic"]
for pkg in packages:
    try:
        __import__(pkg)
    except ImportError:
        subprocess.check_call([sys.executable, "-m", "pip", "install", pkg)

from fastapi import FastAPI, Request, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
import stripe
import requests

app = FastAPI()

# Allow frontend calls
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # Replace with frontend URL
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# -------------------
# Environment / Keys
# -------------------
STRIPE_SECRET_KEY = os.environ.get("STRIPE_SECRET_KEY", "sk_test_...")
stripe.api_key = STRIPE_SECRET_KEY

MPESA_KEY = os.environ.get("MPESA_KEY", "your_mpesa_key")
MPESA_SECRET = os.environ.get("MPESA_SECRET", "your_mpesa_secret")
MPESA_SHORTCODE = os.environ.get("MPESA_SHORTCODE", "your_shortcode")
MPESA_PASSKEY = os.environ.get("MPESA_PASSKEY", "your_passkey")

PAYSTACK_SECRET_KEY = os.environ.get("PAYSTACK_SECRET_KEY", "sk_test_...")
PAYSTACK_PUBLIC_KEY = os.environ.get("PAYSTACK_PUBLIC_KEY", "pk_test_...")

WISE_API_TOKEN = os.environ.get("WISE_API_TOKEN", "your_wise_api_token")

VIDEO_API_KEY = os.environ.get("VIDEO_API_KEY", "your_ai_video_api_key")
VIDEO_API_URL = "https://your-ai-video-api.com/generate"  # Replace with your AI generator

# -------------------
# Models
# -------------------
class PaymentRequest(BaseModel):
    amount: float
    currency: str
    email: str

class VideoRequest(BaseModel):
    prompt: str
    user_email: str

# -------------------
# In-memory DB
# -------------------
users_db = {}        # email -> {email, plan}
affiliates_db = {}   # code -> {email, commission}

# -------------------
# Helper
# -------------------
def can_generate_video(user_email):
    user = users_db.get(user_email)
    if not user:
        raise HTTPException(status_code=401, detail="User not found")
    return True

# -------------------
# Signup (auto ready for video)
# -------------------
@app.post("/api/signup")
async def signup(req: PaymentRequest):
    if req.email in users_db:
        raise HTTPException(status_code=400, detail="User already exists")
    users_db[req.email] = {"email": req.email, "plan": "free"}  # free plan by default
    return {"message": "User created, ready to generate videos"}

# -------------------
# Login
# -------------------
@app.post("/api/login")
async def login(req: PaymentRequest):
    if req.email not in users_db:
        raise HTTPException(status_code=400, detail="User not found")
    return {"message": "Login successful", "user": users_db[req.email]}

# -------------------
# Video Generation
# -------------------
@app.post("/api/generate-video")
async def generate_video(req: VideoRequest):
    can_generate_video(req.user_email)
    user = users_db[req.user_email]
    length = 6 if user["plan"] == "free" else 30  # free users = 6s, paid = 30s
    payload = {"prompt": req.prompt, "user_email": req.user_email, "length_seconds": length}
    headers = {"Authorization": f"Bearer {VIDEO_API_KEY}", "Content-Type": "application/json"}
    try:
        response = requests.post(VIDEO_API_URL, json=payload, headers=headers)
        response.raise_for_status()
        data = response.json()
        video_url = data.get("video_url")
        if not video_url:
            raise HTTPException(status_code=500, detail="Video generation failed")
        return {"video_url": video_url, "message": f"Video generated successfully ({length}s)"}
    except requests.RequestException as e:
        raise HTTPException(status_code=500, detail=f"Video API error: {str(e)}")

# -------------------
# Stripe Payment
# -------------------
@app.post("/api/create-stripe-payment")
async def create_stripe_payment(req: PaymentRequest):
    try:
        payment_intent = stripe.PaymentIntent.create(
            amount=int(req.amount * 100),
            currency=req.currency.lower(),
            receipt_email=req.email,
        )
        # Upgrade user to paid plan automatically
        if req.email in users_db:
            users_db[req.email]["plan"] = "paid"
        return {"client_secret": payment_intent.client_secret}
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))

# -------------------
# M-Pesa Express
# -------------------
@app.post("/api/mpesa-express")
async def mpesa_express(req: PaymentRequest):
    # Placeholder: implement STK push
    if req.email in users_db:
        users_db[req.email]["plan"] = "paid"
    return {"message": f"STK Push triggered for {req.amount} {req.currency} to {req.email}, user upgraded to paid"}

# -------------------
# Paystack
# -------------------
@app.post("/api/paystack-init")
async def paystack_init(req: PaymentRequest):
    headers = {"Authorization": f"Bearer {PAYSTACK_SECRET_KEY}", "Content-Type": "application/json"}
    data = {"email": req.email, "amount": int(req.amount * 100), "callback_url": "https://bb-6-ym40.onrender.com/api/paystack-webhook"}
    response = requests.post("https://api.paystack.co/transaction/initialize", json=data, headers=headers)
    return response.json()

@app.post("/api/paystack-webhook")
async def paystack_webhook(request: Request):
    event = await request.json()
    if event.get("event") == "charge.success":
        email = event["data"]["customer"]["email"]
        if email in users_db:
            users_db[email]["plan"] = "paid"
        return {"status": "success"}
    return {"status": "ignored"}

# -------------------
# Affiliate
# -------------------
@app.post("/api/affiliate")
async def affiliate(req: PaymentRequest):
    code = req.email.split("@")[0] + "_ref"
    affiliates_db[code] = {"email": req.email, "commission": 0}
    return {"referral_code": code, "message": "Affiliate created"}

# -------------------
# Run Server
# -------------------
if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=int(os.environ.get("PORT", 8000)))
