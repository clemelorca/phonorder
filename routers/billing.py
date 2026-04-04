"""
Facturación de suscripciones Skanorder vía MercadoPago Preapproval.
Flujo:
  1. Admin abre panel-mysub → hace click en "Suscribirse" o "Cambiar plan"
  2. POST /billing/subscribe  → crea preapproval en MP → retorna init_point URL
  3. Admin aprueba en MP → MP redirige a /billing/return?store_id=X
  4. MP envía webhook POST /billing/webhook → actualiza sub como active
"""
from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import RedirectResponse
from database import (get_db, Store, Subscription, SystemConfig,
                      SubStatus, Plan, User, SalesLead, LeadStatus)
from auth import get_current_user, require_superadmin
from security import encrypt_field, decrypt_field
from pydantic import BaseModel
from typing import Optional
import httpx, json, smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from datetime import datetime, timedelta

router = APIRouter(tags=["billing"])

# ── Precios por plan (CLP) ────────────────────────────────────
PLAN_PRICES = {
    "starter": 49990,
    "negocio": 99990,
    "cadena": 0,  # A medida: precio definido por superadmin vía cotización
}
PLAN_LABELS = {
    "starter": "🌱 Starter",
    "negocio": "🏪 Negocio",
    "cadena": "🏢 Cadena",
}

# ── helpers ──────────────────────────────────────────────────

def _get_mp_token(db) -> str:
    cfg = db.query(SystemConfig).filter(SystemConfig.key == "billing_mp_token").first()
    if not cfg or not cfg.value:
        raise HTTPException(400, "Token de MercadoPago para facturación no configurado. Configúralo en Superadmin → Facturación.")
    return decrypt_field(cfg.value)

def _base_url(request: Request) -> str:
    return str(request.base_url).rstrip("/")

# ── Superadmin: config token de billing ──────────────────────

class BillingConfigIn(BaseModel):
    mp_access_token: str

@router.get("/billing/config")
def get_billing_config(db=Depends(get_db), _=Depends(require_superadmin)):
    cfg = db.query(SystemConfig).filter(SystemConfig.key == "billing_mp_token").first()
    token = cfg.value if cfg else None
    # Enmascarar token
    masked = ("..." + token[-6:]) if token and len(token) > 6 else (token or "")
    return {"configured": bool(token), "token_hint": masked}

@router.put("/billing/config")
def set_billing_config(data: BillingConfigIn, db=Depends(get_db), _=Depends(require_superadmin)):
    cfg = db.query(SystemConfig).filter(SystemConfig.key == "billing_mp_token").first()
    encrypted = encrypt_field(data.mp_access_token)
    if cfg:
        cfg.value = encrypted
    else:
        cfg = SystemConfig(key="billing_mp_token", value=encrypted)
        db.add(cfg)
    db.commit()
    return {"ok": True}

@router.get("/billing/plans")
def list_plans():
    return [{"plan": p, "label": PLAN_LABELS[p], "price": PLAN_PRICES[p]} for p in PLAN_PRICES]

# ── Suscripción: crear preapproval MP ────────────────────────

class SubscribeIn(BaseModel):
    store_id: int
    plan: str

