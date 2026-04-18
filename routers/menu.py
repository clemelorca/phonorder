from fastapi import APIRouter,Depends,HTTPException
from database import get_db,QRCode,Store,Category,Product
from schemas import MenuResponse,MenuCategory,MenuProduct

router=APIRouter(tags=["menu"])

@router.get("/menu-data",response_model=MenuResponse)
def get_menu(token:str,db=Depends(get_db)):
    qr=db.query(QRCode).filter(QRCode.token==token).first()
    if not qr: raise HTTPException(404,"QR inválido")
    s=db.query(Store).filter(Store.id==qr.store_id,Store.is_active==True).first()
    if not s: raise HTTPException(404,"Tienda no disponible")
    cats=db.query(Category).filter(Category.store_id==s.id).order_by(Category.order).all()
    unc=db.query(Product).filter(Product.store_id==s.id,Product.is_active==True,Product.category_id==None).all()
    result=[]
    for cat in cats:
        prods=db.query(Product).filter(Product.category_id==cat.id,Product.is_active==True).all()
        if prods: result.append(MenuCategory(id=cat.id,name=cat.name,order=cat.order,products=[MenuProduct.model_validate(p) for p in prods]))
    if unc: result.append(MenuCategory(id=0,name="Otros",order=999,products=[MenuProduct.model_validate(p) for p in unc]))
    return MenuResponse(store_id=s.id,store_name=s.name,store_description=s.description,
        store_logo=s.logo_b64,table_label=qr.table_label,categories=result,
        primary_color=s.primary_color or "#01696f")
