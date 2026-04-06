from fastapi import APIRouter,Depends,HTTPException
from sqlalchemy import func
from database import (get_db,Order,OrderItem,Product,Category,Store,
    PaymentStatus,OrderStatus,UserRole,StoreStaff)
from auth import get_current_user
from datetime import datetime,date,timedelta
import os,json,httpx

router=APIRouter(prefix="/stores",tags=["ai"])

def _chk(sid,cu,db):
    s=db.query(Store).filter(Store.id==sid).first()
    if not s: raise HTTPException(404)
    if cu.role==UserRole.superadmin or s.owner_id==cu.id: return
    if not db.query(StoreStaff).filter(StoreStaff.store_id==sid,StoreStaff.user_id==cu.id).first(): raise HTTPException(403)

def _build_context(sid,db):
    today=datetime.combine(date.today(),datetime.min.time())
    week_start=today-timedelta(days=6)
    month_start=datetime(today.year,today.month,1)
    s=db.query(Store).filter(Store.id==sid).first()

    # Revenue últimos 14 días
    daily=[]
    for i in range(13,-1,-1):
        d=today-timedelta(days=i)
        d_end=d+timedelta(days=1)
        rev=float(db.query(func.sum(Order.total)).filter(
            Order.store_id==sid,Order.created_at>=d,Order.created_at<d_end,
            Order.payment_status==PaymentStatus.paid).scalar() or 0)
        cnt=db.query(Order).filter(
            Order.store_id==sid,Order.created_at>=d,Order.created_at<d_end).count()
        daily.append({"fecha":d.strftime("%a %d/%m"),"revenue":round(rev),"pedidos":cnt})

    # Pedidos por día de semana (últimas 4 semanas)
    month_orders=db.query(Order).filter(Order.store_id==sid,Order.created_at>=month_start).all()
    dow_map={0:"Lunes",1:"Martes",2:"Miércoles",3:"Jueves",4:"Viernes",5:"Sábado",6:"Domingo"}
    dow_count={v:0 for v in dow_map.values()}
    dow_rev={v:0.0 for v in dow_map.values()}
    for o in month_orders:
        d=dow_map[o.created_at.weekday()]
        dow_count[d]+=1
        if o.payment_status==PaymentStatus.paid: dow_rev[d]+=o.total
    dias=[{"dia":k,"pedidos":dow_count[k],"revenue":round(dow_rev[k])} for k in dow_map.values()]

    # Horas pico (últimos 7 días)
    week_orders=db.query(Order).filter(Order.store_id==sid,Order.created_at>=week_start).all()
    hour_count={h:0 for h in range(0,24)}
    for o in week_orders: hour_count[o.created_at.hour]+=1
    peak_hours=sorted([(h,c) for h,c in hour_count.items() if c>0],key=lambda x:-x[1])[:5]

    # Top productos
    top_q=(db.query(Product.name,
        func.sum(OrderItem.qty).label("qty"),
        func.sum(OrderItem.qty*OrderItem.unit_price).label("revenue"))
        .join(OrderItem).join(Order)
        .filter(Order.store_id==sid)
        .group_by(Product.id)
        .order_by(func.sum(OrderItem.qty).desc()).limit(8).all())
    top_prods=[{"nombre":r.name,"unidades":int(r.qty),"revenue":round(float(r.revenue or 0))} for r in top_q]

    # KPIs generales
    total_orders=db.query(Order).filter(Order.store_id==sid).count()
    paid_orders=db.query(Order).filter(Order.store_id==sid,Order.payment_status==PaymentStatus.paid).count()
    total_rev=float(db.query(func.sum(Order.total)).filter(Order.store_id==sid,Order.payment_status==PaymentStatus.paid).scalar() or 0)
    cancelled=db.query(Order).filter(Order.store_id==sid,Order.status==OrderStatus.cancelled).count()
    avg_ticket=round(total_rev/paid_orders,0) if paid_orders else 0
    cancel_rate=round(cancelled/total_orders*100,1) if total_orders else 0

    # Clientes únicos y recurrentes
    phones=[o.customer_phone for o in db.query(Order).filter(Order.store_id==sid,Order.customer_phone!=None).all()]
    from collections import Counter
    phone_cnt=Counter(phones)
    repeat_customers=sum(1 for c in phone_cnt.values() if c>1)
    unique_customers=len(phone_cnt)

    return {
        "tienda":s.name,
        "plan":s.plan.value,
        "kpis":{
            "total_pedidos":total_orders,
            "pedidos_pagados":paid_orders,
            "revenue_total":round(total_rev),
            "ticket_promedio":avg_ticket,
            "tasa_cancelacion_pct":cancel_rate,
            "clientes_unicos":unique_customers,
            "clientes_recurrentes":repeat_customers,
            "pct_recurrentes":round(repeat_customers/unique_customers*100,1) if unique_customers else 0
        },
        "ultimos_14_dias":daily,
        "por_dia_semana":dias,
        "horas_pico":[{"hora":f"{h:02d}:00","pedidos":c} for h,c in peak_hours],
        "top_productos":top_prods,
    }

