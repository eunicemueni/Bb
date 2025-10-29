# main.py
"""
Kairah Studio - Single-file backend (Final)
- No Stripe (removed)
- Wise manual confirmation endpoint for admins
- Paystack, PayPal, M-Pesa webhook placeholders (best-effort)
- Firebase optional via FIREBASE_SERVICE_ACCOUNT_JSON env var
- Admin protected routes via ADMIN_API_KEY header (x-admin-key)
- Affiliate 70/30 commission, $500 bonus after 100 Lifetime/Cinematic referred sales
- Fame booster price: $9
- Plan-aware video limits (Free 6s, Pro up to 60s, Diamond up to 180s, Cinematic up to 300s, Lifetime unlimited)
- Aspect ratios: 16:9, 9:16, 1:1
- JSON persistence to kairah_data.json
- Writes requirements.txt on startup
Run:
  python main.py
Deploy:
  pip install -r requirements.txt
  uvicorn main:app --host 0.0.0.0 --port $PORT
"""

import os
import sys
import json
import time
import traceback
from typing import Optional, Dict, Any
from decimal import Decimal

# -------------------------
# Auto requirements file
# -------------------------
REQUIREMENTS = [
    "fastapi>=0.95.0",
    "uvicorn>=0.22.0",
    "requests>=2.31.0",
    "python-dotenv>=1.0.0",
    "pydantic>=1.10.10",
    "firebase-admin>=6.0.1",
]
try:
    with open("requirements.txt", "w") as f:
        f.write("\n".join(REQUIREMENTS) + "\n")
except Exception:
    pass

# import libraries, install on first-run if missing
try:
    from fastapi import FastAPI, Request, HTTPException, Header, Depends, Response
    from fastapi.middleware.cors import CORSMiddleware
    from pydantic import BaseModel, Field
    import uvicorn
    import requests
except Exception:
    import subprocess
    subprocess.check_call([sys.executable, "-m", "pip", "install"] + REQUIREMENTS)
    from fastapi import FastAPI, Request, HTTPException, Header, Depends, Response
    from fastapi.middleware.cors import CORSMiddleware
    from pydantic import BaseModel, Field
    import uvicorn
    import requests

# -------------------------
# App and CORS
# -------------------------
app = FastAPI(title="Kairah Studio Backend (Final)")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
    allow_credentials=True,
)

# -------------------------
# Env / Config
# -------------------------
ADMIN_API_KEY = os.environ.get("ADMIN_API_KEY", "kairah_dev_admin_key")
FIREBASE_SERVICE_ACCOUNT_JSON = os.environ.get("FIREBASE_SERVICE_ACCOUNT_JSON", "")
PAYSTACK_SECRET_KEY = os.environ.get("PAYSTACK_SECRET_KEY", "")
PAYSTACK_WEBHOOK_SECRET = os.environ.get("PAYSTACK_WEBHOOK_SECRET", "")
PAYPAL_CLIENT_ID = os.environ.get("PAYPAL_CLIENT_ID", "")
PAYPAL_CLIENT_SECRET = os.environ.get("PAYPAL_CLIENT_SECRET", "")
MPESA_CONSUMER_KEY = os.environ.get("MPESA_CONSUMER_KEY", "")
MPESA_CONSUMER_SECRET = os.environ.get("MPESA_CONSUMER_SECRET", "")
MPESA_SHORTCODE = os.environ.get("MPESA_SHORTCODE", "")
MPESA_PASSKEY = os.environ.get("MPESA_PASSKEY", "")
MPESA_CALLBACK_URL = os.environ.get("MPESA_CALLBACK_URL", "")
VIDEO_API_URL = os.environ.get("VIDEO_API_URL", "")
VIDEO_API_KEY = os.environ.get("VIDEO_API_KEY", "")

WISE_ACCOUNT_NAME = os.environ.get("WISE_ACCOUNT_NAME", "Kairah")
WISE_ROUTING_NUMBER = os.environ.get("WISE_ROUTING_NUMBER", "020123456")
WISE_ACCOUNT_NUMBER = os.environ.get("WISE_ACCOUNT_NUMBER", "12345678")

FAME_BOOSTER_PRICE = float(os.environ.get("FAME_BOOSTER_PRICE", "9.0"))

