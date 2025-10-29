# main.py
"""
Self-contained Kairah Studio backend
- No external credentials required
- Local JSON persistence to kairah_data.json
- Admin key baked-in (change ADMIN_API_KEY value below if you want)
- Endpoints: signup, login, generate-video, download, affiliate endpoints,
  admin confirm-wise (manual payment confirmation), admin exports, faq, health
Run:
  pip install fastapi uvicorn requests pydantic
  python main.py
Then visit: http://localhost:8000/
"""

import os
import json
import time
import traceback
from decimal import Decimal
from typing import Optional, Dict, Any, List

from fastapi import FastAPI, HTTPException, Request, Header, Depends, Response
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field
import uvicorn
import requests

# --------------------------
# Config (no env vars required)
# --------------------------
ADMIN_API_KEY = "kairah_local_admin_key"  # change if you like
DATA_FILE = "kairah_data.json"
FAME_BOOSTER_PRICE = 9.0

PLANS = {
    "Free": {"max_seconds": 6, "video_limit": 1},
    "Pro": {"max_seconds": 60, "video_limit": None},
    "Diamond": {"max_seconds": 180, "video_limit": None},
    "Cinematic": {"max_seconds": 300, "video_limit": None},
    "Lifetime": {"max_seconds": None, "video_limit": None},
}
VALID_RATIOS = ["16:9", "9:16", "1:1"]

# --------------------------
# Persistence helpers
# --------------------------
DEFAULT_STATE = {
    "users": {},        # email -> user dict
    "affiliates": {},   # ref_code -> affiliate dict
    "videos": {},       # video_id -> video dict
    "payments": {},     # payment_id -> payment dict
    "logs": {"video_logs": [], "payment_logs": [], "affiliate_logs": []},
}

def load_state() -> Dict[str, Any]:
    if os.path.exists(DATA_FILE):
        try:
            with open(DATA_FILE, "r") as f:
                return json.load(f)
        except Exception:
            traceback.print_exc()
    # deep copy safe default
    st = json.loads(json.dumps(DEFAULT_STATE))
    return st

def save_state(st: Dict[str, Any]):
    try:
        with open(DATA_FILE, "w") as f:
            json.dump(st, f, indent=2, default=str)
    except Exception:
        traceback.print_exc()

state = load_state()

# seed admin user
if "admin@kairah.local" not in state["users"]:
    state["users"]["admin@kairah.local"] = {
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
    save_state(state)

# --------------------------
# Utilities
# --------------------------
def now_ts():
    return int(time.time())

def log(kind: str, entry: Dict[str, Any]):
    state["logs"].setdefault(kind, []).append(entry)
    save_state(state)

def generate_affiliate_code(email: str) -> str:
    code = f"KA-{abs(hash(email)) % (10**8)}"
    if code not in state["affiliates"]:
        state["affiliates"][code] = {"email": email, "commission": 0.0, "referred": [], "bonuses": 0.0, "payouts": []}
        save_state(state)
    return code

def get_user(email: str) -> Optional[Dict[str, Any]]:
    return state["users"].get(email)

def create_user_local(email: str, display_name: Optional[str]=None, referral_code: Optional[str]=None):
    if email in state["users"]:
        return state["users"][email]
    state["users"][email] = {
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
        aff = state["affiliates"].get(referral_code)
        if aff:
            aff.setdefault("referred", []).append(email)
    save_state(state)
    return state["users"][email]

def upgrade_user_plan(email: str, plan: str):
    if plan not in PLANS:
        raise ValueError("Unknown plan")
    u = state["users"].get(email)
    if u:
        u["plan"] = plan
    else:
        state["users"][email] = {"email": email, "plan": plan, "created_at": now_ts(), "is_admin": False, "generated_videos": 0, "downloads": 0, "fame_booster_paid": False}
    save_state(state)
    return state["users"][email]

def record_payment(payment_id: str, email: str, method: str, amount: float, metadata: Optional[Dict]=None, status: str="completed"):
    state["payments"][payment_id] = {
        "payment_id": payment_id,
        "email": email,
        "method": method,
        "amount": float(amount),
        "metadata": metadata or {},
        "status": status,
        "timestamp": now_ts(),
    }
    log("payment_logs", state["payments"][payment_id])
    save_state(state)
    return state["payments"][payment_id]

def credit_affiliate_for_sale(ref_code: str, sale_amount: float, plan_name: str):
    aff = state["affiliates"].get(ref_code)
    if not aff:
        return 0.0
    commission = float(Decimal(sale_amount) * Decimal("0.70"))  # 70% to affiliate
    aff["commission"] = aff.get("commission", 0.0) + commission
    log("affiliate_logs", {"ref": ref_code, "email": aff.get("email"), "commission_added": commission, "sale_amount": sale_amount, "plan": plan_name, "timestamp": now_ts()})
    # milestone check: count referred Lifetime/Cinematic purchases
    special_sales = 0
    for e in aff.get("referred", []):
        for p in state["payments"].values():
            if p["email"] == e and p["status"] == "completed":
                plan = (p.get("metadata") or {}).get("plan")
                if plan in ("Cinematic", "Lifetime"):
                    special_sales += 1
    if aff.get("_milestone_awarded") is None and special_sales >= 100:
        aff["commission"] = aff.get("commission", 0.0) + 500.0
        aff["bonuses"] = aff.get("bonuses", 0.0) + 500.0
        aff["_milestone_awarded"] = True
        log("affiliate_logs", {"ref": ref_code, "email": aff.get("email"), "bonus_awarded": 500.0, "timestamp": now_ts()})
    save_state(state)
    return commission

# --------------------------
# Models
# --------------------------
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
    requested_seconds: Optional[int] = None
    fame_booster: Optional[bool] = False
    template_id: Optional[str] = None
    music_id: Optional[str] = None

# --------------------------
# App
# --------------------------
app = FastAPI(title="Kairah Studio - Local Backend (No Secrets)")
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])

