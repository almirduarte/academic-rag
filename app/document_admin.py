"""Fila administrativa. Upload não altera a base consultável."""
from __future__ import annotations
import hashlib
import json
import os
from pathlib import Path
import re
import uuid
from fastapi import APIRouter, Depends, HTTPException, Request, Query
from pydantic import BaseModel, Field
from psycopg2.errors import UniqueViolation
from psycopg2.extras import RealDictCursor
from app.auth import require_api_key, require_admin
from app.db import get_conn
from app.document_catalog import DATA_DIR, MAX_BYTES, file_info
from app.documents_store import snapshot, fingerprint

JOBS_DIR=Path(os.environ.get('RAG_DOCUMENT_JOBS_DIR',str(Path(__file__).resolve().parent.parent/'.document-jobs'))).resolve()
if JOBS_DIR == DATA_DIR or DATA_DIR in JOBS_DIR.parents:
    raise RuntimeError('A pasta de tarefas deve ficar fora de data/.')
router=APIRouter(prefix='/documents/admin',dependencies=[Depends(require_api_key)])
ACTIVE=('queued','processing','review','approved','publishing')

def job_path(job_id, suffix):
    return JOBS_DIR / (uuid.UUID(str(job_id)).hex + suffix)

def valid_source(value):
    if not value or len(value)>255 or value in ('.','..') or re.search(r'[/\\\x00-\x1f\x7f]',value) or not value.lower().endswith('.pdf'):
        raise ValueError('Informe um nome de PDF sem diretórios e com até 255 caracteres.')
    return value

def add_job(job_id, operation, source, title, document_id, user_id, upload_sha=None, confirmation=None):
    with get_conn() as conn:
        try:
            with conn.cursor(cursor_factory=RealDictCursor) as cur:
                cur.execute("SET LOCAL lock_timeout='10s'")
                cur.execute('LOCK TABLE "URX_PUBLIC".documents IN SHARE ROW EXCLUSIVE MODE')
                revision=old_source=old_fingerprint=None
                if operation!='include':
                    cur.execute('SELECT * FROM "URX_PUBLIC".documents WHERE doc_id=%s',(document_id,))
                    doc=cur.fetchone()
                    if not doc: raise ValueError('Documento não encontrado.')
                    revision=doc['revision']; old_source=doc['source_file']
                    if operation=='delete':
                        if confirmation!=old_source: raise ValueError('Digite o nome exato do arquivo para confirmar a exclusão.')
                        source=old_source; title=doc['title']
                    # snapshot usa cursor convencional (retorno de tuplas).
                    with conn.cursor() as plain:
                        old_fingerprint=fingerprint(snapshot(plain,old_source))
                if operation=='include' or source!=old_source:
                    cur.execute('''SELECT 1 FROM "URX_PUBLIC".documents WHERE source_file=%s
                        UNION ALL SELECT 1 FROM "URX_PUBLIC".document_chunks WHERE source_file=%s
                        UNION ALL SELECT 1 FROM "URX_PUBLIC".document_summaries WHERE source_file=%s LIMIT 1''',(source,source,source))
                    if cur.fetchone(): raise ValueError('Esse nome já está cadastrado ou indexado. Use Substituir no documento existente.')
                cur.execute('''INSERT INTO "URX_PUBLIC".document_jobs
                    (job_id,operation,state,document_id,requested_by,source_file,title,expected_revision,
                     expected_source,expected_fingerprint,upload_sha256)
                    VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)''',
                    (str(job_id),operation,'approved' if operation=='delete' else 'queued',document_id,user_id,
                     source,title,revision,old_source,old_fingerprint,upload_sha))
            conn.commit()
        except BaseException:
            conn.rollback(); raise

