from __future__ import annotations

from contextlib import contextmanager
from typing import Iterable

import psycopg2
from psycopg2.extras import RealDictCursor, execute_values

from app.config import settings


def _dsn() -> str:
    return (
        f"host={settings.pg_host} "
        f"port={settings.pg_port} "
        f"dbname={settings.pg_database} "
        f"user={settings.pg_user} "
        f"password={settings.pg_password}"
    )


@contextmanager
def get_conn():
    conn = psycopg2.connect(
        _dsn(),
        options='-c search_path="URX_PUBLIC",public',
    )
    try:
        yield conn
    finally:
        conn.close()


def ensure_schema(embedding_dimensions: int) -> None:
    """Create the table if absent; this function does not alter an existing table."""
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("CREATE EXTENSION IF NOT EXISTS vector;")
            cur.execute(
                f'''
                CREATE TABLE IF NOT EXISTS document_chunks (
                    id BIGSERIAL PRIMARY KEY,
                    source_file TEXT NOT NULL,
                    chunk_index INTEGER NOT NULL,
                    content TEXT NOT NULL,
                    embedding vector({embedding_dimensions}) NOT NULL,
                    created_at TIMESTAMP NOT NULL DEFAULT NOW()
                );
                '''
            )
            cur.execute(
                '''
                CREATE INDEX IF NOT EXISTS idx_document_chunks_source_file
                ON document_chunks (source_file);
                '''
            )
        conn.commit()


def count_chunks() -> int:
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT COUNT(*) FROM document_chunks;")
            return int(cur.fetchone()[0])


def get_source_files() -> set[str]:
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("""
                SELECT DISTINCT source_file
                FROM document_chunks
            """)
            return {row[0] for row in cur.fetchall()}
        
        
def clear_chunks() -> None:
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("TRUNCATE TABLE document_chunks RESTART IDENTITY;")
        conn.commit()


def _vector_literal(embedding: list[float]) -> str:
    return "[" + ",".join(str(float(x)) for x in embedding) + "]"


def insert_chunks(rows: Iterable[tuple[str, int, str, list[float]]]) -> None:
    values = [
        (source_file, chunk_index, content, _vector_literal(embedding))
        for source_file, chunk_index, content, embedding in rows
    ]
    if not values:
        return

    with get_conn() as conn:
        with conn.cursor() as cur:
            execute_values(
                cur,
                '''
                INSERT INTO document_chunks (source_file, chunk_index, content, embedding)
                VALUES %s
                ''',
                values,
                template="(%s, %s, %s, %s::vector)",
                page_size=100,
            )
        conn.commit()


def search_similar_chunks(embedding: list[float], top_k: int) -> list[dict]:
    vector_literal = _vector_literal(embedding)
    with get_conn() as conn:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute(
                '''
                SELECT source_file, chunk_index, content,
                       embedding <=> %s::vector AS distance
                FROM document_chunks
                ORDER BY embedding <=> %s::vector
                LIMIT %s;
                ''',
                (vector_literal, vector_literal, top_k),
            )
            rows = cur.fetchall()
    return [dict(row) for row in rows]


def search_similar_summaries(
    embedding: list[float],
    top_k: int = 1,
) -> list[dict]:
    vector_literal = _vector_literal(embedding)
    with get_conn() as conn:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute(
                """
                SELECT source_file, content,
                       embedding <=> %s::vector AS distance
                FROM document_summaries
                WHERE summary_type = 'work'
                  AND book_number IS NULL
                ORDER BY embedding <=> %s::vector
                LIMIT %s;
                """,
                (vector_literal, vector_literal, top_k),
            )
            return [dict(row) for row in cur.fetchall()]


def get_chunk_window(
    source_file: str,
    first_index: int,
    last_index: int,
) -> list[dict]:
    with get_conn() as conn:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute(
                """
                SELECT source_file, chunk_index, content
                FROM document_chunks
                WHERE source_file = %s
                  AND chunk_index BETWEEN %s AND %s
                ORDER BY chunk_index
                """,
                (source_file, first_index, last_index),
            )
            return [dict(row) for row in cur.fetchall()]

def get_document_chunks(
    source_file: str,
    first_index: int,
    last_index: int,
) -> list[dict]:
    with get_conn() as conn:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute(
                """
                SELECT chunk_index, content
                FROM document_chunks
                WHERE source_file = %s
                  AND chunk_index BETWEEN %s AND %s
                ORDER BY chunk_index
                """,
                (source_file, first_index, last_index),
            )
            return [dict(row) for row in cur.fetchall()]


def save_document_summary(
    source_file: str,
    summary_type: str,
    book_number: int | None,
    content: str,
    embedding: list[float],
) -> None:
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                DELETE FROM document_summaries
                WHERE source_file = %s
                  AND summary_type = %s
                  AND COALESCE(book_number, 0) = COALESCE(%s, 0)
                """,
                (source_file, summary_type, book_number),
            )
            cur.execute(
                """
                INSERT INTO document_summaries
                    (source_file, summary_type, book_number, content, embedding)
                VALUES (%s, %s, %s, %s, %s::vector)
                """,
                (
                    source_file,
                    summary_type,
                    book_number,
                    content,
                    _vector_literal(embedding),
                ),
            )
        conn.commit()



def record_query(question: str, user_id: int, ip_address: str) -> int:
    """Registra a consulta do usuário autenticado antes da inferência."""
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute('''INSERT INTO "URX_PUBLIC".transactions
                (tra_user, tra_ip_address, tra_request)
                VALUES (%s, %s, %s) RETURNING tra_id''',
                (user_id, ip_address, question))
            transaction_id = int(cur.fetchone()[0])
        conn.commit()
    return transaction_id


def read_retrieval_snapshot(
    question: str,
    embedding: list[float],
    candidates: int = 20,
    max_corpus: int = 5000,
) -> dict:
    """Leitura consistente para o recuperador experimental. Nenhuma gravação.

    O limite impede carregar silenciosamente um acervo maior que o ensaiado.
    A transação termina antes da inferência BGE. O chamador mantém catalog_read.
    """
    if type(candidates) is not int or type(max_corpus) is not int or min(candidates, max_corpus) < 1:
        raise ValueError('Limites inválidos para leitura do acervo.')
    literal = _vector_literal(embedding)
    with get_conn() as conn:
        conn.set_session(isolation_level='REPEATABLE READ', readonly=True)
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute("SELECT tsvector_to_array(to_tsvector('pg_catalog.portuguese', %s)) AS terms", (question,))
            terms = cur.fetchone()['terms']
            cur.execute('''SELECT source_file, chunk_index, content,
                tsvector_to_array(to_tsvector('pg_catalog.portuguese', content)) AS lexemes
                FROM document_chunks ORDER BY source_file, chunk_index LIMIT %s''', (max_corpus + 1,))
            corpus = [dict(row) for row in cur.fetchall()]
            if len(corpus) > max_corpus:
                raise RuntimeError(f'Acervo excede {max_corpus} trechos; leitura integral interrompida.')
            cur.execute('''SELECT source_file, chunk_index, content,
                embedding <=> %s::vector AS distance
                FROM document_chunks
                ORDER BY embedding <=> %s::vector, source_file, chunk_index LIMIT %s''',
                (literal, literal, candidates))
            hits = [dict(row) for row in cur.fetchall()]
    return dict(corpus=corpus, vector_candidates=hits, query_lexemes=terms)
