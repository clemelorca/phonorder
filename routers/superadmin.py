from fastapi import APIRouter,Depends,HTTPException
from sqlalchemy import func
from database import get_db,User,Store,Order,UserRole,PaymentStatus
from auth import require_superadmin,hash_password
from schemas import UserCreate,UserUpdate,UserOut,StoreOut
from typing import List

router=APIRouter(prefix="/superadmin",tags=["superadmin"])

@router.get("/stats")
def stats(db=Depends(get_db),_=Depends(require_superadmin)):
    return {"total_admins":db.query(User).filter(User.role==UserRole.admin).count(),
            "total_stores":db.query(Store).count(),"active_stores":db.query(Store).filter(Store.is_active==True).count(),
            "total_orders":db.query(Order).count(),
            "total_revenue":db.query(func.sum(Order.total)).filter(Order.payment_status==PaymentStatus.paid).scalar() or 0}

@router.get("/admins",response_model=List[UserOut])
def list_admins(db=Depends(get_db),_=Depends(require_superadmin)):
    return db.query(User).filter(User.role==UserRole.admin).all()

@router.post("/admins",response_model=UserOut)
def create_admin(data:UserCreate,db=Depends(get_db),_=Depends(require_superadmin)):
    if db.query(User).filter(User.email==data.email).first(): raise HTTPException(400,"Email ya registrado")
    u=User(name=data.name,email=data.email,password_hash=hash_password(data.password),role=UserRole.admin,phone=data.phone)
    db.add(u);db.commit();db.refresh(u);return u

@router.patch("/admins/{uid}",response_model=UserOut)
def update_admin(uid:int,data:UserUpdate,db=Depends(get_db),_=Depends(require_superadmin)):
    u=db.query(User).filter(User.id==uid).first()
    if not u: raise HTTPException(404)
    for k,v in data.model_dump(exclude_none=True).items(): setattr(u,k,v)
    db.commit();db.refresh(u);return u

@router.get("/stores",response_model=List[StoreOut])
def all_stores(db=Depends(get_db),_=Depends(require_superadmin)):
    return db.query(Store).all()
