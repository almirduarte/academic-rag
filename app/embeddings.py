from __future__ import annotations

from functools import lru_cache

import torch
from sentence_transformers import SentenceTransformer

from app.config import settings


@lru_cache(maxsize=1)
def _model() -> SentenceTransformer:
    device = settings.embedding_device
    if device.startswith("cuda") and not torch.cuda.is_available():
        raise RuntimeError(
            "EMBEDDING_DEVICE está configurado como CUDA, mas o PyTorch não encontrou uma GPU. "
            "Confira o driver NVIDIA ou defina EMBEDDING_DEVICE=cpu no .env."
        )
    return SentenceTransformer(settings.embedding_model, device=device)


def _encode(texts: list[str]) -> list[list[float]]:
    if not texts:
        return []
    vectors = _model().encode(
        texts,
        batch_size=settings.embedding_batch_size,
        normalize_embeddings=True,
        convert_to_numpy=True,
        show_progress_bar=len(texts) > settings.embedding_batch_size,
    )
    if vectors.shape[1] != settings.embedding_dimensions:
        raise ValueError(
            f"O modelo gerou {vectors.shape[1]} dimensões, mas a configuração espera "
            f"{settings.embedding_dimensions}."
        )
    return vectors.tolist()


def embed_documents(texts: list[str]) -> list[list[float]]:
    """Gera embeddings de documentos com o prefixo exigido pelo E5."""
    return _encode([f"passage: {text}" for text in texts])


def embed_query(text: str) -> list[float]:
    """Gera embedding de consulta normalizado, com o prefixo exigido pelo E5."""
    normalized_text = " ".join(text.split()).casefold()
    return _encode([f"query: {normalized_text}"])[0]


def release_gpu_memory() -> None:
    """Libera VRAM do E5 antes de chamar o LLM local pelo Ollama."""
    model = _model()
    if model.device.type == "cuda":
        model.to("cpu")
        torch.cuda.empty_cache()
