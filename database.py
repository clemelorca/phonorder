from sqlalchemy import (create_engine, Column, Integer, String, Float, Boolean,
    DateTime, ForeignKey, Text, Enum as SAEnum)
from sqlalchemy.orm import declarative_base, relationship, sessionmaker
from datetime import datetime
import enum

DATABASE_URL = "sqlite:///./phonorder.db"
engine = create_engine(DATABASE_URL, connect_args={"check_same_thread": False})
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
class Plan(str, enum.Enum):
    starter="starter"; negocio="negocio"; cadena="cadena"

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
    stores=relationship("Store",back_populates="owner",foreign_keys="Store.owner_id")
    staff_roles=relationship("StoreStaff",back_populates="user")

class Store(Base):
    __tablename__ = "stores"
    id=Column(Integer,primary_key=True,index=True)
    owner_id=Column(Integer,ForeignKey("users.id"),nullable=False)
    name=Column(String(120),nullable=False)
    description=Column(Text)
    address=Column(String(255))
    logo_b64=Column(Text)
    plan=Column(SAEnum(Plan),default=Plan.starter)
    is_active=Column(Boolean,default=True)
    created_at=Column(DateTime,default=datetime.utcnow)
    owner=relationship("User",back_populates="stores",foreign_keys=[owner_id])
    categories=relationship("Category",back_populates="store",cascade="all, delete-orphan")
    products=relationship("Product",back_populates="store",cascade="all, delete-orphan")
    qrcodes=relationship("QRCode",back_populates="store",cascade="all, delete-orphan")
    orders=relationship("Order",back_populates="store")
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
    created_at=Column(DateTime,default=datetime.utcnow)
    updated_at=Column(DateTime,default=datetime.utcnow,onupdate=datetime.utcnow)
    store=relationship("Store",back_populates="orders")
    qr=relationship("QRCode",back_populates="orders")
    items=relationship("OrderItem",back_populates="order",cascade="all, delete-orphan")
    payment=relationship("Payment",back_populates="order",uselist=False)

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

def create_tables():
    Base.metadata.create_all(bind=engine)