DATA_FILE = os.environ.get("KDATA_FILE", "kairah_data.json")

# -------------------------
# Plans & ratios
# -------------------------
PLANS = {
    "Free": {"price_month": 0, "price_year": 0, "max_seconds": 6, "video_limit": 1},
    "Pro": {"price_month": 19, "price_year": 300, "max_seconds": 60, "video_limit": None},
    "Diamond": {"price_month": 49, "price_year": 450, "max_seconds": 180, "video_limit": None},
    "Cinematic": {"price_month": 99, "price_year": 600, "max_seconds": 300, "video_limit": None},
    "Lifetime": {"price_one_time": 500, "max_seconds": None, "video_limit": None},
}

VALID_RATIOS = ["16:9", "9:16", "1:1"]

# -------------------------
# Persistence helpers
# -------------------------
DEFAULT_STATE = {
    "users": {},        # email => {...}
    "affiliates": {},   # ref_code => {...}
    "videos": {},       # video_id => {...}
    "payments": {},     # payment_id => {...}
    "logs": {"video_logs": [], "payment_logs": [], "affiliate_logs": []},
}

def load_data():
    if os.path.exists(DATA_FILE):
        try:
            with open(DATA_FILE, "r") as f:
                return json.load(f)
        except Exception:
            traceback.print_exc()
    return DEFAULT_STATE.copy()

def save_data(state):
    try:
        with open(DATA_FILE, "w") as f:
            json.dump(state, f, indent=2, default=str)
    except Exception:
        traceback.print_exc()

data = load_data()

# seed admin user if missing
if "admin@kairah.local" not in data["users"]:
    data["users"]["admin@kairah.local"] = {
        "email": "admin@kairah.local",
        "display_name": "Kairah Admin",
        "plan": "Lifetime",
        "ref": None,
        "is_admin": True,
        "created_at": int(time.time()),
        "generated_videos": 0,
        "downloads": 0,
        "fame_booster_paid": False,
    }
    save_data(data)

# -------------------------
# Firebase optional
# -------------------------
USE_FIREBASE = False
firebase_admin = None
if FIREBASE_SERVICE_ACCOUNT_JSON:
    try:
        import firebase_admin as _fb
        from firebase_admin import credentials as fb_credentials, auth as fb_auth
        firebase_admin = _fb
        try:
            sa = json.loads(FIREBASE_SERVICE_ACCOUNT_JSON)
            cred = fb_credentials.Certificate(sa)
        except Exception:
            cred = fb_credentials.Certificate(FIREBASE_SERVICE_ACCOUNT_JSON)
        firebase_admin.initialize_app(cred)
        USE_FIREBASE = True
    except Exception:
        USE_FIREBASE = False

# -------------------------
# Utilities
# -------------------------
def now_ts():
    return int(time.time())

def log(kind: str, entry: Dict[str, Any]):
    data["logs"].setdefault(kind, []).append(entry)
    save_data(data)

def generate_affiliate_code(email: str) -> str:
    code = f"KA-{abs(hash(email)) % (10**8)}"
    if code not in data["affiliates"]:
        data["affiliates"][code] = {"email": email, "commission": 0.0, "referred": [], "bonuses": 0.0, "payouts": []}
        save_data(data)
    return code

def get_user(email: str) -> Optional[Dict[str, Any]]:
    if USE_FIREBASE:
        try:
            from firebase_admin import auth as fb_auth
            u = fb_auth.get_user_by_email(email)
            local = data["users"].get(email, {})
            return {**{"email": u.email, "uid": u.uid}, **local}
        except Exception:
            return data["users"].get(email)
    return data["users"].get(email)

def create_user_local(email: str, display_name: Optional[str] = None, referral_code: Optional[str] = None):
    if email in data["users"]:
        return data["users"][email]
    data["users"][email] = {
        "email": email,
        "display_name": display_name or "",
        "plan": "Free",
        "ref": referral_code,
        "created_at": now_ts(),
        "is_admin": False,
        "generated_videos": 0,
        "downloads": 0,
        "fame_booster_paid": False,
    }
    if referral_code:
        aff = data["affiliates"].get(referral_code)
        if aff:
            aff.setdefault("referred", []).append(email)
    save_data(data)
    return data["users"][email]

