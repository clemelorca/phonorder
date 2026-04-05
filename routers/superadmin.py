from fastapi import APIRouter,Depends,HTTPException
from fastapi.responses import StreamingResponse
from sqlalchemy import func, distinct
import csv, io
from database import (get_db,User,Store,Order,Subscription,UserRole,PaymentStatus,
    Plan,SubStatus,GatewayType,StorePaymentConfig,OrderStatus,SubStatus,SalesLead,LeadStatus,SystemConfig)
from auth import require_superadmin,hash_password
from schemas import UserCreate,UserUpdate,UserOut,StoreUpdate
from typing import List,Optional
from datetime import datetime,date,timedelta
from pydantic import BaseModel

class SubUpsert(BaseModel):
    plan:str;status:str;price_monthly:float
    next_billing:Optional[str]=None
    card_last4:Optional[str]=None
    card_brand:Optional[str]=None
    notes:Optional[str]=None

router=APIRouter(prefix="/superadmin",tags=["superadmin"])

@router.get("/stats")
def stats(db=Depends(get_db),_=Depends(require_superadmin)):
    today=datetime.combine(date.today(),datetime.min.time())
    first_month=datetime(today.year,today.month,1)
    first_prev_month=(first_month-timedelta(days=1)).replace(day=1)

    # ── órdenes base ──
    total_orders=db.query(Order).count()
    paid_orders=db.query(Order).filter(Order.payment_status==PaymentStatus.paid).count()
    total_revenue=float(db.query(func.sum(Order.total)).filter(Order.payment_status==PaymentStatus.paid).scalar() or 0)

    # ── ticket promedio y conversión ──
    avg_ticket=round(total_revenue/paid_orders,0) if paid_orders else 0
    conversion_rate=round(paid_orders/total_orders*100,1) if total_orders else 0

    # ── actividad este mes ──
    new_stores_month=db.query(Store).filter(Store.created_at>=first_month).count()
    new_admins_month=db.query(User).filter(User.role==UserRole.admin,User.created_at>=first_month).count()
    new_stores_prev_month=db.query(Store).filter(Store.created_at>=first_prev_month,Store.created_at<first_month).count()

    # ── MRR (suscripciones activas) ──
    mrr=float(db.query(func.sum(Subscription.price_monthly)).filter(
        Subscription.status.in_([SubStatus.active,SubStatus.trial])).scalar() or 0)
    arr=round(mrr*12,0)

    # ── Churn Rate ──────────────────────────────────────────────
    # Canceladas este mes / total subs activas al inicio del mes
    total_subs=db.query(Subscription).count()
    cancelled_subs=db.query(Subscription).filter(Subscription.status==SubStatus.cancelled).count()
    active_subs=db.query(Subscription).filter(Subscription.status==SubStatus.active).count()
    past_due_subs=db.query(Subscription).filter(Subscription.status==SubStatus.past_due).count()
    # Churn = cancelled / total ever
    churn_rate=round(cancelled_subs/total_subs*100,1) if total_subs else 0
    retention_rate=round(100-churn_rate,1)

    # ── Crecimiento mensual ──────────────────────────────────────
    # Tiendas: (nuevas este mes - nuevas mes anterior) / max(nuevas mes anterior,1)
    store_growth_rate=round((new_stores_month-new_stores_prev_month)/max(new_stores_prev_month,1)*100,1)
    # Revenue: este mes vs mes anterior
    revenue_month=float(db.query(func.sum(Order.total)).filter(
        Order.created_at>=first_month,Order.payment_status==PaymentStatus.paid).scalar() or 0)
    revenue_prev_month=float(db.query(func.sum(Order.total)).filter(
        Order.created_at>=first_prev_month,Order.created_at<first_month,
        Order.payment_status==PaymentStatus.paid).scalar() or 0)
    revenue_growth_rate=round((revenue_month-revenue_prev_month)/max(revenue_prev_month,1)*100,1)

    # ── DAU / MAU ────────────────────────────────────────────────
    # Usando pedidos como proxy de actividad de usuarios finales
    dau=db.query(func.count(distinct(Order.customer_phone))).filter(
        Order.created_at>=today,Order.customer_phone.isnot(None)).scalar() or 0
    mau=db.query(func.count(distinct(Order.customer_phone))).filter(
        Order.created_at>=first_month,Order.customer_phone.isnot(None)).scalar() or 0
    # DAU de tiendas (stores con pedidos hoy)
    dau_stores=db.query(func.count(distinct(Order.store_id))).filter(Order.created_at>=today).scalar() or 0
    mau_stores=db.query(func.count(distinct(Order.store_id))).filter(Order.created_at>=first_month).scalar() or 0

    # ── LTV estimado ─────────────────────────────────────────────
    # LTV = avg_ticket * promedio_ordenes_por_cliente
    # Para subs de pago: LTV = avg_price_monthly * (1 / churn_rate_mensual)
    # Como proxy usamos: ingresos totales / clientes únicos
    total_unique_customers=db.query(func.count(distinct(Order.customer_phone))).filter(
        Order.customer_phone.isnot(None)).scalar() or 0
    ltv_estimated=round(total_revenue/total_unique_customers,0) if total_unique_customers else 0
    # LTV de suscripción: precio promedio / churn_rate_mensual
    avg_sub_price=float(db.query(func.avg(Subscription.price_monthly)).filter(
        Subscription.price_monthly>0).scalar() or 0)
    # Churn mensual aproximado (si churn_rate es total, asumimos vida promedio)
    churn_monthly=churn_rate/100  # fracción mensual aproximada
    ltv_subscription=round(avg_sub_price/churn_monthly,0) if churn_monthly>0 else 0

    # ── distribución de estados de pedidos ──
    order_status_stats=[]
    for st in OrderStatus:
        c=db.query(Order).filter(Order.status==st).count()
        order_status_stats.append({"status":st.value,"count":c})

    # ── gateways conectados por tienda ──
    gateway_stats={}
    for gw in GatewayType:
        configured=db.query(StorePaymentConfig).filter(
            StorePaymentConfig.gateway==gw,
            StorePaymentConfig.credentials.isnot(None)
        ).count()
        active=db.query(StorePaymentConfig).filter(
            StorePaymentConfig.gateway==gw,
            StorePaymentConfig.is_active==True,
            StorePaymentConfig.credentials.isnot(None)
        ).count()
        gateway_stats[gw.value]={"configured":configured,"active":active}

    # ── per-plan stats + comisiones ──
    COMMISSION_RATES={"starter":0.02,"negocio":0.015,"cadena":0.0}
    plan_stats=[]
    commission_total=0.0
    commission_month=0.0
    commission_today_val=0.0
    for plan in Plan:
        stores_in_plan=db.query(Store).filter(Store.plan==plan,Store.is_active==True).all()
        sids=[s.id for s in stores_in_plan]
        rate=COMMISSION_RATES.get(plan.value,0.0)
        rev=float(db.query(func.sum(Order.total)).filter(Order.store_id.in_(sids),Order.payment_status==PaymentStatus.paid).scalar() or 0) if sids else 0.0
        rev_month=float(db.query(func.sum(Order.total)).filter(Order.store_id.in_(sids),Order.created_at>=first_month,Order.payment_status==PaymentStatus.paid).scalar() or 0) if sids else 0.0
        rev_today=float(db.query(func.sum(Order.total)).filter(Order.store_id.in_(sids),Order.created_at>=today,Order.payment_status==PaymentStatus.paid).scalar() or 0) if sids else 0.0
        orders_count=db.query(Order).filter(Order.store_id.in_(sids)).count() if sids else 0
        commission_total+=rev*rate
        commission_month+=rev_month*rate
        commission_today_val+=rev_today*rate
        plan_stats.append({"plan":plan.value,"stores":len(stores_in_plan),"revenue":float(rev),"revenue_month":rev_month,"orders":orders_count,"commission_rate":rate})

    # ── Desglose comisión por gateway ─────────────────────────────
    COMMISSION_RATES_SA={"starter":0.02,"negocio":0.015,"cadena":0.0}
    mp_sid_set=set(
        r.store_id for r in db.query(StorePaymentConfig).filter(
            StorePaymentConfig.gateway==GatewayType.mercadopago,
            StorePaymentConfig.is_active==True,
            StorePaymentConfig.credentials.isnot(None)
        ).all()
    )
    commission_mp_month=0.0
    for plan in Plan:
        rate=COMMISSION_RATES_SA.get(plan.value,0.0)
        if rate==0: continue
        sids=[s.id for s in db.query(Store).filter(Store.plan==plan,Store.is_active==True).all() if s.id in mp_sid_set]
        if sids:
            rev=float(db.query(func.sum(Order.total)).filter(
                Order.store_id.in_(sids),Order.created_at>=first_month,
                Order.payment_status==PaymentStatus.paid).scalar() or 0)
            commission_mp_month+=rev*rate
    mp_mktplace_cfg=db.query(SystemConfig).filter(SystemConfig.key=="mp_marketplace_id").first()
    marketplace_configured=bool(mp_mktplace_cfg and mp_mktplace_cfg.value)

    # ── top 5 stores by revenue ──
    top_q=(db.query(Store.id,Store.name,func.sum(Order.total).label("rev"),func.count(Order.id).label("cnt"))
        .join(Order,Order.store_id==Store.id)
        .filter(Order.payment_status==PaymentStatus.paid)
        .group_by(Store.id).order_by(func.sum(Order.total).desc()).limit(5).all())
    top_stores=[{"id":r.id,"name":r.name,"revenue":float(r.rev or 0),"orders":r.cnt} for r in top_q]

    return {
        # ── Base ──
        "total_admins":db.query(User).filter(User.role==UserRole.admin).count(),
        "active_admins":db.query(User).filter(User.role==UserRole.admin,User.is_active==True).count(),
        "total_stores":db.query(Store).count(),
        "active_stores":db.query(Store).filter(Store.is_active==True).count(),
        "total_orders":total_orders,
        "total_revenue":total_revenue,
        "orders_today":db.query(Order).filter(Order.created_at>=today).count(),
        "revenue_today":float(db.query(func.sum(Order.total)).filter(Order.created_at>=today,Order.payment_status==PaymentStatus.paid).scalar() or 0),
        "orders_month":db.query(Order).filter(Order.created_at>=first_month).count(),
        "revenue_month":revenue_month,
        "avg_ticket":avg_ticket,
        "conversion_rate":conversion_rate,
        "new_stores_month":new_stores_month,
        "new_admins_month":new_admins_month,
        # ── Ingresos recurrentes (SaaS fijo) ──
        "mrr":mrr,
        "arr":arr,
        # ── Comisiones por ventas ──
        "commission_total":round(commission_total,0),
        "commission_month":round(commission_month,0),
        "commission_today":round(commission_today_val,0),
        # ── Desglose por gateway ──
        "commission_mp_month":round(commission_mp_month,0),
        "commission_nonmp_month":round(commission_month-commission_mp_month,0),
        "marketplace_configured":marketplace_configured,
        # ── Totales combinados (SaaS + comisiones) ──
        "total_monthly_projected":round(mrr+commission_month,0),
        "total_annual_projected":round(arr+commission_total,0),
        # ── Crecimiento ──
        "store_growth_rate":store_growth_rate,         # % crecimiento tiendas vs mes anterior
        "revenue_growth_rate":revenue_growth_rate,     # % crecimiento revenue vs mes anterior
        # ── Retención y churn ──
        "churn_rate":churn_rate,                       # % subs canceladas sobre total
        "retention_rate":retention_rate,               # 1 - churn
        "active_subs":active_subs,
        "cancelled_subs":cancelled_subs,
        "past_due_subs":past_due_subs,
        "total_subs":total_subs,
        # ── DAU / MAU ──
        "dau":dau,                                     # clientes únicos con pedido hoy
        "mau":mau,                                     # clientes únicos con pedido este mes
        "dau_stores":dau_stores,                       # tiendas con pedidos hoy
        "mau_stores":mau_stores,                       # tiendas activas este mes
        # ── LTV ──
        "ltv_estimated":ltv_estimated,                 # ingresos totales / clientes únicos
        "ltv_subscription":ltv_subscription,           # precio_mensual_promedio / churn_mensual
        "avg_sub_price":round(avg_sub_price,0),        # precio promedio plan de pago
        # ── Notas métricas no calculables sin datos externos ──
        # CAC y Burn Rate requieren datos de inversión/costos → configurar manualmente
        "cac_note":"Requiere datos de inversión en adquisición (no disponibles automáticamente)",
        "burn_rate_note":"Requiere datos de costos operacionales (no disponibles automáticamente)",
        # ── Distribución ──
        "order_status_stats":order_status_stats,
        "gateway_stats":gateway_stats,
        "plan_stats":plan_stats,
        "top_stores":top_stores,
    }