# Admin dependency
async def require_admin(request: Request, x_admin_key: Optional[str] = Header(None)):
    if x_admin_key and x_admin_key == ADMIN_API_KEY:
        return True
    admin_email = request.headers.get("x-admin-email")
    if admin_email:
        u = state["users"].get(admin_email)
        if u and u.get("is_admin"):
            return True
    raise HTTPException(status_code=401, detail="Admin credentials required")

# --------------------------
# Public endpoints
# --------------------------
@app.get("/")
async def index():
    return {"message": "Kairah Studio local backend is live", "time": now_ts()}

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

# Affiliate endpoints
@app.get("/api/affiliate/earnings")
async def affiliate_earnings(email: str):
    ref_code = None
    for code, v in state["affiliates"].items():
        if v.get("email") == email:
            ref_code = code
            break
    if not ref_code:
        return {"total_earned": 0.0, "pending": 0.0, "bonuses": 0.0, "ref_code": None}
    aff = state["affiliates"][ref_code]
    return {"ref_code": ref_code, "total_earned": aff.get("commission", 0.0) + aff.get("bonuses", 0.0), "pending": aff.get("commission", 0.0), "bonuses": aff.get("bonuses", 0.0)}

@app.get("/api/affiliate/referrals")
async def affiliate_referrals(ref_code: str):
    aff = state["affiliates"].get(ref_code)
    if not aff:
        raise HTTPException(status_code=404, detail="Affiliate not found")
    referred = []
    for e in aff.get("referred", []):
        u = state["users"].get(e, {"email": e, "plan": "Free"})
        referred.append({"email": e, "plan": u.get("plan")})
    return {"ref_code": ref_code, "referred": referred}

@app.get("/api/affiliate/me")
async def affiliate_me(email: str):
    for code, v in state["affiliates"].items():
        if v.get("email") == email:
            return {"ref_code": code, "data": v}
    code = generate_affiliate_code(email)
    return {"ref_code": code, "data": state["affiliates"].get(code)}

