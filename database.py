from sqlalchemy import (create_engine, Column, Integer, String, Float, Boolean,
    DateTime, ForeignKey, Text, Enum as SAEnum)
from sqlalchemy.orm import declarative_base, relationship, sessionmaker
from datetime import datetime
import enum

import os
DATABASE_URL = os.getenv("DATABASE_URL", "sqlite:///./skanorder.db")
# Railway PostgreSQL uses postgres:// but SQLAlchemy requires postgresql://
if DATABASE_URL.startswith("postgres://"):
    DATABASE_URL = DATABASE_URL.replace("postgres://", "postgresql://", 1)
_is_sqlite = DATABASE_URL.startswith("sqlite")
engine = create_engine(DATABASE_URL, connect_args={"check_same_thread": False} if _is_sqlite else {})
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()

def get_db():
    db = SessionLocal()
    try: yield db
    finally: db.close()

class UserRole(str, enum.Enum):
    superadmin="superadmin"; admin="admin"; staff="staff"
class StaffRole(str, enum.Enum):
    manager="manager"; staff="staff"
class OrderStatus(str, enum.Enum):
    pending="pending"; confirmed="confirmed"; preparing="preparing"
    ready="ready"; delivered="delivered"; cancelled="cancelled"
class PaymentStatus(str, enum.Enum):
    pending="pending"; paid="paid"; failed="failed"; refunded="refunded"
class PaymentMethod(str, enum.Enum):
    webpay="webpay"; mercadopago="mercadopago"; transfer="transfer"
class QRType(str, enum.Enum):
    table="table"; store="store"
class Plan(str, enum.Enum):
    starter="starter"; negocio="negocio"; cadena="cadena"
class SubStatus(str, enum.Enum):
    active="active"; past_due="past_due"; cancelled="cancelled"; trial="trial"
class GatewayType(str, enum.Enum):
    mercadopago="mercadopago"; webpay="webpay"; getnet="getnet"
class LeadStatus(str, enum.Enum):
    pending="pending"; quoted="quoted"; accepted="accepted"; rejected="rejected"

class User(Base):
    __tablename__ = "users"
    id=Column(Integer,primary_key=True,index=True)
    name=Column(String(120),nullable=False)
    email=Column(String(200),unique=True,index=True,nullable=False)
    password_hash=Column(String(256),nullable=False)
    role=Column(SAEnum(UserRole),default=UserRole.admin)
    phone=Column(String(30))
    is_active=Column(Boolean,default=True)
    created_at=Column(DateTime,default=datetime.utcnow)
    stores=relationship("Store",back_populates="owner",foreign_keys="Store.owner_id",cascade="all, delete-orphan")
    staff_roles=relationship("StoreStaff",back_populates="user",cascade="all, delete-orphan")

class Store(Base):
    __tablename__ = "stores"
    id=Column(Integer,primary_key=True,index=True)
    owner_id=Column(Integer,ForeignKey("users.id"),nullable=False)
    name=Column(String(120),nullable=False)
    description=Column(Text)
    address=Column(String(255))
    logo_b64=Column(Text)
    promo_media_url=Column(String(255))
    promo_media_type=Column(String(10))  # 'image' | 'video'
    plan=Column(SAEnum(Plan),default=Plan.starter)
    is_active=Column(Boolean,default=True)
    created_at=Column(DateTime,default=datetime.utcnow)
    owner=relationship("User",back_populates="stores",foreign_keys=[owner_id])
    categories=relationship("Category",back_populates="store",cascade="all, delete-orphan")
    products=relationship("Product",back_populates="store",cascade="all, delete-orphan")
    qrcodes=relationship("QRCode",back_populates="store",cascade="all, delete-orphan")
    orders=relationship("Order",back_populates="store",cascade="all, delete-orphan")
    staff=relationship("StoreStaff",back_populates="store",cascade="all, delete-orphan")

class StoreStaff(Base):
    __tablename__ = "store_staff"
    id=Column(Integer,primary_key=True,index=True)
    store_id=Column(Integer,ForeignKey("stores.id"),nullable=False)
    user_id=Column(Integer,ForeignKey("users.id"),nullable=False)
    role=Column(SAEnum(StaffRole),default=StaffRole.staff)
    added_at=Column(DateTime,default=datetime.utcnow)
    store=relationship("Store",back_populates="staff")
    user=relationship("User",back_populates="staff_roles")

class Category(Base):
    __tablename__ = "categories"
    id=Column(Integer,primary_key=True,index=True)
    store_id=Column(Integer,ForeignKey("stores.id"),nullable=False)
    name=Column(String(80),nullable=False)
    order=Column(Integer,default=0)
    store=relationship("Store",back_populates="categories")
    products=relationship("Product",back_populates="category")

class Product(Base):
    __tablename__ = "products"
    id=Column(Integer,primary_key=True,index=True)
    store_id=Column(Integer,ForeignKey("stores.id"),nullable=False)
    category_id=Column(Integer,ForeignKey("categories.id"),nullable=True)
    name=Column(String(120),nullable=False)
    description=Column(Text)
    price=Column(Float,nullable=False)
    stock=Column(Integer,default=-1)
    image_b64=Column(Text)
    is_active=Column(Boolean,default=True)
    created_at=Column(DateTime,default=datetime.utcnow)
    store=relationship("Store",back_populates="products")
    category=relationship("Category",back_populates="products")

