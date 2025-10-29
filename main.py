# main.py
"""
Kairah Studio — Single-file backend (Render-ready)
Features:
- Signup / Login (Firebase optional; fallback in-memory)
- Stripe checkout + webhook (auto-upgrade)
- Paystack init + webhook (auto-upgrade)
- M-Pesa STK Push init + callback (placeholder; auto-upgrade on callback)
- PayPal webhook endpoint + manual confirm endpoint (auto-upgrade if webhook delivered)
- Video generation endpoint (calls VIDEO_API_URL with VIDEO_API_KEY)
- Affiliate system (referral codes, commission tracking)
- Single-file deployment: installs missing packages at runtime (good for Render single-file flow)
USAGE:
- Add required environment variables listed below in Render
- Start Command: python main.py
- Build Command: echo "skip build"
"""

import os
import sys
import subprocess
import hmac
import hashlib
import json
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
# Imports
# -----------------------------
from fastapi import FastAPI, Request, HTTPException, Header
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
import requests
import stripe
from dotenv import load_dotenv

# -----------------------------
# Load .env if present
# -----------------------------
load_dotenv()

# -----------------------------
# App and CORS
# -----------------------------
app = FastAPI(title="Kairah Studio Backend")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # in prod replace with your frontend origin
    allow_methods=["*"],
    allow_headers=["*"],
    allow_credentials=True,
)

# -----------------------------
# Environment variables (set these in Render)
# -----------------------------
# Payment keys & webhooks
STRIPE_SECRET_KEY = os.environ.get("STRIPE_SECRET_KEY", "")
STRIPE_WEBHOOK_SECRET = os.environ.get("STRIPE_WEBHOOK_SECRET", "")  # from Stripe dashboard
PAYSTACK_SECRET_KEY = os.environ.get("PAYSTACK_SECRET_KEY", "")      # sk_test_...
PAYSTACK_WEBHOOK_SECRET = os.environ.get("PAYSTACK_WEBHOOK_SECRET", "")  # optional (for signature)
MPESA_CONSUMER_KEY = os.environ.get("MPESA_CONSUMER_KEY", "")
MPESA_CONSUMER_SECRET = os.environ.get("MPESA_CONSUMER_SECRET", "")
MPESA_SHORTCODE = os.environ.get("MPESA_SHORTCODE", "")
MPESA_PASSKEY = os.environ.get("MPESA_PASSKEY", "")
MPESA_CALLBACK_URL = os.environ.get("MPESA_CALLBACK_URL", "")  # e.g. https://<your>/api/mpesa-callback
PAYPAL_WEBHOOK_ID = os.environ.get("PAYPAL_WEBHOOK_ID", "")  # if using PayPal webhooks
PAYPAL_CLIENT_ID = os.environ.get("PAYPAL_CLIENT_ID", "")
PAYPAL_CLIENT_SECRET = os.environ.get("PAYPAL_CLIENT_SECRET", "")

# Video generation
VIDEO_API_URL = os.environ.get("VIDEO_API_URL", "")   # your AI video engine endpoint
VIDEO_API_KEY = os.environ.get("VIDEO_API_KEY", "")   # key for the video engine

# Wise (placeholder)
WISE_API_TOKEN = os.environ.get("WISE_API_TOKEN", "")

# Firebase (optional): supply JSON service account as a base64 or path
FIREBASE_SERVICE_ACCOUNT_JSON = os.environ.get("FIREBASE_SERVICE_ACCOUNT_JSON", "")

# Misc
APP_NAME = os.environ.get("APP_NAME", "Kairah Studio")
PORT = int(os.environ.get("PORT", 8000))

# -----------------------------
# Initialize Stripe
# -----------------------------
if STRIPE_SECRET_KEY:
    stripe.api_key = STRIPE_SECRET_KEY

# -----------------------------
# Firebase init (optional)
# -----------------------------
USE_FIREBASE = False
try:
    if FIREBASE_SERVICE_ACCOUNT_JSON:
        import firebase_admin
        from firebase_admin import credentials, auth
        # If JSON string provided (base64 or raw), try to parse
        try:
            sa = json.loads(FIREBASE_SERVICE_ACCOUNT_JSON)
            cred = credentials.Certificate(sa)
        except Exception:
            # treat as a filepath
            cred = credentials.Certificate(FIREBASE_SERVICE_ACCOUNT_JSON)
        firebase_admin.initialize_app(cred)
        USE_FIREBASE = True
