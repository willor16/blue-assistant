"""Fase 3 — Correo por IMAP/SMTP (Gmail u otro). Sin OAuth ni MCP: usa una
'contraseña de aplicación' que Wilmer genera una vez y guarda en config.toml.

Revisar correos nuevos = cero tokens (es directo). Redactar el cuerpo de un
correo lo hace el cerebro; enviar es una acción directa (sin tokens).

config.toml:
    email_address = "tucorreo@gmail.com"
    email_app_password = "xxxx xxxx xxxx xxxx"   # passwords.google.com -> App passwords
    imap_host = "imap.gmail.com"     # opcional (Gmail por defecto)
    smtp_host = "smtp.gmail.com"     # opcional
"""
from __future__ import annotations
import email
import imaplib
import smtplib
import ssl
from email.header import decode_header
from email.message import EmailMessage

import config


def _creds():
    cfg = config.load()
    return (cfg.get("email_address", "").strip(),
            cfg.get("email_app_password", "").strip(),
            cfg.get("imap_host", "imap.gmail.com").strip(),
            cfg.get("smtp_host", "smtp.gmail.com").strip())


def _decode(raw) -> str:
    if not raw:
        return ""
    parts = []
    for txt, enc in decode_header(raw):
        if isinstance(txt, bytes):
            try:
                parts.append(txt.decode(enc or "utf-8", errors="replace"))
            except Exception:
                parts.append(txt.decode("utf-8", errors="replace"))
        else:
            parts.append(txt)
    return "".join(parts).strip()


def _sender_name(raw_from: str) -> str:
    """De 'Juan Pérez <juan@x.com>' saca 'Juan Pérez'; si no, el correo."""
    raw_from = _decode(raw_from)
    if "<" in raw_from:
        name = raw_from.split("<")[0].strip().strip('"')
        return name or raw_from.split("<")[1].rstrip(">")
    return raw_from


def check_unread(limit: int = 5) -> str:
    addr, pw, imap_host, _ = _creds()
    if not addr or not pw:
        return ("Aún no tengo configurado tu correo, Wilmer. Pon email_address y "
                "email_app_password en config.toml y te lo reviso encantado.")
    try:
        M = imaplib.IMAP4_SSL(imap_host)
        M.login(addr, pw)
        M.select("INBOX")
        typ, data = M.search(None, "UNSEEN")
        ids = data[0].split() if data and data[0] else []
        n = len(ids)
        if n == 0:
            M.logout()
            return "No tienes correos nuevos, Wilmer. Bandeja limpia, qué lujo."
        resumen = []
        for i in reversed(ids[-limit:]):
            typ, md = M.fetch(i, "(BODY.PEEK[HEADER.FIELDS (FROM SUBJECT)])")
            if not md or not md[0]:
                continue
            msg = email.message_from_bytes(md[0][1])
            quien = _sender_name(msg.get("From", ""))
            asunto = _decode(msg.get("Subject", "")) or "(sin asunto)"
            resumen.append(f"de {quien}, asunto: {asunto}")
        M.logout()
        cab = (f"Tienes {n} correo nuevo" if n == 1 else f"Tienes {n} correos nuevos")
        cola = "" if n <= limit else f" (te leo los {limit} más recientes)"
        return f"{cab}, Wilmer{cola}. " + "; ".join(resumen) + "."
    except Exception as e:
        return f"No pude entrar a tu correo, Wilmer: {str(e)[:120]}"


def send_email(to: str, subject: str, body: str) -> str:
    addr, pw, _, smtp_host = _creds()
    if not addr or not pw:
        return ("No tengo tu correo configurado todavía, jefe. Falta "
                "email_address y email_app_password en config.toml.")
    try:
        msg = EmailMessage()
        msg["From"] = addr
        msg["To"] = to
        msg["Subject"] = subject or "(sin asunto)"
        msg.set_content(body or "")
        ctx = ssl.create_default_context()
        with smtplib.SMTP_SSL(smtp_host, 465, context=ctx) as s:
            s.login(addr, pw)
            s.send_message(msg)
        return f"Correo enviado a {to}, Wilmer. Asunto: {subject}."
    except Exception as e:
        return f"No pude enviar el correo, Wilmer: {str(e)[:120]}"
