from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
from fastapi.middleware.cors import CORSMiddleware
from database import create_tables

app=FastAPI(title="Phonorder API",version="1.0.0")
app.add_middleware(CORSMiddleware,allow_origins=["*"],allow_methods=["*"],allow_headers=["*"])

@app.on_event("startup")
def startup(): create_tables()

from routers import auth,superadmin,stores,products,staff,qrcodes,orders,payments,dashboard,websocket
for r in [auth.router,superadmin.router,stores.router,products.router,staff.router,
          qrcodes.router,orders.router,payments.router,dashboard.router,websocket.router]:
    app.include_router(r)

app.mount("/static",StaticFiles(directory="static"),name="static")

@app.get("/menu",include_in_schema=False)
def menu(): return FileResponse("static/menu/index.html")
@app.get("/store",include_in_schema=False)
def store_page(): return FileResponse("static/store/index.html")
@app.get("/admin",include_in_schema=False)
def admin(): return FileResponse("static/admin/index.html")
@app.get("/",include_in_schema=False)
def root(): return FileResponse("static/admin/index.html")
