"""Catálogo e acesso aos originais; não faz ingestão nem altera embeddings."""
from __future__ import annotations
import argparse
import hashlib
import os
import re
from pathlib import Path
from app.db import get_conn

MAX_BYTES = 50 * 1024 * 1024
DATA_DIR = Path(os.environ.get('RAG_DOCUMENTS_DIR', str(Path(__file__).resolve().parent.parent / 'data'))).resolve()


def original_path(name: str) -> Path:
    if not name or not re.fullmatch(r'(?:[^/\\]+|_managed/[0-9a-f]{32}\.pdf)',name):
        raise ValueError('Nome de arquivo inválido.')
    if name in ('.','..'):
        raise ValueError('Nome de arquivo inválido.')
    path = DATA_DIR / name
    if path.is_symlink() or path.parent.is_symlink():
        raise ValueError('Links simbólicos não são permitidos.')
    resolved = path.resolve(strict=True)
    if DATA_DIR not in resolved.parents or not resolved.is_file() or resolved.suffix.lower() != '.pdf':
        raise ValueError('Original documental inválido.')
    return resolved


def file_info(path: Path) -> tuple[int, str]:
    digest = hashlib.sha256()
    total = 0
    with path.open('rb') as file:
        if file.read(5) != b'%PDF-':
            raise ValueError('Arquivo sem assinatura PDF.')
        file.seek(0)
        while block := file.read(1024 * 1024):
            total += len(block)
            if total > MAX_BYTES:
                raise ValueError('O limite desta etapa é 50 MiB por PDF.')
            digest.update(block)
    if not total:
        raise ValueError('Arquivo vazio.')
    return total, digest.hexdigest()


def register(source: str, title: str) -> dict:
    title = title.strip()
    if not 1 <= len(title) <= 300:
        raise ValueError('O título deve ter entre 1 e 300 caracteres.')
    path = original_path(source)
    size, sha = file_info(path)
    with get_conn() as conn:
        try:
            with conn.cursor() as cur:
                # Também bloqueia prepare/apply enquanto o vínculo é registrado.
                cur.execute("SET LOCAL lock_timeout = '10s'")
                cur.execute('LOCK TABLE "URX_PUBLIC".document_chunks IN SHARE MODE')
                cur.execute('SELECT count(*) FROM "URX_PUBLIC".document_chunks WHERE source_file=%s', (source,))
                count = cur.fetchone()[0]
                if not count:
                    raise ValueError('Fonte não indexada. Este comando somente cadastra uma carga existente.')
                cur.execute('''INSERT INTO "URX_PUBLIC".documents
                    (source_file,title,storage_name,sha256,size_bytes) VALUES (%s,%s,%s,%s,%s)
                    ON CONFLICT (source_file) DO NOTHING RETURNING doc_id''', (source,title,source,sha,size))
                inserted = cur.fetchone()
                if inserted:
                    doc_id = inserted[0]
                else:
                    cur.execute('SELECT doc_id,sha256,size_bytes FROM "URX_PUBLIC".documents WHERE source_file=%s', (source,))
                    doc_id, old_sha, old_size = cur.fetchone()
                    if old_sha != sha or old_size != size:
                        raise ValueError('Original diferente do catálogo. Não sobrescreva um documento cadastrado.')
                    cur.execute('UPDATE "URX_PUBLIC".documents SET title=%s WHERE doc_id=%s', (title,doc_id))
            conn.commit()
        except BaseException:
            conn.rollback()
            raise
    return {'id':doc_id,'source_file':source,'chunks':count,'size_bytes':size,'sha256':sha}


def list_documents() -> list[dict]:
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute('''SELECT d.doc_id,d.title,d.source_file,d.registered_at,d.size_bytes,
                (SELECT count(*) FROM "URX_PUBLIC".document_chunks c WHERE c.source_file=d.source_file),
                d.storage_name
                FROM "URX_PUBLIC".documents d ORDER BY lower(d.title),d.doc_id''')
            rows=cur.fetchall()
    result=[]
    for ident,title,source,date,size,count,name in rows:
        available=False
        try:
            available=original_path(name).stat().st_size == size
        except (OSError,ValueError):
            pass
        # Hash é conferido ao abrir/baixar; listagem não lê todos os PDFs.
        result.append(dict(id=ident,title=title,source_file=source,registered_at=date.isoformat(),
                           size_bytes=size,chunks=count,
                           status='disponível' if available and count else 'indisponível',
                           can_download=bool(available and count)))
    return result


def download_document(ident: int) -> tuple[Path,str]:
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute('''SELECT d.storage_name,d.source_file,d.sha256,d.size_bytes
                FROM "URX_PUBLIC".documents d WHERE d.doc_id=%s
                AND EXISTS (SELECT 1 FROM "URX_PUBLIC".document_chunks c WHERE c.source_file=d.source_file)''',(ident,))
            row=cur.fetchone()
    if not row:
        raise LookupError('Documento indisponível.')
    name,source,sha,size=row
    path=original_path(name)
    actual_size,actual_sha=file_info(path)
    if (size,sha)!=(actual_size,actual_sha):
        raise ValueError('O original foi alterado após o cadastro.')
    return path,source


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source',required=True,help='source_file exato já indexado e nome do PDF em data/.')
    parser.add_argument('--title',required=True)
    args=parser.parse_args()
    try:
        import json
        print(json.dumps(register(args.source,args.title),ensure_ascii=False,indent=2))
    except Exception as exc:
        raise SystemExit(f'Cadastro não concluído: {exc}') from exc

if __name__=='__main__': main()
