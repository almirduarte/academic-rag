"""Reconstrução extrativa experimental; não é usada pelo fluxo de produção.

Reconhece títulos numerados em maiúsculas. Não infere exceções nem resume normas.
Uma quebra sem sobreposição verificável interrompe a reconstrução.
"""
from __future__ import annotations
from collections import defaultdict
import re

# Letras maiúsculas portuguesas, sem incluir símbolos do intervalo À-Ý.
UPPER = 'A-ZÁÀÂÃÉÊÍÓÔÕÚÜÇ'

# Cada palavra deve terminar por inteiro. Impede capturar "A" de "Aspirantes".
# Não permite que uma palavra do título termine antes de um ponto.
# Assim, "3.1." não pode fornecer o "3" ao título anterior.
TITLE_WORD = rf'[{UPPER}0-9][{UPPER}0-9ºª]*(?![\w.])'

# Conectores são aceitos entre palavras do título.
TITLE_SEPARATOR = r'(?:\s+|[ \t]*[/()–—-][ \t]*)+'

HEADING = re.compile(
    rf'(?<![\w.])'
    rf'(?P<number>\d+(?:\.\d+)*)\.\s+'
    rf'(?P<title>{TITLE_WORD}(?:{TITLE_SEPARATOR}{TITLE_WORD})*)'
    rf'(?P<closing>[ \t]*\))?'
)

TITLE_CONNECTORS = {
    'A', 'O', 'AS', 'OS',
    'AO', 'AOS', 'À', 'ÀS',
    'DE', 'DA', 'DO', 'DAS', 'DOS',
    'E', 'EM', 'NA', 'NO', 'NAS', 'NOS',
    'OU', 'PARA', 'POR', 'COM', 'SEM',
}


def valid_heading(match):
    """Validação conservadora; ainda não substitui conferência no PDF."""
    parts = match['number'].split('.')

    # Evita interpretar um ano isolado, como "2026.", como seção.
    # É uma convenção deste diagnóstico, não uma regra universal de documentos.
    if len(parts[0]) > 3:
        return False

    words = re.findall(rf'[{UPPER}]+', match['title'])

    # Exige pelo menos uma palavra significativa com três ou mais letras.
    # Siglas como IS ou CE continuam aceitas junto do título por extenso.
    return any(
        len(word) >= 3 and word not in TITLE_CONNECTORS
        for word in words
    )


def heading_title(match):
    return (match['title'] + (match['closing'] or '')).strip()

def rebuild_sections(rows):
    documents = defaultdict(list)
    for row in rows:
        documents[row['source_file']].append(row)
    sections, warnings = [], []
    for source, chunks in sorted(documents.items()):
        chunks.sort(key=lambda c: c['chunk_index'])
        runs = []
        text, spans, previous = '', [], None
        for chunk in chunks:
            value = chunk['content'].strip()
            overlap = 0
            if previous is not None and chunk['chunk_index'] == previous + 1:
                # Sobreposição longa para não unir por coincidência de uma palavra.
                matches = [size for size in range(min(len(text), len(value)), 31, -1)
                           if text.endswith(value[:size])]
                if len(matches) == 1:
                    overlap = matches[0]
                elif len(matches) > 1:
                    warnings.append(f'{source}: sobreposição ambígua antes do trecho {chunk["chunk_index"]}; não foi unida.')
            if spans and not overlap:
                runs.append((text, spans, False))
                warnings.append(f'{source}: continuidade não comprovada antes do trecho {chunk["chunk_index"]}.')
                text, spans = '', []
            start = len(text) - overlap
            text += value[overlap:]
            spans.append((chunk['chunk_index'], start, len(text)))
            previous = chunk['chunk_index']
        if spans:
            runs.append((text, spans, True))
        for run_id, (text, spans, document_end) in enumerate(runs):
            headings = []
            for candidate in HEADING.finditer(text):
                if valid_heading(candidate):
                    headings.append(candidate)
                else:
                    warnings.append(
                        f'{source}: candidato a título rejeitado: '
                        f'{candidate["number"]}. '
                        f'{heading_title(candidate)}'
                    )
            if not headings:
                warnings.append(f'{source}: bloco iniciado no trecho {spans[0][0]} sem títulos reconhecidos.')
            for position, heading in enumerate(headings):
                following = headings[position + 1] if position + 1 < len(headings) else None
                end = following.start() if following else len(text)
                # Fim do documento é evidência mais fraca que um próximo título.
                boundary = 'próximo título' if following else ('fim do texto indexado' if document_end else 'continuidade interrompida')
                indexes = [idx for idx, start, stop in spans if start < end and stop > heading.start()]
                sections.append({
                    'source_file': source, 'chunk_index': f'sec:{run_id}:{heading.start()}',
                    'section': heading['number'],
                    'title': heading_title(heading),
                    'content': text[heading.start():end].strip(), 'source_chunks': indexes,
                    'boundary': boundary, 'complete_boundary': bool(following or document_end),
                })
    return sections, warnings


def build_section_context(sections, question=''):
    return '\n\n'.join(
        f'[Fonte {i}]\nArquivo: {s["source_file"]}\nSeção: {s["section"]} — {s["title"]}\n'
        f'Trechos de origem: {", ".join(map(str, s["source_chunks"]))}\nConteúdo: {s["content"]}'
        for i, s in enumerate(sections, 1)
    )


def section_vector_ranking(sections, vector):
    positions = {(r['source_file'], r['chunk_index']): i for i, r in enumerate(vector, 1)}
    matched = []
    for section in sections:
        ranks = [positions[(section['source_file'], idx)] for idx in section['source_chunks']
                 if (section['source_file'], idx) in positions]
        if ranks:
            matched.append({**section, 'best_vector_rank': min(ranks)})
    return sorted(matched, key=lambda s: (s['best_vector_rank'], s['source_file'], s['chunk_index']))
