"""Worker único, com fila persistente no PostgreSQL e publicação transacional."""
from __future__ import annotations
import gc
import hashlib
import json
import logging
import os
from pathlib import Path
import shutil
import time
import uuid
from psycopg2.extras import RealDictCursor, execute_values
from app.config import settings
from app.db import get_conn, _vector_literal
from app.document_admin import JOBS_DIR, job_path
from app.document_catalog import DATA_DIR, original_path, file_info
from app.document_lock import CATALOG_LOCK, WORKER_LOCK
from app.document_text import extract_document, make_chunks, reading_map
from app.documents_store import snapshot, fingerprint
from app.documents import validate

logging.basicConfig(level=logging.INFO)
log=logging.getLogger(__name__)

def write_json(path,value):
    path.write_text(json.dumps(value,ensure_ascii=False,allow_nan=False),encoding='utf-8')
    path.chmod(0o600)

def set_failed(ident,message):
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("UPDATE \"URX_PUBLIC\".document_jobs SET state='failed',message=%s,updated_at=now() WHERE job_id=%s AND state IN ('processing','publishing')",(message,str(ident)))
        conn.commit()

def claim():
    with get_conn() as conn:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute("SELECT * FROM \"URX_PUBLIC\".document_jobs WHERE state IN ('queued','approved') ORDER BY created_at FOR UPDATE SKIP LOCKED LIMIT 1")
            job=cur.fetchone()
            if not job: return None
            cur.execute("UPDATE \"URX_PUBLIC\".document_jobs SET state=%s,message=%s,updated_at=now() WHERE job_id=%s",
                        ('processing' if job['state']=='queued' else 'publishing','Processamento iniciado.',str(job['job_id'])))
        conn.commit()
    return dict(job)

def authorized(cur,user_id):
    cur.execute('SELECT 1 FROM "URX_PUBLIC".users WHERE use_id=%s AND use_admin AND use_email_confirmed',(user_id,))
    if not cur.fetchone(): raise ValueError('O solicitante não possui mais autorização administrativa.')

def prepare(job):
    ident=job['job_id']; path=job_path(ident,'.pdf')
    with get_conn() as conn:
        with conn.cursor() as cur: authorized(cur,job['requested_by'])
    _,sha=file_info(path)
    if sha!=job['upload_sha256']: raise ValueError('O arquivo recebido foi alterado.')
    text,meta=extract_document(path,max_pages=300,max_chars=500_000)
    if len(text)>500_000 or (meta['pages'] or 0)>300:
        raise ValueError('Limite desta versão: 300 páginas e 500 mil caracteres extraídos por PDF.')
    chunks=make_chunks(text,settings.chunk_size,settings.chunk_overlap)
    summary=reading_map(text,chunks)
    # Worker usa CPU para não disputar a VRAM com Ollama durante as consultas.
    import torch
    from sentence_transformers import SentenceTransformer
    torch.set_num_threads(2)
    model=SentenceTransformer(settings.embedding_model,device='cpu')
    try:
        vectors=model.encode(['passage: '+c['content'] for c in chunks]+['passage: '+summary],
                             batch_size=settings.embedding_batch_size,normalize_embeddings=True,
                             convert_to_numpy=True,show_progress_bar=False).tolist()
    finally:
        del model
        gc.collect()
    replacement={'source_file':job['source_file'],
                 'chunks':[dict(chunk_index=c['chunk_index'],content=c['content'],embedding=v) for c,v in zip(chunks,vectors)],
                 'summaries':[dict(summary_type='work',book_number=None,content=summary,embedding=vectors[-1])]}
    if len(vectors)!=len(chunks)+1: raise ValueError('Número inesperado de embeddings.')
    validate(replacement,settings.embedding_dimensions)
    meta.update(chunks=len(chunks),embedding_model=settings.embedding_model,embedding_dimensions=settings.embedding_dimensions)
    prepared={'replacement':replacement,'metadata':meta}
    write_json(job_path(ident,'.json'),prepared)
    job_path(ident,'.txt').write_text(text,encoding='utf-8')
    write_json(job_path(ident,'.meta.json'),meta)
    digest=hashlib.sha256(job_path(ident,'.json').read_bytes()).hexdigest()
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("UPDATE \"URX_PUBLIC\".document_jobs SET state='review',prepared_sha256=%s,message='Confira o texto extraído e autorize a publicação.',updated_at=now() WHERE job_id=%s AND state='processing'",(digest,str(ident)))
        conn.commit()

