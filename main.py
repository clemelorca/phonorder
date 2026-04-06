from fastapi import FastAPI, Request
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse, JSONResponse
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.trustedhost import TrustedHostMiddleware
from slowapi import Limiter, _rate_limit_exceeded_handler
from slowapi.util import get_remote_address
from slowapi.errors import RateLimitExceeded
from database import create_tables
from security import CORS_ORIGINS, SECURITY_HEADERS, APP_ENV

# ── Rate limiter ──────────────────────────────────────────────
limiter = Limiter(key_func=get_remote_address, default_limits=["200/minute"])

app = FastAPI(
    title="Skanorder API",
    version="1.0.0",
    # Hide docs in production
    docs_url=None if APP_ENV == "production" else "/docs",
    redoc_url=None if APP_ENV == "production" else "/redoc",
)

app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)

# ── CORS ──────────────────────────────────────────────────────
app.add_middleware(
    CORSMiddleware,
    allow_origins=CORS_ORIGINS,
    allow_credentials=True,
    allow_methods=["GET","POST","PUT","PATCH","DELETE","OPTIONS"],
    allow_headers=["Authorization","Content-Type","X-Request-Id"],
)

# ── Security headers middleware ───────────────────────────────
@app.middleware("http")
async def add_security_headers(request: Request, call_next):
    response = await call_next(request)
    for key, value in SECURITY_HEADERS.items():
        response.headers[key] = value
    return response

# ── Body size limit (10 MB) ───────────────────────────────────
MAX_BODY = 10 * 1024 * 1024  # 10 MB

@app.middleware("http")
async def limit_body_size(request: Request, call_next):
    cl = request.headers.get("content-length")
    if cl and int(cl) > MAX_BODY:
        return JSONResponse({"detail": "Payload demasiado grande (máx 10 MB)"}, status_code=413)
    return await call_next(request)

@app.on_event("startup")
def startup():
    create_tables()
    _run_migrations()
    _ensure_superadmin()

def _run_migrations():
    from database import engine
    sa = __import__('sqlalchemy')
    migrations = [
        "ALTER TABLE orders ADD COLUMN tip FLOAT DEFAULT 0.0",
        "ALTER TABLE orders ADD COLUMN order_code VARCHAR(20)",
        "ALTER TABLE orders ADD COLUMN order_qr_token VARCHAR(64)",
        "ALTER TABLE orders ADD COLUMN updated_at TIMESTAMP",
        "ALTER TABLE stores ADD COLUMN promo_media_url VARCHAR(255)",
        "ALTER TABLE stores ADD COLUMN promo_media_type VARCHAR(10)",
        "ALTER TABLE stores ADD COLUMN primary_color VARCHAR(7) DEFAULT '#01696f'",
        "ALTER TABLE subscriptions ADD COLUMN mp_preapproval_id VARCHAR(120)",
        "ALTER TABLE subscriptions ADD COLUMN mp_preapproval_url TEXT",
    ]
    for sql in migrations:
        try:
            with engine.begin() as conn:  # transacción independiente por cada ALTER
                conn.execute(sa.text(sql))
        except Exception:
            pass  # Columna ya existe, ignorar

def _ensure_superadmin():
    import os
    from database import SessionLocal, User, UserRole
    from auth import hash_password
    email = os.getenv("SUPERADMIN_EMAIL", "admin@skanorder.com")
    password = os.getenv("SUPERADMIN_PASSWORD", "")
    if not password:
        return  # No password configured, skip
    db = SessionLocal()
    try:
        u = db.query(User).filter(User.email == email).first()
        if not u:
            u = User(name="Superadmin", email=email,
                     password_hash=hash_password(password),
                     role=UserRole.superadmin, is_active=True)
            db.add(u)
            db.commit()
        elif u.role != UserRole.superadmin or not u.is_active:
            u.role = UserRole.superadmin
            u.is_active = True
            db.commit()
    finally:
        db.close()

from routers import auth,superadmin,stores,products,staff,qrcodes,orders,payments,dashboard,websocket,menu,me,gateways,billing,ai_insights,contact
for r in [auth.router,superadmin.router,stores.router,products.router,staff.router,
          qrcodes.router,orders.router,payments.router,dashboard.router,websocket.router,
          menu.router,me.router,gateways.router,billing.router,ai_insights.router,
          ai_insights.sa_router,contact.router]:
    app.include_router(r)

app.mount("/static",StaticFiles(directory="static"),name="static")

@app.get("/menu",include_in_schema=False)
def menu(): return FileResponse("static/menu/index.html")
@app.get("/store",include_in_schema=False)
def store_page(): return FileResponse("static/store/index.html")
@app.get("/shop",include_in_schema=False)
def shop(): return FileResponse("static/shop/index.html")
@app.get("/track",include_in_schema=False)
def track(): return FileResponse("static/track/index.html")
@app.get("/deliver",include_in_schema=False)
def deliver(): return FileResponse("static/deliver/index.html")
@app.get("/register",include_in_schema=False)
def register_page(): return FileResponse("static/register/index.html")
@app.get("/admin",include_in_schema=False)
def admin(): return FileResponse("static/admin/index.html")
@app.get("/",include_in_schema=False)
def root(): return FileResponse("design/index.html")

@app.post("/setup/superadmin",include_in_schema=False)
def setup_superadmin(request:Request):
    import os
    from database import SessionLocal,User,UserRole,create_tables
    from auth import hash_password
    token=request.headers.get("X-Setup-Token","")
    if token!=os.getenv("SETUP_TOKEN",""):
        return JSONResponse({"error":"forbidden"},status_code=403)
    create_tables()
    db=SessionLocal()
    u=db.query(User).filter(User.email=="admin@skanorder.com").first()
    if not u:
        u=User(name="Superadmin",email="admin@skanorder.com",
               password_hash=hash_password("16210383-Cc"),
               role=UserRole.superadmin,is_active=True)
        db.add(u);db.commit();db.close()
        return {"ok":True,"created":True}
    u.role=UserRole.superadmin;u.is_active=True
    u.password_hash=hash_password("16210383-Cc")
    db.commit();db.close()
    return {"ok":True,"updated":True}
