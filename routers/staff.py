from fastapi import APIRouter,Depends,HTTPException
from database import get_db,User,Store,StoreStaff,UserRole,StaffRole as DBStaffRole
from auth import require_admin,get_current_user,hash_password
from schemas import StaffCreate,StaffOut
from typing import List

router=APIRouter(tags=["staff"])

@router.get("/stores/{sid}/staff",response_model=List[StaffOut])
def list_staff(sid:int,db=Depends(get_db),cu=Depends(get_current_user)):
    return db.query(StoreStaff).filter(StoreStaff.store_id==sid).all()

@router.post("/stores/{sid}/staff",response_model=StaffOut)
def add_staff(sid:int,data:StaffCreate,db=Depends(get_db),cu=Depends(require_admin)):
    s=db.query(Store).filter(Store.id==sid).first()
    if not s or (s.owner_id!=cu.id and cu.role!=UserRole.superadmin): raise HTTPException(403)
    u=db.query(User).filter(User.email==data.email).first()
    if not u:
        u=User(name=data.name,email=data.email,password_hash=hash_password(data.password),role=UserRole.staff,phone=data.phone)
        db.add(u);db.commit();db.refresh(u)
    lnk=StoreStaff(store_id=sid,user_id=u.id,role=DBStaffRole(data.role.value))
    db.add(lnk);db.commit();db.refresh(lnk);return lnk

@router.delete("/stores/{sid}/staff/{lid}")
def rm_staff(sid:int,lid:int,db=Depends(get_db),cu=Depends(require_admin)):
    lnk=db.query(StoreStaff).filter(StoreStaff.id==lid,StoreStaff.store_id==sid).first()
    if not lnk: raise HTTPException(404)
    db.delete(lnk);db.commit();return {"ok":True}
