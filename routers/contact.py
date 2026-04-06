from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, EmailStr
from typing import Optional
import os, resend

router = APIRouter(tags=["contact"])

class ContactForm(BaseModel):
    name: str
    email: EmailStr
    phone: Optional[str] = None
    message: str

@router.post("/contact")
async def send_contact(data: ContactForm):
    api_key = os.getenv("RESEND_API_KEY", "")
    if not api_key:
        raise HTTPException(503, "Servicio de email no configurado")

    resend.api_key = api_key

    html = f"""
    <div style="font-family:sans-serif;max-width:600px;margin:0 auto">
      <h2 style="color:#01696f">Nuevo mensaje de contacto · Skanorder</h2>
      <table style="width:100%;border-collapse:collapse;margin-top:1rem">
        <tr><td style="padding:.6rem;font-weight:700;color:#7a7974;width:120px">Nombre</td><td style="padding:.6rem">{data.name}</td></tr>
        <tr style="background:#f7f6f2"><td style="padding:.6rem;font-weight:700;color:#7a7974">Email</td><td style="padding:.6rem"><a href="mailto:{data.email}">{data.email}</a></td></tr>
        <tr><td style="padding:.6rem;font-weight:700;color:#7a7974">Teléfono</td><td style="padding:.6rem">{data.phone or '—'}</td></tr>
        <tr style="background:#f7f6f2"><td style="padding:.6rem;font-weight:700;color:#7a7974;vertical-align:top">Mensaje</td><td style="padding:.6rem">{data.message}</td></tr>
      </table>
      <p style="margin-top:1.5rem;font-size:.8rem;color:#bab9b4">Enviado desde skanorder.com</p>
    </div>
    """

    try:
        resend.Emails.send({
            "from": "Skanorder Contact <noreply@skanorder.com>",
            "to": ["sales@skanorder.com"],
            "reply_to": data.email,
            "subject": f"Consulta de {data.name} · Skanorder",
            "html": html,
        })
    except Exception as e:
        raise HTTPException(502, "Error al enviar el mensaje")

    return {"ok": True}
