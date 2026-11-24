"""Autenticação local. Endpoints acessíveis somente pelo PHP com X-API-Key."""
from __future__ import annotations
import hashlib
import hmac
import os
import re
import secrets
import threading
import time
from collections import deque
from ipaddress import IPv4Address

from argon2 import PasswordHasher, Type
from argon2.exceptions import VerificationError, InvalidHashError
from fastapi import APIRouter, Depends, Header, HTTPException
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator
from psycopg2.errors import UniqueViolation
from psycopg2.extras import RealDictCursor
from app.config import settings  # carrega .env antes de ler a chave
from app.db import get_conn
from app.email_verification import issue_confirmation, confirm_email
from app.sectors import validate_sector

API_TOKEN = os.getenv('RAG_API_TOKEN', '')
SESSION_SECONDS = 8 * 60 * 60
hasher = PasswordHasher(type=Type.ID)
dummy_hash = hasher.hash(secrets.token_urlsafe(32))
rate_lock = threading.Lock()
crypto_lock = threading.Lock()
attempts: dict[str, deque] = {}


def require_api_key(x_api_key: str | None = Header(default=None, alias='X-API-Key')):
    if not API_TOKEN or not hmac.compare_digest(x_api_key or '', API_TOKEN):
        raise HTTPException(401, 'Acesso não autorizado.')


router = APIRouter(prefix='/auth', dependencies=[Depends(require_api_key)])


def limit_attempts(ip: str):
    """20 tentativas por IP em 15 minutos, neste processo (um worker)."""
    now = time.monotonic()
    with rate_lock:
        for key in list(attempts):
            while attempts[key] and attempts[key][0] <= now - 900:
                attempts[key].popleft()
            if not attempts[key]:
                del attempts[key]
        queue = attempts.setdefault(ip, deque())
        if len(queue) >= 20:
            raise HTTPException(429, 'Muitas tentativas. Aguarde 15 minutos.')
        queue.append(now)


def normalize_email(value: str) -> str:
    value = value.strip().lower()
    if len(value) > 50 or not re.fullmatch(r"[a-z0-9.!#$%&'*+/=?^_`{|}~-]+@[a-z0-9](?:[a-z0-9.-]*[a-z0-9])?\.[a-z]{2,63}", value):
        raise ValueError('Informe um e-mail válido com até 50 caracteres.')
    return value


def validate_cpf(value: str) -> str:
    if not re.fullmatch(r'[0-9.\-\s]+', value):
        raise ValueError('CPF inválido.')
    value = re.sub(r'\D', '', value)
    if len(value) != 11 or len(set(value)) == 1:
        raise ValueError('CPF inválido.')
    for size in (9, 10):
        digit = (sum(int(value[i]) * (size + 1 - i) for i in range(size)) * 10) % 11
        if (0 if digit == 10 else digit) != int(value[size]):
            raise ValueError('CPF inválido.')
    return value


class LoginRequest(BaseModel):
    email: str = Field(max_length=100)
    password: str = Field(min_length=1, max_length=128)
    ip_address: IPv4Address
    _email = field_validator('email')(normalize_email)


class RegisterRequest(LoginRequest):
    password: str = Field(min_length=8, max_length=128)
    full_name: str = Field(min_length=3, max_length=200)
    cpf: str = Field(max_length=20)
    sector: int = Field(strict=True)
    _sector = field_validator('sector')(validate_sector)
    _cpf = field_validator('cpf')(validate_cpf)

    @field_validator('full_name')
    @classmethod
    def full_name_valid(cls, value):
        value = ' '.join(value.split())
        if len(value.split()) < 2 or any(ord(c) < 32 for c in value):
            raise ValueError('Informe nome e sobrenome.')
        return value