def publish(job):
    ident=job['job_id']; operation=job['operation']; staged=None; destination=None; old_path=None
    if operation!='delete':
        blob=job_path(ident,'.json').read_bytes()
        if hashlib.sha256(blob).hexdigest()!=job['prepared_sha256']: raise ValueError('Preparação alterada; reenvie o PDF.')
        prepared=json.loads(blob); replacement=prepared['replacement']
        if prepared['metadata']['embedding_model']!=settings.embedding_model: raise ValueError('Modelo de embeddings mudou; reenvie o PDF.')
        validate(replacement,settings.embedding_dimensions)
        if replacement['source_file']!=job['source_file']: raise ValueError('Fonte da preparação incompatível.')
        staged=job_path(ident,'.pdf'); size,sha=file_info(staged)
        if sha!=job['upload_sha256']: raise ValueError('PDF alterado após o envio.')
        managed=DATA_DIR/'_managed'; managed.mkdir(mode=0o700,parents=True,exist_ok=True)
        if managed.is_symlink(): raise ValueError('Pasta gerenciada não pode ser link simbólico.')
        storage='_managed/'+uuid.UUID(str(ident)).hex+'.pdf'
        destination=DATA_DIR/storage
        # Arquivo completo e imutável antes de qualquer alteração nas linhas ativas.
        with staged.open('rb') as inp, destination.open('xb') as out:
            shutil.copyfileobj(inp,out); out.flush(); os.fsync(out.fileno())
        destination.chmod(0o600)
    committed=False
    try:
        with get_conn() as conn:
            try:
                with conn.cursor() as cur:
                    cur.execute("SET LOCAL lock_timeout='120s'")
                    cur.execute('SELECT pg_advisory_xact_lock(%s)',(CATALOG_LOCK,))
                    cur.execute('LOCK TABLE "URX_PUBLIC".documents, "URX_PUBLIC".document_chunks, "URX_PUBLIC".document_summaries IN SHARE ROW EXCLUSIVE MODE')
                    cur.execute('SELECT state FROM "URX_PUBLIC".document_jobs WHERE job_id=%s FOR UPDATE',(str(ident),))
                    if cur.fetchone() != ('publishing',):
                        raise ValueError('A tarefa não está mais autorizada para publicação.')
                    authorized(cur,job['requested_by'])
                    if operation!='include':
                        cur.execute('SELECT source_file,revision,storage_name FROM "URX_PUBLIC".documents WHERE doc_id=%s',(job['document_id'],))
                        current=cur.fetchone()
                        if not current or current[:2]!=(job['expected_source'],job['expected_revision']):
                            raise ValueError('Documento mudou desde a solicitação. Reenvie a operação.')
                        if fingerprint(snapshot(cur,current[0]))!=job['expected_fingerprint']:
                            raise ValueError('Trechos ou resumo mudaram desde a solicitação.')
                        try: old_path=original_path(current[2])
                        except FileNotFoundError: pass
                    if operation=='include' or job['source_file']!=job['expected_source']:
                        cur.execute('''SELECT 1 FROM "URX_PUBLIC".documents WHERE source_file=%s
                            UNION ALL SELECT 1 FROM "URX_PUBLIC".document_chunks WHERE source_file=%s
                            UNION ALL SELECT 1 FROM "URX_PUBLIC".document_summaries WHERE source_file=%s LIMIT 1''',
                            (job['source_file'],)*3)
                        if cur.fetchone(): raise ValueError('Nome de destino já foi ocupado.')
                    if operation!='include':
                        cur.execute('DELETE FROM "URX_PUBLIC".document_summaries WHERE source_file=%s',(job['expected_source'],))
                        cur.execute('DELETE FROM "URX_PUBLIC".document_chunks WHERE source_file=%s',(job['expected_source'],))
                    if operation=='delete':
                        cur.execute('DELETE FROM "URX_PUBLIC".documents WHERE doc_id=%s',(job['document_id'],))
                    else:
                        source=job['source_file']
                        execute_values(cur,'INSERT INTO "URX_PUBLIC".document_chunks (source_file,chunk_index,content,embedding) VALUES %s',
                            [(source,c['chunk_index'],c['content'],_vector_literal(c['embedding'])) for c in replacement['chunks']],template='(%s,%s,%s,%s::vector)')
                        execute_values(cur,'INSERT INTO "URX_PUBLIC".document_summaries (source_file,summary_type,book_number,content,embedding) VALUES %s',
                            [(source,s['summary_type'],s['book_number'],s['content'],_vector_literal(s['embedding'])) for s in replacement['summaries']],template='(%s,%s,%s,%s,%s::vector)')
                        if operation=='include':
                            cur.execute('''INSERT INTO "URX_PUBLIC".documents (source_file,title,storage_name,sha256,size_bytes)
                                VALUES (%s,%s,%s,%s,%s) RETURNING doc_id''',(source,job['title'],storage,sha,size))
                            job['document_id']=cur.fetchone()[0]
                        else:
                            cur.execute('''UPDATE "URX_PUBLIC".documents SET source_file=%s,title=%s,storage_name=%s,sha256=%s,
                                size_bytes=%s,revision=revision+1,registered_at=now() WHERE doc_id=%s''',
                                (source,job['title'],storage,sha,size,job['document_id']))
                    cur.execute("UPDATE \"URX_PUBLIC\".document_jobs SET state='done',document_id=%s,message='Operação concluída.',updated_at=now() WHERE job_id=%s",(job['document_id'],str(ident)))
                conn.commit(); committed=True
            except BaseException:
                conn.rollback(); raise
    finally:
        if not committed and destination:
            # Uma falha no retorno de COMMIT pode ocorrer após confirmação no servidor.
            # Preserve o arquivo; nunca remova um PDF possivelmente já ativo.
            log.warning('Arquivo gerenciado preservado após falha; conferir referência no catálogo: %s', destination)
    # Os arquivos antigos não ficam disponíveis como versões históricas.
    if old_path:
        try: old_path.unlink(missing_ok=True)
        except OSError:
            log.exception('Carga publicada, mas o original antigo não pôde ser removido: %s',old_path)
            with get_conn() as conn:
                with conn.cursor() as cur:
                    cur.execute("UPDATE \"URX_PUBLIC\".document_jobs SET message='Base atualizada; administrador deve conferir a remoção do arquivo antigo no disco.' WHERE job_id=%s",(str(ident),))
                conn.commit()