class QRCode(Base):
    __tablename__ = "qrcodes"
    id=Column(Integer,primary_key=True,index=True)
    store_id=Column(Integer,ForeignKey("stores.id"),nullable=False)
    table_label=Column(String(60),nullable=False)
    token=Column(String(64),unique=True,index=True,nullable=False)
    qr_type=Column(SAEnum(QRType),default=QRType.table)
    created_at=Column(DateTime,default=datetime.utcnow)
    store=relationship("Store",back_populates="qrcodes")
    orders=relationship("Order",back_populates="qr")

class Order(Base):
    __tablename__ = "orders"
    id=Column(Integer,primary_key=True,index=True)
    store_id=Column(Integer,ForeignKey("stores.id"),nullable=False)
    qr_id=Column(Integer,ForeignKey("qrcodes.id"),nullable=True)
    customer_name=Column(String(120))
    customer_phone=Column(String(30))
    total=Column(Float,nullable=False)
    status=Column(SAEnum(OrderStatus),default=OrderStatus.pending)
    payment_status=Column(SAEnum(PaymentStatus),default=PaymentStatus.pending)
    notes=Column(Text)
    order_code=Column(String(20),unique=True,index=True,nullable=True)
    order_qr_token=Column(String(64),unique=True,index=True,nullable=True)
    created_at=Column(DateTime,default=datetime.utcnow)
    updated_at=Column(DateTime,default=datetime.utcnow,onupdate=datetime.utcnow)
    store=relationship("Store",back_populates="orders")
    qr=relationship("QRCode",back_populates="orders")
    items=relationship("OrderItem",back_populates="order",cascade="all, delete-orphan")
    payment=relationship("Payment",back_populates="order",uselist=False,cascade="all, delete-orphan")

class OrderItem(Base):
    __tablename__ = "order_items"
    id=Column(Integer,primary_key=True,index=True)
    order_id=Column(Integer,ForeignKey("orders.id"),nullable=False)
    product_id=Column(Integer,ForeignKey("products.id"),nullable=False)
    qty=Column(Integer,nullable=False)
    unit_price=Column(Float,nullable=False)
    notes=Column(String(255))
    order=relationship("Order",back_populates="items")
    product=relationship("Product")

class Payment(Base):
    __tablename__ = "payments"
    id=Column(Integer,primary_key=True,index=True)
    order_id=Column(Integer,ForeignKey("orders.id"),nullable=False)
    amount=Column(Float,nullable=False)
    method=Column(SAEnum(PaymentMethod),default=PaymentMethod.webpay)
    status=Column(SAEnum(PaymentStatus),default=PaymentStatus.pending)
    external_ref=Column(String(120))
    created_at=Column(DateTime,default=datetime.utcnow)
    order=relationship("Order",back_populates="payment")

class Subscription(Base):
    __tablename__ = "subscriptions"
    id=Column(Integer,primary_key=True,index=True)
    store_id=Column(Integer,ForeignKey("stores.id"),nullable=False,unique=True)
    plan=Column(SAEnum(Plan),nullable=False,default=Plan.starter)
    status=Column(SAEnum(SubStatus),default=SubStatus.trial)
    price_monthly=Column(Float,nullable=False,default=0.0)
    started_at=Column(DateTime,default=datetime.utcnow)
    next_billing=Column(DateTime,nullable=True)
    card_last4=Column(String(4),nullable=True)
    card_brand=Column(String(20),nullable=True)
    notes=Column(Text,nullable=True)
    mp_preapproval_id=Column(String(120),nullable=True)   # MercadoPago preapproval ID
    mp_preapproval_url=Column(Text,nullable=True)          # URL de autorización MP
    store=relationship("Store",back_populates="subscription")

class SystemConfig(Base):
    __tablename__ = "system_config"
    key=Column(String(100),primary_key=True)
    value=Column(Text,nullable=True)

# Add back-reference to Store
Store.subscription=relationship("Subscription",back_populates="store",uselist=False,cascade="all, delete-orphan")

class StorePaymentConfig(Base):
    __tablename__ = "store_payment_configs"
    id=Column(Integer,primary_key=True,index=True)
    store_id=Column(Integer,ForeignKey("stores.id"),nullable=False)
    gateway=Column(SAEnum(GatewayType),nullable=False)
    is_active=Column(Boolean,default=False)
    credentials=Column(Text,nullable=True)  # JSON: gateway-specific keys
    updated_at=Column(DateTime,default=datetime.utcnow,onupdate=datetime.utcnow)
    store=relationship("Store",back_populates="payment_configs")

Store.payment_configs=relationship("StorePaymentConfig",back_populates="store",cascade="all, delete-orphan")
Store.leads=relationship("SalesLead",back_populates="store",cascade="all, delete-orphan")

class SalesLead(Base):
    __tablename__ = "sales_leads"
    id=Column(Integer,primary_key=True,index=True)
    store_id=Column(Integer,ForeignKey("stores.id"),nullable=False)
    contact_name=Column(String(120),nullable=False)
    contact_email=Column(String(200),nullable=False)
    contact_phone=Column(String(30),nullable=True)
    message=Column(Text,nullable=True)
    status=Column(SAEnum(LeadStatus),default=LeadStatus.pending)
    quoted_price=Column(Float,nullable=True)
    created_at=Column(DateTime,default=datetime.utcnow)
    updated_at=Column(DateTime,default=datetime.utcnow,onupdate=datetime.utcnow)
    store=relationship("Store",back_populates="leads")

def create_tables():
    Base.metadata.create_all(bind=engine)
