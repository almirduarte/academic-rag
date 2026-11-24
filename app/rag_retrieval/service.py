"""Núcleo reutilizável. Sem banco, Ollama, gabaritos ou nomes de documentos."""
from collections import Counter
import math

from .core import Corpus, pool_ids, ranked
from .selector import choose

COVERAGE_NOTICE = (
    'Seleção parcial do acervo; a cobertura integral da pergunta não foi verificada. '
    'Condições em trechos não selecionados ou normas referenciadas podem faltar.'
)
BUDGET_NOTICE = (
    'Orçamento estimado por caracteres; não garante encaixe no tokenizer do gerador.'
)


def lexical_rank(rows, terms, limit):
    """Mesmo sinal lexical do diagnóstico: presença ponderada, não BM25."""
    terms = set(terms)
    df = Counter(t for row in rows for t in set(row['lexemes']))
    n = len(rows)
    weights = {t: math.log(1 + (n - df[t] + .5) / (df[t] + .5)) for t in terms}
    scored = []
    for row in rows:
        matched = sorted(terms.intersection(row['lexemes']))
        if matched:
            scored.append(dict(row, matched_terms=matched,
                               lexical_score=sum(weights[t] for t in matched)))
    scored.sort(key=lambda c: (-c['lexical_score'], c['source_file'], c['chunk_index']))
    return scored[:limit]


def validate_inputs(row):
    if not isinstance(row['question'], str) or not row['question'].strip():
        raise ValueError('Pergunta vazia.')
    if not isinstance(row['system_prompt'], str):
        raise ValueError('Prompt inválido.')
    config = row['configuration']
    for name, minimum in [('context_window', 1), ('output_reserved', 1), ('margin_reserved', 0)]:
        value = config[name]
        if type(value) is not int or value < minimum:
            raise ValueError('Orçamento inválido: ' + name)
    ratio = config['chars_per_token']
    if isinstance(ratio, bool) or not isinstance(ratio, (int, float)) or not math.isfinite(ratio) or ratio <= 0:
        raise ValueError('chars_per_token inválido.')
    chunks = {}
    for c in row['corpus']:
        if (not isinstance(c['source_file'], str) or not c['source_file']
                or type(c['chunk_index']) is not int or not isinstance(c['content'], str)):
            raise ValueError('Trecho inválido.')
        key = (c['source_file'], c['chunk_index'])
        if key in chunks:
            raise ValueError('Índice duplicado no mesmo documento.')
        chunks[key] = c
    for c in row['vector_candidates'] + row['lexical_candidates']:
        original = chunks.get((c['source_file'], c['chunk_index']))
        if original is None or ('content' in c and c['content'] != original['content']):
            raise ValueError('Candidato não corresponde ao corpus desta consulta.')


def retrieve(row, score_pairs, *, top_k=8, headroom=256):
    """score_pairs(question, candidates) -> scores na mesma ordem.

    candidates contêm unit_id e passage. Só pontua a união dos candidatos
    vetoriais/lexicais. Expansão estrutural pode acrescentar alíneas irmãs.
    Não decide se uma resposta gerada é correta ou completa.
    """
    validate_inputs(row)
    index = Corpus(row['corpus'])
    allowed = pool_ids(index.candidates, row['vector_candidates'] + row['lexical_candidates'])
    candidates = [c for c in index.candidates if c['unit_id'] in allowed]
    if not candidates:
        raise ValueError('Nenhuma unidade estruturada elegível nos candidatos recuperados.')
    scores = list(score_pairs(row['question'], candidates))
    ranking = ranked(candidates, scores)
    selection = choose(index, ranking, row, top_k=top_k, headroom=headroom)
    # As fontes retornadas cobrem corpo, apoios e definições, não só os candidatos.
    keys = set()
    for part in selection['parts']:
        for span in part['source_spans']:
            keys.add((part['source_file'], span['chunk']))
    for d in selection['definitions']:
        keys.add((d['source_file'], d['chunk_index']))
    partial = [d['section'] for d in selection['decisions'] if d['mode'] != 'whole_section']
    warnings = [COVERAGE_NOTICE, BUDGET_NOTICE]
    if partial:
        warnings.append('Seções com seleção parcial: ' + ', '.join(partial) + '.')
    warnings.extend(index.warnings)
    warnings.extend(selection['warnings'])
    return dict(context=selection['final_context'],
                sources=[dict(file=source, chunk=idx) for source, idx in sorted(keys)],
                ranking=ranking, selection=selection,
                candidate_count=len(candidates), omitted_units=index.omitted,
                warnings=list(dict.fromkeys(warnings)),
                coverage='not_verified', semantic_review='not_performed')
