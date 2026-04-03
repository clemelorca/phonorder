from fastapi import APIRouter,Depends,HTTPException
from database import get_db,Payment,Order,PaymentStatus,OrderStatus
from schemas import PaymentOut
import uuid

router=APIRouter(prefix="/payments",tags=["payments"])

@router.post("/{oid}/confirm",response_model=PaymentOut)
def confirm(oid:int,db=Depends(get_db)):
    pay=db.query(Payment).filter(Payment.order_id==oid).first()
    if not pay: raise HTTPException(404)
    pay.status=PaymentStatus.paid;pay.external_ref=f"WEBPAY-{uuid.uuid4().hex[:12].upper()}"
    o=db.query(Order).filter(Order.id==oid).first()
    if o: o.payment_status=PaymentStatus.paid;o.status=OrderStatus.confirmed
    db.commit();db.refresh(pay);return pay

@router.post("/{oid}/fail",response_model=PaymentOut)
def fail(oid:int,db=Depends(get_db)):
    pay=db.query(Payment).filter(Payment.order_id==oid).first()
    if not pay: raise HTTPException(404)
    pay.status=PaymentStatus.failed
    o=db.query(Order).filter(Order.id==oid).first()
    if o: o.payment_status=PaymentStatus.failed;o.status=OrderStatus.cancelled
    db.commit();db.refresh(pay);return pay

@router.get("/{oid}",response_model=PaymentOut)
def get_pay(oid:int,db=Depends(get_db)):
    pay=db.query(Payment).filter(Payment.order_id==oid).first()
    if not pay: raise HTTPException(404)
    return pay
