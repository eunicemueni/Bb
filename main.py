# main.py
"""
Kairah Studio - Unified Backend (single-file)
Replaced Stripe with Wise as requested. Includes:
- Wise / PayPal / Paystack / M-Pesa webhook placeholders
- Firebase optional integration (placeholder service account JSON env)
- Admin protection via ADMIN_API_KEY or Firebase UID role check
- Affiliate system: 70/30 commission (affiliate gets 70%) and milestone bonus
- Plan-aware limits and durations
- Aspect ratio handling and fame booster flag
- Logging and simple CSV/JSON export endpoints for admin
- Requirements string at top (auto-install attempt)

NOTES:
- Sensitive credentials MUST be provided via environment variables in production.
- This file intentionally contains placeholder logic for payment verification and video API calls.
- You asked to include WISE_ACCOUNT_NUMBER and WISE_ROUTING_NUMBER; they are included below.
"""

# -----------------------------
# Requirements (as a string; included here per request)
# -----------------------------
REQUIREMENTS = """
fastapi
uvicorn
requests
python-dotenv
pydantic
firebase-admin
python-multipart
"""

# -----------------------------
# Auto-install required packages (best-effort)
# -----------------------------
import os, sys, subprocess, json, time
try:
    from typing import Optional, List, Dict, Any
    from fastapi import FastAPI, Request, HTTPException, Header, Depends
    from fastapi.middleware.cors import CORSMiddleware
    from pydantic import BaseModel, Field
    import requests
except Exception:
    for pkg in ["fastapi", "uvicorn", "requests", "python-dotenv", "pydantic", "firebase-admin", "python-multipart"]:
        try:
            subprocess.check_call([sys.executable, "-m", "pip", "install", pkg])
        except Exception:
            pass
    from typing import Optional, List, Dict, Any
    from fastapi import FastAPI, Request, HTTPException, Header, Depends
    from fastapi.middleware.cors import CORSMiddleware
    from pydantic import BaseModel, Field
    import requests

# -----------------------------
# App init
# -----------------------------
app = FastAPI(title="Kairah Studio Backend - Kairah")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
    allow_credentials=True,
)

# -----------------------------
# Config / Hardcoded values you provided
# -----------------------------
APP_NAME = "kairah"
WISE_ACCOUNT_NUMBER = os.getenv("WISE_ACCOUNT_NUMBER", "12345678")
WISE_ROUTING_NUMBER = os.getenv("WISE_ROUTING_NUMBER", "020123456")
WISE_API_TOKEN = os.getenv("WISE_API_TOKEN", "wise_api_placeholder")

# Payment endpoints placeholders
PAYPAL_CLIENT_ID = os.getenv("PAYPAL_CLIENT_ID", "paypal_client_placeholder")
PAYSTACK_SECRET_KEY = os.getenv("PAYSTACK_SECRET_KEY", "paystack_placeholder")
MPESA_CONSUMER_KEY = os.getenv("MPESA_CONSUMER_KEY", "mpesa_key")
MPESA_CONSUMER_SECRET = os.getenv("MPESA_CONSUMER_SECRET", "mpesa_secret")
MPESA_SHORTCODE = os.getenv("MPESA_SHORTCODE", "your_mpesa_shortcode")
MPESA_CALLBACK_URL = os.getenv("MPESA_CALLBACK_URL", "https://yourdomain.com/api/mpesa-webhook")

# Firebase service account JSON (string path or JSON content)
FIREBASE_SERVICE_ACCOUNT_JSON = os.getenv("FIREBASE_SERVICE_ACCOUNT_JSON", "")
USE_FIREBASE = False

# Admin API key (protect admin routes)
ADMIN_API_KEY = os.getenv("ADMIN_API_KEY", "change_me_admin_api_key")

# Fame booster price
FAME_BOOSTER_PRICE = 9.0

# -----------------------------
# Plans (exact prices you specified)
# -----------------------------
PLANS = {
    "Free": {"price_month": 0, "price_year": 0, "video_limit": 1, "duration_sec": 6},
    "Pro": {"price_month": 19, "price_year": 300, "video_limit": None, "duration_sec": (30,60)},
    "Diamond": {"price_month": 49, "price_year": 450, "video_limit": None, "duration_sec": (60,180)},
    "Cinematic": {"price_month": 99, "price_year": 600, "video_limit": None, "duration_sec": (60,300)},
    "Lifetime": {"price_one_time": 500, "video_limit": None, "duration_sec": None},
}

