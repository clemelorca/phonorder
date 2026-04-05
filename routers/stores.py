from fastapi import APIRouter,Depends,HTTPException,UploadFile,File
from database import get_db,Store,StoreStaff,UserRole
from auth import require_admin,get_current_user
from schemas import StoreCreate,StoreUpdate,StoreOut
from typing import List
import os,shutil

router=APIRouter(prefix="/stores",tags=["stores"])

def _ok(s,u,db):
    if u.role==UserRole.superadmin or s.owner_id==u.id: return True
    return bool(db.query(StoreStaff).filter(StoreStaff.store_id==s.id,StoreStaff.user_id==u.id).first())

@router.get("",response_model=List[StoreOut])
@router.get("/",response_model=List[StoreOut],include_in_schema=False)
def list_stores(db=Depends(get_db),cu=Depends(get_current_user)):
    if cu.role==UserRole.superadmin: return db.query(Store).all()
    owned=db.query(Store).filter(Store.owner_id==cu.id).all()
    ids={s.id for s in owned}
    extra=db.query(Store).filter(Store.id.in_([r.store_id for r in db.query(StoreStaff).filter(StoreStaff.user_id==cu.id).all()]),~Store.id.in_(ids)).all()
    return owned+extra

PLAN_STORE_LIMITS={"starter":1,"negocio":3,"cadena":999}

@router.post("",response_model=StoreOut)
@router.post("/",response_model=StoreOut,include_in_schema=False)
def create_store(data:StoreCreate,db=Depends(get_db),cu=Depends(require_admin)):
    if cu.role.value!="superadmin":
        owned=db.query(Store).filter(Store.owner_id==cu.id).count()
        # Determinar plan del usuario según su primera tienda
        first=db.query(Store).filter(Store.owner_id==cu.id).first()
        plan=first.plan.value if first else "starter"
        limit=PLAN_STORE_LIMITS.get(plan,1)
        if owned>=limit:
            raise HTTPException(403,f"Tu plan {plan} permite máximo {limit} tienda(s). Actualiza tu plan para agregar más.")
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

@router.post("/{sid}/promo")
async def upload_promo(sid:int,file:UploadFile=File(...),db=Depends(get_db),cu=Depends(require_admin)):
    s=db.query(Store).filter(Store.id==sid).first()
    if not s or (s.owner_id!=cu.id and cu.role!=UserRole.superadmin): raise HTTPException(403)
    ct=file.content_type or ''
    if ct.startswith('image/'): mtype='image'
    elif ct.startswith('video/'): mtype='video'
    else: raise HTTPException(400,"Solo se aceptan imágenes o videos")
    ext=ct.split('/')[-1].split(';')[0].strip()
    if ext=='jpeg': ext='jpg'
    folder=f"static/media/stores/{sid}"
    os.makedirs(folder,exist_ok=True)
    # Borrar promo anterior si existe
    for f2 in os.listdir(folder):
        if f2.startswith('promo.'): os.remove(os.path.join(folder,f2))
    path=f"{folder}/promo.{ext}"
    with open(path,'wb') as out: shutil.copyfileobj(file.file,out)
    s.promo_media_url=f"/static/media/stores/{sid}/promo.{ext}"
    s.promo_media_type=mtype
    db.commit();db.refresh(s)
    return {"url":s.promo_media_url,"type":mtype}

@router.delete("/{sid}/promo")
def delete_promo(sid:int,db=Depends(get_db),cu=Depends(require_admin)):
    s=db.query(Store).filter(Store.id==sid).first()
    if not s or (s.owner_id!=cu.id and cu.role!=UserRole.superadmin): raise HTTPException(403)
    folder=f"static/media/stores/{sid}"
    if os.path.exists(folder):
        for f2 in os.listdir(folder):
            if f2.startswith('promo.'): os.remove(os.path.join(folder,f2))
    s.promo_media_url=None;s.promo_media_type=None
    db.commit();return {"ok":True}

@router.delete("/{sid}")
def del_store(sid:int,db=Depends(get_db),cu=Depends(require_admin)):
    s=db.query(Store).filter(Store.id==sid).first()
    if not s or (s.owner_id!=cu.id and cu.role!=UserRole.superadmin): raise HTTPException(403)
    s.is_active=False;db.commit();return {"ok":True}
