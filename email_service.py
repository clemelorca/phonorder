import os
import logging
import resend

resend.api_key = os.getenv("RESEND_API_KEY", "")
FROM_EMAIL = "Skanorder <noreply@skanorder.com>"
log = logging.getLogger("skanorder.email")

def send_welcome_email(to: str, name: str, plan: str = "starter"):
    plan_names = {"starter": "Starter", "negocio": "Negocio", "cadena": "Cadena"}
    plan_label = plan_names.get(plan, "Starter")
    try:
        resend.Emails.send({
            "from": FROM_EMAIL,
            "to": [to],
            "subject": "Bienvenido a Skanorder",
            "html": f"""
            <div style="font-family:sans-serif;max-width:560px;margin:0 auto;color:#111;">
              <img src="https://skanorder.com/static/skanorder.svg" alt="Skanorder" style="height:40px;margin-bottom:24px;">
              <h2 style="margin:0 0 8px;">Hola {name}, bienvenido/a 👋</h2>
              <p>Tu cuenta en Skanorder fue creada exitosamente con el plan <strong>{plan_label}</strong>.</p>
              <p>Ya puedes entrar a tu panel y comenzar a configurar tu tienda.</p>
              <a href="https://skanorder.com/admin" style="display:inline-block;background:#01696f;color:#fff;padding:12px 24px;border-radius:8px;text-decoration:none;font-weight:600;margin:16px 0;">
                Ir a mi panel →
              </a>
              <p style="color:#666;font-size:14px;margin-top:32px;">Si tienes dudas escríbenos a <a href="mailto:hola@skanorder.com">hola@skanorder.com</a></p>
            </div>
            """
        })
    except Exception as e:
        log.exception("send_welcome_email failed for %s: %s", to, e)

def send_password_reset_email(to: str, name: str, reset_token: str):
    reset_url = f"https://skanorder.com/reset-password?token={reset_token}"
    try:
        resend.Emails.send({
            "from": FROM_EMAIL,
            "to": [to],
            "subject": "Recuperar contraseña — Skanorder",
            "html": f"""
            <div style="font-family:sans-serif;max-width:560px;margin:0 auto;color:#111;">
              <img src="https://skanorder.com/static/skanorder.svg" alt="Skanorder" style="height:40px;margin-bottom:24px;">
              <h2 style="margin:0 0 8px;">Recuperar contraseña</h2>
              <p>Hola {name}, recibimos una solicitud para restablecer tu contraseña.</p>
              <a href="{reset_url}" style="display:inline-block;background:#01696f;color:#fff;padding:12px 24px;border-radius:8px;text-decoration:none;font-weight:600;margin:16px 0;">
                Restablecer contraseña →
              </a>
              <p style="color:#666;font-size:13px;">Este enlace expira en 30 minutos. Si no solicitaste esto, ignora este email.</p>
            </div>
            """
        })
    except Exception as e:
        log.exception("send_password_reset_email failed for %s: %s", to, e)