def upgrade_user_plan(email: str, plan: str):
    if plan not in PLANS:
        raise ValueError("Unknown plan")
    u = data["users"].get(email)
    if u:
        u["plan"] = plan
    else:
        data["users"][email] = {"email": email, "plan": plan, "created_at": now_ts(), "is_admin": False, "generated_videos": 0, "downloads": 0, "fame_booster_paid": False}
    save_data(data)
    return data["users"][email]

def record_payment(payment_id: str, email: str, method: str, amount: float, metadata: Dict[str, Any] = None, status: str = "completed"):
    data["payments"][payment_id] = {
        "payment_id": payment_id,
        "email": email,
        "method": method,
        "amount": float(amount),
        "metadata": metadata or {},
        "status": status,
        "timestamp": now_ts(),
    }
    log("payment_logs", data["payments"][payment_id])
    save_data(data)
    return data["payments"][payment_id]

def credit_affiliate_for_sale(ref_code: str, sale_amount: float, plan_name: str):
    aff = data["affiliates"].get(ref_code)
    if not aff:
        return 0.0
    commission = float(Decimal(sale_amount) * Decimal("0.70"))
    aff["commission"] = aff.get("commission", 0.0) + commission
    log("affiliate_logs", {"ref": ref_code, "email": aff.get("email"), "commission_added": commission, "sale_amount": sale_amount, "plan": plan_name, "timestamp": now_ts()})
    # check milestone
    special_sales = 0
    for e in aff.get("referred", []):
        for p in data["payments"].values():
            if p["email"] == e and p["status"] == "completed":
                plan = p.get("metadata", {}).get("plan")
                if plan in ("Cinematic", "Lifetime"):
                    special_sales += 1
    if aff.get("_milestone_awarded") is None and special_sales >= 100:
        aff["commission"] = aff.get("commission", 0.0) + 500.0
        aff["bonuses"] = aff.get("bonuses", 0.0) + 500.0
        aff["_milestone_awarded"] = True
        log("affiliate_logs", {"ref": ref_code, "email": aff.get("email"), "bonus_awarded": 500.0, "timestamp": now_ts()})
    save_data(data)
    return commission

# -------------------------
# Pydantic models
# -------------------------
class SignupRequest(BaseModel):
    email: str
    display_name: Optional[str] = None
    referral_code: Optional[str] = None

class LoginRequest(BaseModel):
    email: str

class VideoRequest(BaseModel):
    user_email: str
    prompt: str
    aspect_ratio: Optional[str] = Field("16:9")
    requested_seconds: Optional[int] = Field(None)
    fame_booster: Optional[bool] = False
    template_id: Optional[str] = None
    music_id: Optional[str] = None

# -------------------------
# Admin dependency
# -------------------------
async def require_admin(request: Request, x_admin_key: Optional[str] = Header(None)):
    if x_admin_key and x_admin_key == ADMIN_API_KEY:
        return True
    admin_email = request.headers.get("x-admin-email")
    if admin_email:
        u = data["users"].get(admin_email)
        if u and u.get("is_admin"):
            return True
    raise HTTPException(status_code=401, detail="Admin credentials required")

# -------------------------
# Routes
# -------------------------
@app.get("/")
async def index():
    return {"message": "Kairah Studio Backend (Final) is live", "time": now_ts()}

@app.post("/api/signup")
async def api_signup(req: SignupRequest):
    if get_user(req.email):
        raise HTTPException(status_code=400, detail="User already exists")
    user = create_user_local(req.email, req.display_name, req.referral_code)
    code = generate_affiliate_code(req.email)
    return {"message": "User created", "user": user, "affiliate_code": code}

@app.post("/api/login")
async def api_login(req: LoginRequest):
    user = get_user(req.email)
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    return {"message": "Login success", "user": user}

# Affiliate
@app.get("/api/affiliate/earnings")
async def affiliate_earnings(email: str):
    ref_code = None
    for code, v in data["affiliates"].items():
        if v.get("email") == email:
            ref_code = code
            break
    if not ref_code:
        return {"total_earned": 0.0, "pending": 0.0, "bonuses": 0.0, "ref_code": None}
    aff = data["affiliates"][ref_code]
    return {"ref_code": ref_code, "total_earned": aff.get("commission", 0.0) + aff.get("bonuses", 0.0), "pending": aff.get("commission", 0.0), "bonuses": aff.get("bonuses", 0.0)}

