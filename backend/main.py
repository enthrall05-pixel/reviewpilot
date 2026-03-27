# ╔══════════════════╗
# ║  Created by G/C  ║
# ╚══════════════════╝
import os
import json
import stripe
import anthropic
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
from supabase import create_client

app = FastAPI(title="ReviewPilot API")

app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])

# ── Clients ──────────────────────────────────────────────────────────────────
ANTHROPIC_KEY   = os.environ.get("ANTHROPIC_API_KEY", "")
STRIPE_KEY      = os.environ.get("STRIPE_SECRET_KEY", "")
STRIPE_WEBHOOK  = os.environ.get("STRIPE_WEBHOOK_SECRET", "")
STRIPE_PRICE_ID = os.environ.get("STRIPE_PRICE_ID", "price_1TFQG1EsXD6vSEDHd0c7jTxS")
SUPABASE_URL    = os.environ.get("SUPABASE_URL", "")
SUPABASE_KEY    = os.environ.get("SUPABASE_KEY", "")
DOMAIN          = os.environ.get("DOMAIN", "http://localhost:8080")

FREE_LIMIT = 10

ai     = anthropic.Anthropic(api_key=ANTHROPIC_KEY)
stripe.api_key = STRIPE_KEY
sb     = create_client(SUPABASE_URL, SUPABASE_KEY)

# ── Models ───────────────────────────────────────────────────────────────────
class GenerateRequest(BaseModel):
    device_id: str
    review_text: str
    business_name: str = ""
    platform: str = "Google"
    rating: int = 0
    tone: str = "professional"  # professional | friendly | apologetic

class CheckoutRequest(BaseModel):
    device_id: str

# ── Helpers ───────────────────────────────────────────────────────────────────
def get_or_create_user(device_id: str) -> dict:
    res = sb.table("rp_users").select("*").eq("device_id", device_id).execute()
    if res.data:
        return res.data[0]
    sb.table("rp_users").insert({"device_id": device_id}).execute()
    return {"device_id": device_id, "tier": "free", "count": 0, "stripe_customer": None}

def increment_count(device_id: str):
    sb.rpc("rpc_increment_rp_count", {"p_device_id": device_id}).execute()
    # fallback direct update
    user = get_or_create_user(device_id)
    sb.table("rp_users").update({"count": user["count"] + 1}).eq("device_id", device_id).execute()

def save_review(device_id: str, data: dict, replies: list):
    sb.table("rp_reviews").insert({
        "device_id": device_id,
        "business_name": data.get("business_name", ""),
        "platform": data.get("platform", "Google"),
        "review_text": data["review_text"],
        "rating": data.get("rating", 0),
        "replies": replies,
    }).execute()

def downgrade_by_customer(customer_id: str):
    sb.table("rp_users").update({"tier": "free"}).eq("stripe_customer", customer_id).execute()

# ── Routes ────────────────────────────────────────────────────────────────────
@app.get("/health")
def health():
    return {"ok": True}

@app.post("/generate")
async def generate(req: GenerateRequest):
    user = get_or_create_user(req.device_id)

    # reset count daily
    from datetime import datetime, timezone, timedelta
    reset_at = user.get("reset_at", "")
    if reset_at:
        try:
            reset_time = datetime.fromisoformat(reset_at.replace("Z", "+00:00"))
            if datetime.now(timezone.utc) - reset_time > timedelta(days=1):
                sb.table("rp_users").update({"count": 0, "reset_at": datetime.now(timezone.utc).isoformat()}).eq("device_id", req.device_id).execute()
                user["count"] = 0
        except Exception:
            pass

    # paywall
    if user["tier"] == "free" and user["count"] >= FREE_LIMIT:
        return JSONResponse(content={"upgrade": True, "replies": []})

    # build prompt
    star_context = f"{req.rating}-star" if req.rating else ""
    business_ctx = f" for {req.business_name}" if req.business_name else ""
    tone_map = {
        "professional": "professional and polished",
        "friendly": "warm, friendly and personal",
        "apologetic": "empathetic and apologetic where needed"
    }
    tone_desc = tone_map.get(req.tone, "professional")

    prompt = f"""You are a review response specialist. Generate 3 distinct reply options to the following {star_context} customer review{business_ctx} on {req.platform}.

Review: "{req.review_text}"

Requirements:
- Each reply should be {tone_desc}
- Keep each reply between 2-4 sentences
- Reply 1: Short and punchy (1-2 sentences)
- Reply 2: Standard response (2-3 sentences)
- Reply 3: Detailed and thorough (3-4 sentences)
- Don't be generic — reference specifics from the review
- Sound human, not robotic
- If negative review, acknowledge the issue and offer resolution

Return ONLY a JSON array with exactly 3 strings, no other text:
["reply 1 text", "reply 2 text", "reply 3 text"]"""

    try:
        msg = ai.messages.create(
            model="claude-haiku-4-5-20251001",
            max_tokens=800,
            messages=[{"role": "user", "content": prompt}]
        )
        raw = msg.content[0].text.strip()
        # extract JSON array
        start = raw.find("[")
        end = raw.rfind("]") + 1
        replies = json.loads(raw[start:end])
    except Exception as e:
        return JSONResponse(status_code=500, content={"error": str(e)})

    # save and increment
    save_review(req.device_id, req.dict(), replies)
    increment_count(req.device_id)

    messages_left = max(0, FREE_LIMIT - user["count"] - 1)

    return {
        "replies": replies,
        "upgrade": False,
        "tier": user["tier"],
        "messages_left": messages_left if user["tier"] == "free" else None,
        "near_limit": user["tier"] == "free" and 0 < messages_left <= 3
    }

@app.get("/history")
async def history(device_id: str):
    res = sb.table("rp_reviews").select("*").eq("device_id", device_id).order("created_at", desc=True).limit(20).execute()
    return {"reviews": res.data}

@app.post("/checkout")
async def checkout(req: CheckoutRequest):
    try:
        session = stripe.checkout.Session.create(
            payment_method_types=["card"],
            line_items=[{"price": STRIPE_PRICE_ID, "quantity": 1}],
            mode="subscription",
            success_url=f"{DOMAIN}/?upgraded=1",
            cancel_url=f"{DOMAIN}/",
            metadata={"device_id": req.device_id},
            subscription_data={"metadata": {"device_id": req.device_id}},
        )
        return {"url": session.url}
    except Exception as e:
        return JSONResponse(status_code=500, content={"error": str(e)})

@app.post("/webhook/stripe")
async def stripe_webhook(request: Request):
    payload = await request.body()
    sig = request.headers.get("stripe-signature", "")
    try:
        if STRIPE_WEBHOOK:
            event = stripe.Webhook.construct_event(payload, sig, STRIPE_WEBHOOK)
        else:
            event = json.loads(payload)
    except Exception as e:
        return JSONResponse(status_code=400, content={"error": str(e)})

    etype = event.get("type", "")
    obj = event["data"]["object"]

    if etype == "checkout.session.completed":
        device_id = obj.get("metadata", {}).get("device_id")
        customer = obj.get("customer")
        if device_id:
            sb.table("rp_users").update({"tier": "pro", "stripe_customer": customer}).eq("device_id", device_id).execute()

    elif etype in ("customer.subscription.deleted", "invoice.payment_failed"):
        customer = obj.get("customer")
        if customer:
            downgrade_by_customer(customer)

    return {"ok": True}

# ── Serve frontend ────────────────────────────────────────────────────────────
FRONTEND_DIR = os.path.join(os.path.dirname(__file__), "..", "frontend")
app.mount("/", StaticFiles(directory=FRONTEND_DIR, html=True), name="static")