except Exception:
    USE_FIREBASE = False

# -----------------------------
# Simple in-memory DB (fallback)
# -----------------------------
users_db = {}        # email -> {"email":..., "plan":"free|paid|diamond", "ref": ref_code}
affiliates_db = {}   # ref_code -> {"email":..., "commission": float}
videos_db = {}       # video_id -> {"email":..., "prompt":..., "url":...}
payments_db = {}     # payment_id -> {"email", "method", "amount", "status"}

# -----------------------------
# Models
# -----------------------------
class SignupRequest(BaseModel):
    email: str
    display_name: Optional[str] = None
    referral_code: Optional[str] = None

class LoginRequest(BaseModel):
    email: str

class VideoRequest(BaseModel):
    prompt: str
    user_email: str

class PaymentInitRequest(BaseModel):
    amount: float
    currency: str = "KES"
    email: str
    metadata: Optional[dict] = None

# -----------------------------
# Helpers
# -----------------------------
def get_user(email: str):
    if USE_FIREBASE:
        # try to get user from Firebase; if not found, fallback to local
        try:
            from firebase_admin import auth as fb_auth
            u = fb_auth.get_user_by_email(email)
            # minimal representation
            return {"email": u.email, "uid": u.uid, "plan": "free"}
        except Exception:
            return users_db.get(email)
    return users_db.get(email)

def create_user_local(email: str, display_name: Optional[str] = None, referral_code: Optional[str] = None):
    users_db[email] = {"email": email, "display_name": display_name or "", "plan": "free", "ref": referral_code}
    # register affiliate if referral code present
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
    # if user was referred, credit that referrer
    user = users_db.get(email)
    if not user:
        return
    ref = user.get("ref")
    if not ref:
        return
    aff = affiliates_db.get(ref)
    if aff is None:
        return
    # simple commission: 5%
    commission = amount * 0.05
    aff["commission"] = aff.get("commission", 0) + commission
    return commission

# -----------------------------
# Routes
# -----------------------------
@app.get("/")
def index():
    return {"message": f"{APP_NAME} backend is live."}

# --- Signup / Login ---
@app.post("/api/signup")
def api_signup(req: SignupRequest):
    if get_user(req.email):
        raise HTTPException(status_code=400, detail="User already exists")
    user = create_user_local(req.email, req.display_name, req.referral_code)
    return {"message": "User created", "user": user}

@app.post("/api/login")
def api_login(req: LoginRequest):
    user = get_user(req.email)
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    return {"message": "Login success", "user": user}

# --- Affiliate creation ---
@app.post("/api/affiliate/create")
def api_create_affiliate(req: SignupRequest):
    # create a referral code based on email prefix (simple)
    code = req.email.split("@")[0] + "_ref"
    affiliates_db[code] = {"email": req.email, "commission": 0.0, "referred": []}
    return {"referral_code": code, "message": "Affiliate created"}

# --- Video generation ---
@app.post("/api/generate-video")
def api_generate_video(req: VideoRequest):
    user = get_user(req.user_email)
    if not user:
        raise HTTPException(status_code=401, detail="User not found. Please signup/login.")
    # plan-based length
    length = 6 if user.get("plan", "free") == "free" else 30
    # call external video API
    if not VIDEO_API_URL or not VIDEO_API_KEY:
        # fallback: return mock URL (useful for testing)
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
        # record
        video_id = f"{req.user_email.replace('@','_')}_{len(videos_db)+1}"
        videos_db[video_id] = {"email": req.user_email, "prompt": req.prompt, "url": video_url, "length": length}
        return {"video_url": video_url, "message": f"Video generated ({length}s)"}
    except requests.RequestException as e:
        raise HTTPException(status_code=502, detail=f"Video service error: {str(e)}")

# --- Stripe: create payment intent / checkout session (example uses PaymentIntent) ---
@app.post("/api/stripe/create-payment-intent")
def stripe_create_payment_intent(req: PaymentInitRequest):
    if not STRIPE_SECRET_KEY:
        raise HTTPException(status_code=400, detail="Stripe not configured")
    try:
        intent = stripe.PaymentIntent.create(
            amount=int(req.amount * 100),
            currency=req.currency.lower(),
            receipt_email=req.email,
            metadata=req.metadata or {},
        )
        # record pending payment
        record_payment(intent.id, req.email, "stripe", req.amount, status="pending")
        return {"client_secret": intent.client_secret, "id": intent.id}
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))

