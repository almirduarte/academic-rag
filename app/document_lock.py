"""Sincroniza a leitura RAG com a publicação atômica dos documentos."""
from contextlib import contextmanager
from app.db import get_conn
CATALOG_LOCK = 714202601
WORKER_LOCK = 714202602

@contextmanager
def catalog_read():
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute('SELECT pg_advisory_xact_lock_shared(%s)',(CATALOG_LOCK,))
        yield
        # get_conn fecha a conexão e libera o lock inclusive se ocorrer exceção.