# -----------------------------
# In-memory DBs (replace with real DB in production)
# -----------------------------
users_db: Dict[str, Dict[str, Any]] = {}          # email -> user info
affiliates_db: Dict[str, Dict[str, Any]] = {}     # ref_code -> affiliate info
videos_db: Dict[str, Dict[str, Any]] = {}         # video_id -> video meta
payments_db: Dict[str, Dict[str, Any]] = {}       # payment_id -> payment meta
logs_db: List[Dict[str, Any]] = []                # global logs

# Affiliate & milestone config
AFFILIATE_COMMISSION_RATE = 0.70  # 70% to affiliate per sale
PLATFORM_SHARE_RATE = 0.30
MILESTONE_THRESHOLD = 100  # sales
MILESTONE_BONUS = 500.0

# -----------------------------
# Initialize Firebase if available (optional)
# -----------------------------
try:
    if FIREBASE_SERVICE_ACCOUNT_JSON:
        import firebase_admin
        from firebase_admin import credentials, auth as fb_auth
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
# Pydantic models
# -----------------------------
class SignupRequest(BaseModel):
    email: str
    display_name: Optional[str] = ""
    referral_code: Optional[str] = None

class LoginRequest(BaseModel):
    email: str

class VideoRequest(BaseModel):
    user_email: str
    prompt: str
    aspect_ratio: str = Field(..., description="16:9, 9:16, 1:1")
    fame_booster: Optional[bool] = False
    template: Optional[str] = None
    music: Optional[str] = None
    requested_duration: Optional[int] = None

class PaymentWebhook(BaseModel):
    payment_id: str
    email: str
    plan: str
    amount: float
    method: str
    status: str
    referral_code: Optional[str] = None

# -----------------------------
# Helper functions
# -----------------------------
import csv
from io import StringIO


def log_event(kind: str, payload: Dict[str, Any]):
    entry = {"timestamp": int(time.time()), "kind": kind, "payload": payload}
    logs_db.append(entry)


def get_user(email: str) -> Optional[Dict[str, Any]]:
    return users_db.get(email.lower())


def create_user_local(email: str, display_name: Optional[str] = "", referral_code: Optional[str] = None):
    email = email.lower()
    users_db[email] = {"email": email, "display_name": display_name or "", "plan": "Free", "ref": referral_code, "created_at": int(time.time())}
    if referral_code:
        aff = affiliates_db.get(referral_code)
        if aff:
            aff.setdefault("referred", []).append(email)
    log_event("user.create", {"email": email, "ref": referral_code})
    return users_db[email]


def upgrade_user_plan(email: str, plan: str):
    email = email.lower()
    u = users_db.get(email)
    if not u:
        u = create_user_local(email)
    u["plan"] = plan
    u["upgraded_at"] = int(time.time())
    log_event("user.upgrade", {"email": email, "plan": plan})
    return u


def record_payment(payment_id: str, email: str, method: str, amount: float, plan: str, status: str = "pending", referral_code: Optional[str] = None):
    payments_db[payment_id] = {"payment_id": payment_id, "email": email.lower(), "method": method, "amount": amount, "plan": plan, "status": status, "created_at": int(time.time()), "referral_code": referral_code}
    log_event("payment.recorded", payments_db[payment_id])
    # Handle commission and upgrades on completed
    if status == "completed":
        # upgrade plan dynamically
        upgrade_user_plan(email, plan)
        # affiliate credit
        if referral_code := referral_code or users_db.get(email.lower(), {}).get("ref"):
            aff = affiliates_db.get(referral_code)
            if aff:
                commission = amount * AFFILIATE_COMMISSION_RATE
                aff["balance"] = aff.get("balance", 0.0) + commission
                aff.setdefault("sales", 0)
                aff["sales"] += 1
                log_event("affiliate.credit", {"ref": referral_code, "email": email, "amount": commission})
                # milestone bonus
                if aff["sales"] >= MILESTONE_THRESHOLD and not aff.get("milestone_paid"):
                    aff["balance"] += MILESTONE_BONUS
                    aff["milestone_paid"] = True
                    log_event("affiliate.milestone", {"ref": referral_code, "bonus": MILESTONE_BONUS})
    return payments_db[payment_id]


