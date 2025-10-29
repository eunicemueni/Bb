import os
import sys
import subprocess
import json
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
# Initialize FastAPI App
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
# Environment Variables / Keys
# -----------------------------
PAYSTACK_SECRET_KEY = os.getenv("PAYSTACK_SECRET_KEY", "your_paystack_secret")
PAYSTACK_WEBHOOK_SECRET = os.getenv("PAYSTACK_WEBHOOK_SECRET", "paystack_webhook_secret")
PAYPAL_CLIENT_ID = os.getenv("PAYPAL_CLIENT_ID", "your_paypal_client_id")
PAYPAL_SECRET = os.getenv("PAYPAL_SECRET", "your_paypal_secret")
MPESA_CONSUMER_KEY = os.getenv("MPESA_CONSUMER_KEY", "your_mpesa_key")
MPESA_CONSUMER_SECRET = os.getenv("MPESA_CONSUMER_SECRET", "your_mpesa_secret")
MPESA_SHORTCODE = os.getenv("MPESA_SHORTCODE", "your_shortcode")
MPESA_PASSKEY = os.getenv("MPESA_PASSKEY", "your_passkey")
MPESA_CALLBACK_URL = os.getenv("MPESA_CALLBACK_URL", "https://yourdomain.com/api/mpesa-webhook")

# Wise Payment Integration Environment Variables
WISE_API_KEY = os.getenv("WISE_API_KEY", "your_wise_api_key")  # Add your Wise API Key here
WISE_BUSINESS_NAME = os.getenv("WISE_BUSINESS_NAME", "kairah")  # Your business name on Wise
WISE_ROUTING_NUMBER = os.getenv("WISE_ROUTING_NUMBER", "020123456")  # Routing number for Wise payments
WISE_ACCOUNT_NUMBER = os.getenv("WISE_ACCOUNT_NUMBER", "12345678")  # Account number for Wise payments

VIDEO_API_URL = os.getenv("VIDEO_API_URL", "https://yourvideoapi.com/generate")
VIDEO_API_KEY = os.getenv("VIDEO_API_KEY", "your_video_api_key")
PORT = int(os.getenv("PORT", 8000))
FIREBASE_SERVICE_ACCOUNT_JSON = os.getenv("FIREBASE_SERVICE_ACCOUNT_JSON", "")

# -----------------------------
# Firebase Initialization
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
# In-memory DB
# -----------------------------
users_db = {}
affiliates_db = {}
videos_db = {}
payments_db = {}

PLANS = {
    "Free": {"price_month": 0, "price_year": 0, "video_limit": 1},
    "Pro": {"price_month": 19, "price_year": 300, "video_limit": 10},
    "Diamond": {"price_month": 49, "price_year": 450, "video_limit": None},
    "Cinematic": {"price_month": 99, "price_year": 600, "video_limit": None},
    "Lifetime": {"price_one_time": 500, "video_limit": None},
}

FAME_BOOSTER_PRICE = 9

# -----------------------------
# Helper functions: Users, Payments, Affiliates
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

def upgrade_user_plan(email: str, plan: str):
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
    if not user: return
    ref = user.get("ref")
    if not ref: return
    aff = affiliates_db.get(ref)
    if aff is None: return
    commission = amount * 0.3  # 30% commission
    aff["commission"] = aff.get("commission", 0) + commission
    return commission

# -----------------------------
# Routes: Signup/Login, Video, Payments, Affiliate, Admin
# -----------------------------
@app.get("/")
async def index():
    return {"message": "Kairah Studio Backend Live!"}

# -----------------------------
# Route to Handle Wise Payment Webhook
# -----------------------------
@app.post("/api/wise-webhook")
async def wise_webhook(req: Request):
    payload = await req.json()
    # Process the Wise payment webhook payload
    if payload.get("status") == "COMPLETED":
        email = payload.get("email")
        amount = payload.get("amount")
        plan = "Pro"  # Update based on the plan purchased
        upgrade_user_plan(email, plan)
        record_payment(payload["id"], email, "wise", amount, "completed")
    return {"status": "success"}

# -----------------------------
# Payment Methods (to be displayed in frontend)
# -----------------------------
@app.get("/api/payment-methods")
async def payment_methods():
    return {
        "methods": [
            {"name": "Wise", "method": "wise", "icon": "wise_icon_url_here"},
            {"name": "Paystack", "method": "paystack", "icon": "paystack_icon_url_here"},
            {"name": "PayPal", "method": "paypal", "icon": "paypal_icon_url_here"},
            {"name": "M-Pesa", "method": "mpesa", "icon": "mpesa_icon_url_here"},
        ]
    }

# -----------------------------
# Run Server
# -----------------------------
if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=PORT)