@app.get("/api/affiliate/referrals")
async def affiliate_referrals(ref_code: str):
    aff = data["affiliates"].get(ref_code)
    if not aff:
        raise HTTPException(status_code=404, detail="Affiliate not found")
    referred = []
    for e in aff.get("referred", []):
        u = data["users"].get(e, {"email": e, "plan": "Free"})
        referred.append({"email": e, "plan": u.get("plan")})
    return {"ref_code": ref_code, "referred": referred}

@app.get("/api/affiliate/referrals/me")
async def affiliate_me(email: str):
    for code, v in data["affiliates"].items():
        if v.get("email") == email:
            return {"ref_code": code, "data": v}
    code = generate_affiliate_code(email)
    return {"ref_code": code, "data": data["affiliates"].get(code)}

# Video generation
@app.post("/api/generate-video")
async def api_generate_video(req: VideoRequest):
    user = get_user(req.user_email)
    if not user:
        raise HTTPException(status_code=401, detail="User not found. Please signup/login.")
    plan = user.get("plan", "Free")
    plan_info = PLANS.get(plan, PLANS["Free"])
    max_seconds = plan_info.get("max_seconds")
    if req.requested_seconds:
        if max_seconds is not None and req.requested_seconds > max_seconds:
            raise HTTPException(status_code=400, detail=f"Your plan '{plan}' allows max {max_seconds} seconds.")
        length = req.requested_seconds
    else:
        if plan == "Free":
            length = 6
        elif plan == "Pro":
            length = 30
        elif plan == "Diamond":
            length = 90
        elif plan == "Cinematic":
            length = 180
        else:
            length = 60
    if req.aspect_ratio not in VALID_RATIOS:
        raise HTTPException(status_code=400, detail=f"Invalid aspect ratio. Allowed: {VALID_RATIOS}")
    if (req.template_id or req.music_id) and plan not in ("Diamond", "Cinematic", "Lifetime"):
        raise HTTPException(status_code=403, detail="Premium templates/music available to Diamond, Cinematic, Lifetime only.")
    if req.fame_booster and not user.get("fame_booster_paid"):
        return {"require_payment": True, "price": FAME_BOOSTER_PRICE, "message": "Fame booster requires $9 payment. Use admin /api/admin/confirm-wise to confirm."}
    if plan == "Free":
        if user.get("generated_videos", 0) >= 1:
            raise HTTPException(status_code=403, detail="Free plan allows only 1 generated video. Upgrade for more.")
    video_id = f"{req.user_email.replace('@','_')}_{len(data['videos'])+1}_{now_ts()}"
    video_url = f"https://cdn.kairahstudio.com/mock_videos/{video_id}.mp4"
    if VIDEO_API_URL and VIDEO_API_KEY:
        try:
            payload = {
                "prompt": req.prompt,
                "user_email": req.user_email,
                "length_seconds": length,
                "aspect_ratio": req.aspect_ratio,
                "template_id": req.template_id,
                "music_id": req.music_id,
                "fame_booster": req.fame_booster,
            }
            resp = requests.post(VIDEO_API_URL, json=payload, headers={"Authorization": f"Bearer {VIDEO_API_KEY}"}, timeout=120)
            resp.raise_for_status()
            d = resp.json()
            video_url = d.get("video_url") or d.get("url") or video_url
        except Exception:
            pass
    data["videos"][video_id] = {"video_id": video_id, "email": req.user_email, "prompt": req.prompt, "url": video_url, "length": length, "aspect_ratio": req.aspect_ratio, "timestamp": now_ts(), "fame_booster": req.fame_booster}
    data["users"].setdefault(req.user_email, {"email": req.user_email, "generated_videos": 0})
    data["users"][req.user_email]["generated_videos"] = data["users"][req.user_email].get("generated_videos", 0) + 1
    log("video_logs", {"video_id": video_id, "user": req.user_email, "prompt": req.prompt, "length": length, "aspect_ratio": req.aspect_ratio, "timestamp": now_ts()})
    save_data(data)
    return {"video_url": video_url, "video_id": video_id, "message": f"Video generated ({length}s)"}