@router.get("/stats/export")
def export_stats(db=Depends(get_db),_=Depends(require_superadmin)):
    """Exporta el resumen del dashboard en formato CSV (compatible con Excel)."""
    from datetime import date
    today_dt=datetime.combine(date.today(),datetime.min.time())
    first_month=datetime(today_dt.year,today_dt.month,1)

    total_orders=db.query(Order).count()
    paid_orders=db.query(Order).filter(Order.payment_status==PaymentStatus.paid).count()
    total_revenue=float(db.query(func.sum(Order.total)).filter(Order.payment_status==PaymentStatus.paid).scalar() or 0)
    avg_ticket=round(total_revenue/paid_orders,0) if paid_orders else 0
    mrr=float(db.query(func.sum(Subscription.price_monthly)).filter(Subscription.status.in_([SubStatus.active,SubStatus.trial])).scalar() or 0)

    COMMISSION_RATES_EXP={"starter":0.02,"negocio":0.015,"cadena":0.0}
    commission_total=0.0; commission_month=0.0
    plan_rows=[]
    for plan in Plan:
        stores_in_plan=db.query(Store).filter(Store.plan==plan,Store.is_active==True).all()
        sids=[s.id for s in stores_in_plan]
        rate=COMMISSION_RATES_EXP.get(plan.value,0.0)
        rev=float(db.query(func.sum(Order.total)).filter(Order.store_id.in_(sids),Order.payment_status==PaymentStatus.paid).scalar() or 0) if sids else 0.0
        rev_m=float(db.query(func.sum(Order.total)).filter(Order.store_id.in_(sids),Order.created_at>=first_month,Order.payment_status==PaymentStatus.paid).scalar() or 0) if sids else 0.0
        commission_total+=rev*rate; commission_month+=rev_m*rate
        plan_rows.append((plan.value,len(stores_in_plan),rev,rev_m,rate*100))

    subs=db.query(Subscription).all()
    stores_all=db.query(Store).filter(Store.is_active==True).all()

    output=io.StringIO()
    w=csv.writer(output)

    # ── Resumen General ──
    w.writerow(["=== RESUMEN GENERAL ==="])
    w.writerow(["Fecha exportación",datetime.utcnow().strftime("%Y-%m-%d %H:%M UTC")])
    w.writerow([])
    w.writerow(["MÉTRICA","VALOR"])
    w.writerow(["Tiendas activas",db.query(Store).filter(Store.is_active==True).count()])
    w.writerow(["Admins activos",db.query(User).filter(User.role==UserRole.admin,User.is_active==True).count()])
    w.writerow(["Total pedidos",total_orders])
    w.writerow(["Pedidos pagados",paid_orders])
    w.writerow(["Revenue total (CLP)",int(total_revenue)])
    w.writerow(["Ticket promedio (CLP)",int(avg_ticket)])
    w.writerow([])

    # ── Ingresos Recurrentes ──
    w.writerow(["=== INGRESOS RECURRENTES (SaaS) ==="])
    w.writerow(["MÉTRICA","VALOR"])
    w.writerow(["MRR SaaS (CLP)",int(mrr)])
    w.writerow(["ARR SaaS (CLP)",int(mrr*12)])
    w.writerow(["Comisiones este mes (CLP)",int(commission_month)])
    w.writerow(["Comisiones históricas (CLP)",int(commission_total)])
    w.writerow(["Total proyectado mes (CLP)",int(mrr+commission_month)])
    w.writerow(["Total proyectado año (CLP)",int(mrr*12+commission_total)])
    w.writerow([])

    # ── Por Plan ──
    w.writerow(["=== DISTRIBUCIÓN POR PLAN ==="])
    w.writerow(["PLAN","TIENDAS","REVENUE TOTAL (CLP)","REVENUE ESTE MES (CLP)","COMISIÓN %"])
    for r in plan_rows:
        w.writerow([r[0],r[1],int(r[2]),int(r[3]),f"{r[4]}%"])
    w.writerow([])

    # ── Suscripciones ──
    w.writerow(["=== SUSCRIPCIONES ==="])
    w.writerow(["TIENDA","PLAN","ESTADO","PRECIO MENSUAL (CLP)","PRÓXIMO COBRO"])
    for s in subs:
        store=db.query(Store).filter(Store.id==s.store_id).first()
        w.writerow([store.name if store else s.store_id,s.plan.value,s.status.value,int(s.price_monthly),s.next_billing.strftime("%Y-%m-%d") if s.next_billing else ""])
    w.writerow([])

    # ── Tiendas ──
    w.writerow(["=== TIENDAS ACTIVAS ==="])
    w.writerow(["ID","NOMBRE","PLAN","DIRECCIÓN","CREADA"])
    for s in stores_all:
        w.writerow([s.id,s.name,s.plan.value,s.address or "",s.created_at.strftime("%Y-%m-%d")])

    output.seek(0)
    filename=f"skanorder_dashboard_{date.today().strftime('%Y%m%d')}.csv"
    return StreamingResponse(
        iter([output.getvalue().encode('utf-8-sig')]),  # utf-8-sig para Excel en Windows
        media_type="text/csv",
        headers={"Content-Disposition":f"attachment; filename={filename}"}
    )

