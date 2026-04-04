from fastapi import APIRouter,Depends,HTTPException
from database import get_db,User,Store,Subscription,SubStatus,Plan
from auth import get_current_user,hash_password
from pydantic import BaseModel
from typing import Optional
from datetime import datetime

router=APIRouter(prefix="/me",tags=["me"])

class ProfileUpdate(BaseModel):
    name:Optional[str]=None
    phone:Optional[str]=None
    password:Optional[str]=None

class CardUpdate(BaseModel):
    card_brand:Optional[str]=None
    card_last4:Optional[str]=None

@router.patch("/profile")
def update_profile(data:ProfileUpdate,db=Depends(get_db),cu=Depends(get_current_user)):
    u=db.query(User).filter(User.id==cu.id).first()
    if data.name: u.name=data.name
    if data.phone is not None: u.phone=data.phone
    if data.password: u.password_hash=hash_password(data.password)
    db.commit();db.refresh(u)
    return {"id":u.id,"name":u.name,"email":u.email,"role":u.role,"phone":u.phone,"is_active":u.is_active}

@router.get("/subscription")
def my_subscription(db=Depends(get_db),cu=Depends(get_current_user)):
    stores=db.query(Store).filter(Store.owner_id==cu.id,Store.is_active==True).all()
    result=[]
    for s in stores:
        sub=db.query(Subscription).filter(Subscription.store_id==s.id).first()
        result.append({
            "store_id":s.id,"store_name":s.name,
            "plan":sub.plan.value if sub else s.plan.value,
            "status":sub.status.value if sub else "trial",
            "price_monthly":sub.price_monthly if sub else 0.0,
            "next_billing":sub.next_billing.isoformat() if sub and sub.next_billing else None,
            "card_last4":sub.card_last4 if sub else None,
            "card_brand":sub.card_brand if sub else None,
            "notes":sub.notes if sub else None,
            "started_at":sub.started_at.isoformat() if sub and sub.started_at else None,
        })
    return result

@router.patch("/subscription/{store_id}/card")
def update_card(store_id:int,data:CardUpdate,db=Depends(get_db),cu=Depends(get_current_user)):
    s=db.query(Store).filter(Store.id==store_id,Store.owner_id==cu.id).first()
    if not s: raise HTTPException(403,"No tienes acceso a esta tienda")
    sub=db.query(Subscription).filter(Subscription.store_id==store_id).first()
    if not sub: raise HTTPException(404,"Sin suscripción activa")
    if data.card_brand is not None: sub.card_brand=data.card_brand
    if data.card_last4 is not None: sub.card_last4=data.card_last4
    db.commit()
    return {"ok":True}

@router.post("/subscription/{store_id}/cancel")
def cancel_my_subscription(store_id:int,db=Depends(get_db),cu=Depends(get_current_user)):
    s=db.query(Store).filter(Store.id==store_id,Store.owner_id==cu.id).first()
    if not s: raise HTTPException(403,"No tienes acceso a esta tienda")
    sub=db.query(Subscription).filter(Subscription.store_id==store_id).first()
    if not sub: raise HTTPException(404,"Sin suscripción activa")
    if sub.status==SubStatus.cancelled: raise HTTPException(400,"Ya cancelada")
    sub.status=SubStatus.cancelled
    sub.mp_preapproval_id=None
    sub.mp_preapproval_url=None
    db.commit()
    return {"ok":True}
