"""Operações documentais isoladas; nenhuma alteração nas tabelas de autenticação."""
import hashlib
import json
import struct
from app.db import get_conn, _vector_literal


def fingerprint(value):
    # pgvector armazena float32; a representação decimal devolvida pode mudar.
    canonical = json.loads(json.dumps(value))
    for item in canonical['chunks'] + canonical['summaries']:
        item['embedding'] = [struct.pack('!f', float(x)).hex() for x in item['embedding']]
    return hashlib.sha256(json.dumps(canonical, sort_keys=True, ensure_ascii=False,
                                    separators=(',', ':')).encode()).hexdigest()


def snapshot(cur, source):
    cur.execute('''SELECT chunk_index, content, embedding::text
                   FROM document_chunks WHERE source_file=%s ORDER BY chunk_index, id''', (source,))
    chunks = [{'chunk_index': i, 'content': t, 'embedding': json.loads(v)} for i,t,v in cur.fetchall()]
    cur.execute('''SELECT summary_type, book_number, content, embedding::text
                   FROM document_summaries WHERE source_file=%s
                   ORDER BY summary_type, COALESCE(book_number,0), id''', (source,))
    summaries = [{'summary_type': s, 'book_number': b, 'content': t, 'embedding': json.loads(v)}
                 for s,b,t,v in cur.fetchall()]
    return {'source_file': source, 'chunks': chunks, 'summaries': summaries}


def read_snapshot(source):
    with get_conn() as conn:
        conn.set_session(isolation_level='REPEATABLE READ', readonly=True)
        with conn.cursor() as cur:
            return snapshot(cur, source)


def replace_atomic(expected, replacement):
    """API deve estar parada: uma consulta RAG abre várias conexões independentes."""
    from psycopg2.extras import execute_values
    old = expected['source_file']
    new = replacement['source_file']
    with get_conn() as conn:
        try:
            with conn.cursor() as cur:
                cur.execute("SET LOCAL lock_timeout = '10s'")
                # Bloqueia inclusive os gravadores antigos que não usam advisory lock.
                cur.execute('LOCK TABLE document_chunks, document_summaries IN SHARE ROW EXCLUSIVE MODE')
                current = snapshot(cur, old)
                if fingerprint(current) != fingerprint(expected):
                    raise ValueError('A fonte mudou desde a preparação; prepare novamente.')
                if new != old:
                    destination = snapshot(cur, new)
                    if destination['chunks'] or destination['summaries']:
                        raise ValueError('A fonte de destino já existe; substituição recusada.')
                cur.execute('DELETE FROM document_summaries WHERE source_file=%s', (old,))
                cur.execute('DELETE FROM document_chunks WHERE source_file=%s', (old,))
                execute_values(cur, '''INSERT INTO document_chunks
                    (source_file, chunk_index, content, embedding) VALUES %s''',
                    [(new,c['chunk_index'],c['content'],_vector_literal(c['embedding']))
                     for c in replacement['chunks']],
                    template='(%s,%s,%s,%s::vector)', page_size=100)
                if replacement['summaries']:
                    execute_values(cur, '''INSERT INTO document_summaries
                        (source_file, summary_type, book_number, content, embedding) VALUES %s''',
                        [(new,s['summary_type'],s['book_number'],s['content'],_vector_literal(s['embedding']))
                         for s in replacement['summaries']],
                        template='(%s,%s,%s,%s,%s::vector)', page_size=100)
            conn.commit()
        except BaseException:
            conn.rollback()
            raise


def get_definition_chunks(source):
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(r'''SELECT source_file,chunk_index,content FROM document_chunks
                WHERE source_file=%s
                  AND (content ~ 'Ciclo[[:space:]]+Escolar[[:space:]]*\(CE\)'
                       OR content ~ 'Ciclo[[:space:]]+Pós-Escolar[[:space:]]*\(CPE\)')
                ORDER BY chunk_index LIMIT 2''', (source,))
            return [dict(zip(('source_file','chunk_index','content'),row)) for row in cur.fetchall()]