@router.get("/{sid}/ai-insights")
async def ai_insights(sid:int,db=Depends(get_db),cu=Depends(get_current_user)):
    _chk(sid,cu,db)
    api_key=os.getenv("GROQ_API_KEY","")
    if not api_key:
        raise HTTPException(503,"API key de IA no configurada")

    ctx=_build_context(sid,db)
    today_str=date.today().strftime("%A %d de %B de %Y")

    prompt=f"""Eres un asesor experto en restaurantes y negocios de delivery/QR. Analiza los datos reales de esta tienda y entrega insights accionables en español.

HOY: {today_str}
DATOS DE LA TIENDA:
{json.dumps(ctx, ensure_ascii=False, indent=2)}

Responde SOLO con un JSON válido con esta estructura exacta (sin markdown, sin texto extra):
{{
  "resumen_ejecutivo": "2-3 frases sobre el estado general del negocio",
  "ventas": {{
    "tendencia": "creciendo|estable|bajando",
    "insight": "observación principal sobre ventas",
    "prediccion_semana": "predicción concreta para la próxima semana",
    "accion": "1 acción específica recomendada"
  }},
  "productos": {{
    "estrella": "nombre del producto top y por qué",
    "oportunidad": "producto o categoría con potencial sin explotar",
    "accion": "1 acción específica (ej: combo, precio, promoción)"
  }},
  "operaciones": {{
    "hora_pico": "horario con más demanda y cómo prepararse",
    "dia_fuerte": "día de la semana más fuerte",
    "dia_debil": "día más flojo y qué hacer",
    "accion": "1 mejora operacional concreta"
  }},
  "clientes": {{
    "fidelizacion": "análisis de recurrencia y qué significa",
    "accion": "1 estrategia de fidelización concreta"
  }},
  "staff": {{
    "recomendacion_turnos": "cuándo necesitas más personal y cuándo menos",
    "accion": "1 ajuste de turno concreto para esta semana"
  }},
  "alerta": {{
    "tiene_alerta": true,
    "mensaje": "si hay algo urgente (tasa cancelación alta, caída de revenue, stock bajo) descríbelo; si no hay alerta pon null"
  }},
  "score_negocio": {{
    "valor": 75,
    "label": "Buen ritmo",
    "detalle": "1 frase explicando el score del 1 al 100"
  }}
}}"""

    async with httpx.AsyncClient(timeout=30) as client:
        resp=await client.post(
            "https://api.groq.com/openai/v1/chat/completions",
            headers={"Authorization":f"Bearer {api_key}","Content-Type":"application/json"},
            json={"model":"llama-3.1-8b-instant","max_tokens":1500,"temperature":0.3,
                  "messages":[{"role":"user","content":prompt}]}
        )
    if resp.status_code!=200:
        raise HTTPException(502,"Error al consultar IA")

    text=resp.json()["choices"][0]["message"]["content"].strip()
    # Limpiar posible markdown
    if text.startswith("```"): text=text.split("```")[1]; text=text[text.find("\n"):].strip()
    try:
        insights=json.loads(text)
    except Exception:
        raise HTTPException(502,"Respuesta de IA inválida")

    return {"insights":insights,"contexto_usado":ctx}
