from fastapi import APIRouter,Depends,HTTPException
from database import get_db,Store,Product,Category,StoreStaff,UserRole
from auth import require_admin,get_current_user
from schemas import ProductCreate,ProductUpdate,ProductOut,CategoryCreate,CategoryOut,ProductBulkRequest,ProductBulkResult
from typing import List

router=APIRouter(tags=["products"])

def _s(sid,cu,db):
    s=db.query(Store).filter(Store.id==sid,Store.is_active==True).first()
    if not s: raise HTTPException(404)
    if cu.role!=UserRole.superadmin and s.owner_id!=cu.id:
        if not db.query(StoreStaff).filter(StoreStaff.store_id==sid,StoreStaff.user_id==cu.id).first(): raise HTTPException(403)
    return s

@router.get("/stores/{sid}/categories",response_model=List[CategoryOut])
def list_cats(sid:int,db=Depends(get_db),cu=Depends(get_current_user)):
    _s(sid,cu,db);return db.query(Category).filter(Category.store_id==sid).order_by(Category.order).all()

@router.post("/stores/{sid}/categories",response_model=CategoryOut)
def create_cat(sid:int,data:CategoryCreate,db=Depends(get_db),cu=Depends(require_admin)):
    _s(sid,cu,db);c=Category(store_id=sid,**data.model_dump());db.add(c);db.commit();db.refresh(c);return c

@router.delete("/stores/{sid}/categories/{cid}")
def del_cat(sid:int,cid:int,db=Depends(get_db),cu=Depends(require_admin)):
    _s(sid,cu,db);c=db.query(Category).filter(Category.id==cid,Category.store_id==sid).first()
    if not c: raise HTTPException(404)
    db.delete(c);db.commit();return {"ok":True}

@router.get("/stores/{sid}/products",response_model=List[ProductOut])
def list_prods(sid:int,db=Depends(get_db),cu=Depends(get_current_user)):
    _s(sid,cu,db);return db.query(Product).filter(Product.store_id==sid).all()

@router.post("/stores/{sid}/products",response_model=ProductOut)
def create_prod(sid:int,data:ProductCreate,db=Depends(get_db),cu=Depends(require_admin)):
    _s(sid,cu,db);p=Product(store_id=sid,**data.model_dump());db.add(p);db.commit();db.refresh(p);return p

@router.post("/stores/{sid}/products/bulk",response_model=ProductBulkResult)
def bulk_create_prods(sid:int,data:ProductBulkRequest,db=Depends(get_db),cu=Depends(require_admin)):
    _s(sid,cu,db)
    existing={c.name.lower():c for c in db.query(Category).filter(Category.store_id==sid).all()}
    created=0;cats_created=0;skipped=[]
    for item in data.items:
        if not item.name or not item.name.strip():
            skipped.append("(sin nombre)");continue
        if item.price is None or item.price<0:
            skipped.append(item.name);continue
        cat_id=None
        if item.category_name and item.category_name.strip():
            key=item.category_name.strip().lower()
            if key in existing:
                cat_id=existing[key].id
            else:
                c=Category(store_id=sid,name=item.category_name.strip())
                db.add(c);db.flush()
                existing[key]=c;cat_id=c.id;cats_created+=1
        p=Product(store_id=sid,name=item.name.strip(),price=float(item.price),
                  stock=int(item.stock if item.stock is not None else -1),
                  description=(item.description.strip() if item.description else None),
                  category_id=cat_id,is_active=True)
        db.add(p);created+=1
    db.commit()
    return ProductBulkResult(created=created,categories_created=cats_created,skipped=skipped)

@router.patch("/stores/{sid}/products/{pid}",response_model=ProductOut)
def update_prod(sid:int,pid:int,data:ProductUpdate,db=Depends(get_db),cu=Depends(require_admin)):
    _s(sid,cu,db);p=db.query(Product).filter(Product.id==pid,Product.store_id==sid).first()
    if not p: raise HTTPException(404)
    for k,v in data.model_dump(exclude_none=True).items(): setattr(p,k,v)
    db.commit();db.refresh(p);return p

@router.delete("/stores/{sid}/products/{pid}")
def del_prod(sid:int,pid:int,db=Depends(get_db),cu=Depends(require_admin)):
    _s(sid,cu,db);p=db.query(Product).filter(Product.id==pid,Product.store_id==sid).first()
    if not p: raise HTTPException(404)
    db.delete(p);db.commit();return {"ok":True}
