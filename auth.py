from datetime import datetime, timedelta
from jose import JWTError, jwt
from passlib.context import CryptContext
from fastapi import Depends, HTTPException
from fastapi.security import OAuth2PasswordBearer
from sqlalchemy.orm import Session
from database import get_db, User, UserRole
from security import SECRET_KEY

ALGORITHM="HS256"
ACCESS_MIN=60       # 1 hour (was 8h — reduced for security)
REFRESH_DAYS=14     # 14 days (was 30)
pwd=CryptContext(schemes=["bcrypt"],deprecated="auto",bcrypt__rounds=12)
oauth2=OAuth2PasswordBearer(tokenUrl="/auth/login")

def hash_password(p): return pwd.hash(p)
def verify_password(plain,h):
    try: return pwd.verify(plain,h)
    except Exception: return False
def _tok(data,exp):
    d=data.copy(); d["exp"]=datetime.utcnow()+exp
    return jwt.encode(d,SECRET_KEY,algorithm=ALGORITHM)
def create_access_token(uid,role): return _tok({"sub":str(uid),"role":role},timedelta(minutes=ACCESS_MIN))
def create_refresh_token(uid): return _tok({"sub":str(uid),"type":"refresh"},timedelta(days=REFRESH_DAYS))
def decode_token(token):
    try: return jwt.decode(token,SECRET_KEY,algorithms=[ALGORITHM])
    except JWTError: raise HTTPException(401,"Token inválido")
def get_current_user(token:str=Depends(oauth2),db:Session=Depends(get_db)):
    p=decode_token(token)
    u=db.query(User).filter(User.id==int(p["sub"])).first()
    if not u or not u.is_active: raise HTTPException(401,"Usuario inactivo")
    return u
def require_role(*roles):
    def chk(cu=Depends(get_current_user)):
        if cu.role not in roles: raise HTTPException(403,"Sin permisos")
        return cu
    return chk
require_superadmin=require_role(UserRole.superadmin)
require_admin=require_role(UserRole.superadmin,UserRole.admin)
require_staff=require_role(UserRole.superadmin,UserRole.admin,UserRole.staff)