@router.post("/billing/subscribe")
async def subscribe(data: SubscribeIn, request: Request,
                    db=Depends(get_db), cu=Depends(get_current_user)):
    # Verificar ownership
    s = db.query(Store).filter(Store.id == data.store_id, Store.owner_id == cu.id).first()
    if not s:
        raise HTTPException(403, "No tienes acceso a esta tienda")

    try:
        plan = Plan(data.plan)
    except ValueError:
        raise HTTPException(400, "Plan inválido")

    price = PLAN_PRICES.get(data.plan, 0)

    # Plan gratuito: solo actualizar sub sin MP
    if price == 0:
        sub = db.query(Subscription).filter(Subscription.store_id == data.store_id).first()
        if not sub:
            sub = Subscription(store_id=data.store_id, plan=plan,
                               status=SubStatus.active, price_monthly=0)
            db.add(sub)
        else:
            sub.plan = plan
            sub.status = SubStatus.active
            sub.price_monthly = 0
            sub.mp_preapproval_id = None
            sub.mp_preapproval_url = None
        s.plan = plan
        db.commit()
        return {"plan": data.plan, "free": True, "checkout_url": None}

    access_token = _get_mp_token(db)
    base = _base_url(request)

    payload = {
        "reason": f"{PLAN_LABELS[data.plan]} - {s.name} (Skanorder)",
        "payer_email": cu.email,
        "auto_recurring": {
            "frequency": 1,
            "frequency_type": "months",
            "transaction_amount": price,
            "currency_id": "CLP",
        },
        "back_url": f"{base}/billing/return?store_id={data.store_id}&plan={data.plan}",
        "external_reference": f"{data.store_id}|{data.plan}|{cu.id}",
        "status": "pending",
    }

    async with httpx.AsyncClient() as client:
        resp = await client.post(
            "https://api.mercadopago.com/preapproval",
            json=payload,
            headers={"Authorization": f"Bearer {access_token}"},
            timeout=15,
        )

    if resp.status_code not in (200, 201):
        raise HTTPException(502, f"MercadoPago: {resp.text[:200]}")

    mp_data = resp.json()
    preapproval_id = mp_data.get("id")
    checkout_url = mp_data.get("init_point")

    # Guardar preapproval_id en sub (o crear sub pendiente)
    sub = db.query(Subscription).filter(Subscription.store_id == data.store_id).first()
    if not sub:
        sub = Subscription(store_id=data.store_id, plan=plan,
                           status=SubStatus.trial, price_monthly=price,
                           mp_preapproval_id=preapproval_id,
                           mp_preapproval_url=checkout_url)
        db.add(sub)
    else:
        sub.plan = plan
        sub.price_monthly = price
        sub.mp_preapproval_id = preapproval_id
        sub.mp_preapproval_url = checkout_url
    db.commit()

    return {"plan": data.plan, "free": False, "checkout_url": checkout_url}

# ── Return desde MP ───────────────────────────────────────────

@router.get("/billing/return")
async def billing_return(store_id: int, plan: str,
                         preapproval_id: Optional[str] = None,
                         status: Optional[str] = None,
                         db=Depends(get_db)):
    sub = db.query(Subscription).filter(Subscription.store_id == store_id).first()
    # MP puede no confirmar instantáneamente; el webhook lo actualizará
    # Aquí solo redirigimos al admin con mensaje
    if status == "approved" or (sub and sub.mp_preapproval_id):
        return RedirectResponse(f"/admin?billing=pending&plan={plan}")
    return RedirectResponse(f"/admin?billing=cancelled")

# ── Webhook MP preapproval ────────────────────────────────────

@router.post("/billing/webhook")
async def billing_webhook(request: Request, db=Depends(get_db)):
    try:
        body = await request.json()
    except Exception:
        return {"ok": True}

    event_type = body.get("type")
    if event_type not in ("subscription_preapproval", "preapproval"):
        return {"ok": True}

    preapproval_id = body.get("data", {}).get("id")
    if not preapproval_id:
        return {"ok": True}

    # Buscar sub por preapproval_id
    sub = db.query(Subscription).filter(
        Subscription.mp_preapproval_id == preapproval_id
    ).first()
    if not sub:
        return {"ok": True}

    # Consultar estado en MP
    cfgs = db.query(SystemConfig).filter(SystemConfig.key == "billing_mp_token").first()
    if not cfgs or not cfgs.value:
        return {"ok": True}

    async with httpx.AsyncClient() as client:
        resp = await client.get(
            f"https://api.mercadopago.com/preapproval/{preapproval_id}",
            headers={"Authorization": f"Bearer {decrypt_field(cfgs.value)}"},
            timeout=10,
        )

    if resp.status_code != 200:
        return {"ok": True}

    mp = resp.json()
    mp_status = mp.get("status")
    ext_ref = mp.get("external_reference", "")

    # Parsear external_reference: "store_id|plan|user_id"
    parts = ext_ref.split("|")
    if len(parts) >= 2:
        try:
            plan_val = Plan(parts[1])
            sub.plan = plan_val
            store = db.query(Store).filter(Store.id == sub.store_id).first()
            if store:
                store.plan = plan_val
        except ValueError:
            pass

    if mp_status == "authorized":
        sub.status = SubStatus.active
        sub.next_billing = datetime.utcnow() + timedelta(days=30)
        # Extraer datos de tarjeta si MP los provee
        payer = mp.get("payer", {})
        card = mp.get("card", {})
        if card.get("last_four_digits"):
            sub.card_last4 = card["last_four_digits"]
        if card.get("payment_method", {}).get("id"):
            sub.card_brand = card["payment_method"]["id"]
    elif mp_status == "paused":
        sub.status = SubStatus.past_due
    elif mp_status == "cancelled":
        sub.status = SubStatus.cancelled
        sub.mp_preapproval_id = None

    db.commit()
    return {"ok": True}