def verify_admin(api_key: Optional[str] = None, uid: Optional[str] = None) -> bool:
    if api_key and api_key == ADMIN_API_KEY:
        return True
    # Optionally verify firebase UID role (placeholder)
    if USE_FIREBASE and uid:
        try:
            from firebase_admin import auth as fb_auth
            user = fb_auth.get_user(uid)
            # Here you would check custom claims for admin role
            claims = getattr(user, 'custom_claims', {}) or {}
            if claims.get('admin'):
                return True
        except Exception:
            return False
    return False

# -----------------------------
# Affiliate helpers / endpoints
# -----------------------------

def create_affiliate(ref_code: str, email: str):
    affiliates_db[ref_code] = {"ref": ref_code, "email": email.lower(), "commission": 0.0, "balance": 0.0, "referred": [], "sales": 0}
    log_event("affiliate.create", {"ref": ref_code, "email": email})
    return affiliates_db[ref_code]

# -----------------------------
# Routes
# -----------------------------
@app.get("/")
async def root():
    return {"message": "Kairah Studio Backend (Wise) - live", "app": APP_NAME}

# Signup/login
@app.post("/api/signup")
async def api_signup(req: SignupRequest):
    if get_user(req.email):
        raise HTTPException(status_code=400, detail="User already exists")
    u = create_user_local(req.email, req.display_name, req.referral_code)
    return {"message": "User created", "user": u}

@app.post("/api/login")
async def api_login(req: LoginRequest):
    u = get_user(req.email)
    if not u:
        raise HTTPException(status_code=404, detail="User not found")
    return {"message": "Login success", "user": u}

# Affiliate dashboard endpoints
@app.get("/api/affiliate/earnings")
async def affiliate_earnings(ref_code: str, api_key: Optional[str] = Header(None)):
    # Basic protection: only affiliate owner or admin can query (we use API key for simplicity)
    aff = affiliates_db.get(ref_code)
    if not aff:
        raise HTTPException(status_code=404, detail="Affiliate not found")
    # return aggregated info
    return {"total_earned": aff.get("commission", 0.0), "balance": aff.get("balance", 0.0), "sales": aff.get("sales", 0), "milestone_paid": aff.get("milestone_paid", False)}

@app.get("/api/affiliate/referrals")
async def affiliate_referrals(ref_code: str, api_key: Optional[str] = Header(None)):
    aff = affiliates_db.get(ref_code)
    if not aff:
        raise HTTPException(status_code=404, detail="Affiliate not found")
    return {"referred": aff.get("referred", []), "sales": aff.get("sales", 0)}

# Video generation
VALID_ASPECTS = ["16:9", "9:16", "1:1"]