# --- Stripe webhook to confirm payments and auto-upgrade ---
@app.post("/api/stripe/webhook")
async def stripe_webhook(request: Request, stripe_signature: Optional[str] = Header(None)):
    payload = await request.body()
    sig_header = stripe_signature
    event = None
    # If webhook secret provided, verify signature
    if STRIPE_WEBHOOK_SECRET and sig_header:
        try:
            event = stripe.Webhook.construct_event(payload, sig_header, STRIPE_WEBHOOK_SECRET)
        except Exception as e:
            raise HTTPException(status_code=400, detail=f"Webhook signature verification failed: {str(e)}")
    else:
        # fallback: parse JSON without verification (less secure)
        try:
            event = json.loads(payload)
        except Exception:
            raise HTTPException(status_code=400, detail="Invalid payload")
    # Handle event types
    etype = event.get("type") if isinstance(event, dict) else getattr(event, "type", None)
    if etype == "payment_intent.succeeded" or etype == "charge.succeeded":
        # obtain email & id
        data = event.get("data", {}).get("object", {}) if isinstance(event, dict) else event.data.object
        payment_id = data.get("id") or data.get("payment_intent") or ""
        amount = (data.get("amount") or 0) / 100.0
        receipt_email = data.get("receipt_email") or (data.get("billing_details") or {}).get("email")
        # upgrade user
        if receipt_email:
            upgrade_user_plan(receipt_email, "paid")
            record_payment(payment_id or "", receipt_email, "stripe", amount, status="succeeded")
            # affiliate credit
            try:
                credit_affiliate(receipt_email, amount)
            except:
                pass
        return {"status": "success"}
    return {"status": "ignored"}

# --- Paystack: initialize transaction ---
@app.post("/api/paystack/init")
def paystack_init(req: PaymentInitRequest):
    if not PAYSTACK_SECRET_KEY:
        raise HTTPException(status_code=400, detail="Paystack not configured")
    url = "https://api.paystack.co/transaction/initialize"
    headers = {"Authorization": f"Bearer {PAYSTACK_SECRET_KEY}", "Content-Type": "application/json"}
    data = {"email": req.email, "amount": int(req.amount * 100), "currency": req.currency, "callback_url": os.environ.get("PAYSTACK_CALLBACK_URL", "")}
    try:
        resp = requests.post(url, json=data, headers=headers)
        resp.raise_for_status()
        j = resp.json()
        # record pending
        init_ref = j.get("data", {}).get("reference")
        if init_ref:
            record_payment(init_ref, req.email, "paystack", req.amount, status="pending")
        return j
    except requests.RequestException as e:
        raise HTTPException(status_code=502, detail=str(e))

# --- Paystack webhook (verify signature if provided) ---
@app.post("/api/paystack/webhook")
async def paystack_webhook(request: Request, x_paystack_signature: Optional[str] = Header(None)):
    payload_bytes = await request.body()
    payload = payload_bytes.decode()
    # Verify signature if secret provided
    if PAYSTACK_WEBHOOK_SECRET and x_paystack_signature:
        computed = hmac.new(PAYSTACK_WEBHOOK_SECRET.encode(), msg=payload_bytes, digestmod=hashlib.sha512).hexdigest()
        if not hmac.compare_digest(computed, x_paystack_signature):
            raise HTTPException(status_code=400, detail="Invalid Paystack signature")
    try:
        event = json.loads(payload)
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid payload")
    if event.get("event") == "charge.success":
        data = event.get("data", {})
        amount = (data.get("amount") or 0) / 100.0
        reference = data.get("reference")
        customer = data.get("customer", {})
        email = (customer.get("email") or data.get("customer_email") or "")
        # upgrade
        if email:
            upgrade_user_plan(email, "paid")
            record_payment(reference or "", email, "paystack", amount, status="succeeded")
            credit_affiliate(email, amount)
        return {"status": "ok"}
    return {"status": "ignored"}

# --- M-Pesa: STK Push Init (placeholder) ---
@app.post("/api/mpesa/init")
def mpesa_init(req: PaymentInitRequest):
    # This implementation is placeholder. To do real STK push:
    # 1) Get OAuth token from Safaricom with consumer key/secret
    # 2) Build password = base64(shortcode + passkey + timestamp)
    # 3) POST to STK push endpoint with required fields
    # 4) Record reference & wait for callback at /api/mpesa/callback
    record_payment("mpesa_init_"+str(len(payments_db)+1), req.email, "mpesa", req.amount, status="pending")
    return {"message": "M-Pesa STK Push initiated (placeholder). Configure real STK logic with Safaricom credentials."}

