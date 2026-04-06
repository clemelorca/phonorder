from fastapi import APIRouter,Depends,HTTPException
from fastapi.responses import StreamingResponse
from sqlalchemy import func
from database import (get_db,Order,OrderItem,Product,Category,Store,PaymentStatus,OrderStatus,UserRole,StoreStaff)
from auth import get_current_user
from schemas import DashboardMetrics
from datetime import datetime,date,timedelta
import csv,io

router=APIRouter(prefix="/dashboard",tags=["dashboard"])

def _chk(sid,cu,db):
    s=db.query(Store).filter(Store.id==sid).first()
    if not s: raise HTTPException(404)
    if cu.role==UserRole.superadmin or s.owner_id==cu.id: return
    if not db.query(StoreStaff).filter(StoreStaff.store_id==sid,StoreStaff.user_id==cu.id).first(): raise HTTPException(403)

@router.get("/stores/{sid}",response_model=DashboardMetrics)
def metrics(sid:int,db=Depends(get_db),cu=Depends(get_current_user)):
    _chk(sid,cu,db)
    today=datetime.combine(date.today(),datetime.min.time())
    active=[OrderStatus.confirmed,OrderStatus.preparing,OrderStatus.ready]
    top=db.query(Product.name,func.sum(OrderItem.qty).label("q")).join(OrderItem).join(Order).filter(Order.store_id==sid).group_by(Product.id).order_by(func.sum(OrderItem.qty).desc()).limit(5).all()
    return DashboardMetrics(
        orders_today=db.query(Order).filter(Order.store_id==sid,Order.created_at>=today).count(),
        revenue_today=db.query(func.sum(Order.total)).filter(Order.store_id==sid,Order.created_at>=today,Order.payment_status==PaymentStatus.paid).scalar() or 0,
        orders_active=db.query(Order).filter(Order.store_id==sid,Order.status.in_(active)).count(),
        orders_total=db.query(Order).filter(Order.store_id==sid).count(),
        revenue_total=db.query(func.sum(Order.total)).filter(Order.store_id==sid,Order.payment_status==PaymentStatus.paid).scalar() or 0,
        top_products=[{"name":r.name,"qty":int(r.q)} for r in top],
        orders_by_status={s.value:db.query(Order).filter(Order.store_id==sid,Order.status==s).count() for s in OrderStatus})

