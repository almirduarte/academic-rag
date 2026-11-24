"""Extração e mapa extrativo. Perfis de correção são vinculados ao SHA-256."""
from pathlib import Path
import hashlib
import re

NCGEN_2026_SHA256 = '1ec7cd6b78bcfe295ea38e63c0e015aad8705534776aca814fb55eda3fa78756'
HEADING = re.compile(r'(?m)^(\d+(?:\.\d+)*\.)\s+([A-ZÀ-Ý][A-ZÀ-Ý0-9ºª /()–—-]+)\s*$')


def extract_document(path: Path, *, max_pages: int | None = None, max_chars: int | None = None) -> tuple[str, dict]:
    digest = hashlib.sha256(path.read_bytes()).hexdigest()
    if path.suffix.lower() == '.txt':
        text = path.read_text(encoding='utf-8').strip()
        pages = None
    elif path.suffix.lower() == '.pdf':
        from pypdf import PdfReader
        reader = PdfReader(path)
        pages = len(reader.pages)
        if max_pages is not None and pages > max_pages:
            raise ValueError(f'PDF excede o limite de {max_pages} páginas.')
        parts = []
        total = 0
        for page in reader.pages:
            part = (page.extract_text() or '').strip()
            total += len(part) + 1
            if max_chars is not None and total > max_chars:
                raise ValueError(f'Texto excede o limite de {max_chars} caracteres.')
            parts.append(part)
        if any(not x for x in parts):
            raise ValueError('PDF contém página sem texto extraível; confira/OCR antes de indexar.')
        text = '\n'.join(parts)
    else:
        raise ValueError('Somente PDF ou TXT UTF-8.')
    profile = 'texto-sem-correcao-especifica'
    repairs = 0
    if digest == NCGEN_2026_SHA256:
        profile = 'ncgen-197-2026-revisado'
        # Retira cabeçalhos/rodapés repetidos, inclusive entre numerador e denominador.
        text = re.sub(r'(?m)^Continuação do anexo, da Port nº 197/2026, da DEnsM\.\s*$', '', text)
        text = re.sub(r'(?m)^\s*-\s*\d+ de 23\s*-\s*', '', text)
        # A fração interna de TT1 deve ser tratada antes das frações simples.
        pattern = r'TT1\s*=\s*\[\(Av¹\s*\+\s*Av²\s*\+\s*\.\.\.\s*\+\s*Av\s+n\s*\)\s*\+\s*2\s*T1\]\s*/\s*3\s*\n\s*n\b'
        text, n = re.subn(pattern, 'TT1 = [((Av¹ + Av² + ... + Avn) / n) + 2 T1] / 3', text)
        if n != 1:
            raise ValueError('Perfil do PDF: não foi possível conferir a fração de TT1.')
        repairs += n
        # Expressões exibidas no PDF com numerador numa linha e divisor na seguinte.
        pattern = r'(?m)^(?P<lhs>(?:GC1\s*=\s*G1|GC[234]|G[234]|MD|MFT1|PP[12]|GTFM|NC|AO|GFC))\s*=\s*(?P<num>[^\n]+?)\s*\n\s*(?P<den>\d+)\s*(?=\n|$)'
        def fraction(m):
            numerator = m['num'].strip()
            suffix = ''
            if numerator.endswith(', onde:'):
                numerator = numerator[:-7].strip()
                suffix = ', onde:'
            numerator = re.sub(r'\s*,\s*', ',', numerator)
            numerator = ' '.join(numerator.split())
            return f"{m['lhs']} = ({numerator}) / {m['den']}{suffix}"
        text, n = re.subn(pattern, fraction, text)
        if n != 18:
            raise ValueError(f'Perfil do PDF: esperadas 18 frações simples; encontradas {n}.')
        repairs += n
    if len(text.strip()) < 100:
        raise ValueError('Texto extraído insuficiente; nada será gravado.')
    return text.strip(), {'sha256': digest, 'pages': pages, 'profile': profile, 'formula_repairs': repairs}


def make_chunks(text: str, size: int, overlap: int) -> list[dict]:
    if size < 100 or not 0 <= overlap < size:
        raise ValueError('Tamanho/sobreposição inválidos.')
    clean = ' '.join(text.split())
    result = []
    start = 0
    while start < len(clean):
        end = min(start + size, len(clean))
        result.append({'chunk_index': len(result), 'content': clean[start:end].strip(),
                       'start': start, 'end': end})
        if end == len(clean):
            break
        start = end - overlap
    return result


def reading_map(text: str, chunks: list[dict]) -> str:
    """Mapa de localização sem geração de regras ou números pelo LLM."""
    paragraphs = []
    for heading in HEADING.finditer(text):
        label = ' '.join(heading.group().split())
        offset = len(' '.join(text[:heading.start()].split()))
        if offset:
            offset += 1
        indexes = [c['chunk_index'] for c in chunks
                   if c['start'] <= offset < c['end']]
        if indexes:
            paragraphs.append(label + ' ' + ' '.join(f'[chunk {i}]' for i in indexes))
    if not paragraphs:
        # Fallback extrativo: início de cada trecho, com referência conferível.
        paragraphs = [c['content'][:100] + f"… [chunk {c['chunk_index']}]" for c in chunks]
    return 'Mapa extrativo de localização. Conferir as regras nos trechos originais.\n\n' + '\n\n'.join(paragraphs)
