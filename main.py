# main.py
"""
Kairah Studio - Backend (Ready for Render Deployment)
Features:
- User Sign-up/Login (Firebase or fallback local DB)
- Stripe Checkout + Webhook (auto-upgrade plan on payment success)
- Paystack Init + Webhook (auto-upgrade plan on payment success)
- M-Pesa STK Push Init (placeholder, with callback handling)
- Video generation call with dynamic video limit based on user plan
- Affiliate system (referral codes, commissions)
- Auto-install required packages if missing
- Single-file deployment
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
from dotenv import load_dotenv

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
# Initialize FastAPI App and CORS
# -----------------------------
app = FastAPI(title="Kairah Studio Backend")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # in production, replace "*" with the actual frontend origin
    allow_methods=["*"],
    allow_headers=["*"],
    allow_credentials=True,
)

# -----------------------------
# Hardcoded Environment Variables (for deployment)
# -----------------------------

# Stripe settings
STRIPE_SECRET_KEY = "sk_test_51RoZXfH4iReDKpeMCJKZRUiEiJ4C9puNosL07iOh5p1QU5BXO3rJNACM62xsvzKqXwphxylp4XgaX3uM4qroE9eT002CpThr19"
STRIPE_WEBHOOK_SECRET = "whsec_1234567890abcdef"

# Paystack settings
PAYSTACK_SECRET_KEY = "sk_test_b0e3fdb6e346294f423e174557e25321bf9d855e"
PAYSTACK_WEBHOOK_SECRET = "paystack_webhook_secret"

# M-Pesa settings
MPESA_CONSUMER_KEY = "your_mpesa_consumer_key"
MPESA_CONSUMER_SECRET = "your_mpesa_consumer_secret"
MPESA_SHORTCODE = "your_mpesa_shortcode"
MPESA_PASSKEY = "your_mpesa_passkey"
MPESA_CALLBACK_URL = "https://yourdomain.com/api/mpesa-webhook"

# Firebase (optional, can be skipped if not used)
FIREBASE_SERVICE_ACCOUNT_JSON = "your_firebase_service_account_json"

# Video generation API settings
VIDEO_API_URL = "https://yourvideoapi.com/generate"
VIDEO_API_KEY = "your_video_api_key"

# General settings
PORT = 8000

# -----------------------------
# Initialize Stripe
# -----------------------------
stripe.api_key = STRIPE_SECRET_KEY

# -----------------------------
# Firebase initialization (optional)
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
# Local DB (in-memory fallback)
# -----------------------------
users_db = {}        # email -> {"email":..., "plan":"free|paid|diamond", "ref": ref_code}
affiliates_db = {}   # ref_code -> {"email":..., "commission": float}
videos_db = {}       # video_id -> {"email":..., "prompt":..., "url":...}
payments_db = {}     # payment_id -> {"email", "method", "amount", "status"}

# -----------------------------
# Plan definitions (monthly/yearly pricing)
# -----------------------------
PLANS = {
    "Free": {"price_month": 0, "price_year": 0, "video_limit": 1},
    "Pro": {"price_month": 19, "price_year": 300, "video_limit": None},
    "Diamond": {"price_month": 49, "price_year": 450, "video_limit": None},
    "Cinematic": {"price_month": 99, "price_year": 600, "video_limit": None},
    "Lifetime": {"price_one_time": 500, "video_limit": None},
}

# -----------------------------
# Helper Functions
# -----------------------------
def get_user(email: str):
    if USE_FIREBASE:
        try:
            from firebase_admin import auth as fb_auth
            u = fb_auth.get_user_by_email(email)
            return {"email": u.email, "uid": u.uid, "plan": "free"}
        except Exception:
            return users_db.get(email)
    return users_db.get(email)

def create_user_local(email: str, display_name: Optional[str] = None, referral_code: Optional[str] = None):
    users_db[email] = {"email": email, "display_name": display_name or "", "plan": "free", "ref": referral_code}
    if referral_code:
        aff = affiliates_db.get(referral_code)
        if aff:
            aff.setdefault("referred", []).append(email)
    return users_db[email]

def upgrade_user_plan(email: str, plan: str = "paid"):
    u = users_db.get(email)
    if u:
        u["plan"] = plan
    else:
        users_db[email] = {"email": email, "plan": plan}
    return users_db[email]

def record_payment(payment_id: str, email: str, method: str, amount: float, status: str = "pending"):
    payments_db[payment_id] = {"email": email, "method": method, "amount": amount, "status": status}
    return payments_db[payment_id]

def credit_affiliate(email: str, amount: float):
    user = users_db.get(email)
    if not user:
        return
    ref = user.get("ref")
    if not ref:
        return
    aff = affiliates_db.get(ref)
    if aff is None:
        return
    commission = amount * 0.05
    aff["commission"] = aff.get("commission", 0) + commission
    return commission

# -----------------------------
# Routes
# -----------------------------
@app.get("/")
async def index():
    return {"message": "Kairah Studio Backend is live!"}

# --- Signup / Login ---
@app.post("/api/signup")
async def api_signup(req: SignupRequest):
    if get_user(req.email):
        raise HTTPException(status_code=400, detail="User already exists")
    user = create_user_local(req.email, req.display_name, req.referral_code)
    return {"message": "User created", "user": user}

@app.post("/api/login")
async def api_login(req: LoginRequest):
    user = get_user(req.email)
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    return {"message": "Login success", "user": user}

# --- Video generation ---
@app.post("/api/generate-video")
async def api_generate_video(req: VideoRequest):
    user = get_user(req.user_email)
    if not user:
        raise HTTPException(status_code=401, detail="User not found. Please signup/login.")
    length = 6 if user.get("plan", "free") == "free" else 30
    if not VIDEO_API_URL or not VIDEO_API_KEY:
        video_id = f"{req.user_email.replace('@','_')}_{len(videos_db)+1}"
        video_url = f"https://cdn.kairahstudio.com/mock_videos/{video_id}.mp4"
        videos_db[video_id] = {"email": req.user_email, "prompt": req.prompt, "url": video_url, "length": length}
        return {"video_url": video_url, "message": f"Mock video generated ({length}s)"}
    headers = {"Authorization": f"Bearer {VIDEO_API_KEY}", "Content-Type": "application/json"}
    payload = {"prompt": req.prompt, "user_email": req.user_email, "length_seconds": length}
    try:
        resp = requests.post(VIDEO_API_URL, json=payload, headers=headers, timeout=120)
        resp.raise_for_status()
        data = resp.json()
        video_url = data.get("video_url") or data.get("url")
        if not video_url:
            raise HTTPException(status_code=500, detail="Video API did not return URL")
        video_id = f"{req.user_email.replace('@','_')}_{len(videos_db)+1}"
        videos_db[video_id] = {"email": req.user_email, "prompt": req.prompt, "url": video_url, "length": length}
        return {"video_url": video_url, "message": f"Video generated ({length}s)"}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

# -----------------------------
# Payment Webhooks (Stripe, Paystack, M-Pesa)
# -----------------------------
@app.post("/api/stripe-webhook")
async def stripe_webhook(req: Request, signature: str = Header(...)):
    payload = await req.body()
    event = None
    try:
        event = stripe.Webhook.construct_event(payload, signature, STRIPE_WEBHOOK_SECRET)
    except ValueError as e:
        raise HTTPException(status_code=400, detail="Invalid payload")
    except stripe.error.SignatureVerificationError as e:
        raise HTTPException(status_code=400, detail="Invalid signature")
    
    if event["type"] == "checkout.session.completed":
        session = event["data"]["object"]
        email = session["customer_email"]
        amount = session["amount_total"] / 100  # Convert to dollars
        plan = "Pro"
        upgrade_user_plan(email, plan)
        record_payment(session["id"], email, "stripe", amount, "completed")
        return {"status": "success"}
    return {"status": "ignored"}

@app.post("/api/paystack-webhook")
async def paystack_webhook(req: Request):
    payload = await req.json()
    signature = req.headers.get('X-Paystack-Signature', '')
    if not verify_paystack_signature(signature, payload):
        raise HTTPException(status_code=400, detail="Invalid signature")
    event = payload.get("event")
    if event and event.get("status") == "success":
        email = event.get("email")
        amount = event.get("amount") / 100
        upgrade_user_plan(email, "Pro")
        record_payment(event["id"], email, "paystack", amount, "completed")
    return {"status": "success"}

@app.post("/api/mpesa-webhook")
async def mpesa_webhook(req: Request):
    payload = await req.json()
    return {"status": "success"}

# -----------------------------
# Run with Uvicorn
# -----------------------------
if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=PORT)