def cleanup():
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT job_id FROM \"URX_PUBLIC\".document_jobs WHERE state IN ('done','failed','cancelled')")
            ids=[r[0] for r in cur.fetchall()]
    for ident in ids:
        for suffix in ('.pdf','.json','.txt','.meta.json'):
            try: job_path(ident,suffix).unlink(missing_ok=True)
            except OSError: log.exception('Falha ao limpar temporário de %s',ident)

def main():
    os.umask(0o077); JOBS_DIR.mkdir(mode=0o700,parents=True,exist_ok=True)
    # Conexão dedicada mantém a exclusividade do worker inclusive entre tarefas.
    with get_conn() as guard:
        guard.autocommit=True
        with guard.cursor() as cur:
            cur.execute('SELECT pg_try_advisory_lock(%s)',(WORKER_LOCK,))
            if not cur.fetchone()[0]: raise SystemExit('Já existe um worker documental ativo.')
            cur.execute("UPDATE \"URX_PUBLIC\".document_jobs SET state='failed',message='Execução interrompida. Reenvie a operação; a transação não confirmada foi desfeita.',updated_at=now() WHERE state IN ('processing','publishing')")
        log.info('Worker documental iniciado; embeddings em CPU.')
        while True:
            # Detecta perda da conexão que mantém o lock; systemd reinicia.
            with guard.cursor() as cur: cur.execute('SELECT 1')
            cleanup(); job=claim()
            if not job:
                time.sleep(2); continue
            try:
                if job['state']=='queued': prepare(job)
                else: publish(job)
            except Exception as exc:
                log.exception('Falha na tarefa %s',job['job_id'])
                message=str(exc) if isinstance(exc,ValueError) else 'Falha no processamento. Consulte o log do worker.'
                set_failed(job['job_id'],message)

if __name__=='__main__': main()
