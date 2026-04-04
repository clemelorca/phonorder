from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import RedirectResponse
from database import (get_db, Store, Order, Payment, StorePaymentConfig,
    GatewayType, PaymentStatus, OrderStatus, StoreStaff, UserRole, SystemConfig, Plan)
from auth import get_current_user
from security import verify_mp_signature, decrypt_field, encrypt_field
from pydantic import BaseModel
from typing import Optional
import json, os, httpx
from datetime import datetime

router = APIRouter(tags=["gateways"])

# ── helpers ──────────────────────────────────────────────────

def _chk_store(sid, cu, db):
    s = db.query(Store).filter(Store.id == sid).first()
    if not s: raise HTTPException(404)
    if cu.role == UserRole.superadmin or s.owner_id == cu.id: return s
    if db.query(StoreStaff).filter(StoreStaff.store_id==sid, StoreStaff.user_id==cu.id).first(): return s
    raise HTTPException(403)

def _base_url(request: Request):
    return str(request.base_url).rstrip("/")

def _get_cfg(sid, gateway, db) -> Optional[dict]:
    cfg = db.query(StorePaymentConfig).filter(
        StorePaymentConfig.store_id==sid,
        StorePaymentConfig.gateway==GatewayType(gateway),
        StorePaymentConfig.is_active==True
    ).first()
    if not cfg or not cfg.credentials: return None
    return json.loads(decrypt_field(cfg.credentials))

# ── config endpoints ──────────────────────────────────────────

class GatewayConfig(BaseModel):
    is_active: bool = True
    credentials: dict

@router.get("/stores/{sid}/gateways")
def list_gateways(sid: int, db=Depends(get_db), cu=Depends(get_current_user)):
    _chk_store(sid, cu, db)
    result = {}
    for gw in GatewayType:
        cfg = db.query(StorePaymentConfig).filter(
            StorePaymentConfig.store_id==sid,
            StorePaymentConfig.gateway==gw
        ).first()
        result[gw.value] = {
            "configured": bool(cfg and cfg.credentials),
            "is_active": cfg.is_active if cfg else False,
            "updated_at": cfg.updated_at.isoformat() if cfg else None
        }
    return result

@router.put("/stores/{sid}/gateways/{gateway}")
def save_gateway(sid: int, gateway: str, data: GatewayConfig,
                 db=Depends(get_db), cu=Depends(get_current_user)):
    _chk_store(sid, cu, db)
    try: gw = GatewayType(gateway)
    except ValueError: raise HTTPException(400, "Gateway no válido")
    cfg = db.query(StorePaymentConfig).filter(
        StorePaymentConfig.store_id==sid, StorePaymentConfig.gateway==gw
    ).first()
    encrypted = encrypt_field(json.dumps(data.credentials))
    if cfg:
        cfg.credentials = encrypted
        cfg.is_active = data.is_active
        cfg.updated_at = datetime.utcnow()
    else:
        cfg = StorePaymentConfig(store_id=sid, gateway=gw,
            credentials=encrypted, is_active=data.is_active)
        db.add(cfg)
    db.commit()
    return {"ok": True}

@router.delete("/stores/{sid}/gateways/{gateway}")
def remove_gateway(sid: int, gateway: str, db=Depends(get_db), cu=Depends(get_current_user)):
    _chk_store(sid, cu, db)
    try: gw = GatewayType(gateway)
    except ValueError: raise HTTPException(400)
    cfg = db.query(StorePaymentConfig).filter(
        StorePaymentConfig.store_id==sid, StorePaymentConfig.gateway==gw
    ).first()
    if cfg:
        cfg.is_active = False
        cfg.credentials = None
        db.commit()
    return {"ok": True}

@router.patch("/stores/{sid}/gateways/{gateway}/toggle")
def toggle_gateway(sid: int, gateway: str, db=Depends(get_db), cu=Depends(get_current_user)):
    """Activa o desactiva un gateway sin tocar las credenciales."""
    _chk_store(sid, cu, db)
    try: gw = GatewayType(gateway)
    except ValueError: raise HTTPException(400)
    cfg = db.query(StorePaymentConfig).filter(
        StorePaymentConfig.store_id==sid, StorePaymentConfig.gateway==gw
    ).first()
    if not cfg or not cfg.credentials:
        raise HTTPException(400, "Gateway no configurado")
    cfg.is_active = not cfg.is_active
    cfg.updated_at = datetime.utcnow()
    db.commit()
    return {"ok": True, "is_active": cfg.is_active}