@router.get("/admins",response_model=List[UserOut])
def list_admins(db=Depends(get_db),_=Depends(require_superadmin)):
    return db.query(User).filter(User.role==UserRole.admin).order_by(User.created_at.desc()).all()

@router.post("/admins",response_model=UserOut)
def create_admin(data:UserCreate,db=Depends(get_db),_=Depends(require_superadmin)):
    if db.query(User).filter(User.email==data.email).first(): raise HTTPException(400,"Email ya registrado")
    u=User(name=data.name,email=data.email,password_hash=hash_password(data.password),role=UserRole.admin,phone=data.phone)
    db.add(u);db.commit();db.refresh(u);return u

@router.patch("/admins/{uid}",response_model=UserOut)
def update_admin(uid:int,data:UserUpdate,db=Depends(get_db),_=Depends(require_superadmin)):
    u=db.query(User).filter(User.id==uid).first()
    if not u: raise HTTPException(404)
    for k,v in data.model_dump(exclude_none=True).items():
        if k=="password": u.password_hash=hash_password(v)
        else: setattr(u,k,v)
    db.commit();db.refresh(u);return u

@router.delete("/admins/{uid}")
def delete_admin(uid:int,db=Depends(get_db),_=Depends(require_superadmin)):
    u=db.query(User).filter(User.id==uid).first()
    if not u: raise HTTPException(404)
    if u.role==UserRole.superadmin: raise HTTPException(403,"No se puede eliminar superadmin")
    db.delete(u);db.commit();return {"ok":True}