# Download restriction
@app.get("/api/download")
async def api_download(video_id: str, email: str):
    v = data["videos"].get(video_id)
    if not v:
        raise HTTPException(status_code=404, detail="Video not found")
    u = get_user(email)
    if not u:
        raise HTTPException(status_code=401, detail="User required")
    if u.get("plan") == "Free":
        if u.get("downloads", 0) >= 1:
            raise HTTPException(status_code=403, detail="Free plan allows only one download. Upgrade to download more.")
        u["downloads"] = u.get("downloads", 0) + 1
        save_data(data)
    return {"video_url": v["url"], "message": "Download granted"}

# Paystack webhook (best-effort)
@app.post("/api/paystack-webhook")
async def paystack_webhook(request: Request):
    payload = await request.json()
    try:
        status = payload.get("event") or payload.get("status") or payload.get("data", {}).get("status")
        if status == "success" or payload.get("data", {}).get("status") == "success":
            data_obj = payload.get("data", payload)
            email = data_obj.get("customer", {}).get("email") or data_obj.get("email")
            amount = data_obj.get("amount", 0) / 100.0 if data_obj.get("amount") else 0.0
            plan = (data_obj.get("metadata") or {}).get("plan") or "Pro"
            if email:
                upgrade_user_plan(email, plan)
                p = record_payment(data_obj.get("id", f"paystack_{now_ts()}"), email, "paystack", amount, metadata={"plan": plan})
                ref = data["users"].get(email, {}).get("ref")
                if ref:
                    credit_affiliate_for_sale(ref, amount, plan)
    except Exception:
        traceback.print_exc()
        raise HTTPException(status_code=400, detail="Invalid payload")
    return {"status": "ok"}

# PayPal webhook (best-effort)
@app.post("/api/paypal-webhook")
async def paypal_webhook(request: Request):
    payload = await request.json()
    try:
        resource = payload.get("resource", payload)
        email = resource.get("payer", {}).get("email_address") or resource.get("billing_email")
        amount = 0.0
        try:
            amount = float((resource.get("amount", {}).get("value")) or 0.0)
        except Exception:
            amount = 0.0
        plan = resource.get("custom_id") or resource.get("invoice_id") or "Pro"
        if email:
            upgrade_user_plan(email, plan)
            p = record_payment(resource.get("id", f"paypal_{now_ts()}"), email, "paypal", amount, metadata={"plan": plan})
            ref = data["users"].get(email, {}).get("ref")
            if ref:
                credit_affiliate_for_sale(ref, amount, plan)
    except Exception:
        traceback.print_exc()
        raise HTTPException(status_code=400, detail="Invalid payload")
    return {"status": "ok"}

# M-Pesa webhook (placeholder)
@app.post("/api/mpesa-webhook")
async def mpesa_webhook(request: Request):
    payload = await request.json()
    # provider-specific parsing required; accept and log
    try:
        # parse if metadata present with email/plan
        body = payload.get("Body", payload)
        # handle real provider payload by mapping to email/amount/plan
    except Exception:
        pass
    return {"status": "ok"}

# Wise manual confirm by admin
@app.post("/api/admin/confirm-wise")
async def admin_confirm_wise(payment_id: str, email: str, amount: float, plan: str = "Pro", ref_code: Optional[str] = None, admin: bool = Depends(require_admin)):
    try:
        rec = record_payment(payment_id, email, "wise", amount, metadata={"plan": plan})
        upgrade_user_plan(email, plan)
        ref = ref_code or data["users"].get(email, {}).get("ref")
        if ref:
            credit_affiliate_for_sale(ref, amount, plan)
        save_data(data)
        return {"status": "ok", "payment": rec}
    except Exception as e:
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=str(e))

# Admin & reporting
@app.get("/admin/export/logs")
async def admin_export_logs(admin: bool = Depends(require_admin)):
    return data["logs"]