@router.post('/upload',status_code=202)
async def upload(request: Request, operation: str=Query(pattern='^(include|replace)$'),
                 source_file: str=Query(max_length=255), title: str=Query(min_length=1,max_length=300),
                 document_id: int | None=Query(default=None,gt=0), user: dict=Depends(require_admin)):
    try:
        source=valid_source(source_file)
        if not title.strip(): raise ValueError('Informe o título.')
        if operation=='replace' and document_id is None: raise ValueError('Selecione o documento a substituir.')
        if operation=='include' and document_id is not None: raise ValueError('Inclusão não recebe documento de origem.')
    except ValueError as exc: raise HTTPException(422,str(exc)) from exc
    JOBS_DIR.mkdir(mode=0o700,parents=True,exist_ok=True)
    ident=uuid.uuid4(); path=job_path(ident,'.pdf'); total=0
    try:
        with path.open('xb') as output:
            path.chmod(0o600)
            async for block in request.stream():
                total+=len(block)
                if total>MAX_BYTES: raise HTTPException(413,'O limite é 50 MiB por PDF.')
                output.write(block)
        _,sha=file_info(path)
        add_job(ident,operation,source,title.strip(),document_id,user['use_id'],sha)
    except BaseException as exc:
        path.unlink(missing_ok=True)
        if isinstance(exc,UniqueViolation): raise HTTPException(409,'Já existe uma tarefa pendente para esse documento ou nome.') from exc
        if isinstance(exc,ValueError): raise HTTPException(422,str(exc)) from exc
        raise
    return {'job_id':str(ident),'message':'Arquivo recebido. Aguarde o processamento e confira o texto extraído antes de publicar.'}

class DeleteRequest(BaseModel):
    document_id: int=Field(gt=0)
    confirmation: str

@router.post('/delete',status_code=202)
def delete(data:DeleteRequest,user:dict=Depends(require_admin)):
    ident=uuid.uuid4()
    try: add_job(ident,'delete','','',data.document_id,user['use_id'],confirmation=data.confirmation)
    except UniqueViolation: raise HTTPException(409,'Já existe uma tarefa pendente para esse documento.') from None
    except ValueError as exc: raise HTTPException(422,str(exc)) from exc
    return {'job_id':str(ident),'message':'Exclusão confirmada e colocada na fila.'}

@router.post('/jobs')
def jobs(user:dict=Depends(require_admin)):
    with get_conn() as conn:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute('''SELECT job_id,operation,state,document_id,source_file,title,message,created_at,updated_at
                FROM "URX_PUBLIC".document_jobs ORDER BY created_at DESC LIMIT 50''')
            return {'jobs':[dict(r) for r in cur.fetchall()]}

class JobRequest(BaseModel):
    job_id: uuid.UUID

@router.post('/preview')
def preview(data:JobRequest,user:dict=Depends(require_admin)):
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute('SELECT state FROM "URX_PUBLIC".document_jobs WHERE job_id=%s',(str(data.job_id),))
            row=cur.fetchone()
    if not row or row[0]!='review': raise HTTPException(409,'O texto não está disponível para revisão.')
    try:
        text=job_path(data.job_id,'.txt').read_text(encoding='utf-8')
        meta=json.loads(job_path(data.job_id,'.meta.json').read_text())
    except (OSError,ValueError): raise HTTPException(409,'Preparação indisponível; cancele e reenvie o arquivo.') from None
    return {'text':text,'metadata':meta}

@router.post('/approve')
def approve(data:JobRequest,user:dict=Depends(require_admin)):
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute('''UPDATE "URX_PUBLIC".document_jobs SET state='approved',updated_at=now(),message='Publicação autorizada.'
                WHERE job_id=%s AND state='review' RETURNING job_id''',(str(data.job_id),))
            if not cur.fetchone(): raise HTTPException(409,'Tarefa não está aguardando revisão.')
        conn.commit()
    return {'message':'Publicação autorizada e colocada na fila.'}

@router.post('/cancel')
def cancel(data:JobRequest,user:dict=Depends(require_admin)):
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute('''UPDATE "URX_PUBLIC".document_jobs SET state='cancelled',updated_at=now(),message='Cancelado pelo administrador.'
                WHERE job_id=%s AND state IN ('queued','review','approved') RETURNING job_id''',(str(data.job_id),))
            if not cur.fetchone(): raise HTTPException(409,'A tarefa já está executando ou foi encerrada.')
        conn.commit()
    return {'message':'Tarefa cancelada.'}