# Video generation
@app.post("/api/generate-video")
async def api_generate_video(req: VideoRequest):
    user = get_user(req.user_email)
    if not user:
        raise HTTPException(status_code=401, detail="User not found. Please signup/login.")
    plan = user.get("plan", "Free")
    plan_info = PLANS.get(plan, PLANS["Free"])
    max_seconds = plan_info.get("max_seconds")
    # determine length
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
    # aspect ratio
    if req.aspect_ratio not in VALID_RATIOS:
        raise HTTPException(status_code=400, detail=f"Invalid aspect ratio. Allowed: {VALID_RATIOS}")
    # premium template/music restriction
    if (req.template_id or req.music_id) and plan not in ("Diamond", "Cinematic", "Lifetime"):
        raise HTTPException(status_code=403, detail="Premium templates/music are available to Diamond, Cinematic, and Lifetime plans only.")
    # fame booster check
    if req.fame_booster and not user.get("fame_booster_paid"):
        return {"require_payment": True, "price": FAME_BOOSTER_PRICE, "message": "Fame booster requires $9 payment. Use admin confirm-wise to mark as paid."}
    # free limit
    if plan == "Free" and user.get("generated_videos", 0) >= 1:
        raise HTTPException(status_code=403, detail="Free plan allows only 1 generated video. Upgrade to create more.")
    # create mock video
    video_id = f"{req.user_email.replace('@','_')}_{len(state['videos'])+1}_{now_ts()}"
    video_url = f"https://cdn.kairahstudio.com/mock_videos/{video_id}.mp4"
    state["videos"][video_id] = {"video_id": video_id, "email": req.user_email, "prompt": req.prompt, "url": video_url, "length": length, "aspect_ratio": req.aspect_ratio, "timestamp": now_ts(), "fame_booster": req.fame_booster}
    state["users"].setdefault(req.user_email, {"email": req.user_email, "generated_videos": 0})
    state["users"][req.user_email]["generated_videos"] = state["users"][req.user_email].get("generated_videos", 0) + 1
    log("video_logs", {"video_id": video_id, "user": req.user_email, "prompt": req.prompt, "length": length, "aspect_ratio": req.aspect_ratio, "timestamp": now_ts()})
    save_state(state)
    return {"video_url": video_url, "video_id": video_id, "message": f"Video generated ({length}s)"}

# Download
@app.get("/api/download")
async def api_download(video_id: str, email: str):
    v = state["videos"].get(video_id)
    if not v:
        raise HTTPException(status_code=404, detail="Video not found")
    u = get_user(email)
    if not u:
        raise HTTPException(status_code=401, detail="User required")
    if u.get("plan") == "Free":
        if u.get("downloads", 0) >= 1:
            raise HTTPException(status_code=403, detail="Free plan allows only one download. Upgrade to download more.")
        u["downloads"] = u.get("downloads", 0) + 1
        save_state(state)
    return {"video_url": v["url"], "message": "Download granted"}

# --------------------------
# Payment webhooks (mocked/no external)
# --------------------------
# We removed Stripe and any need for external provider credentials.
# For Paystack/PayPal/M-Pesa you can still POST payloads here; handlers are basic best-effort.

@app.post("/api/paystack-webhook")
async def paystack_webhook(req: Request):
    payload = await req.json()
    # best-effort: if payload contains email + amount + metadata.plan, treat as success
    data_obj = payload.get("data", payload)
    email = data_obj.get("customer", {}).get("email") or data_obj.get("email")
    amount = data_obj.get("amount", 0) / 100.0 if data_obj.get("amount") else data_obj.get("amount", 0) or 0.0
    plan = (data_obj.get("metadata") or {}).get("plan") or payload.get("plan")
    if email:
        upgrade_user_plan(email, plan or "Pro")
        record_payment(data_obj.get("id", f"paystack_{now_ts()}"), email, "paystack", amount, metadata={"plan": plan})
        ref = state["users"].get(email, {}).get("ref")
        if ref:
            credit_affiliate_for_sale(ref, float(amount), plan or "Pro")
    return {"status": "ok"}

@app.post("/api/paypal-webhook")
async def paypal_webhook(req: Request):
    payload = await req.json()
    # best-effort parse
    resource = payload.get("resource", payload)
    email = resource.get("payer", {}).get("email_address") or resource.get("billing_email")
    amount = 0.0
    try:
        amount = float((resource.get("amount", {}).get("value")) or 0.0)
    except Exception:
        amount = 0.0
    plan = resource.get("custom_id") or resource.get("invoice_id") or payload.get("plan")
    if email:
        upgrade_user_plan(email, plan or "Pro")
        record_payment(resource.get("id", f"paypal_{now_ts()}"), email, "paypal", amount, metadata={"plan": plan})
        ref = state["users"].get(email, {}).get("ref")
        if ref:
            credit_affiliate_for_sale(ref, float(amount), plan or "Pro")
    return {"status": "ok"}

