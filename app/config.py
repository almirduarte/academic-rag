from __future__ import annotations

import os
from dataclasses import dataclass
from dotenv import load_dotenv

load_dotenv()


def configured_app_name() -> str:
    value = " ".join(os.getenv("APP_NAME", "Farol Acadêmico").split())
    if not value:
        return "Farol Acadêmico"
    if len(value) > 120 or not value.isprintable():
        raise ValueError("APP_NAME deve ter até 120 caracteres imprimíveis.")
    return value


@dataclass(frozen=True)
class Settings:
    app_name: str = configured_app_name()
    embedding_model: str = os.getenv("EMBEDDING_MODEL", "intfloat/multilingual-e5-base")
    embedding_dimensions: int = int(os.getenv("EMBEDDING_DIMENSIONS", "768"))
    embedding_device: str = os.getenv("EMBEDDING_DEVICE", "cuda")
    embedding_batch_size: int = int(os.getenv("EMBEDDING_BATCH_SIZE", "8"))

    ollama_url: str = os.getenv("OLLAMA_URL", "http://localhost:11434").rstrip("/")
    ollama_model: str = os.getenv("OLLAMA_MODEL", "qwen3:1.7b")
    ollama_num_ctx: int = int(os.getenv("OLLAMA_NUM_CTX", "4096"))
    ollama_num_predict: int = int(os.getenv("OLLAMA_NUM_PREDICT", "300"))
    ollama_timeout_seconds: int = int(os.getenv("OLLAMA_TIMEOUT_SECONDS", "240"))

    public_url: str = os.getenv("FAROL_PUBLIC_URL", "https://farol-academico.uranux.com.br").rstrip("/")
    smtp_host: str = os.getenv("SMTP_HOST", "")
    smtp_port: int = int(os.getenv("SMTP_PORT", "587"))
    smtp_security: str = os.getenv("SMTP_SECURITY", "starttls")
    smtp_user: str = os.getenv("SMTP_USER", "")
    smtp_password: str = os.getenv("SMTP_PASSWORD", "")
    smtp_from: str = os.getenv("SMTP_FROM", "")

    pg_host: str = os.getenv("PGHOST", "localhost")
    pg_port: int = int(os.getenv("PGPORT", "5432"))
    pg_database: str = os.getenv("PGDATABASE", "academic_rag")
    pg_user: str = os.getenv("PGUSER", "postgres")
    pg_password: str = os.getenv("PGPASSWORD", "postgres")

    top_k: int = int(os.getenv("TOP_K", "3"))
    chunk_size: int = int(os.getenv("CHUNK_SIZE", "1200"))
    chunk_overlap: int = int(os.getenv("CHUNK_OVERLAP", "150"))


settings = Settings()
