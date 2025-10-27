"""
Kairah Studio — Unified Backend (Single-File Edition)
Works on Render, Replit, or local Python.
No external folders or configs required.
"""

from fastapi import FastAPI, Form, UploadFile, File, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from typing import Optional
import uvicorn

app = FastAPI(
    title="Kairah Studio Backend",
    description="Divine Cinematics AI API — unified single-file backend",
    version="1.0"
)

# --- Allow all origins (for frontend)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# -------------------------------------------------------------------
#  ROOT & AUTH
# -------------------------------------------------------------------

@app.get("/")
async def home():
    return {"message": "✨ Kairah Studio Backend is Live — Beyond Reality, Into Royalty ✨"}

users = {}

@app.post("/signup/")
async def signup(email: str = Form(...), password: str = Form(...)):
    if email in users:
        raise HTTPException(status_code=400, detail="User already exists")
    users[email] = password
    return {"status": "success", "message": f"Welcome {email}, your Kairah journey begins 👑"}

@app.post("/login/")
async def login(email: str = Form(...), password: str = Form(...)):
    if users.get(email) != password:
        raise HTTPException(status_code=401, detail="Invalid credentials")
    return {"status": "success", "message": f"Welcome back, {email}"}

# -------------------------------------------------------------------
#  AI GENERATION MOCK ENDPOINTS
# -------------------------------------------------------------------

@app.post("/generate/video/")
async def generate_video(prompt: str = Form(...), length: str = Form("1min")):
    return {
        "status": "success",
        "prompt": prompt,
        "length": length,
        "url": "https://example.com/generated_cinematic.mp4"
    }

@app.post("/generate/image/")
async def generate_image(prompt: str = Form(...)):
    return {
        "status": "success",
        "prompt": prompt,
        "image_url": "https://example.com/generated_image.png"
    }

@app.post("/generate/audio/")
async def generate_audio(prompt: str = Form(...)):
    return {
        "status": "success",
        "prompt": prompt,
        "audio_url": "https://example.com/generated_audio.mp3"
    }

# -------------------------------------------------------------------
#  PRICING / SUBSCRIPTION MOCK
# -------------------------------------------------------------------

plans = {
    "free": {"price": 0, "features": ["1 short video", "preview tools"]},
    "pro": {"price": 19, "features": ["1-min videos", "10 gens/month", "HD export"]},
    "diamond": {"price": 49, "features": ["2-min videos", "40 gens/month", "4K export"]},
    "cinematic": {"price": 99, "features": ["3-min films", "unlimited", "studio tools"]},
    "lifetime": {"price": 500, "features": ["Full access forever"]}
}

@app.get("/plans/")
async def get_plans():
    return {"plans": plans}

# -------------------------------------------------------------------
#  AFFILIATE MOCK
# -------------------------------------------------------------------

affiliates = {}

@app.post("/affiliate/register/")
async def register_affiliate(email: str = Form(...)):
    affiliates[email] = {"sales": 0, "commission": 0}
    return {"status": "success", "message": f"{email} enrolled — 30% commission active"}

@app.post("/affiliate/sale/")
async def record_sale(email: str = Form(...), amount: float = Form(...)):
    if email not in affiliates:
        raise HTTPException(status_code=404, detail="Affiliate not found")
    commission = round(amount * 0.30, 2)
    affiliates[email]["sales"] += 1
    affiliates[email]["commission"] += commission
    return {
        "status": "recorded",
        "email": email,
        "earned": commission,
        "total_commission": affiliates[email]["commission"]
    }

# -------------------------------------------------------------------
#  PAYMENT PLACEHOLDERS
# -------------------------------------------------------------------

@app.post("/pay/stripe/")
async def stripe_pay(email: str = Form(...), plan: str = Form(...)):
    return {
        "gateway": "Stripe",
        "email": email,
        "plan": plan,
        "redirect_url": "https://checkout.stripe.com/pay/mock_session"
    }

@app.post("/pay/paypal/")
async def paypal_pay(email: str = Form(...), plan: str = Form(...)):
    return {
        "gateway": "PayPal",
        "email": email,
        "plan": plan,
        "redirect_url": "https://www.paypal.com/checkoutnow?session=mock123"
    }

# -------------------------------------------------------------------
#  SUPPORT / SETTINGS
# -------------------------------------------------------------------

@app.get("/support/")
async def support():
    return {
        "support_email": "keishapoa@gmail.com",
        "faq": [
            "How do I upgrade my plan?",
            "How long does generation take?",
            "Can I earn from referrals?",
            "Is my data secure?",
            "Can I cancel anytime?",
        ],
    }

@app.get("/settings/")
async def settings():
    return {
        "theme": "customizable",
        "video_export": ["720p", "1080p", "4K"],
        "integration": ["Stripe", "PayPal", "Firebase (optional)"],
        "affiliate_commission": "30%",
        "lifetime_bonus": "$500 after 100 sales"
    }

# -------------------------------------------------------------------
#  RUN
# -------------------------------------------------------------------

if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=10000)
