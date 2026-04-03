from fastapi import APIRouter,Depends,HTTPException
from database import get_db,Store,StoreStaff,UserRole
from auth import require_admin,get_current_user
from schemas import StoreCreate,StoreUpdate,StoreOut
from typing import List

router=APIRouter(prefix="/stores",tags=["stores"])

def _ok(s,u,db):
    if u.role==UserRole.superadmin or s.owner_id==u.id: return True
    return bool(db.query(StoreStaff).filter(StoreStaff.store_id==s.id,StoreStaff.user_id==u.id).first())

@router.get("/",response_model=List[StoreOut])
def list_stores(db=Depends(get_db),cu=Depends(get_current_user)):
    if cu.role==UserRole.superadmin: return db.query(Store).all()
    owned=db.query(Store).filter(Store.owner_id==cu.id).all()
    ids={s.id for s in owned}
    extra=db.query(Store).filter(Store.id.in_([r.store_id for r in db.query(StoreStaff).filter(StoreStaff.user_id==cu.id).all()]),~Store.id.in_(ids)).all()
    return owned+extra

@router.post("/",response_model=StoreOut)
def create_store(data:StoreCreate,db=Depends(get_db),cu=Depends(require_admin)):
    s=Store(**data.model_dump(),owner_id=cu.id);db.add(s);db.commit();db.refresh(s);return s

@router.get("/{sid}",response_model=StoreOut)
def get_store(sid:int,db=Depends(get_db),cu=Depends(get_current_user)):
    s=db.query(Store).filter(Store.id==sid).first()
    if not s or not _ok(s,cu,db): raise HTTPException(404)
    return s

@router.patch("/{sid}",response_model=StoreOut)
def update_store(sid:int,data:StoreUpdate,db=Depends(get_db),cu=Depends(require_admin)):
    s=db.query(Store).filter(Store.id==sid).first()
    if not s or not _ok(s,cu,db): raise HTTPException(404)
    for k,v in data.model_dump(exclude_none=True).items(): setattr(s,k,v)
    db.commit();db.refresh(s);return s

@router.delete("/{sid}")
def del_store(sid:int,db=Depends(get_db),cu=Depends(require_admin)):
    s=db.query(Store).filter(Store.id==sid).first()
    if not s or (s.owner_id!=cu.id and cu.role!=UserRole.superadmin): raise HTTPException(403)
    s.is_active=False;db.commit();return {"ok":True}