# ── checkout ──────────────────────────────────────────────────

@router.post("/orders/{oid}/checkout")
async def create_checkout(oid: int, request: Request, db=Depends(get_db)):
    """Crea sesión de pago y retorna URL de redirección."""
    o = db.query(Order).filter(Order.id == oid).first()
    if not o: raise HTTPException(404, "Pedido no encontrado")
    if o.payment and o.payment.status == PaymentStatus.paid:
        raise HTTPException(400, "Pedido ya pagado")

    base = _base_url(request)
    # Elegir gateway activo (prioridad: MP > Webpay > Getnet)
    gateway_order = [GatewayType.mercadopago, GatewayType.webpay, GatewayType.getnet]
    chosen_gw = None
    chosen_creds = None
    for gw in gateway_order:
        creds = _get_cfg(o.store_id, gw.value, db)
        if creds:
            chosen_gw = gw
            chosen_creds = creds
            break

    if not chosen_gw:
        raise HTTPException(400, "Esta tienda no tiene método de pago configurado")

    items_desc = ", ".join(f"{it.qty}x {it.product.name}" for it in o.items)
    title = f"Pedido {o.order_code or '#'+str(o.id)}"

    if chosen_gw == GatewayType.mercadopago:
        url = await _mp_checkout(o, chosen_creds, title, base, db)
    elif chosen_gw == GatewayType.webpay:
        url = await _webpay_checkout(o, chosen_creds, base, db)
    elif chosen_gw == GatewayType.getnet:
        url = await _getnet_checkout(o, chosen_creds, title, base)

    return {"gateway": chosen_gw.value, "checkout_url": url}

# ── MercadoPago ───────────────────────────────────────────────

COMMISSION_RATES = {"starter": 0.02, "negocio": 0.015, "cadena": 0.0}

def _get_commission_amount(order, db) -> tuple:
    """Retorna (commission_amount_clp, rate) según el plan de la tienda."""
    store = db.query(Store).filter(Store.id == order.store_id).first()
    if not store:
        return 0, 0.0
    plan_key = store.plan.value if hasattr(store.plan, 'value') else str(store.plan)
    rate = COMMISSION_RATES.get(plan_key, 0.0)
    amount = round(float(order.total) * rate)
    return amount, rate

def _get_mp_marketplace_id(db) -> Optional[str]:
    cfg = db.query(SystemConfig).filter(SystemConfig.key == "mp_marketplace_id").first()
    return cfg.value if cfg and cfg.value else None

async def _mp_checkout(order, creds: dict, title: str, base: str, db=None) -> str:
    import mercadopago
    sdk = mercadopago.SDK(creds["access_token"])
    pref = {
        "items": [{"title": title, "quantity": 1, "unit_price": float(order.total),
                   "currency_id": "CLP"}],
        "back_urls": {
            "success": f"{base}/pay/return?gateway=mercadopago&order_id={order.id}&status=success",
            "failure": f"{base}/pay/return?gateway=mercadopago&order_id={order.id}&status=failure",
            "pending": f"{base}/pay/return?gateway=mercadopago&order_id={order.id}&status=pending",
        },
        "auto_return": "approved",
        "notification_url": f"{base}/payments/webhook/mercadopago",
        "external_reference": str(order.id),
    }
    # ── Marketplace split de comisión ──────────────────────────
    if db:
        marketplace_id = _get_mp_marketplace_id(db)
        commission, rate = _get_commission_amount(order, db)
        if marketplace_id and commission > 0:
            pref["marketplace"] = marketplace_id
            pref["marketplace_fee"] = commission
    result = sdk.preference().create(pref)
    resp = result.get("response", {})
    if "id" not in resp:
        raise HTTPException(502, f"MercadoPago error: {resp.get('message','desconocido')}")
    use_sandbox = creds.get("sandbox", True)
    return resp["sandbox_init_point"] if use_sandbox else resp["init_point"]