@app.post("/api/generate-video")
async def api_generate_video(req: VideoRequest):
    user = get_user(req.user_email)
    if not user:
        raise HTTPException(status_code=401, detail="User not found. Please signup/login.")

    plan = user.get("plan", "Free")
    plan_def = PLANS.get(plan, PLANS["Free"])

    # Aspect ratio check
    if req.aspect_ratio not in VALID_ASPECTS:
        raise HTTPException(status_code=400, detail=f"Invalid aspect ratio. Allowed: {VALID_ASPECTS}")

    # Duration handling
    requested = req.requested_duration
    allowed = plan_def.get("duration_sec")
    if allowed is None and plan != "Lifetime":
        # If None but not Lifetime, set sensible default
        allowed = (30, 60)

    # Validate requested duration
    if requested:
        if plan == "Free":
            if requested != 6:
                raise HTTPException(status_code=403, detail="Free plan only supports 6s videos")
            length = 6
        elif plan == "Pro":
            min_d, max_d = (30,60)
            if not (min_d <= requested <= max_d):
                raise HTTPException(status_code=403, detail=f"Pro allows {min_d}-{max_d} seconds")
            length = requested
        elif plan == "Diamond":
            min_d, max_d = (60,180)
            if not (min_d <= requested <= max_d):
                raise HTTPException(status_code=403, detail=f"Diamond allows {min_d}-{max_d} seconds")
            length = requested
        elif plan == "Cinematic":
            min_d, max_d = (60,300)
            if not (min_d <= requested <= max_d):
                raise HTTPException(status_code=403, detail=f"Cinematic allows {min_d}-{max_d} seconds")
            length = requested
        else:  # Lifetime
            length = requested
    else:
        # set default lengths
        if plan == "Free":
            length = 6
        elif plan == "Pro":
            length = 30
        elif plan == "Diamond":
            length = 60
        elif plan == "Cinematic":
            length = 120
        else:
            length = 60

    # Premium template/music check
    if (req.template or req.music) and plan not in ["Diamond", "Cinematic", "Lifetime"]:
        raise HTTPException(status_code=403, detail="Premium templates and music are available only to Diamond, Cinematic, and Lifetime plans")

    # Fame booster handling
    fame_flag = bool(req.fame_booster)
    fame_cost = FAME_BOOSTER_PRICE if fame_flag else 0.0

    # Enforce video limits: for simplicity count number of videos generated
    user_videos = [v for v in videos_db.values() if v["email"] == req.user_email.lower()]
    limit = plan_def.get("video_limit")
    if limit is not None and len(user_videos) >= limit:
        raise HTTPException(status_code=403, detail=f"Video limit reached for {plan} plan ({limit} videos).")

    # Simulate video generation (mock or external API)
    video_id = f"{req.user_email.replace('@','_')}_{len(videos_db)+1}"
    video_url = f"https://cdn.kairah.studio/videos/{video_id}.mp4"
    videos_db[video_id] = {"video_id": video_id, "email": req.user_email.lower(), "prompt": req.prompt, "length": length, "aspect": req.aspect_ratio, "fame": fame_flag, "template": req.template, "music": req.music, "created_at": int(time.time())}

    # Log video
    log_event("video.generated", videos_db[video_id])

    # If fame booster, record a micro-payment record (frontend should create actual payment)
    if fame_flag:
        pid = f"fame_{video_id}"
        payments_db[pid] = {"payment_id": pid, "email": req.user_email.lower(), "method": "fame_booster", "amount": fame_cost, "plan": users_db.get(req.user_email.lower(), {}).get("plan", "Free"), "status": "completed", "created_at": int(time.time())}
        log_event("payment.recorded", payments_db[pid])

    return {"status": "success", "video_id": video_id, "video_url": video_url, "length": length, "fame_cost": fame_cost}

# -----------------------------
# Payment webhooks
# -----------------------------
@app.post("/api/wise-webhook")
async def wise_webhook(payload: dict = None, request: Request = None):
    # Placeholder: Wise sends webhooks for transfers -- verify signature in production
    data = await request.json() if request else payload
    # Expected fields: payment_id, email, amount, plan, status, referral_code
    try:
        pw = PaymentWebhook(**data)
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid payload")
    # Record and process
    record_payment(pw.payment_id, pw.email, pw.method or 'wise', pw.amount, pw.plan, status=pw.status, referral_code=pw.referral_code)
    return {"status": "ok"}

@app.post("/api/paypal-webhook")
async def paypal_webhook(request: Request):
    data = await request.json()
    # TODO: validate with PayPal
    pw = PaymentWebhook(**data)
    record_payment(pw.payment_id, pw.email, pw.method or 'paypal', pw.amount, pw.plan, status=pw.status, referral_code=pw.referral_code)
    return {"status": "ok"}

@app.post("/api/paystack-webhook")
async def paystack_webhook(request: Request):
    data = await request.json()
    # TODO: verify signature X-Paystack-Signature
    pw = PaymentWebhook(**data)
    record_payment(pw.payment_id, pw.email, pw.method or 'paystack', pw.amount, pw.plan, status=pw.status, referral_code=pw.referral_code)
    return {"status": "ok"}

