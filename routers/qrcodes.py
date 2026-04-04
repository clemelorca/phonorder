from fastapi import APIRouter,Depends,HTTPException
from database import get_db,Store,QRCode,UserRole,QRType
from auth import require_admin,get_current_user
from schemas import QRCreate,QROut
from typing import List
import uuid,qrcode,io,base64

router=APIRouter(tags=["qrcodes"])

def _gen(url):
    q=qrcode.QRCode(box_size=6,border=2);q.add_data(url);q.make(fit=True)
    img=q.make_image(fill_color="black",back_color="white")
    buf=io.BytesIO();img.save(buf,format="PNG")
    return base64.b64encode(buf.getvalue()).decode()

def _out(q,url):
    return QROut(**{**QROut.model_validate(q).model_dump(),"qr_image_b64":_gen(url)})

@router.get("/stores/{sid}/qrcodes",response_model=List[QROut])
def list_qr(sid:int,db=Depends(get_db),cu=Depends(get_current_user)):
    results=[]
    for q in db.query(QRCode).filter(QRCode.store_id==sid).all():
        url=f"/shop?token={q.token}" if q.qr_type==QRType.store else f"/menu?token={q.token}"
        results.append(_out(q,url))
    return results

@router.post("/stores/{sid}/qrcodes",response_model=QROut)
def create_qr(sid:int,data:QRCreate,db=Depends(get_db),cu=Depends(require_admin)):
    s=db.query(Store).filter(Store.id==sid).first()
    if not s or (s.owner_id!=cu.id and cu.role!=UserRole.superadmin): raise HTTPException(403)
    tok=uuid.uuid4().hex
    q=QRCode(store_id=sid,table_label=data.table_label,token=tok,qr_type=data.qr_type)
    db.add(q);db.commit();db.refresh(q)
    url=f"/shop?token={tok}" if data.qr_type==QRType.store else f"/menu?token={tok}"
    return _out(q,url)

@router.get("/stores/{sid}/qrcodes/store",response_model=QROut)
def get_or_create_store_qr(sid:int,db=Depends(get_db),cu=Depends(require_admin)):
    s=db.query(Store).filter(Store.id==sid).first()
    if not s or (s.owner_id!=cu.id and cu.role!=UserRole.superadmin): raise HTTPException(403)
    q=db.query(QRCode).filter(QRCode.store_id==sid,QRCode.qr_type==QRType.store).first()
    if not q:
        tok=uuid.uuid4().hex
        q=QRCode(store_id=sid,table_label="Tienda",token=tok,qr_type=QRType.store)
        db.add(q);db.commit();db.refresh(q)
    return _out(q,f"/shop?token={q.token}")

@router.delete("/stores/{sid}/qrcodes/{qid}")
def del_qr(sid:int,qid:int,db=Depends(get_db),cu=Depends(require_admin)):
    q=db.query(QRCode).filter(QRCode.id==qid,QRCode.store_id==sid).first()
    if not q: raise HTTPException(404)
    db.delete(q);db.commit();return {"ok":True}
