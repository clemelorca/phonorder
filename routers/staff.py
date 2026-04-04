from fastapi import APIRouter,Depends,HTTPException
from database import get_db,User,Store,StoreStaff,UserRole,StaffRole as DBStaffRole
from auth import require_admin,get_current_user,hash_password
from schemas import StaffCreate,StaffOut
from typing import List,Optional
from pydantic import BaseModel

class StaffUpdate(BaseModel):
    name:Optional[str]=None
    role:Optional[str]=None
    password:Optional[str]=None

router=APIRouter(tags=["staff"])

def _chk_store_access(sid:int,cu,db):
    s=db.query(Store).filter(Store.id==sid).first()
    if not s: raise HTTPException(404)
    if cu.role==UserRole.superadmin or s.owner_id==cu.id: return s
    if db.query(StoreStaff).filter(StoreStaff.store_id==sid,StoreStaff.user_id==cu.id).first(): return s
    raise HTTPException(403)

@router.get("/stores/{sid}/staff",response_model=List[StaffOut])
def list_staff(sid:int,db=Depends(get_db),cu=Depends(get_current_user)):
    _chk_store_access(sid,cu,db)
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

@router.patch("/stores/{sid}/staff/{lid}",response_model=StaffOut)
def update_staff(sid:int,lid:int,data:StaffUpdate,db=Depends(get_db),cu=Depends(require_admin)):
    s=db.query(Store).filter(Store.id==sid).first()
    if not s or (s.owner_id!=cu.id and cu.role!=UserRole.superadmin): raise HTTPException(403)
    lnk=db.query(StoreStaff).filter(StoreStaff.id==lid,StoreStaff.store_id==sid).first()
    if not lnk: raise HTTPException(404)
    if data.role:
        lnk.role=DBStaffRole(data.role)
    if data.name or data.password:
        u=db.query(User).filter(User.id==lnk.user_id).first()
        if data.name: u.name=data.name
        if data.password: u.password_hash=hash_password(data.password)
    db.commit();db.refresh(lnk);return lnk

@router.delete("/stores/{sid}/staff/{lid}")
def rm_staff(sid:int,lid:int,db=Depends(get_db),cu=Depends(require_admin)):
    s=db.query(Store).filter(Store.id==sid).first()
    if not s or (s.owner_id!=cu.id and cu.role!=UserRole.superadmin): raise HTTPException(403)
    lnk=db.query(StoreStaff).filter(StoreStaff.id==lid,StoreStaff.store_id==sid).first()
    if not lnk: raise HTTPException(404)
    db.delete(lnk);db.commit();return {"ok":True}
