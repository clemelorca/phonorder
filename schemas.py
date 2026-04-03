from pydantic import BaseModel,EmailStr
from typing import Optional,List
from datetime import datetime
from enum import Enum

class UserRole(str,Enum):
    superadmin="superadmin";admin="admin";staff="staff"
class StaffRole(str,Enum):
    manager="manager";staff="staff"
class OrderStatus(str,Enum):
    pending="pending";confirmed="confirmed";preparing="preparing"
    ready="ready";delivered="delivered";cancelled="cancelled"
class PaymentStatus(str,Enum):
    pending="pending";paid="paid";failed="failed";refunded="refunded"
class Plan(str,Enum):
    starter="starter";negocio="negocio";cadena="cadena"

class LoginRequest(BaseModel):
    email:EmailStr;password:str
class TokenResponse(BaseModel):
    access_token:str;refresh_token:str;token_type:str="bearer"
    user_id:int;role:str;name:str
class RefreshRequest(BaseModel):
    refresh_token:str

class UserCreate(BaseModel):
    name:str;email:EmailStr;password:str
    role:UserRole=UserRole.admin;phone:Optional[str]=None
class UserUpdate(BaseModel):
    name:Optional[str]=None;phone:Optional[str]=None;is_active:Optional[bool]=None
class UserOut(BaseModel):
    id:int;name:str;email:str;role:UserRole
    phone:Optional[str];is_active:bool;created_at:datetime
    model_config={"from_attributes":True}

class StoreCreate(BaseModel):
    name:str;description:Optional[str]=None;address:Optional[str]=None
    logo_b64:Optional[str]=None;plan:Plan=Plan.starter
class StoreUpdate(BaseModel):
    name:Optional[str]=None;description:Optional[str]=None;address:Optional[str]=None
    logo_b64:Optional[str]=None;plan:Optional[Plan]=None;is_active:Optional[bool]=None
class StoreOut(BaseModel):
    id:int;owner_id:int;name:str;description:Optional[str]
    address:Optional[str];logo_b64:Optional[str];plan:Plan
    is_active:bool;created_at:datetime
    model_config={"from_attributes":True}

class StaffCreate(BaseModel):
    name:str;email:EmailStr;password:str
    phone:Optional[str]=None;role:StaffRole=StaffRole.staff
class StaffOut(BaseModel):
    id:int;store_id:int;user_id:int;role:StaffRole;added_at:datetime;user:UserOut
    model_config={"from_attributes":True}

class CategoryCreate(BaseModel):
    name:str;order:int=0
class CategoryOut(BaseModel):
    id:int;store_id:int;name:str;order:int
    model_config={"from_attributes":True}

class ProductCreate(BaseModel):
    name:str;description:Optional[str]=None;price:float;stock:int=-1
    category_id:Optional[int]=None;image_b64:Optional[str]=None;is_active:bool=True
class ProductUpdate(BaseModel):
    name:Optional[str]=None;description:Optional[str]=None;price:Optional[float]=None
    stock:Optional[int]=None;category_id:Optional[int]=None
    image_b64:Optional[str]=None;is_active:Optional[bool]=None
class ProductOut(BaseModel):
    id:int;store_id:int;category_id:Optional[int];name:str
    description:Optional[str];price:float;stock:int;is_active:bool;image_b64:Optional[str]
    model_config={"from_attributes":True}

class QRCreate(BaseModel):
    table_label:str
class QROut(BaseModel):
    id:int;store_id:int;table_label:str;token:str;created_at:datetime
    qr_image_b64:Optional[str]=None
    model_config={"from_attributes":True}

class OrderItemIn(BaseModel):
    product_id:int;qty:int;notes:Optional[str]=None
class OrderCreate(BaseModel):
    qr_token:str;customer_name:Optional[str]=None;customer_phone:Optional[str]=None
    items:List[OrderItemIn];notes:Optional[str]=None;payment_method:str="webpay"
class OrderItemOut(BaseModel):
    id:int;product_id:int;qty:int;unit_price:float;notes:Optional[str];product:ProductOut
    model_config={"from_attributes":True}
class OrderOut(BaseModel):
    id:int;store_id:int;customer_name:Optional[str];customer_phone:Optional[str]
    total:float;status:OrderStatus;payment_status:PaymentStatus
    notes:Optional[str];created_at:datetime;updated_at:datetime;items:List[OrderItemOut]=[]
    model_config={"from_attributes":True}
class OrderStatusUpdate(BaseModel):
    status:OrderStatus

class PaymentOut(BaseModel):
    id:int;order_id:int;amount:float;method:str;status:PaymentStatus
    external_ref:Optional[str];created_at:datetime
    model_config={"from_attributes":True}

class DashboardMetrics(BaseModel):
    orders_today:int;revenue_today:float;orders_active:int
    orders_total:int;revenue_total:float;top_products:List[dict];orders_by_status:dict

class MenuProduct(BaseModel):
    id:int;name:str;description:Optional[str];price:float
    stock:int;image_b64:Optional[str];category_id:Optional[int]
    model_config={"from_attributes":True}
class MenuCategory(BaseModel):
    id:int;name:str;order:int;products:List[MenuProduct]=[]
    model_config={"from_attributes":True}
class MenuResponse(BaseModel):
    store_id:int;store_name:str;store_description:Optional[str]
    store_logo:Optional[str];table_label:str;categories:List[MenuCategory]