def token_hash(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def current_user(authorization: str | None = Header(default=None)) -> dict:
    if not authorization or not authorization.startswith('Bearer '):
        raise HTTPException(401, 'Sua sessão expirou. Entre novamente.')
    token = authorization[7:]
    if not re.fullmatch(r'[A-Za-z0-9_-]{43}', token):
        raise HTTPException(401, 'Sessão inválida.')
    with get_conn() as conn:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute('''SELECT u.use_id, u.use_nome_completo, u.use_email, u.use_admin,
                    u.use_cpf, u.use_setor
                FROM "URX_PUBLIC".auth_sessions s
                JOIN "URX_PUBLIC".users u ON u.use_id = s.user_id
                WHERE s.token_hash = %s AND s.expires_at > now() AND u.use_email_confirmed''', (token_hash(token),))
            user = cur.fetchone()
    if not user:
        raise HTTPException(401, 'Sua sessão expirou. Entre novamente.')
    return dict(user)


@router.post('/register', status_code=201)
def register(data: RegisterRequest):
    limit_attempts(str(data.ip_address))
    with crypto_lock:
        password_hash = hasher.hash(data.password)
    try:
        with get_conn() as conn:
            with conn.cursor() as cur:
                cur.execute('''INSERT INTO "URX_PUBLIC".users
                    (use_setor, use_password, use_cpf, use_email, use_nome_completo, use_ip_address, use_email_confirmed)
                    VALUES (%s,%s,%s,%s,%s,%s,FALSE)''',
                    (data.sector, password_hash, data.cpf, data.email, data.full_name, str(data.ip_address)))
            conn.commit()
    except UniqueViolation:
        raise HTTPException(409, 'Não foi possível cadastrar com os dados informados. Se já possui cadastro, entre com seu e-mail e senha.') from None
    sent = issue_confirmation(data.email)
    return {'message': (
        'Cadastro criado. Confira seu e-mail para confirmar o endereço antes de entrar. Verifique também a pasta de spam.'
        if sent else
        'Cadastro criado, mas não foi possível enviar a confirmação agora. Aguarde um minuto e use Reenviar confirmação. Sua conta permanece pendente.'
    )}


@router.post('/login')
def login(data: LoginRequest):
    limit_attempts(str(data.ip_address))
    with get_conn() as conn:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            # Mesmo lock das alterações de senha/e-mail: impede que um login
            # concorrente crie sessão com credenciais antigas após a revogação.
            cur.execute('SELECT * FROM "URX_PUBLIC".users WHERE lower(use_email) = %s FOR UPDATE', (data.email,))
            user = cur.fetchone()
            with crypto_lock:
                try:
                    hasher.verify(user['use_password'] if user else dummy_hash, data.password)
                except (VerificationError, InvalidHashError):
                    raise HTTPException(401, 'E-mail ou senha inválidos.') from None
                if not user:
                    raise HTTPException(401, 'E-mail ou senha inválidos.')
                if not user['use_email_confirmed']:
                    raise HTTPException(403, 'Confirme seu e-mail antes de entrar. Se necessário, use Reenviar confirmação.')
                if hasher.check_needs_rehash(user['use_password']):
                    cur.execute('UPDATE "URX_PUBLIC".users SET use_password=%s WHERE use_id=%s',
                                (hasher.hash(data.password), user['use_id']))
            token = secrets.token_urlsafe(32)
            cur.execute('DELETE FROM "URX_PUBLIC".auth_sessions WHERE expires_at <= now()')
            cur.execute('''INSERT INTO "URX_PUBLIC".auth_sessions (token_hash,user_id,expires_at)
                VALUES (%s,%s,now() + %s * interval '1 second')''',
                (token_hash(token), user['use_id'], SESSION_SECONDS))
        conn.commit()
    return {'token': token, 'expires_in': SESSION_SECONDS,
            'user': {'id': user['use_id'], 'full_name': user['use_nome_completo']}}


@router.post('/logout')
def logout(authorization: str | None = Header(default=None)):
    if authorization and authorization.startswith('Bearer '):
        with get_conn() as conn:
            with conn.cursor() as cur:
                cur.execute('DELETE FROM "URX_PUBLIC".auth_sessions WHERE token_hash=%s',
                            (token_hash(authorization[7:]),))
            conn.commit()
    return {'message': 'Sessão encerrada.'}


class ResendRequest(BaseModel):
    email: str = Field(max_length=100)
    ip_address: IPv4Address
    _email = field_validator('email')(normalize_email)


class ConfirmRequest(BaseModel):
    token: str = Field(pattern=r'^[A-Za-z0-9_-]{43}$')
    ip_address: IPv4Address


@router.post('/resend-confirmation')
def resend_confirmation(data: ResendRequest):
    limit_attempts(str(data.ip_address))
    issue_confirmation(data.email)
    return {'message': 'Se houver cadastro pendente, enviaremos uma confirmação. Verifique também o spam e aguarde ao menos um minuto antes de solicitar novamente. Se não receber, procure o administrador.'}


@router.post('/confirm-email')
def confirm_registration(data: ConfirmRequest):
    limit_attempts(str(data.ip_address))
    if not confirm_email(data.token):
        raise HTTPException(400, 'Link inválido, expirado ou já utilizado. Tente entrar ou solicite uma nova confirmação.')
    return {'message': 'E-mail confirmado. Você já pode entrar com seu e-mail e senha.'}


def require_admin(user: dict = Depends(current_user)) -> dict:
    if not user.get('use_admin', False):
        raise HTTPException(403, 'Operação permitida somente a administradores.')
    return user


def profile_fields(user: dict) -> dict:
    """Lista explícita; nunca retornar hash de senha, papel administrativo ou sessão."""
    return dict(id=user['use_id'], full_name=user['use_nome_completo'],
                email=user['use_email'], cpf=user['use_cpf'], sector=user['use_setor'])


class ProfileUpdateRequest(BaseModel):
    model_config = ConfigDict(extra='forbid')
    full_name: str = Field(min_length=3, max_length=200)
    email: str = Field(max_length=100)
    cpf: str = Field(max_length=20)
    sector: int = Field(strict=True)
    current_password: str = Field(min_length=1, max_length=128)
    ip_address: IPv4Address
    _email = field_validator('email')(normalize_email)
    _cpf = field_validator('cpf')(validate_cpf)
    _sector = field_validator('sector')(validate_sector)

    @field_validator('full_name')
    @classmethod
    def full_name_valid(cls, value):
        return RegisterRequest.full_name_valid(value)


class PasswordChangeRequest(BaseModel):
    model_config = ConfigDict(extra='forbid')
    current_password: str = Field(min_length=1, max_length=128)
    new_password: str = Field(min_length=8, max_length=128)
    password_confirmation: str = Field(min_length=8, max_length=128)
    ip_address: IPv4Address

    @model_validator(mode='after')
    def matching_passwords(self):
        if self.new_password != self.password_confirmation:
            raise ValueError('A confirmação da nova senha não confere.')
        if self.new_password == self.current_password:
            raise ValueError('A nova senha deve ser diferente da senha atual.')
        return self


def locked_account(cur, user_id: int, authorization: str | None) -> dict:
    # user_id sempre vem de current_user, nunca do corpo submetido.
    cur.execute('SELECT * FROM "URX_PUBLIC".users WHERE use_id=%s FOR UPDATE', (user_id,))
    account = cur.fetchone()
    token = authorization[7:] if authorization and authorization.startswith('Bearer ') else ''
    if not account or not account['use_email_confirmed'] or not re.fullmatch(r'[A-Za-z0-9_-]{43}', token):
        raise HTTPException(401, 'Sua sessão expirou. Entre novamente.')
    # A dependência pode ter autorizado a sessão antes de outra transação
    # trocar a senha. Reconfere depois de adquirir o lock do usuário.
    cur.execute('''SELECT 1 FROM "URX_PUBLIC".auth_sessions
        WHERE user_id=%s AND token_hash=%s AND expires_at>clock_timestamp()''',
        (user_id, token_hash(token)))
    if not cur.fetchone():
        raise HTTPException(401, 'Sua sessão expirou. Entre novamente.')
    return dict(account)


def verify_current_password(account: dict, password: str) -> None:
    with crypto_lock:
        try:
            hasher.verify(account['use_password'], password)
        except (VerificationError, InvalidHashError):
            raise HTTPException(400, 'A senha atual não confere.') from None


@router.post('/profile')
def profile(user: dict = Depends(current_user)):
    return {'user': profile_fields(user)}


@router.post('/update-profile')
def update_profile(data: ProfileUpdateRequest, user: dict = Depends(current_user),
                   authorization: str | None = Header(default=None)):
    limit_attempts(str(data.ip_address))
    email_changed = False
    try:
        with get_conn() as conn:
            with conn.cursor(cursor_factory=RealDictCursor) as cur:
                account = locked_account(cur, user['use_id'], authorization)
                verify_current_password(account, data.current_password)
                email_changed = account['use_email'].lower() != data.email
                cur.execute('''UPDATE "URX_PUBLIC".users
                    SET use_nome_completo=%s, use_email=%s, use_cpf=%s, use_setor=%s
                    WHERE use_id=%s RETURNING use_id, use_nome_completo, use_email, use_cpf, use_setor''',
                    (data.full_name, data.email, data.cpf, data.sector, account['use_id']))
                updated = dict(cur.fetchone())
                if email_changed:
                    cur.execute('''UPDATE "URX_PUBLIC".users
                        SET use_email_confirmed=FALSE, use_email_confirmed_at=NULL WHERE use_id=%s''',
                        (account['use_id'],))
                    cur.execute('DELETE FROM "URX_PUBLIC".auth_sessions WHERE user_id=%s', (account['use_id'],))
                    cur.execute('DELETE FROM "URX_PUBLIC".email_confirmations WHERE user_id=%s', (account['use_id'],))
            conn.commit()
    except UniqueViolation:
        raise HTTPException(409, 'Não foi possível salvar: e-mail ou CPF já utilizado em outro cadastro.') from None
    if email_changed:
        # Reutiliza confirmação e reenvio existentes. Falha de SMTP não desfaz
        # cadastro já salvo nem reativa sessões com o endereço anterior.
        try:
            sent = issue_confirmation(data.email)
        except Exception as exc:
            import logging
            logging.getLogger(__name__).error('Falha ao emitir confirmação após alterar e-mail (%s).', type(exc).__name__)
            sent = False
        message = ('Dados salvos. As sessões foram encerradas. Confirme o novo e-mail antes de entrar novamente.'
                   if sent else 'Dados salvos e sessões encerradas, mas não foi possível enviar a confirmação. '
                   'Use Reenviar confirmação com o novo e-mail antes de entrar novamente.')
        return dict(message=message, reauthenticate=True, email_confirmation_required=True)
    return dict(message='Dados atualizados.', user=profile_fields(updated),
                reauthenticate=False, email_confirmation_required=False)


@router.post('/change-password')
def change_password(data: PasswordChangeRequest, user: dict = Depends(current_user),
                    authorization: str | None = Header(default=None)):
    limit_attempts(str(data.ip_address))
    with get_conn() as conn:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            account = locked_account(cur, user['use_id'], authorization)
            verify_current_password(account, data.current_password)
            with crypto_lock:
                password_hash = hasher.hash(data.new_password)
            cur.execute('UPDATE "URX_PUBLIC".users SET use_password=%s WHERE use_id=%s',
                        (password_hash, account['use_id']))
            cur.execute('DELETE FROM "URX_PUBLIC".auth_sessions WHERE user_id=%s', (account['use_id'],))
        conn.commit()
    return dict(message='Senha alterada. Todas as sessões foram encerradas. Entre com a nova senha.',
                reauthenticate=True)
