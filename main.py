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
def startup(): create_tables()

from routers import auth,superadmin,stores,products,staff,qrcodes,orders,payments,dashboard,websocket,menu,me,gateways,billing
for r in [auth.router,superadmin.router,stores.router,products.router,staff.router,
          qrcodes.router,orders.router,payments.router,dashboard.router,websocket.router,
          menu.router,me.router,gateways.router,billing.router]:
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
def root(): return FileResponse("static/admin/index.html")