@router.post("/payments/webhook/mercadopago")
async def mp_webhook(request: Request, db=Depends(get_db)):
    raw_body = await request.body()

    # ── Verificar firma de MercadoPago ──
    if not verify_mp_signature(dict(request.headers), raw_body):
        raise HTTPException(401, "Firma de webhook inválida")

    try:
        body = json.loads(raw_body)
    except Exception:
        return {"ok": True}

    if body.get("type") != "payment": return {"ok": True}
    payment_id = body.get("data", {}).get("id")
    if not payment_id: return {"ok": True}

    cfgs = db.query(StorePaymentConfig).filter(
        StorePaymentConfig.gateway==GatewayType.mercadopago,
        StorePaymentConfig.is_active==True
    ).all()
    for cfg in cfgs:
        try:
            creds = json.loads(decrypt_field(cfg.credentials or "{}"))
            import mercadopago
            sdk = mercadopago.SDK(creds.get("access_token",""))
            result = sdk.payment().get(payment_id)
            pay = result.get("response",{})
            ext_ref = str(pay.get("external_reference",""))
            if not ext_ref: continue
            order_id = int(ext_ref)
            o = db.query(Order).filter(Order.id==order_id, Order.store_id==cfg.store_id).first()
            if not o: continue
            if pay.get("status") == "approved":
                _confirm_order(o, db)
            break
        except Exception:
            continue
    return {"ok": True}

# ── Webpay (Transbank) ────────────────────────────────────────

async def _webpay_checkout(order, creds: dict, base: str, db) -> str:
    from transbank.webpay.webpay_plus.transaction import Transaction
    from transbank.common.integration_type import IntegrationType
    from transbank.common.options import WebpayOptions

    env = IntegrationType.TEST if creds.get("environment","test") == "test" else IntegrationType.LIVE
    opts = WebpayOptions(
        commerce_code=creds["commerce_code"],
        api_key=creds["api_key"],
        integration_type=env
    )
    return_url = f"{base}/pay/return?gateway=webpay&order_id={order.id}"
    resp = Transaction.create(
        buy_order=str(order.id),
        session_id=str(order.id),
        amount=int(order.total),
        return_url=return_url,
        options=opts
    )
    token = resp.get("token") or resp.token
    url = resp.get("url") or resp.url
    # Guardar token para confirmar después
    pay = order.payment
    if pay:
        pay.external_ref = token
        db.commit()
    return f"{url}?token_ws={token}"

@router.get("/pay/return")
async def payment_return(request: Request, gateway: str, order_id: int,
                         status: Optional[str] = None,
                         token_ws: Optional[str] = None,
                         TBK_TOKEN: Optional[str] = None,
                         db=Depends(get_db)):
    """Landing page de retorno desde gateway."""
    o = db.query(Order).filter(Order.id == order_id).first()
    if not o:
        return RedirectResponse(f"/shop?payment=error&msg=orden_no_encontrada")

    # Webpay: confirmar transacción
    if gateway == "webpay":
        t = token_ws or TBK_TOKEN
        if not t or TBK_TOKEN:  # TBK_TOKEN = pago anulado/rechazado
            return RedirectResponse(f"/shop?payment=failure&order_code={o.order_code}")
        creds = _get_cfg(o.store_id, "webpay", db)
        if creds:
            try:
                from transbank.webpay.webpay_plus.transaction import Transaction
                from transbank.common.integration_type import IntegrationType
                from transbank.common.options import WebpayOptions
                env = IntegrationType.TEST if creds.get("environment","test")=="test" else IntegrationType.LIVE
                opts = WebpayOptions(creds["commerce_code"], creds["api_key"], env)
                result = Transaction.commit(token=t, options=opts)
                resp_code = result.get("response_code") if isinstance(result, dict) else result.response_code
                if resp_code == 0:
                    _confirm_order(o, db)
                    return RedirectResponse(f"/shop?payment=success&order_code={o.order_code}")
            except Exception as e:
                pass
        return RedirectResponse(f"/shop?payment=failure&order_code={o.order_code}")

    # MercadoPago: ya se confirma por webhook, solo redirect
    if gateway == "mercadopago":
        if status == "approved" or status == "success":
            _confirm_order(o, db)
            return RedirectResponse(f"/shop?payment=success&order_code={o.order_code}")
        return RedirectResponse(f"/shop?payment=failure&order_code={o.order_code}")

    # Getnet
    if gateway == "getnet":
        if status == "success":
            _confirm_order(o, db)
            return RedirectResponse(f"/shop?payment=success&order_code={o.order_code}")
        return RedirectResponse(f"/shop?payment=failure&order_code={o.order_code}")

    return RedirectResponse(f"/shop?payment=error")