@router.get("/stores")
def all_stores(db=Depends(get_db),_=Depends(require_superadmin)):
    stores=db.query(Store).order_by(Store.created_at.desc()).all()
    result=[]
    for s in stores:
        owner=db.query(User).filter(User.id==s.owner_id).first()
        orders_count=db.query(Order).filter(Order.store_id==s.id).count()
        rev=float(db.query(func.sum(Order.total)).filter(Order.store_id==s.id,Order.payment_status==PaymentStatus.paid).scalar() or 0)
        result.append({
            "id":s.id,"name":s.name,"description":s.description,"address":s.address,
            "plan":s.plan.value if s.plan else "starter","is_active":s.is_active,
            "created_at":s.created_at.isoformat(),
            "owner_id":s.owner_id,
            "owner_name":owner.name if owner else "—",
            "owner_email":owner.email if owner else "—",
            "owner_active":owner.is_active if owner else False,
            "promo_media_url":s.promo_media_url,"promo_media_type":s.promo_media_type,
            "orders_count":orders_count,"revenue":rev
        })
    return result

@router.patch("/stores/{sid}")
def update_store_sa(sid:int,data:StoreUpdate,db=Depends(get_db),_=Depends(require_superadmin)):
    s=db.query(Store).filter(Store.id==sid).first()
    if not s: raise HTTPException(404)
    for k,v in data.model_dump(exclude_none=True).items(): setattr(s,k,v)
    db.commit();db.refresh(s);return {"ok":True}

