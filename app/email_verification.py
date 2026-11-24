"""Confirmação de e-mail: tokens opacos, uso único e armazenamento somente do hash."""
from __future__ import annotations
import hashlib
import logging
import secrets
import smtplib
import ssl
from email.message import EmailMessage
from email.utils import formatdate, make_msgid
from urllib.parse import urlsplit
from app.config import settings
from app.db import get_conn

logger = logging.getLogger(__name__)
TTL_SECONDS = 86400


def send_confirmation(address: str, token: str) -> None:
    base = urlsplit(settings.public_url)
    if (base.scheme != 'https' or not base.netloc or base.username or base.password
            or base.query or base.fragment):
        raise ValueError('FAROL_PUBLIC_URL precisa ser uma URL HTTPS fixa.')
    if not settings.smtp_host or not settings.smtp_from:
        raise ValueError('Configure SMTP_HOST e SMTP_FROM.')
    if settings.smtp_security not in ('starttls', 'ssl'):
        raise ValueError('SMTP_SECURITY deve ser starttls ou ssl.')
    if bool(settings.smtp_user) != bool(settings.smtp_password):
        raise ValueError('Configure usuário e senha SMTP juntos.')
    message = EmailMessage()
    message['From'] = settings.smtp_from
    message['To'] = address
    message['Subject'] = f'{settings.app_name} — confirme seu e-mail'
    message['Date'] = formatdate(localtime=False)
    message['Message-ID'] = make_msgid()
    # Fragmento não é enviado nos logs de acesso HTTP. O navegador o envia por POST.
    link = f'{settings.public_url}/confirmar-email.php#token={token}'
    message.set_content(
        f'Foi solicitada a confirmação deste endereço em {settings.app_name}, '
        'para cadastro ou alteração de e-mail.\n\n'
        'Para confirmar, abra o link e pressione Confirmar e-mail:\n'
        f'{link}\n\n'
        'O link é válido por 24 horas e só pode ser usado uma vez. '
        'Se você solicitou outro link, utilize o mais recente.\n\n'
        'Se você não solicitou esta confirmação, ignore esta mensagem. '
        'Não compartilhe o link.\n'
    )
    context = ssl.create_default_context()
    if settings.smtp_security == 'ssl':
        client = smtplib.SMTP_SSL(settings.smtp_host, settings.smtp_port, timeout=10, context=context)
    else:
        client = smtplib.SMTP(settings.smtp_host, settings.smtp_port, timeout=10)
    with client:
        if settings.smtp_security == 'starttls':
            client.ehlo()
            client.starttls(context=context)
            client.ehlo()
        if settings.smtp_user:
            client.login(settings.smtp_user, settings.smtp_password)
        client.send_message(message)


def issue_confirmation(email: str) -> bool:
    token = secrets.token_urlsafe(32)
    digest = hashlib.sha256(token.encode()).hexdigest()
    with get_conn() as conn:
        with conn.cursor() as cur:
            # Uma emissão por usuário a cada minuto, inclusive entre workers.
            cur.execute('''SELECT use_id, use_email_confirmed FROM "URX_PUBLIC".users
                WHERE lower(use_email) = %s FOR UPDATE''', (email,))
            user = cur.fetchone()
            if not user or user[1]:
                return False
            cur.execute('''INSERT INTO "URX_PUBLIC".email_confirmations
                (user_id, token_hash, expires_at, issued_at)
                VALUES (%s,%s,now() + %s * interval '1 second', now())
                ON CONFLICT (user_id) DO UPDATE
                SET token_hash=EXCLUDED.token_hash, expires_at=EXCLUDED.expires_at,
                    issued_at=EXCLUDED.issued_at
                WHERE email_confirmations.issued_at <= now() - interval '60 seconds'
                RETURNING user_id''', (user[0], digest, TTL_SECONDS))
            if not cur.fetchone():
                return False
        conn.commit()
    # Commit antes do SMTP: se o envio falhar, a conta continua pendente.
    try:
        send_confirmation(email, token)
    except Exception as exc:
        # Não registrar credenciais SMTP, endereço, corpo ou token.
        logger.error('Falha no envio de confirmação (%s).', type(exc).__name__)
        return False
    return True


def confirm_email(token: str) -> bool:
    digest = hashlib.sha256(token.encode()).hexdigest()
    with get_conn() as conn:
        with conn.cursor() as cur:
            # Mesma ordem de locks do reenvio; rechecagem após adquirir o lock.
            cur.execute('''SELECT u.use_id FROM "URX_PUBLIC".users u
                JOIN "URX_PUBLIC".email_confirmations c ON c.user_id=u.use_id
                WHERE c.token_hash=%s AND NOT u.use_email_confirmed
                FOR UPDATE OF u''', (digest,))
            row = cur.fetchone()
            if not row:
                return False
            cur.execute('''DELETE FROM "URX_PUBLIC".email_confirmations
                WHERE user_id=%s AND token_hash=%s AND expires_at>clock_timestamp()
                RETURNING user_id''', (row[0], digest))
            if not cur.fetchone():
                return False
            cur.execute('''UPDATE "URX_PUBLIC".users
                SET use_email_confirmed=TRUE, use_email_confirmed_at=now()
                WHERE use_id=%s''', (row[0],))
        conn.commit()
    return True
