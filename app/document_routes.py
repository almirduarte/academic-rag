"""Rotas somente de leitura, protegidas pela chave PHP e pela sessão do usuário."""
import logging
from typing import Literal
from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse
from starlette.background import BackgroundTask
from urllib.parse import quote
from app.document_lock import catalog_read
from pydantic import BaseModel, Field
from app.auth import current_user, require_api_key
from app.document_catalog import list_documents, download_document

logger=logging.getLogger(__name__)
router=APIRouter(prefix='/documents',dependencies=[Depends(require_api_key),Depends(current_user)])

class DownloadRequest(BaseModel):
    id: int = Field(gt=0)
    disposition: Literal['inline','attachment'] = 'attachment'

@router.post('/list')
def documents(user: dict = Depends(current_user)):
    try:
        return {'documents':list_documents(), 'is_admin':bool(user.get('use_admin', False))}
    except Exception as exc:
        logger.exception('Falha ao listar catálogo documental')
        raise HTTPException(503,'Não foi possível consultar os documentos.') from exc

@router.post('/download')
def download(data: DownloadRequest):
    try:
        with catalog_read():
            path,name=download_document(data.id)
            handle=path.open('rb')
    except LookupError:
        raise HTTPException(404,'Documento indisponível.') from None
    except (OSError,ValueError):
        raise HTTPException(409,'O original está ausente ou foi alterado. Solicite a conferência ao administrador.') from None
    except Exception as exc:
        logger.exception('Falha ao consultar original documental')
        raise HTTPException(503,'Não foi possível acessar o documento.') from exc
    def stream():
        try:
            while block := handle.read(1024 * 1024):
                yield block
        finally:
            handle.close()
    return StreamingResponse(stream(),media_type='application/pdf',background=BackgroundTask(handle.close),
        headers={'Cache-Control':'no-store','X-Content-Type-Options':'nosniff',
                 'Content-Disposition':data.disposition+"; filename*=UTF-8''"+quote(name,safe='')})
