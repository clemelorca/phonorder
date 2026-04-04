from fastapi import APIRouter,Depends,HTTPException
from database import get_db,Payment,Order,PaymentStatus,OrderStatus,Store,StoreStaff,UserRole
from auth import get_current_user
from schemas import PaymentOut
from routers.websocket import manager
import uuid

router=APIRouter(prefix="/payments",tags=["payments"])

def _chk_order(oid:int, cu, db):
    o=db.query(Order).filter(Order.id==oid).first()
    if not o: raise HTTPException(404)
    s=db.query(Store).filter(Store.id==o.store_id).first()
    if not s: raise HTTPException(404)
    if cu.role==UserRole.superadmin or s.owner_id==cu.id: return o
    if db.query(StoreStaff).filter(StoreStaff.store_id==o.store_id,StoreStaff.user_id==cu.id).first(): return o
    raise HTTPException(403)

@router.post("/{oid}/confirm",response_model=PaymentOut)
async def confirm(oid:int,db=Depends(get_db),cu=Depends(get_current_user)):
    o=_chk_order(oid,cu,db)
    pay=db.query(Payment).filter(Payment.order_id==oid).first()
    if not pay: raise HTTPException(404)
    pay.status=PaymentStatus.paid;pay.external_ref=f"MANUAL-{uuid.uuid4().hex[:12].upper()}"
    o.payment_status=PaymentStatus.paid;o.status=OrderStatus.confirmed
    if not o.order_qr_token: o.order_qr_token=uuid.uuid4().hex
    db.commit();db.refresh(pay)
    await manager.broadcast(o.store_id,{"event":"new_order","order_id":o.id,"order_code":o.order_code,"status":o.status})
    return pay

@router.post("/{oid}/fail",response_model=PaymentOut)
def fail(oid:int,db=Depends(get_db),cu=Depends(get_current_user)):
    o=_chk_order(oid,cu,db)
    pay=db.query(Payment).filter(Payment.order_id==oid).first()
    if not pay: raise HTTPException(404)
    pay.status=PaymentStatus.failed
    o.payment_status=PaymentStatus.failed;o.status=OrderStatus.cancelled
    db.commit();db.refresh(pay);return pay

@router.get("/{oid}",response_model=PaymentOut)
def get_pay(oid:int,db=Depends(get_db),cu=Depends(get_current_user)):
    o=_chk_order(oid,cu,db)
    pay=db.query(Payment).filter(Payment.order_id==oid).first()
    if not pay: raise HTTPException(404)
    return pay
