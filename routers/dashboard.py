from fastapi import APIRouter,Depends,HTTPException
from fastapi.responses import StreamingResponse
from sqlalchemy import func
from database import (get_db,Order,OrderItem,Product,Store,PaymentStatus,OrderStatus,UserRole,StoreStaff)
from auth import get_current_user
from schemas import DashboardMetrics
from datetime import datetime,date
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
