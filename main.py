# main.py
"""
Kairah Studio single-file backend (Stripe + mocked PayPal + email notifications)
Drop into Render as the only file in the repo.
Environment variables control secrets (do not paste them here).
"""

import os
import json
import stripe
import requests
import smtplib
from email.message import EmailMessage
from typing import Optional, Dict, Any
from fastapi import FastAPI, Request, HTTPException, Header, Depends
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from datetime import datetime, timezone

# ---------- CONFIG FROM ENV ----------
STRIPE_SECRET = os.getenv("STRIPE_SECRET", "")
STRIPE_WEBHOOK_SECRET = os.getenv("STRIPE_WEBHOOK_SECRET", "")
# Example: {"pro_month":"price_xxx","diamond_month":"price_yyy","lifetime":"price_zzz"}
STRIPE_PRICE_MAP = json.loads(os.getenv("STRIPE_PRICE_MAP", "{}") or "{}")

# PayPal will be mocked until your account is verified
PAYPAL_MOCK_MODE = os.getenv("PAYPAL_MOCK_MODE", "true").lower() in ("1","true","yes")

# Email / support
SUPPORT_EMAIL = os.getenv("SUPPORT_EMAIL", "keishapoa@gmail.com")
SMTP_HOST = os.getenv("SMTP_HOST", "")
SMTP_PORT = int(os.getenv("SMTP_PORT", "587"))
SMTP_USER = os.getenv("SMTP_USER", "")
SMTP_PASS = os.getenv("SMTP_PASS", "")

# Affiliate & admin
AFFILIATE_COMMISSION = float(os.getenv("AFFILIATE_COMMISSION", "0.30"))
ADMIN_TOKEN = os.getenv("ADMIN_TOKEN", "change-this-to-a-strong-token")

# Optional Firebase admin credentials JSON (path or JSON string)
FIREBASE_CREDENTIALS_JSON = os.getenv("FIREBASE_CREDENTIALS_JSON", "")
FRONTEND_BASE = os.getenv("FRONTEND_BASE", "https://your-frontend.example")

# --------- INIT LIBS ----------
app = FastAPI(title="Kairah Studio Backend (single-file)")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # tighten in production
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

if STRIPE_SECRET:
    stripe.api_key = STRIPE_SECRET

# Minimal in-memory stores used if Firestore not configured
_affiliates = {}    # affiliate_id -> {earnings: float, sales:int}
_users = {}         # email -> {plan, usage}
_jobs = []          # job history

# ---------- Pydantic models ----------
class StripeSessionRequest(BaseModel):
    uid: Optional[str] = None
    price_key: str
    affiliate_id: Optional[str] = None
    mode: Optional[str] = "subscription"

class PayPalOrderRequest(BaseModel):
    uid: Optional[str] = None
    plan_key: str
    amount: float
    affiliate_id: Optional[str] = None

class GenerateRequest(BaseModel):
    uid: str
    prompt: str
    style: Optional[Dict[str, Any]] = None

# ---------- Utilities ----------
def log(msg: str):
    print(f"[{datetime.now(timezone.utc).isoformat()}] {msg}")

def send_email(subject: str, body: str, to: Optional[str] = None, reply_to: Optional[str] = None):
    """
    Sends email via SMTP if credentials provided. If not configured, prints to logs.
    """
    to_addr = to or SUPPORT_EMAIL
    msg = EmailMessage()
    msg["Subject"] = subject
    msg["From"] = SMTP_USER or "no-reply@kairahstudio.com"
    msg["To"] = to_addr
    if reply_to:
        msg["Reply-To"] = reply_to
    msg.set_content(body)
    if SMTP_HOST and SMTP_USER and SMTP_PASS:
        try:
            with smtplib.SMTP(SMTP_HOST, SMTP_PORT, timeout=15) as s:
                s.starttls()
                s.login(SMTP_USER, SMTP_PASS)
                s.send_message(msg)
            log(f"Email sent to {to_addr} (subject: {subject})")
        except Exception as e:
            log(f"Email send error: {e}. Subject: {subject}. Body: {body}")
    else:
        # Not configured — log the email
        log(f"(EMAIL-SKIP) To: {to_addr}, Subject: {subject}\n{body}")

