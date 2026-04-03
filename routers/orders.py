from fastapi import APIRouter,Depends,HTTPException
from database import (get_db,Order,OrderItem,Product,QRCode,Payment,Store,
    OrderStatus,PaymentStatus,PaymentMethod,StoreStaff,UserRole)
from auth import get_current_user
from schemas import OrderCreate,OrderOut,OrderStatusUpdate
from typing import List,Optional
from datetime import datetime

router=APIRouter(tags=["orders"])

def _chk(sid,cu,db):
    s=db.query(Store).filter(Store.id==sid).first()
    if not s: raise HTTPException(404)
    if cu.role==UserRole.superadmin or s.owner_id==cu.id: return
    if not db.query(StoreStaff).filter(StoreStaff.store_id==sid,StoreStaff.user_id==cu.id).first(): raise HTTPException(403)

@router.post("/orders",response_model=OrderOut)
def create_order(data:OrderCreate,db=Depends(get_db)):
    qr=db.query(QRCode).filter(QRCode.token==data.qr_token).first()
    if not qr: raise HTTPException(404,"QR inválido")
    total=0.0;pairs=[]
    for item in data.items:
        p=db.query(Product).filter(Product.id==item.product_id,Product.store_id==qr.store_id,Product.is_active==True).first()
        if not p: raise HTTPException(400,f"Producto {item.product_id} no disponible")
        if p.stock!=-1 and p.stock<item.qty: raise HTTPException(400,f"Stock insuficiente: {p.name}")
        total+=p.price*item.qty;pairs.append((p,item))
    o=Order(store_id=qr.store_id,qr_id=qr.id,customer_name=data.customer_name,
            customer_phone=data.customer_phone,total=total,notes=data.notes)
    db.add(o);db.flush()
    for p,item in pairs:
        db.add(OrderItem(order_id=o.id,product_id=p.id,qty=item.qty,unit_price=p.price,notes=item.notes))
        if p.stock!=-1: p.stock-=item.qty
    db.add(Payment(order_id=o.id,amount=total,method=PaymentMethod(data.payment_method),status=PaymentStatus.pending))
    db.commit();db.refresh(o);return o

@router.get("/stores/{sid}/orders",response_model=List[OrderOut])
def list_orders(sid:int,status:Optional[str]=None,db=Depends(get_db),cu=Depends(get_current_user)):
    _chk(sid,cu,db)
    q=db.query(Order).filter(Order.store_id==sid)
    if status: q=q.filter(Order.status==status)
    return q.order_by(Order.created_at.desc()).all()

@router.get("/orders/{oid}",response_model=OrderOut)
def get_order(oid:int,db=Depends(get_db)):
    o=db.query(Order).filter(Order.id==oid).first()
    if not o: raise HTTPException(404)
    return o

@router.patch("/orders/{oid}/status",response_model=OrderOut)
def upd_status(oid:int,data:OrderStatusUpdate,db=Depends(get_db),cu=Depends(get_current_user)):
    o=db.query(Order).filter(Order.id==oid).first()
    if not o: raise HTTPException(404)
    _chk(o.store_id,cu,db)
    o.status=data.status;o.updated_at=datetime.utcnow()
    db.commit();db.refresh(o);return o