@router.get("/stores/{sid}/analytics")
def analytics(sid:int,db=Depends(get_db),cu=Depends(get_current_user)):
    _chk(sid,cu,db)
    today=datetime.combine(date.today(),datetime.min.time())
    week_start=today-timedelta(days=6)
    month_start=datetime(today.year,today.month,1)

    # Tendencia: últimos 7 días
    revenue_7days=[]
    for i in range(6,-1,-1):
        d=today-timedelta(days=i)
        d_end=d+timedelta(days=1)
        rev=float(db.query(func.sum(Order.total)).filter(
            Order.store_id==sid,Order.created_at>=d,Order.created_at<d_end,
            Order.payment_status==PaymentStatus.paid).scalar() or 0)
        cnt=db.query(Order).filter(
            Order.store_id==sid,Order.created_at>=d,Order.created_at<d_end).count()
        revenue_7days.append({"date":d.strftime("%d/%m"),"revenue":rev,"orders":cnt})

    # KPIs semana/mes
    revenue_week=float(db.query(func.sum(Order.total)).filter(
        Order.store_id==sid,Order.created_at>=week_start,
        Order.payment_status==PaymentStatus.paid).scalar() or 0)
    orders_week=db.query(Order).filter(Order.store_id==sid,Order.created_at>=week_start).count()
    revenue_month=float(db.query(func.sum(Order.total)).filter(
        Order.store_id==sid,Order.created_at>=month_start,
        Order.payment_status==PaymentStatus.paid).scalar() or 0)
    orders_month=db.query(Order).filter(Order.store_id==sid,Order.created_at>=month_start).count()

    # Ticket promedio
    paid_count=db.query(Order).filter(Order.store_id==sid,Order.payment_status==PaymentStatus.paid).count()
    total_rev=float(db.query(func.sum(Order.total)).filter(
        Order.store_id==sid,Order.payment_status==PaymentStatus.paid).scalar() or 0)
    avg_ticket=round(total_rev/paid_count,0) if paid_count else 0

    # Pedidos por hora (últimos 7 días)
    recent=db.query(Order).filter(Order.store_id==sid,Order.created_at>=week_start).all()
    hour_map={h:0 for h in range(0,24)}
    for o in recent: hour_map[o.created_at.hour]+=1
    orders_by_hour=[{"hour":h,"count":hour_map[h]} for h in range(0,24)]

    # Tasa cancelación
    total_all=db.query(Order).filter(Order.store_id==sid).count()
    cancelled=db.query(Order).filter(Order.store_id==sid,Order.status==OrderStatus.cancelled).count()
    cancellation_rate=round(cancelled/total_all*100,1) if total_all else 0

    # Top productos por revenue
    top_q=(db.query(Product.name,
        func.sum(OrderItem.qty).label("qty"),
        func.sum(OrderItem.qty*OrderItem.unit_price).label("revenue"))
        .join(OrderItem).join(Order)
        .filter(Order.store_id==sid,Order.payment_status==PaymentStatus.paid)
        .group_by(Product.id)
        .order_by(func.sum(OrderItem.qty*OrderItem.unit_price).desc()).limit(6).all())
    top_products=[{"name":r.name,"qty":int(r.qty),"revenue":float(r.revenue or 0)} for r in top_q]

    # Top categorías
    cat_q=(db.query(Category.name,
        func.count(Order.id).label("orders"),
        func.sum(OrderItem.qty*OrderItem.unit_price).label("revenue"))
        .join(Product,Product.category_id==Category.id)
        .join(OrderItem,OrderItem.product_id==Product.id)
        .join(Order,Order.id==OrderItem.order_id)
        .filter(Order.store_id==sid,Order.payment_status==PaymentStatus.paid)
        .group_by(Category.id)
        .order_by(func.sum(OrderItem.qty*OrderItem.unit_price).desc()).limit(5).all())
    top_categories=[{"name":r.name,"orders":r.orders,"revenue":float(r.revenue or 0)} for r in cat_q]

    tips_today=float(db.query(func.sum(Order.tip)).filter(Order.store_id==sid,Order.created_at>=today,Order.payment_status==PaymentStatus.paid).scalar() or 0)
    tips_month=float(db.query(func.sum(Order.tip)).filter(Order.store_id==sid,Order.created_at>=month_start,Order.payment_status==PaymentStatus.paid).scalar() or 0)
    tips_total=float(db.query(func.sum(Order.tip)).filter(Order.store_id==sid,Order.payment_status==PaymentStatus.paid).scalar() or 0)

    return {
        "revenue_7days":revenue_7days,
        "avg_ticket":avg_ticket,
        "tips_today":tips_today,
        "tips_month":tips_month,
        "tips_total":tips_total,
        "revenue_week":revenue_week,
        "orders_week":orders_week,
        "revenue_month":revenue_month,
        "orders_month":orders_month,
        "orders_by_hour":orders_by_hour,
        "cancellation_rate":cancellation_rate,
        "top_products":top_products,
        "top_categories":top_categories,
    }

@router.get("/stores/{sid}/customers")
def customers(sid:int,db=Depends(get_db),cu=Depends(get_current_user)):
    _chk(sid,cu,db)
    orders=db.query(Order).filter(Order.store_id==sid).order_by(Order.created_at.asc()).all()
    by_phone={}
    for o in orders:
        key=o.customer_phone or f"anon_{o.id}"
        if key not in by_phone:
            by_phone[key]={
                "name":o.customer_name or "Sin nombre","phone":o.customer_phone or "—",
                "orders":0,"total_spent":0.0,
                "first_order":o.created_at,"last_order":o.created_at,
            }
        c=by_phone[key]
        c["orders"]+=1
        if o.payment_status==PaymentStatus.paid: c["total_spent"]+=o.total
        if o.created_at>c["last_order"]:
            c["last_order"]=o.created_at
            if o.customer_name: c["name"]=o.customer_name
    result=sorted(by_phone.values(),key=lambda x:x["total_spent"],reverse=True)
    for r in result:
        r["first_order"]=r["first_order"].isoformat()
        r["last_order"]=r["last_order"].isoformat()
    return result

@router.get("/stores/{sid}/csv")
def export_csv(sid:int,db=Depends(get_db),cu=Depends(get_current_user)):
    _chk(sid,cu,db)
    orders=db.query(Order).filter(Order.store_id==sid).order_by(Order.created_at.desc()).all()
    buf=io.StringIO();w=csv.writer(buf)
    w.writerow(["id","cliente","telefono","total","estado","pago","fecha"])
    for o in orders: w.writerow([o.id,o.customer_name or "",o.customer_phone or "",o.total,o.status.value,o.payment_status.value,o.created_at.isoformat()])
    buf.seek(0)
    return StreamingResponse(io.BytesIO(buf.read().encode("utf-8-sig")),media_type="text/csv",
        headers={"Content-Disposition":f"attachment; filename=orders_{sid}.csv"})