def record_affiliate_sale(affiliate_id: str, amount: float, source: str = "stripe"):
    if not affiliate_id:
        return
    entry = _affiliates.setdefault(affiliate_id, {"earnings":0.0, "sales":0})
    commission = round(amount * AFFILIATE_COMMISSION, 2)
    entry["earnings"] += commission
    entry["sales"] += 1
    log(f"Affiliate {affiliate_id} credited {commission} from {source} (gross {amount})")
    return commission

def save_job(uid: str, typ: str, prompt: str, result_url: str):
    job = {"uid":uid,"type":typ,"prompt":prompt,"result_url":result_url,"created_at":datetime.now(timezone.utc).isoformat()}
    _jobs.append(job)
    return job

# ---------- Routes ----------
@app.get("/")
def root():
    return {"message": "Kairah Studio Backend Running ✅", "time": datetime.now(timezone.utc).isoformat()}

# Prices endpoint (for frontend)
@app.get("/prices")
def prices():
    return {"prices": STRIPE_PRICE_MAP or {"pro_month":"price_pro","diamond_month":"price_diamond","lifetime":"price_life"}}

# Create Stripe Checkout Session (frontend calls this to get checkout url)
@app.post("/create-stripe-session")
def create_stripe_session(req: StripeSessionRequest):
    if not STRIPE_SECRET:
        raise HTTPException(500, "Stripe not configured on server")
    price_id = STRIPE_PRICE_MAP.get(req.price_key) or req.price_key
    if not price_id:
        raise HTTPException(400, "Invalid price_key")
    metadata = {"affiliate_id": req.affiliate_id or "", "uid": req.uid or ""}
    try:
        session = stripe.checkout.Session.create(
            payment_method_types=["card"],
            line_items=[{"price": price_id, "quantity":1}],
            mode="subscription" if req.mode=="subscription" else "payment",
            metadata=metadata,
            success_url=f"{FRONTEND_BASE}/payments/success?session_id={{CHECKOUT_SESSION_ID}}",
            cancel_url=f"{FRONTEND_BASE}/payments/cancel"
        )
        return {"id": session.id, "url": session.url}
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))

# Stripe webhook to confirm payments
@app.post("/webhook/stripe")
async def stripe_webhook(request: Request):
    if not STRIPE_WEBHOOK_SECRET:
        raise HTTPException(500, "Stripe webhook secret missing")
    payload = await request.body()
    sig_header = request.headers.get("stripe-signature", "")
    try:
        event = stripe.Webhook.construct_event(payload, sig_header, STRIPE_WEBHOOK_SECRET)
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Webhook signature error: {e}")

    typ = event["type"]
    data = event["data"]["object"]
    log(f"Stripe event received: {typ}")

    # Handle checkout.session.completed
    if typ == "checkout.session.completed":
        session = data
        metadata = session.get("metadata") or {}
        affiliate = metadata.get("affiliate_id") or ""
        uid = metadata.get("uid") or ""
        amount = None
        try:
            amount = session.get("amount_total") / 100.0 if session.get("amount_total") else None
        except:
            amount = None
        # record affiliate
        if affiliate and amount:
            commission = record_affiliate_sale(affiliate, amount, source="stripe")
            # notify support
            subj = f"Kairah: Affiliate credited ${commission} (affiliate: {affiliate})"
            body = f"Affiliate {affiliate} earned ${commission} from a Stripe sale. Gross: ${amount}. Session: {session.get('id')}"
            send_email(subj, body)
        # notify support + user if possible
        subj_s = "Kairah: New Stripe purchase"
        body_s = f"Stripe purchase completed. UID: {uid}. Amount: ${amount}. Session: {session.get('id')}"
        send_email(subj_s, body_s)
    # invoice.payment_succeeded - recurring events
    if typ == "invoice.payment_succeeded":
        invoice = data
        amt = invoice.get("amount_paid")/100.0 if invoice.get("amount_paid") else None
        send_email("Kairah: Recurring payment succeeded", f"Invoice {invoice.get('id')} paid: ${amt}")
    return {"status":"ok"}

# Create PayPal order (mocked if PAYPAL_MOCK_MODE=true)
@app.post("/create-paypal-order")
def create_paypal_order(req: PayPalOrderRequest):
    if PAYPAL_MOCK_MODE:
        # return a fake approval link that frontend can use for testing
        fake_link = f"{FRONTEND_BASE}/paypal/mock-approve?plan={req.plan_key}&amount={req.amount}"
        log(f"Mock PayPal order created for plan {req.plan_key} amount {req.amount}")
        return {"status":"mock","approval_url": fake_link}
    # If you later add real PayPal, implement token + order creation here
    raise HTTPException(501, "PayPal not implemented (use mock mode)")