@app.post("/api/mpesa-webhook")
async def mpesa_webhook(req: Request):
    payload = await req.json()
    # placeholder: accept and log for manual processing
    # If you want to auto-upgrade, POST {"email": "...", "amount": 10, "plan":"Pro"} to this endpoint
    email = payload.get("email")
    amount = payload.get("amount", 0)
    plan = payload.get("plan")
    if email and amount:
        upgrade_user_plan(email, plan or "Pro")
        record_payment(f"mpesa_{now_ts()}", email, "mpesa", amount, metadata={"plan": plan})
        ref = state["users"].get(email, {}).get("ref")
        if ref:
            credit_affiliate_for_sale(ref, float(amount), plan or "Pro")
    return {"status": "ok"}

# --------------------------
# Wise manual confirmation (admin)
# --------------------------
@app.post("/api/admin/confirm-wise")
async def admin_confirm_wise(payment_id: str, email: str, amount: float, plan: str = "Pro", ref_code: Optional[str] = None, admin: bool = Depends(require_admin)):
    # Admin confirms manual Wise transfer. This upgrades plan and credits affiliate.
    rec = record_payment(payment_id, email, "wise", amount, metadata={"plan": plan})
    upgrade_user_plan(email, plan)
    ref = ref_code or state["users"].get(email, {}).get("ref")
    if ref:
        credit_affiliate_for_sale(ref, float(amount), plan)
    save_state(state)
    return {"status": "ok", "payment": rec}

# --------------------------
# Admin & reports
# --------------------------
@app.get("/admin/users")
async def admin_list_users(admin: bool = Depends(require_admin)):
    return {"users": list(state["users"].values())}

@app.get("/admin/export/logs")
async def admin_export_logs(admin: bool = Depends(require_admin)):
    return state["logs"]

@app.get("/admin/export/csv/{logname}")
async def admin_export_csv(logname: str, admin: bool = Depends(require_admin)):
    logs = state["logs"].get(logname)
    if logs is None:
        raise HTTPException(status_code=404, detail="Log not found")
    if not logs:
        return Response(content="", media_type="text/csv")
    keys = sorted({k for r in logs for k in r.keys()})
    csv_lines = [",".join(keys)]
    for r in logs:
        csv_lines.append(",".join([str(r.get(k, "")) for k in keys]))
    return Response(content="\n".join(csv_lines), media_type="text/csv")

@app.post("/admin/create-admin")
async def admin_create_admin(email: str, admin: bool = Depends(require_admin)):
    if email not in state["users"]:
        create_user_local(email)
    state["users"][email]["is_admin"] = True
    save_state(state)
    return {"status": "ok", "email": email}

@app.post("/admin/affiliate/payout")
async def admin_affiliate_payout(ref_code: str, amount: float, admin: bool = Depends(require_admin)):
    aff = state["affiliates"].get(ref_code)
    if not aff:
        raise HTTPException(status_code=404, detail="Affiliate not found")
    available = aff.get("commission", 0.0)
    if amount > available:
        raise HTTPException(status_code=400, detail="Insufficient commission")
    aff["commission"] = round(available - amount, 2)
    aff.setdefault("payouts", []).append({"amount": amount, "timestamp": now_ts()})
    log("affiliate_logs", {"ref": ref_code, "payout": amount, "timestamp": now_ts()})
    save_state(state)
    return {"status": "ok", "remaining_commission": aff["commission"]}

# FAQ & health
FAQ = [
    {"q": "How many free videos?", "a": "Free users can generate one 6-second video. Upgrade to Pro for more."},
    {"q": "What plans exist?", "a": "Pro, Diamond, Cinematic, Lifetime."},
]
@app.get("/api/faq")
async def api_faq(q: Optional[str] = None):
    if q:
        ql = q.lower()
        return [f for f in FAQ if ql in f["q"].lower() or ql in f["a"].lower()]
    return FAQ

@app.get("/health")
async def health():
    return {"status": "ok", "time": now_ts()}

# --------------------------
# Run
# --------------------------
if __name__ == "__main__":
    print("Starting Kairah Studio local backend (no external credentials required).")
    print("Admin key (use header x-admin-key):", ADMIN_API_KEY)
    uvicorn.run("main:app", host="0.0.0.0", port=8000)
