from fastapi import APIRouter,Depends,HTTPException
from database import get_db,User
from auth import verify_password,create_access_token,create_refresh_token,decode_token,get_current_user
from schemas import LoginRequest,TokenResponse,RefreshRequest,UserOut

router=APIRouter(prefix="/auth",tags=["auth"])

@router.post("/login",response_model=TokenResponse)
def login(data:LoginRequest,db=Depends(get_db)):
    u=db.query(User).filter(User.email==data.email).first()
    if not u or not verify_password(data.password,u.password_hash): raise HTTPException(401,"Credenciales incorrectas")
    if not u.is_active: raise HTTPException(403,"Usuario inactivo")
    return TokenResponse(access_token=create_access_token(u.id,u.role.value),
        refresh_token=create_refresh_token(u.id),user_id=u.id,role=u.role.value,name=u.name)

@router.post("/refresh",response_model=TokenResponse)
def refresh(data:RefreshRequest,db=Depends(get_db)):
    p=decode_token(data.refresh_token)
    if p.get("type")!="refresh": raise HTTPException(401)
    u=db.query(User).filter(User.id==int(p["sub"])).first()
    if not u or not u.is_active: raise HTTPException(401)
    return TokenResponse(access_token=create_access_token(u.id,u.role.value),
        refresh_token=create_refresh_token(u.id),user_id=u.id,role=u.role.value,name=u.name)

@router.get("/me",response_model=UserOut)
def me(cu=Depends(get_current_user)): return cu