# PayPal webhook placeholder (mock)
@app.post("/webhook/paypal")
async def webhook_paypal(request: Request):
    payload = await request.json()
    log(f"PayPal webhook (mock) received: {json.dumps(payload)[:500]}")
    send_email("Kairah: PayPal webhook (mock)", f"Payload: {json.dumps(payload, indent=2)[:2000]}")
    # parse affiliate if present (mock)
    aff = payload.get("affiliate_id") if isinstance(payload, dict) else None
    amount = float(payload.get("amount",0)) if isinstance(payload, dict) else 0.0
    if aff and amount:
        record_affiliate_sale(aff, amount, source="paypal")
    return {"status":"ok"}

# Mocked generation endpoints
@app.post("/generate/video")
def generate_video(req: GenerateRequest):
    # basic quota check (in-memory)
    u = _users.setdefault(req.uid, {"plan":"Free","usage":{"videos":0}})
    if u["plan"] == "Free" and u["usage"].get("videos",0) >= 1:
        raise HTTPException(403, "Free plan limit reached")
    # mock result url
    result = f"https://cdn.kairah.example/videos/{req.uid}/{int(datetime.now().timestamp())}.mp4"
    save_job = save_job  # alias to silence linter if needed
    job = save_job(req.uid, "video", req.prompt, result)
    u["usage"]["videos"] = u["usage"].get("videos",0) + 1
    send_email("Kairah: Video generation started", f"UID: {req.uid}\nPrompt: {req.prompt}\nResult URL (mock): {result}")
    return {"status":"processing", "job": job}

@app.post("/generate/image")
def generate_image(req: GenerateRequest):
    u = _users.setdefault(req.uid, {"plan":"Free","usage":{"images":0}})
    result = f"https://cdn.kairah.example/images/{req.uid}/{int(datetime.now().timestamp())}.png"
    job = save_job(req.uid, "image", req.prompt, result)
    u["usage"]["images"] = u["usage"].get("images",0) + 1
    return {"status":"ready","result_url":result,"job":job}

@app.post("/generate/audio")
def generate_audio(req: GenerateRequest):
    u = _users.setdefault(req.uid, {"plan":"Free","usage":{"audio":0}})
    result = f"https://cdn.kairah.example/audio/{req.uid}/{int(datetime.now().timestamp())}.mp3"
    job = save_job(req.uid, "audio", req.prompt, result)
    u["usage"]["audio"] = u["usage"].get("audio",0) + 1
    return {"status":"ready","result_url":result,"job":job}

# Affiliate register & payout runner
@app.post("/affiliate/register")
def affiliate_register(affiliate_id: str):
    _affiliates.setdefault(affiliate_id, {"earnings":0.0,"sales":0})
    return {"status":"ok","affiliate":affiliate_id}

@app.post("/admin/affiliate/payouts")
def admin_affiliate_payouts(x_admin_token: Optional[str] = Header(None)):
    if x_admin_token != ADMIN_TOKEN:
        raise HTTPException(401, "Unauthorized")
    payouts = []
    for aid, info in _affiliates.items():
        if info["earnings"] >= 500.0:
            payouts.append({"affiliate":aid,"amount":info["earnings"]})
            # reset ledger after scheduling payout
            info["earnings"] = 0.0
            info["sales"] = 0
            send_email("Kairah: Affiliate payout scheduled", f"Affiliate {aid} scheduled for payout of ${info['earnings']}", to=SUPPORT_EMAIL)
    return {"payouts":payouts}

# Simple helpers for frontend
@app.get("/api/plans")
def get_plans():
    return {
        "plans":[
            {"name":"Free","price":0,"features":["1 free 6s clip (watermarked)"]},
            {"name":"Pro","price":19,"features":["1-min video, 10gens/mo, 1080p export"]},
            {"name":"Diamond","price":49,"features":["2-3min video, 4K export, bulk gen"]},
            {"name":"Cinematic","price":99,"features":["Studio controls, priority renders"]},
            {"name":"Lifetime","price":500,"features":["All features, lifetime access"]},
        ]
    }

@app.get("/api/support")
def api_support():
    return {"support_email": SUPPORT_EMAIL}

# ---------- Run notes ----------
# On Render set Build command: pip install fastapi uvicorn stripe requests python-dotenv
# Start command: uvicorn main:app --host 0.0.0.0 --port $PORT
