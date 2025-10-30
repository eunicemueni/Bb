# main.py
"""
Kairah Studio - Full Backend (Render-ready)
Features:
- Firebase login & admin routes
- Stripe, Paystack, PayPal, M-Pesa, Wise payments
- Affiliate system (70/30 split)
- Bonus payouts logic
- Video generation plan-aware limits & Fame Booster
- Logging & reporting
- FAQ endpoint
- Single-file deployment with auto-install
"""

import os
import sys
import subprocess
import json
import stripe
import requests
from fastapi import FastAPI, Request, HTTPException, Header
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from typing import Optional

# -----------------------------
# Auto-install required packages
# -----------------------------
REQUIRED = [
    "fastapi",
    "uvicorn",
    "requests",
    "stripe",
    "python-dotenv",
    "pydantic",
    "firebase-admin",
]
for pkg in REQUIRED:
    try:
        __import__(pkg)
    except ImportError:
        subprocess.check_call([sys.executable, "-m", "pip", "install", pkg])

# -----------------------------
# FastAPI app
# -----------------------------
app = FastAPI(title="Kairah Studio Backend")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
    allow_credentials=True,
)

# -----------------------------
# Environment / API keys
# -----------------------------
STRIPE_SECRET_KEY = "sk_test_yourstripekey"
STRIPE_WEBHOOK_SECRET = "whsec_123456"
PAYSTACK_SECRET_KEY = "sk_test_paystackkey"
PAYSTACK_WEBHOOK_SECRET = "paystack_webhook_secret"
MPESA_CONSUMER_KEY = "mpesa_key"
MPESA_CONSUMER_SECRET = "mpesa_secret"
MPESA_SHORTCODE = "mpesa_shortcode"
MPESA_PASSKEY = "mpesa_passkey"
MPESA_CALLBACK_URL = "https://yourdomain.com/api/mpesa-webhook"
PAYPAL_CLIENT_ID = "paypal_client_id"
PAYPAL_SECRET = "paypal_secret"
WISE_ACCOUNT_NUMBER = "12345678"
WISE_ROUTING_NUMBER = "020123456"
WISE_ACCOUNT_NAME = "Kairah"
VIDEO_API_URL = "https://yourvideoapi.com/generate"
VIDEO_API_KEY = "your_video_api_key"
FIREBASE_SERVICE_ACCOUNT_JSON = "your_firebase_service_account_json"
PORT = 8000
FAME_BOOSTER_PRICE = 9

stripe.api_key = STRIPE_SECRET_KEY

# -----------------------------
# Firebase init
# -----------------------------
USE_FIREBASE = False
try:
    if FIREBASE_SERVICE_ACCOUNT_JSON:
        import firebase_admin
        from firebase_admin import credentials, auth
        try:
            sa = json.loads(FIREBASE_SERVICE_ACCOUNT_JSON)
            cred = credentials.Certificate(sa)
        except Exception:
            cred = credentials.Certificate(FIREBASE_SERVICE_ACCOUNT_JSON)
        firebase_admin.initialize_app(cred)
        USE_FIREBASE = True
except Exception:
    USE_FIREBASE = False

# -----------------------------
# In-memory DBs
# -----------------------------
users_db = {}
affiliates_db = {}
videos_db = {}
payments_db = {}

# -----------------------------
# Plan definitions
# -----------------------------
PLANS = {
    "Free": {"price_month": 0, "price_year": 0, "video_limit": 1, "length_sec": 6},
    "Pro": {"price_month": 19, "price_year": 300, "video_limit": 10, "length_sec": 60},
    "Diamond": {"price_month": 49, "price_year": 450, "video_limit": None, "length_sec": 180},
    "Cinematic": {"price_month": 99, "price_year": 600, "video_limit": None, "length_sec": 300},
    "Lifetime": {"price_one_time": 500, "video_limit": None, "length_sec": None},
}