# --- M-Pesa callback (Safaricom will POST here when STK Push completes) ---
@app.post("/api/mpesa/callback")
async def mpesa_callback(request: Request):
    # Safaricom will POST JSON with result; parse and upgrade user if succeeded
    payload = await request.json()
    # You should inspect payload structure from Safaricom docs
    # This is a generic handler: if it finds phone/email and success status -> upgrade
    # Example: payload.get("Body", {}).get("stkCallback", {})
    try:
        stk = payload.get("Body", {}).get("stkCallback", {})
        result_code = stk.get("ResultCode")
        metadata = stk.get("CallbackMetadata", {}).get("Item", [])
        # extract phone or transaction amount
        phone = None
        for item in metadata:
            if item.get("Name") in ("PhoneNumber", "MpesaReceiptNumber", "Amount"):
                # best-effort extraction
                pass
        if result_code == 0:
            # success: we do not reliably have user email from M-Pesa; match via stored payments or ask frontend to pass metadata
            # For now, mark the last pending mpesa payment as succeeded
            for pid, p in payments_db.items():
                if p["method"] == "mpesa" and p["status"] == "pending":
                    payments_db[pid]["status"] = "succeeded"
                    # upgrade by email
                    upgrade_user_plan(p["email"], "paid")
                    credit_affiliate(p["email"], p["amount"])
                    break
            return {"status": "success"}
    except Exception:
        pass
    return {"status": "ignored"}

# --- PayPal webhook (if you have webhook configured) ---
@app.post("/api/paypal/webhook")
async def paypal_webhook(request: Request):
    payload = await request.json()
    # For full verification you should call PayPal's /v1/notifications/verify-webhook-signature
    # Here we do a simple handler: when payment completed, upgrade user
    event_type = payload.get("event_type")
    if event_type in ("PAYMENT.CAPTURE.COMPLETED", "CHECKOUT.ORDER.APPROVED"):
        # extract payer email & amount
        resource = payload.get("resource", {})
        payer = resource.get("payer", {})
        email = ""
        if payer:
            email = (payer.get("email_address") or payer.get("payer_email") or "")
        amount = 0.0
        amt_obj = resource.get("amount") or resource.get("purchase_units", [{}])[0].get("amount", {})
        try:
            amount = float(amt_obj.get("value", 0.0))
        except:
            amount = 0.0
        if email:
            upgrade_user_plan(email, "paid")
            record_payment("paypal_"+str(len(payments_db)+1), email, "paypal", amount, status="succeeded")
            credit_affiliate(email, amount)
        return {"status": "ok"}
    return {"status": "ignored"}

# Manual PayPal confirm (useful for personal PayPal: you confirm after receiving a PayPal.me payment)
@app.post("/api/paypal/manual-confirm")
def paypal_manual_confirm(email: str, amount: float):
    # admin/manual endpoint: mark a PayPal payment as succeeded and upgrade user
    pid = f"paypal_manual_{len(payments_db)+1}"
    record_payment(pid, email, "paypal", amount, status="succeeded")
    upgrade_user_plan(email, "paid")
    credit_affiliate(email, amount)
    return {"status": "ok", "payment_id": pid}

# --- Wise placeholder for payouts (expand as needed) ---
@app.post("/api/wise/payout")
def wise_payout(email: str, amount: float, currency: str = "USD"):
    # Placeholder: you need WISE_API_TOKEN and proper beneficiary setup
    if not WISE_API_TOKEN:
        raise HTTPException(status_code=400, detail="Wise not configured")
    # Implement Wise transfer creation here
    return {"status": "queued", "message": "Wise payout placeholder — implement beneficiary creation & transfer"}

# --- Admin / Debug endpoints (protected in production) ---
@app.get("/api/admin/status")
def admin_status():
    return {
        "users_count": len(users_db),
        "affiliates_count": len(affiliates_db),
        "payments_count": len(payments_db),
    }

@app.get("/api/user/{email}")
def admin_get_user(email: str):
    return users_db.get(email) or {"error": "not found"}

# -----------------------------
# Run app
# -----------------------------
if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=PORT)