# ── Getnet (Santander Chile) ──────────────────────────────────

async def _getnet_checkout(order, creds: dict, title: str, base: str) -> str:
    env_url = "https://api.getneteurope.com" if creds.get("environment","sandbox")=="production" else "https://api-sandbox.getneteurope.com"
    # Obtener token OAuth
    async with httpx.AsyncClient() as client:
        tok_resp = await client.post(f"{env_url}/v1/oauth/token",
            data={"grant_type":"client_credentials"},
            auth=(creds["client_id"], creds["client_secret"]),
            timeout=10
        )
        if tok_resp.status_code != 200:
            raise HTTPException(502, "Getnet: error de autenticación")
        access_token = tok_resp.json()["access_token"]

        # Crear sesión de pago
        payload = {
            "merchant_id": creds["merchant_id"],
            "order_id": str(order.id),
            "amount": {"total": int(order.total), "currency": "CLP"},
            "description": title,
            "callback_url": f"{base}/payments/webhook/getnet",
            "frontend_url": {
                "success": f"{base}/pay/return?gateway=getnet&order_id={order.id}&status=success",
                "failure": f"{base}/pay/return?gateway=getnet&order_id={order.id}&status=failure",
            }
        }
        pay_resp = await client.post(f"{env_url}/v1/payment-links",
            json=payload,
            headers={"Authorization": f"Bearer {access_token}"},
            timeout=10
        )
        if pay_resp.status_code not in (200, 201):
            raise HTTPException(502, f"Getnet: {pay_resp.text}")
        return pay_resp.json().get("payment_url") or pay_resp.json().get("redirect_url")

@router.post("/payments/webhook/getnet")
async def getnet_webhook(request: Request, db=Depends(get_db)):
    # Getnet sends an Authorization: Bearer header with the merchant's client_secret
    auth_header = request.headers.get("authorization","")
    bearer_token = auth_header.removeprefix("Bearer ").strip()

    body = await request.json()
    order_id = body.get("order_id")
    status = body.get("status")
    if not order_id: return {"ok": True}

    o = db.query(Order).filter(Order.id==int(order_id)).first()
    if not o: return {"ok": True}

    # Verify the token matches stored Getnet credentials for this store
    cfg = db.query(StorePaymentConfig).filter(
        StorePaymentConfig.store_id==o.store_id,
        StorePaymentConfig.gateway==GatewayType.getnet,
        StorePaymentConfig.is_active==True
    ).first()
    if cfg and cfg.credentials:
        creds = json.loads(decrypt_field(cfg.credentials))
        if bearer_token and creds.get("client_secret") != bearer_token:
            raise HTTPException(401, "Firma de webhook inválida")

    if status in ("approved","paid","success"):
        _confirm_order(o, db)
    return {"ok": True}

# ── shared confirm ────────────────────────────────────────────

def _confirm_order(o: Order, db):
    """Marca orden y pago como pagado si aún no lo está."""
    if o.payment_status == PaymentStatus.paid:
        return
    import uuid
    o.payment_status = PaymentStatus.paid
    o.status = OrderStatus.confirmed
    if not o.order_qr_token:
        o.order_qr_token = uuid.uuid4().hex
    o.updated_at = datetime.utcnow()
    if o.payment:
        o.payment.status = PaymentStatus.paid
    db.commit()
