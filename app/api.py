from __future__ import annotations

import logging
import threading
from ipaddress import IPv4Address

from fastapi import FastAPI, HTTPException, Depends
from pydantic import BaseModel, Field

from app.query import run_query, NoContextError
from app.config import settings
from app.db import record_query
from app.auth import router as auth_router, current_user, require_api_key

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = FastAPI(title=f"{settings.app_name} — API")
app.include_router(auth_router)
from app.document_routes import router as document_router
app.include_router(document_router)
from app.document_admin import router as document_admin_router
app.include_router(document_admin_router)
inference_lock = threading.Lock()


class AskRequest(BaseModel):
    question: str = Field(min_length=1, max_length=2000)
    ip_address: IPv4Address


@app.post("/app/config", dependencies=[Depends(require_api_key)])
def app_config():
    # Lista explícita: nunca serializar settings, que contém segredos.
    return {"app_name": settings.app_name}


@app.get("/health")
def health():
    return {"status": "ok"}


@app.post("/ask", dependencies=[Depends(require_api_key)])
def ask(
    request: AskRequest,
    user: dict = Depends(current_user),
):
    question = request.question.strip()
    if not question:
        raise HTTPException(status_code=422, detail="Informe uma pergunta.")

    # Commit independente: preserva o registro mesmo se a inferência falhar.
    # Registra antes de aguardar a fila de processamento.
    try:
        transaction_id = record_query(
            question=question,
            user_id=user["use_id"],
            ip_address=str(request.ip_address),
        )
    except Exception as exc:
        logger.exception("Falha ao registrar a consulta")
        raise HTTPException(
            status_code=503,
            detail="Não foi possível registrar a consulta. Tente novamente mais tarde.",
        ) from exc

    with inference_lock:
        try:
            result = run_query(question)
            if result["output_limit_reached"]:
                logger.warning(
                    "Consulta %s: resposta atingiu o limite de saída",
                    transaction_id,
                )
        except NoContextError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except RuntimeError as exc:
            logger.exception("Falha ao consultar o modelo local")
            raise HTTPException(status_code=502, detail=str(exc)) from exc
        except Exception as exc:
            logger.exception("Falha ao processar a pergunta")
            raise HTTPException(
                status_code=500,
                detail="Falha interna ao processar a pergunta.",
            ) from exc

    return {"transaction_id": transaction_id, **result}