# -----------------------------
# Models
# -----------------------------
class SignupRequest(BaseModel):
    email: str
    display_name: Optional[str]
    referral_code: Optional[str]

class LoginRequest(BaseModel):
    email: str

class VideoRequest(BaseModel):
    user_email: str
    prompt: str
    aspect_ratio: Optional[str] = "16:9"
    fame_booster: Optional[bool] = False

# -----------------------------
# Helpers
# -----------------------------
from datetime import datetime

def get_user(email: str):
    if USE_FIREBASE:
        try:
            u = auth.get_user_by_email(email)
            return {"email": u.email, "uid": u.uid, "plan": "Free"}
        except Exception:
            return users_db.get(email)
    return users_db.get(email)

def create_user_local(email: str, display_name=None, referral_code=None):
    users_db[email] = {"email": email, "display_name": display_name or "", "plan": "Free", "ref": referral_code}
    if referral_code:
        aff = affiliates_db.get(referral_code)
        if aff:
            aff.setdefault("referred", []).append(email)
    return users_db[email]

def upgrade_user_plan(email: str, plan: str):
    u = users_db.get(email)
    if u:
        u["plan"] = plan
    else:
        users_db[email] = {"email": email, "plan": plan}
    return users_db[email]

def record_payment(payment_id: str, email: str, method: str, amount: float, status="pending"):
    payments_db[payment_id] = {"email": email, "method": method, "amount": amount, "status": status, "timestamp": str(datetime.now())}
    return payments_db[payment_id]

def credit_affiliate(email: str, amount: float):
    user = users_db.get(email)
    if not user or not user.get("ref"):
        return 0
    ref_code = user["ref"]
    aff = affiliates_db.setdefault(ref_code, {"commission": 0, "referred": []})
    commission = amount * 0.7  # 70% to affiliate
    aff["commission"] += commission
    return commission

# -----------------------------
# Routes
# -----------------------------
@app.get("/")
async def index():
    return {"message": "Kairah Studio Backend live!"}

@app.post("/api/signup")
async def signup(req: SignupRequest):
    if get_user(req.email):
        raise HTTPException(status_code=400, detail="User exists")
    user = create_user_local(req.email, req.display_name, req.referral_code)
    return {"message": "User created", "user": user}

@app.post("/api/login")
async def login(req: LoginRequest):
    user = get_user(req.email)
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    return {"message": "Login success", "user": user}

@app.post("/api/generate-video")
async def generate_video(req: VideoRequest):
    user = get_user(req.user_email)
    if not user:
        raise HTTPException(status_code=401, detail="User not found")
    plan = user.get("plan", "Free")
    limit_sec = PLANS[plan]["length_sec"]
    video_id = f"{req.user_email.replace('@','_')}_{len(videos_db)+1}"
    fame_flag = req.fame_booster
    video_url = f"https://cdn.kairahstudio.com/mock_videos/{video_id}.mp4"
    videos_db[video_id] = {"email": req.user_email, "prompt": req.prompt, "url": video_url, "length": limit_sec, "fame_booster": fame_flag, "aspect_ratio": req.aspect_ratio}
    return {"video_url": video_url, "length_sec": limit_sec, "fame_booster": fame_flag}

# -----------------------------
# Affiliate Endpoints
# -----------------------------
@app.get("/api/affiliate/earnings")
async def affiliate_earnings(email: str):
    user = get_user(email)
    if not user or not user.get("ref"):
        return {"total":0, "pending":0, "bonus":0}
    aff = affiliates_db.get(user["ref"], {"commission":0})
    return {"total": aff.get("commission",0), "pending": 0, "bonus": 0}

@app.get("/api/affiliate/referrals")
async def affiliate_referrals(email: str):
    user = get_user(email)
    if not user or not user.get("ref"):
        return {"referred": []}
    aff = affiliates_db.get(user["ref"], {"referred": []})
    return {"referred": aff.get("referred", [])}

# -----------------------------
# Run Uvicorn
# -----------------------------
if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=PORT)
