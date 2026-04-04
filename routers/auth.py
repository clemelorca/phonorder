from fastapi import APIRouter,Depends,HTTPException,Request
from database import get_db,User,StoreStaff,StaffRole,UserRole
from auth import verify_password,create_access_token,create_refresh_token,decode_token,get_current_user,hash_password
from schemas import LoginRequest,TokenResponse,RefreshRequest,UserOut,RegisterRequest
from main import limiter

router=APIRouter(prefix="/auth",tags=["auth"])

def _get_staff_role(uid:int,db):
    """Retorna 'manager' si el usuario es manager en alguna tienda, 'staff' si es solo staff, None si no es staff."""
    links=db.query(StoreStaff).filter(StoreStaff.user_id==uid).all()
    if not links: return None
    return "manager" if any(l.role==StaffRole.manager for l in links) else "staff"

@router.post("/login",response_model=TokenResponse)
@limiter.limit("10/minute")  # Brute-force protection
def login(request:Request,data:LoginRequest,db=Depends(get_db)):
    u=db.query(User).filter(User.email==data.email).first()
    # Always verify (even if user not found) to prevent timing attacks
    hash_to_check=u.password_hash if u else "$2b$12$invalidhashpadding000000000000000000000000000000000000"
    if not verify_password(data.password,hash_to_check) or not u:
        raise HTTPException(401,"Credenciales incorrectas")
    if not u.is_active: raise HTTPException(403,"Usuario inactivo")
    staff_role=_get_staff_role(u.id,db)
    return TokenResponse(access_token=create_access_token(u.id,u.role.value),
        refresh_token=create_refresh_token(u.id),user_id=u.id,role=u.role.value,name=u.name,staff_role=staff_role)

@router.post("/refresh",response_model=TokenResponse)
@limiter.limit("20/minute")
def refresh(request:Request,data:RefreshRequest,db=Depends(get_db)):
    p=decode_token(data.refresh_token)
    if p.get("type")!="refresh": raise HTTPException(401)
    u=db.query(User).filter(User.id==int(p["sub"])).first()
    if not u or not u.is_active: raise HTTPException(401)
    staff_role=_get_staff_role(u.id,db)
    return TokenResponse(access_token=create_access_token(u.id,u.role.value),
        refresh_token=create_refresh_token(u.id),user_id=u.id,role=u.role.value,name=u.name,staff_role=staff_role)

@router.post("/register",response_model=TokenResponse)
@limiter.limit("5/minute")
def register(request:Request,data:RegisterRequest,db=Depends(get_db)):
    if db.query(User).filter(User.email==data.email).first():
        raise HTTPException(400,"Este email ya está registrado")
    u=User(name=data.name,email=data.email,password_hash=hash_password(data.password),
           role=UserRole.admin,phone=data.phone,is_active=True)
    db.add(u);db.commit();db.refresh(u)
    staff_role=_get_staff_role(u.id,db)
    return TokenResponse(access_token=create_access_token(u.id,u.role.value),
        refresh_token=create_refresh_token(u.id),user_id=u.id,role=u.role.value,name=u.name,staff_role=staff_role)

@router.get("/me",response_model=UserOut)
def me(cu=Depends(get_current_user)): return cu