@router.delete("/stores/{sid}")
def delete_store_sa(sid:int,db=Depends(get_db),_=Depends(require_superadmin)):
    s=db.query(Store).filter(Store.id==sid).first()
    if not s: raise HTTPException(404)
    db.delete(s);db.commit();return {"ok":True}

# ── Suscripciones ────────────────────────────────────────────

@router.get("/subscriptions")
def list_subscriptions(db=Depends(get_db),_=Depends(require_superadmin)):
    subs=db.query(Subscription).all()
    result=[]
    for sub in subs:
        store=db.query(Store).filter(Store.id==sub.store_id).first()
        owner=db.query(User).filter(User.id==store.owner_id).first() if store else None
        result.append({
            "id":sub.id,"store_id":sub.store_id,
            "store_name":store.name if store else "—",
            "owner_id":owner.id if owner else None,
            "owner_name":owner.name if owner else "—",
            "owner_email":owner.email if owner else "—",
            "plan":sub.plan.value,"status":sub.status.value,
            "price_monthly":sub.price_monthly,
            "started_at":sub.started_at.isoformat() if sub.started_at else None,
            "next_billing":sub.next_billing.isoformat() if sub.next_billing else None,
            "card_last4":sub.card_last4,"card_brand":sub.card_brand,"notes":sub.notes,
            "store_active":store.is_active if store else False,
        })
    return result