# ── Helper email ──────────────────────────────────────────────

def _send_email(db, to: str, subject: str, body_html: str):
    try:
        def _cfg(key):
            r = db.query(SystemConfig).filter(SystemConfig.key == key).first()
            return r.value if r and r.value else None
        host = _cfg("smtp_host"); user = _cfg("smtp_user")
        pw = _cfg("smtp_pass"); from_addr = _cfg("smtp_from")
        if not all([host, user, pw, from_addr]):
            return
        port = int(_cfg("smtp_port") or 587)
        msg = MIMEMultipart()
        msg["Subject"] = subject; msg["From"] = from_addr; msg["To"] = to
        msg.attach(MIMEText(body_html, "html"))
        with smtplib.SMTP(host, port) as s:
            s.starttls(); s.login(user, pw); s.send_message(msg)
    except Exception:
        pass

# ── Plan Cadena: solicitud de cotización ─────────────────────

class PlanRequestIn(BaseModel):
    store_id: int
    contact_name: str
    contact_email: str
    contact_phone: Optional[str] = None
    message: Optional[str] = None

@router.post("/me/plan-request", status_code=201)
def create_plan_request(data: PlanRequestIn, db=Depends(get_db), cu=Depends(get_current_user)):
    s = db.query(Store).filter(Store.id == data.store_id, Store.owner_id == cu.id).first()
    if not s:
        raise HTTPException(403, "No tienes acceso a esta tienda")
    lead = SalesLead(
        store_id=data.store_id, contact_name=data.contact_name,
        contact_email=data.contact_email, contact_phone=data.contact_phone,
        message=data.message, status=LeadStatus.pending,
    )
    db.add(lead); db.commit(); db.refresh(lead)
    phone_line = f"<p><strong>Teléfono:</strong> {data.contact_phone}</p>" if data.contact_phone else ""
    msg_line = f"<p><strong>Mensaje:</strong> {data.message}</p>" if data.message else ""
    _send_email(db, "sales@skanorder.com",
        f"Nueva solicitud plan Cadena – {s.name}",
        f"<h2>Nueva solicitud de plan Cadena</h2>"
        f"<p><strong>Tienda:</strong> {s.name} (#{s.id})</p>"
        f"<p><strong>Contacto:</strong> {data.contact_name} ({data.contact_email})</p>"
        f"{phone_line}{msg_line}<p><strong>Lead ID:</strong> #{lead.id}</p>")
    return {"id": lead.id, "status": lead.status}

@router.get("/me/plan-leads")
def my_plan_leads(db=Depends(get_db), cu=Depends(get_current_user)):
    store_ids = [s.id for s in db.query(Store).filter(Store.owner_id == cu.id).all()]
    if not store_ids:
        return []
    leads = db.query(SalesLead).filter(SalesLead.store_id.in_(store_ids)).order_by(SalesLead.created_at.desc()).all()
    return [{"id":l.id,"store_id":l.store_id,"store_name":l.store.name,
             "contact_name":l.contact_name,"contact_email":l.contact_email,
             "message":l.message,"status":l.status,"quoted_price":l.quoted_price,
             "created_at":l.created_at.isoformat()} for l in leads]

@router.post("/me/plan-leads/{lead_id}/accept")
def accept_plan_lead(lead_id: int, db=Depends(get_db), cu=Depends(get_current_user)):
    lead = db.query(SalesLead).filter(SalesLead.id == lead_id).first()
    if not lead:
        raise HTTPException(404, "Solicitud no encontrada")
    store = db.query(Store).filter(Store.id == lead.store_id, Store.owner_id == cu.id).first()
    if not store:
        raise HTTPException(403, "No tienes acceso")
    if lead.status != LeadStatus.quoted:
        raise HTTPException(400, "Esta solicitud no tiene precio cotizado aún")
    sub = db.query(Subscription).filter(Subscription.store_id == lead.store_id).first()
    if not sub:
        sub = Subscription(store_id=lead.store_id, plan=Plan.cadena,
                           status=SubStatus.active, price_monthly=lead.quoted_price)
        db.add(sub)
    else:
        sub.plan = Plan.cadena; sub.price_monthly = lead.quoted_price; sub.status = SubStatus.active
    store.plan = Plan.cadena
    lead.status = LeadStatus.accepted
    db.commit()
    return {"ok": True, "price": lead.quoted_price}
