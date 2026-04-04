from database import (SessionLocal,create_tables,User,Store,Category,Product,QRCode,
    Order,OrderItem,Payment,UserRole,StaffRole,StoreStaff,Plan,OrderStatus,PaymentStatus,PaymentMethod)
from auth import hash_password
import uuid,random
from datetime import datetime,timedelta

create_tables()
db=SessionLocal()
for M in [Payment,OrderItem,Order,QRCode,StoreStaff,Product,Category,Store,User]:
    db.query(M).delete()
db.commit()

su=User(name="Super Admin",email="super@skanorder.com",password_hash=hash_password("skanorder2026"),role=UserRole.superadmin)
admin=User(name="Claudia Moreno",email="admin@cafefondue.cl",password_hash=hash_password("admin1234"),role=UserRole.admin,phone="+56 9 8765 4321")
db.add_all([su,admin]);db.commit()

store=Store(owner_id=admin.id,name="Cafe Fondue",description="Cafeteria artesanal en Santiago centro.",address="Av. O'Higgins 340, Santiago",plan=Plan.negocio)
db.add(store);db.commit()

s1=User(name="Rodrigo Vega",email="staff1@cafefondue.cl",password_hash=hash_password("staff1234"),role=UserRole.staff)
s2=User(name="Valentina Rios",email="staff2@cafefondue.cl",password_hash=hash_password("staff1234"),role=UserRole.staff)
db.add_all([s1,s2]);db.commit()
db.add(StoreStaff(store_id=store.id,user_id=s1.id,role=StaffRole.manager))
db.add(StoreStaff(store_id=store.id,user_id=s2.id,role=StaffRole.staff))

hot=Category(store_id=store.id,name="Bebidas calientes",order=1)
cold=Category(store_id=store.id,name="Bebidas frias",order=2)
food=Category(store_id=store.id,name="Comida",order=3)
post=Category(store_id=store.id,name="Postres",order=4)
db.add_all([hot,cold,food,post]);db.commit()

raw=[(hot.id,"Cafe Americano","Cafe colombiano tostado medio",1800,-1),
     (hot.id,"Cafe Latte","Espresso doble con leche",2500,-1),
     (hot.id,"Cappuccino","Espresso leche y espuma",2500,-1),
     (hot.id,"Te Verde","Sencha japones",1500,-1),
     (hot.id,"Chocolate Caliente","Cacao 70% leche entera",2800,-1),
     (cold.id,"Frappe de Cafe","Cafe helado batido",3200,20),
     (cold.id,"Limonada Natural","Limon agua mineral menta",2200,-1),
     (cold.id,"Jugo de Naranja","Naranja fresca exprimida",2800,15),
     (cold.id,"Agua Mineral","500ml",800,-1),
     (food.id,"Tostado Jamon Queso","Pan jamon artesanal queso gouda",3500,-1),
     (food.id,"Croissant Mantequilla","Recien horneado",2800,12),
     (food.id,"Avocado Toast","Pan palta tomate huevo",4500,-1),
     (food.id,"Empanada de Queso","Masa casera horneada",2200,20),
     (post.id,"Cheesecake Frutilla","Cremoso con frutilla",3800,8),
     (post.id,"Brownie Chocolate","Humedo chips belgica",2500,15),
     (post.id,"Muffin Arandanos","Esponjoso arandanos",2000,20)]
prods=[]
for cid,name,desc,price,stock in raw:
    p=Product(store_id=store.id,category_id=cid,name=name,description=desc,price=price,stock=stock)
    db.add(p);prods.append(p)
db.commit()

tokens={}
for lbl in ["Mesa 1","Mesa 2","Mesa 3","Mesa 4","Mesa 5","Barra","Terraza"]:
    tok=uuid.uuid4().hex
    db.add(QRCode(store_id=store.id,table_label=lbl,token=tok));tokens[lbl]=tok
db.commit()

qr=db.query(QRCode).filter(QRCode.store_id==store.id).first()
demos=[("Ana Garcia","+56 9 1111 2222",[0,1,9],OrderStatus.delivered,PaymentStatus.paid),
       ("Luis Herrera","+56 9 3333 4444",[5,10],OrderStatus.delivered,PaymentStatus.paid),
       ("Maria Paz",None,[2,14],OrderStatus.delivered,PaymentStatus.paid),
       ("Felipe Torres","+56 9 5555 6666",[1,13,15],OrderStatus.preparing,PaymentStatus.paid),
       ("Sofia Leon",None,[6,11],OrderStatus.confirmed,PaymentStatus.paid),
       ("Diego Munoz","+56 9 7777 8888",[3,12],OrderStatus.pending,PaymentStatus.pending)]
for name,phone,idxs,ost,pst in demos:
    items=[(prods[i],random.randint(1,2)) for i in idxs]
    total=sum(p.price*q for p,q in items)
    ago=timedelta(minutes=random.randint(5,90))
    o=Order(store_id=store.id,qr_id=qr.id,customer_name=name,customer_phone=phone,
            total=total,status=ost,payment_status=pst,
            created_at=datetime.utcnow()-ago,updated_at=datetime.utcnow()-ago)
    db.add(o);db.flush()
    for p,qty in items: db.add(OrderItem(order_id=o.id,product_id=p.id,qty=qty,unit_price=p.price))
    db.add(Payment(order_id=o.id,amount=total,method=PaymentMethod.webpay,status=pst,
        external_ref=f"WEBPAY-{uuid.uuid4().hex[:8].upper()}" if pst==PaymentStatus.paid else None))
db.commit()

print("\n" + "="*55)
print("  OK  Base de datos lista!")
print("="*55)
print(f"  Superadmin -> super@skanorder.com / skanorder2026")
print(f"  Admin      -> admin@cafefondue.cl / admin1234")
print(f"  Staff 1    -> staff1@cafefondue.cl / staff1234")
print(f"  Staff 2    -> staff2@cafefondue.cl / staff1234")
print(f"\n  Menu Mesa 1:")
print(f"  http://localhost:8000/menu?token={tokens['Mesa 1']}")
print("="*55)
db.close()