@router.put("/stores/{sid}/subscription")
def upsert_subscription(sid:int,data:SubUpsert,db=Depends(get_db),_=Depends(require_superadmin)):
    s=db.query(Store).filter(Store.id==sid).first()
    if not s: raise HTTPException(404)
    sub=db.query(Subscription).filter(Subscription.store_id==sid).first()
    nb=datetime.fromisoformat(data.next_billing) if data.next_billing else None
    if not sub:
        sub=Subscription(store_id=sid,plan=Plan(data.plan),status=SubStatus(data.status),
            price_monthly=data.price_monthly,next_billing=nb,
            card_last4=data.card_last4,card_brand=data.card_brand,notes=data.notes)
        db.add(sub)
    else:
        sub.plan=Plan(data.plan);sub.status=SubStatus(data.status)
        sub.price_monthly=data.price_monthly;sub.next_billing=nb
        sub.card_last4=data.card_last4;sub.card_brand=data.card_brand;sub.notes=data.notes
    # Sync plan on store
    s.plan=Plan(data.plan)
    db.commit();db.refresh(sub)
    return {"ok":True}

@router.delete("/stores/{sid}/subscription")
def cancel_subscription(sid:int,db=Depends(get_db),_=Depends(require_superadmin)):
    sub=db.query(Subscription).filter(Subscription.store_id==sid).first()
    if not sub: raise HTTPException(404)
    sub.status=SubStatus.cancelled;db.commit();return {"ok":True}

# ── Marketplace config ───────────────────────────────────────

class MarketplaceConfigIn(BaseModel):
    mp_marketplace_id: str

@router.get("/marketplace-config")
def get_marketplace_config(db=Depends(get_db),_=Depends(require_superadmin)):
    cfg=db.query(SystemConfig).filter(SystemConfig.key=="mp_marketplace_id").first()
    return {"mp_marketplace_id":cfg.value if cfg and cfg.value else None,
            "configured":bool(cfg and cfg.value)}

@router.put("/marketplace-config")
def set_marketplace_config(data:MarketplaceConfigIn,db=Depends(get_db),_=Depends(require_superadmin)):
    cfg=db.query(SystemConfig).filter(SystemConfig.key=="mp_marketplace_id").first()
    if cfg:
        cfg.value=data.mp_marketplace_id
    else:
        cfg=SystemConfig(key="mp_marketplace_id",value=data.mp_marketplace_id)
        db.add(cfg)
    db.commit()
    return {"ok":True}

# ── Plan Leads (solicitudes plan Cadena) ─────────────────────

class LeadQuoteIn(BaseModel):
    quoted_price: float

@router.get("/plan-leads")
def list_plan_leads(db=Depends(get_db),_=Depends(require_superadmin)):
    leads=db.query(SalesLead).order_by(SalesLead.created_at.desc()).all()
    return [{"id":l.id,"store_id":l.store_id,"store_name":l.store.name,
             "contact_name":l.contact_name,"contact_email":l.contact_email,
             "contact_phone":l.contact_phone,"message":l.message,
             "status":l.status,"quoted_price":l.quoted_price,
             "created_at":l.created_at.isoformat()} for l in leads]

@router.patch("/plan-leads/{lead_id}")
def quote_plan_lead(lead_id:int,data:LeadQuoteIn,db=Depends(get_db),_=Depends(require_superadmin)):
    lead=db.query(SalesLead).filter(SalesLead.id==lead_id).first()
    if not lead: raise HTTPException(404)
    lead.quoted_price=data.quoted_price
    lead.status=LeadStatus.quoted
    db.commit()
    return {"ok":True}