@app.get("/admin/export/csv/{logname}")
async def admin_export_csv(logname: str, admin: bool = Depends(require_admin)):
    if logname not in data["logs"]:
        raise HTTPException(status_code=404, detail="Log not found")
    rows = data["logs"][logname]
    if not rows:
        return Response(content="", media_type="text/csv")
    keys = sorted({k for r in rows for k in r.keys()})
    csv_lines = [",".join(keys)]
    for r in rows:
        csv_lines.append(",".join([str(r.get(k, "")) for k in keys]))
    return Response(content="\n".join(csv_lines), media_type="text/csv")

@app.get("/admin/users")
async def admin_list_users(admin: bool = Depends(require_admin)):
    return {"users": list(data["users"].values())}

@app.post("/admin/create-admin")
async def admin_create_admin(email: str, admin: bool = Depends(require_admin)):
    u = data["users"].get(email)
    if not u:
        create_user_local(email)
    data["users"][email]["is_admin"] = True
    save_data(data)
    return {"status": "ok", "email": email}

@app.post("/admin/action/ban-user")
async def admin_ban_user(email: str, admin: bool = Depends(require_admin)):
    if email in data["users"]:
        data["users"][email]["banned"] = True
        save_data(data)
        return {"status": "ok", "email": email}
    raise HTTPException(status_code=404, detail="User not found")

@app.post("/admin/affiliate/payout")
async def admin_affiliate_payout(ref_code: str, amount: float, admin: bool = Depends(require_admin)):
    aff = data["affiliates"].get(ref_code)
    if not aff:
        raise HTTPException(status_code=404, detail="Affiliate not found")
    available = aff.get("commission", 0.0)
    if amount > available:
        raise HTTPException(status_code=400, detail="Insufficient commission")
    aff["commission"] = round(available - amount, 2)
    aff.setdefault("payouts", []).append({"amount": amount, "timestamp": now_ts()})
    log("affiliate_logs", {"ref": ref_code, "payout": amount, "timestamp": now_ts()})
    save_data(data)
    return {"status": "ok", "remaining_commission": aff["commission"]}

@app.get("/admin/export/all")
async def admin_export_all(admin: bool = Depends(require_admin)):
    users_csv = "email,display_name,plan,created_at,is_admin\n"
    for u in data["users"].values():
        users_csv += f'{u.get("email","")},{u.get("display_name","")},{u.get("plan","")},{u.get("created_at","")},{u.get("is_admin",False)}\n'
    videos_csv = "video_id,email,prompt,url,length,aspect_ratio,timestamp\n"
    for v in data["videos"].values():
        videos_csv += f'{v.get("video_id","")},{v.get("email","")},"{str(v.get("prompt","")).replace(","," ")}",{v.get("url","")},{v.get("length","")},{v.get("aspect_ratio","")},{v.get("timestamp","")}\n'
    payments_csv = "payment_id,email,method,amount,status,timestamp\n"
    for p in data["payments"].values():
        payments_csv += f'{p.get("payment_id","")},{p.get("email","")},{p.get("method","")},{p.get("amount","")},{p.get("status","")},{p.get("timestamp","")}\n'
    return {"users_csv": users_csv, "videos_csv": videos_csv, "payments_csv": payments_csv}

# FAQ
FAQ_CONTENT = [
    {"q": "How many free videos?", "a": "Free users can generate one 6-second video. Upgrade to Pro for more."},
    {"q": "What plans exist?", "a": "Pro, Diamond, Cinematic, Lifetime. See pricing in frontend."},
    {"q": "What payment methods?", "a": "Wise (manual confirmation), Paystack, PayPal, M-Pesa via webhooks."},
]
@app.get("/api/faq")
async def api_faq(q: Optional[str] = None):
    if q:
        q_lower = q.lower()
        return [f for f in FAQ_CONTENT if q_lower in f["q"].lower() or q_lower in f["a"].lower()]
    return FAQ_CONTENT

# Health
@app.get("/health")
async def health():
    return {"status": "ok", "time": now_ts()}

# -------------------------
# Run
# -------------------------
if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8000))
    print("Starting Kairah Studio Backend (Final).")
    print("Ensure ADMIN_API_KEY and any provider env vars are set in your environment.")
    uvicorn.run("main:app", host="0.0.0.0", port=port, reload=False)
