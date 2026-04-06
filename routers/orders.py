from fastapi import APIRouter,Depends,HTTPException,Request
from fastapi.responses import JSONResponse
from database import (get_db,Order,OrderItem,Product,QRCode,Payment,Store,
    OrderStatus,PaymentStatus,PaymentMethod,StoreStaff,UserRole)
from auth import get_current_user
from schemas import OrderCreate,OrderOut,OrderStatusUpdate,OrderPublicOut
from typing import List,Optional
from datetime import datetime
import random,string,qrcode,io,base64,os
from routers.websocket import manager

router=APIRouter(tags=["orders"])

def _chk(sid,cu,db):
    s=db.query(Store).filter(Store.id==sid).first()
    if not s: raise HTTPException(404)
    if cu.role==UserRole.superadmin or s.owner_id==cu.id: return
    if not db.query(StoreStaff).filter(StoreStaff.store_id==sid,StoreStaff.user_id==cu.id).first(): raise HTTPException(403)

def _gen_order_code(db):
    for _ in range(10):
        code=''.join(random.choices(string.ascii_uppercase+string.digits,k=6))
        if not db.query(Order).filter(Order.order_code==code).first(): return code
    raise HTTPException(500,"No se pudo generar código de pedido")

@router.post("/orders",response_model=OrderOut)
async def create_order(data:OrderCreate,db=Depends(get_db)):
    qr=db.query(QRCode).filter(QRCode.token==data.qr_token).first()
    if not qr: raise HTTPException(404,"QR inválido")
    total=0.0;pairs=[]
    for item in data.items:
        p=db.query(Product).filter(Product.id==item.product_id,Product.store_id==qr.store_id,Product.is_active==True).first()
        if not p: raise HTTPException(400,f"Producto {item.product_id} no disponible")
        if p.stock!=-1 and p.stock<item.qty: raise HTTPException(400,f"Stock insuficiente: {p.name}")
        total+=p.price*item.qty;pairs.append((p,item))
    tip=round(float(data.tip or 0),2)
    o=Order(store_id=qr.store_id,qr_id=qr.id,customer_name=data.customer_name,
            customer_phone=data.customer_phone,total=total+tip,tip=tip,notes=data.notes,
            order_code=_gen_order_code(db))
    db.add(o);db.flush()
    for p,item in pairs:
        db.add(OrderItem(order_id=o.id,product_id=p.id,qty=item.qty,unit_price=p.price,notes=item.notes))
        if p.stock!=-1: p.stock-=item.qty
    db.add(Payment(order_id=o.id,amount=total,method=PaymentMethod(data.payment_method),status=PaymentStatus.pending))
    db.commit();db.refresh(o)
    await manager.broadcast(o.store_id,{"event":"new_order","order_id":o.id,"order_code":o.order_code,"status":o.status.value})
    return o

@router.get("/stores/{sid}/orders",response_model=List[OrderOut])
def list_orders(sid:int,status:Optional[str]=None,phone:Optional[str]=None,
                db=Depends(get_db),cu=Depends(get_current_user)):
    _chk(sid,cu,db)
    q=db.query(Order).filter(Order.store_id==sid)
    if status: q=q.filter(Order.status==status)
    if phone: q=q.filter(Order.customer_phone==phone)
    return q.order_by(Order.created_at.desc()).all()

@router.get("/orders/{oid}",response_model=OrderOut)
def get_order(oid:int,db=Depends(get_db),cu=Depends(get_current_user)):
    o=db.query(Order).filter(Order.id==oid).first()
    if not o: raise HTTPException(404)
    _chk(o.store_id,cu,db)
    return o

@router.patch("/orders/{oid}/status",response_model=OrderOut)
async def upd_status(oid:int,data:OrderStatusUpdate,db=Depends(get_db),cu=Depends(get_current_user)):
    o=db.query(Order).filter(Order.id==oid).first()
    if not o: raise HTTPException(404)
    _chk(o.store_id,cu,db)
    o.status=data.status;o.updated_at=datetime.utcnow()
    db.commit();db.refresh(o)
    await manager.broadcast(o.store_id,{"event":"order_update","order_id":o.id,"status":o.status,"order_code":o.order_code})
    return o

# ── Endpoints públicos ─────────────────────────────────────────

@router.get("/public/stores/{sid}")
def public_store_info(sid:int,db=Depends(get_db)):
    s=db.query(Store).filter(Store.id==sid,Store.is_active==True).first()
    if not s: raise HTTPException(404)
    return {"id":s.id,"name":s.name,"description":s.description,"address":s.address,
            "logo":s.logo_b64,"promo_url":s.promo_media_url,"promo_type":s.promo_media_type}

@router.get("/public/orders/{order_code}",response_model=OrderPublicOut)
def track_order(order_code:str,db=Depends(get_db)):
    o=db.query(Order).filter(Order.order_code==order_code).first()
    if not o: raise HTTPException(404,"Pedido no encontrado")
    return o

@router.get("/public/stores/{sid}/board",response_model=List[OrderPublicOut])
def live_board(sid:int,db=Depends(get_db)):
    active=[OrderStatus.confirmed,OrderStatus.preparing,OrderStatus.ready]
    return (db.query(Order)
              .filter(Order.store_id==sid,Order.status.in_(active),
                      Order.payment_status==PaymentStatus.paid,Order.order_code!=None)
              .order_by(Order.created_at.asc()).all())

@router.get("/deliver-qr/{token}")
def order_delivery_qr(token:str,request:Request,db=Depends(get_db)):
    o=db.query(Order).filter(Order.order_qr_token==token).first()
    if not o: raise HTTPException(404,"QR inválido")
    base=os.getenv("BASE_URL",str(request.base_url).rstrip("/"))
    url=f"{base}/deliver?token={token}"
    q=qrcode.QRCode(box_size=6,border=2);q.add_data(url);q.make(fit=True)
    img=q.make_image(fill_color="black",back_color="white")
    buf=io.BytesIO();img.save(buf,format="PNG")
    b64=base64.b64encode(buf.getvalue()).decode()
    return {"qr_b64":b64,"order_code":o.order_code,"url":url}

@router.post("/orders/deliver/{token}",response_model=OrderOut)
async def deliver_order(token:str,db=Depends(get_db),cu=Depends(get_current_user)):
    o=db.query(Order).filter(Order.order_qr_token==token).first()
    if not o: raise HTTPException(404,"QR de pedido inválido")
    # Verificar que el usuario tiene acceso a esta tienda
    from database import StoreStaff,UserRole
    s=db.query(Store).filter(Store.id==o.store_id).first()
    if cu.role!=UserRole.superadmin and s.owner_id!=cu.id:
        if not db.query(StoreStaff).filter(StoreStaff.store_id==o.store_id,StoreStaff.user_id==cu.id).first():
            raise HTTPException(403,"Sin permiso para esta tienda")
    if o.status==OrderStatus.delivered: raise HTTPException(400,"Pedido ya entregado")
    if o.status!=OrderStatus.ready: raise HTTPException(400,"El pedido no está listo para entrega")
    o.status=OrderStatus.delivered;o.updated_at=datetime.utcnow()
    db.commit();db.refresh(o)
    await manager.broadcast(o.store_id,{"event":"order_update","order_id":o.id,"status":o.status,"order_code":o.order_code})
    return o