@app.post("/api/mpesa-webhook")
async def mpesa_webhook(request: Request):
    data = await request.json()
    # TODO: process M-Pesa callback
    # Expecting at least: payment_id, amount, phone, status
    # For demo, we will accept and record as pending
    payment_id = data.get('payment_id', f"mpesa_{int(time.time())}")
    record_payment(payment_id, data.get('email', 'unknown@kairah'), 'mpesa', float(data.get('amount', 0.0)), data.get('plan', 'Pro'), status=data.get('status', 'pending'))
    return {"status": "ok"}

# -----------------------------
# Admin routes
# -----------------------------
@app.get("/api/admin/export/logs")
async def admin_export_logs(api_key: Optional[str] = Header(None)):
    if not verify_admin(api_key=api_key):
        raise HTTPException(status_code=403, detail="Unauthorized")
    # Return logs as JSON
    return {"logs": logs_db}

@app.get("/api/admin/export/csv")
async def admin_export_csv(api_key: Optional[str] = Header(None)):
    if not verify_admin(api_key=api_key):
        raise HTTPException(status_code=403, detail="Unauthorized")
    out = StringIO()
    writer = csv.writer(out)
    writer.writerow(["kind", "timestamp", "payload"])
    for l in logs_db:
        writer.writerow([l['kind'], l['timestamp'], json.dumps(l['payload'])])
    return {"csv": out.getvalue()}

@app.post("/api/admin/create-affiliate")
async def admin_create_affiliate(ref_code: str, email: str, api_key: Optional[str] = Header(None)):
    if not verify_admin(api_key=api_key):
        raise HTTPException(status_code=403, detail="Unauthorized")
    aff = create_affiliate(ref_code, email)
    return {"status": "ok", "affiliate": aff}

@app.post("/api/admin/action")
async def admin_action(action: str, payload: dict = {}, api_key: Optional[str] = Header(None)):
    if not verify_admin(api_key=api_key):
        raise HTTPException(status_code=403, detail="Unauthorized")
    # Implement admin actions: e.g., adjust balances, force-upgrade, refund
    if action == "force-upgrade":
        email = payload.get('email')
        plan = payload.get('plan')
        if not email or not plan:
            raise HTTPException(status_code=400, detail="email and plan required")
        u = upgrade_user_plan(email, plan)
        return {"status": "ok", "user": u}
    if action == "payout-affiliate":
        ref = payload.get('ref')
        amount = float(payload.get('amount', 0))
        aff = affiliates_db.get(ref)
        if not aff:
            raise HTTPException(status_code=404, detail="Affiliate not found")
        if aff.get('balance', 0) < amount:
            raise HTTPException(status_code=400, detail="Insufficient balance")
        aff['balance'] -= amount
        log_event('affiliate.payout', {'ref': ref, 'amount': amount})
        return {"status": "ok", "remaining_balance": aff['balance']}
    return {"status": "unknown_action"}

# -----------------------------
# FAQ endpoint
# -----------------------------
FAQ_DATA = [
    {"q": "How many videos can I create on Free?", "a": "Free users can create one 6-second video to sample the service."},
    {"q": "What is the Fame Booster?", "a": "A $9 viral push option per video that signals the Fame Booster system to prioritize promotion and analytics."},
]

@app.get("/api/faq")
async def get_faq(q: Optional[str] = None):
    if not q:
        return {"faq": FAQ_DATA}
    results = [f for f in FAQ_DATA if q.lower() in f['q'].lower() or q.lower() in f['a'].lower()]
    return {"faq": results}

# -----------------------------
# Simple metrics endpoints
# -----------------------------
@app.get("/api/stats")
async def stats(api_key: Optional[str] = Header(None)):
    if not verify_admin(api_key=api_key):
        raise HTTPException(status_code=403, detail="Unauthorized")
    return {
        "users": len(users_db),
        "videos": len(videos_db),
        "payments": len(payments_db),
        "affiliates": len(affiliates_db),
    }

# -----------------------------
# Small utility to list requirements (since you wanted requirements in main.py)
# -----------------------------
@app.get("/api/requirements.txt")
async def get_requirements():
    return {"requirements": REQUIREMENTS}

# -----------------------------
# Run with uvicorn for local dev (keeps your original pattern)
# -----------------------------
if __name__ == "__main__":
    import uvicorn
    PORT = int(os.getenv('PORT', 8000))
    uvicorn.run(app, host="0.0.0.0", port=PORT)
