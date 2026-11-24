"""Experimento somente leitura. Não chama Ollama e não altera a API."""
from __future__ import annotations
import argparse
import ast
from collections import Counter
from contextlib import contextmanager
import inspect
import json
import math
from app.retrieval_sections import rebuild_sections, build_section_context, section_vector_ranking
from pathlib import Path
import time
from unittest.mock import patch


QUESTIONS = [
    'Quais regras do curso distinguem os aspirantes brasileiros dos estrangeiros?',
    'Em que ano é realizada a Inspeção de Saúde regulamentar?',
    'Quantos anos escolares estão previstos no curso da escola naval?',
    'Qual é a fórmula para cálculo do grau de classificação ao final do 4º ano escolar?',
]


def key(chunk):
    return (chunk['source_file'], chunk['chunk_index'])


def lexical_rank(rows, query_terms):
    """Presença de lexemas, ponderada pela raridade no corpus; não é BM25."""
    terms = set(query_terms)
    df = Counter(term for row in rows for term in set(row['lexemes']))
    n = len(rows)
    weights = {term: math.log(1 + (n - df[term] + .5) / (df[term] + .5)) for term in terms}
    ranked = []
    for row in rows:
        matched = sorted(terms & set(row['lexemes']))
        if matched:
            ranked.append({**row, 'matched_terms': matched,
                           'lexical_score': sum(weights[t] for t in matched)})
    ranked.sort(key=lambda c: (-c['lexical_score'], *key(c)))
    return ranked, weights


def fuse(vector, lexical, rrf_k=60):
    """Reciprocal Rank Fusion, pesos iguais; chave é documento + índice."""
    candidates = {}
    for label, ranking in [('vector', vector), ('lexical', lexical)]:
        for position, chunk in enumerate(ranking, 1):
            identifier = key(chunk)
            current = candidates.setdefault(identifier, {**chunk, 'rrf_score': 0., 'ranks': {}})
            if label in current['ranks']:
                continue
            current['ranks'][label] = position
            current['rrf_score'] += 1 / (rrf_k + position)
            if label == 'lexical':
                current['matched_terms'] = chunk['matched_terms']
                current['lexical_score'] = chunk['lexical_score']
    return sorted(candidates.values(), key=lambda c: (-c['rrf_score'], *key(c)))


def default_system(query_module):
    """Lê a string do prompt em uso sem executar geração ou copiar prompt antigo."""
    tree = ast.parse(inspect.getsource(query_module.ask_local_llm_result))
    for node in ast.walk(tree):
        if isinstance(node, ast.Assign) and any(isinstance(t, ast.Name) and t.id == 'system' for t in node.targets):
            value = node.value
            if isinstance(value, ast.BoolOp) and isinstance(value.op, ast.Or):
                result = ast.literal_eval(value.values[-1])
                if isinstance(result, str):
                    return result
    raise RuntimeError('Não foi possível extrair o prompt atual. Nenhuma estimativa será inventada.')


def estimate(question, context, system, chars_per_token):
    # Heurística explícita para triagem. Não é o tokenizer do modelo.
    text = system + '\nCONTEXTO:\n' + context + '\n\nPERGUNTA:\n' + question
    return math.ceil(len(text) / chars_per_token)


def budget_pack(ranking, build_context, question, system, window, output, margin, ratio, max_chunks):
    selected, excluded = [], []
    for candidate in ranking:
        if len(selected) >= max_chunks:
            excluded.append({**candidate, 'excluded_reason': 'limite de quantidade'})
            continue
        proposed = selected + [candidate]
        context = build_context(proposed, question)
        if estimate(question, context, system, ratio) + output + margin > window:
            excluded.append({**candidate, 'excluded_reason': 'orçamento estimado de contexto'})
        else:
            selected = proposed
    return selected, excluded


def list_ids(chunks):
    return [f"{c['source_file']}:{c['chunk_index']}" for c in chunks]


def read_corpus(db, question, cap):
    from psycopg2.extras import RealDictCursor
    with db.get_conn() as conn:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute("SELECT tsvector_to_array(to_tsvector('pg_catalog.portuguese', %s)) AS terms", (question,))
            terms = cur.fetchone()['terms']
            cur.execute('''SELECT source_file, chunk_index, content,
                tsvector_to_array(to_tsvector('pg_catalog.portuguese', content)) AS lexemes
                FROM document_chunks ORDER BY source_file, chunk_index LIMIT %s''', (cap + 1,))
            rows = [dict(row) for row in cur.fetchall()]
    if len(rows) > cap:
        raise RuntimeError(f'Corpus maior que {cap} trechos. Este diagnóstico faz leitura integral; reavalie antes de aumentar o limite.')
    if len({key(row) for row in rows}) != len(rows):
        raise RuntimeError('Existem índices duplicados para o mesmo documento. Corrija antes da comparação.')
    return rows, terms

def filter_section_relevance(ranking, terms, weights, relative_min):
    """Filtro experimental; pontuação relativa não é probabilidade."""
    # Evita que lexemas isolados, como "é", influenciem esta comparação.
    query_terms = {term for term in terms if len(term) > 1}
    scored = []

    for section in ranking:
        content_matches = query_terms & set(section.get('lexemes', []))
        title_matches = query_terms & set(section.get('title_lexemes', []))

        content_weight = sum(weights.get(t, 0.) for t in content_matches)
        title_weight = sum(weights.get(t, 0.) for t in title_matches)

        scored.append({
            **section,
            'content_matches': sorted(content_matches),
            'title_matches': sorted(title_matches),
            'title_weight': title_weight,
            'relevance_score': content_weight + 0.25 * title_weight,
        })

    best = max((s['relevance_score'] for s in scored), default=0.)
    accepted, rejected = [], []

    for section in scored:
        relative = section['relevance_score'] / best if best > 0 else 0.
        section['relative_relevance'] = relative

        if best <= 0:
            section['excluded_reason'] = 'sem correspondência lexical útil'
            rejected.append(section)
        elif relative < relative_min:
            section['excluded_reason'] = (
                f'correspondência relativa {relative:.3f} '
                f'abaixo do limite {relative_min:.3f}'
            )
            rejected.append(section)
        else:
            accepted.append(section)

    accepted.sort(
        key=lambda s: (-s['relevance_score'], -s['rrf_score'], *key(s))
    )
    rejected.sort(
        key=lambda s: (-s['relevance_score'], -s['rrf_score'], *key(s))
    )
    return accepted, rejected

def diagnose(question, args):
    from app import query, db, document_lock, documents_store
    from app.config import settings
    original_get_conn = db.get_conn
    original_embed = query.embed_query
    capture = {}
    started = time.perf_counter()

    @contextmanager
    def readonly_conn():
        yield snapshot_conn

    def capture_embedding(text):
        vector = original_embed(text)
        capture['embedding'] = vector
        return vector

    def no_generation(question, context, system_prompt=None):
        capture['context'] = context
        capture['system'] = system_prompt
        return query.LLMResponse(answer='', done_reason='stop')

    # Executa o fluxo atual integral até a fronteira de geração. Captura o contexto
    # real (inclusive definições e recortes); substitui somente a chamada ao LLM.
    with original_get_conn() as snapshot_conn:
        snapshot_conn.set_session(isolation_level='REPEATABLE READ', readonly=True)
        # Uma mesma transação para seleção atual, candidatos e corpus.
        with patch.object(db, 'get_conn', readonly_conn), \
             patch.object(document_lock, 'get_conn', readonly_conn), \
             patch.object(documents_store, 'get_conn', readonly_conn), \
             patch.object(query, 'embed_query', capture_embedding), \
             patch.object(query, 'ask_local_llm_result', no_generation), \
             patch.object(query, 'urlopen', side_effect=RuntimeError('Chamada ao gerador bloqueada')):
            baseline = query.run_query(question)
            if 'context' not in capture:
                raise RuntimeError('O fluxo atual não passou pelo ponto esperado de captura.')
            vector = db.search_similar_chunks(capture['embedding'], args.candidates)
            corpus, terms = read_corpus(db, question, args.max_corpus)
            sections, structure_warnings = rebuild_sections(corpus)
            if sections:
                # Tokenização lexical idêntica à do diagnóstico de trechos.
                with snapshot_conn.cursor() as cur:
                    cur.execute("""SELECT tsvector_to_array(to_tsvector('pg_catalog.portuguese', value->>'content')),
                        tsvector_to_array(to_tsvector('pg_catalog.portuguese', value->>'title'))
                        FROM jsonb_array_elements(%s::jsonb) WITH ORDINALITY AS items(value, ord)
                        ORDER BY ord""", (json.dumps(sections),))
                    for section, (lexemes, title_lexemes) in zip(sections, cur.fetchall()):
                        section['lexemes'] = lexemes
                        section['title_lexemes'] = title_lexemes

    lexical_all, weights = lexical_rank(corpus, terms)
    lexical = lexical_all[:args.candidates]
    ranking = fuse(vector, lexical)
    system = capture['system'] if capture['system'] is not None else default_system(query)
    window = settings.ollama_num_ctx
    output = settings.ollama_num_predict
    if window <= 0 or output <= 0:
        raise RuntimeError('Janela e limite de saída devem ser positivos para calcular o orçamento.')
    selected, excluded = budget_pack(ranking, query.build_context, question, system,
        window, output, args.margin, args.chars_per_token, args.max_chunks)
    hybrid_context = query.build_context(selected, question)
    baseline_ids = [(s['file'], s['chunk']) for s in baseline['sources']]
    selected_ids = {key(c) for c in selected}
    baseline_est = estimate(question, capture['context'], system, args.chars_per_token)
    hybrid_est = estimate(question, hybrid_context, system, args.chars_per_token)
    # Seções são unidades indivisíveis: se não couberem, informar; nunca cortar a ressalva.
    eligible = [section for section in sections if section['complete_boundary']]
    sec_lexical, _ = lexical_rank(eligible, terms)
    sec_vector = section_vector_ranking(eligible, vector)
    sec_ranking = fuse(sec_vector, sec_lexical[:args.candidates])
    
    sec_accepted, sec_rejected = filter_section_relevance(
        sec_ranking, terms, weights, args.section_relative_min
    )

    # Mantém todas as candidatas e suas pontuações no relatório.
    sec_ranking = sorted(
        sec_accepted + sec_rejected,
        key=lambda s: (-s['relevance_score'], -s['rrf_score'], *key(s))
    )

    # O orçamento é aplicado somente às candidatas que passaram pelo filtro.
    # Cada seção continua sendo incluída inteira ou excluída.
    sec_selected, sec_budget_excluded = budget_pack(
        sec_accepted,
        build_section_context,
        question,
        system,
        window,
        output,
        args.margin,
        args.chars_per_token,
        len(sec_accepted),
    )
    sec_excluded = sec_rejected + sec_budget_excluded
    sec_context = build_section_context(sec_selected)
    sec_total = estimate(question, sec_context, system, args.chars_per_token) + output + args.margin
    result = {
        'snapshot_schema_version': 2,
        'question': question, 'model': settings.ollama_model,
        'system_prompt': system,
        'corpus': corpus,
        'corpus_chunks': len(corpus), 'query_lexemes': terms, 'lexeme_weights': weights,
        'configuration': {'candidates_per_search': args.candidates, 'rrf_k': 60,
            'max_chunks': args.max_chunks, 'chars_per_token': args.chars_per_token,
            'context_window': window, 'output_reserved': output, 'margin_reserved': args.margin,
            'token_count_method': 'heurística por caracteres; não garante encaixe no tokenizer real',
            'section_relative_min': args.section_relative_min,
            'section_title_bonus': 0.25},
        'baseline': {'sources': baseline['sources'], 'context': capture['context'],
            'chars': len(capture['context']), 'input_tokens_estimated': baseline_est,
            'total_reserved_estimated': baseline_est + output + args.margin},
        'vector_candidates': vector, 'lexical_candidates': lexical,
        'hybrid_ranking': ranking, 'hybrid_selected': selected, 'hybrid_excluded': excluded,
        'hybrid_context': hybrid_context, 'hybrid_chars': len(hybrid_context),
        'hybrid_input_tokens_estimated': hybrid_est,
        'hybrid_total_reserved_estimated': hybrid_est + output + args.margin,
        'baseline_sources_not_selected': [list(k) for k in baseline_ids if k not in selected_ids],
        'new_sources': [list(key(c)) for c in selected if key(c) not in baseline_ids],
        'structural': {
            'method': 'seções numeradas em maiúsculas; sobreposição exata >=32 caracteres; unidades inteiras',
            'warnings': structure_warnings,
            'detected_sections': sections,
            'ranking': sec_ranking, 'selected': sec_selected, 'excluded': sec_excluded,
            'context': sec_context, 'chars': len(sec_context),
            'total_reserved_estimated': sec_total,
            'coverage_warning': 'Seleção parcial do documento; seções excluídas podem conter regras relevantes. '
                'Limites de seção são heurísticos e devem ser conferidos no PDF. '
                'Referências a outros artigos não são expandidas automaticamente.',
        },
        'elapsed_seconds': round(time.perf_counter() - started, 3),
        'generation_calls': 0,
    }
    print('\nPERGUNTA:', question)
    print('Lexemas:', ', '.join(terms) or '(nenhum)')
    print('ATUAL:', ', '.join(f"{s['file']}:{s['chunk']}" for s in baseline['sources']))
    for label, candidates in [('VETORIAL', vector), ('PALAVRAS', lexical), ('COMBINADA', ranking)]:
        print(label + ':', ', '.join(list_ids(candidates)))
    print('SELEÇÃO EXPERIMENTAL:', ', '.join(list_ids(selected)) or '(vazia)')
    print('Fontes atuais fora da seleção:', result['baseline_sources_not_selected'])
    print('Novas fontes:', result['new_sources'])
    print(f"Contexto atual: {len(capture['context'])} caracteres; total estimado com reservas: {result['baseline']['total_reserved_estimated']}/{window}")
    print(f"Contexto experimental: {len(hybrid_context)} caracteres; total estimado com reservas: {result['hybrid_total_reserved_estimated']}/{window}")
    print(f'Reservas: {output} tokens de saída + {args.margin} de margem. Contagem aproximada, não validada pelo tokenizer.')
    print('Trechos selecionados (prévia):')
    for c in selected:
        print(f"  {c['source_file']}:{c['chunk_index']} | ranks={c['ranks']} | palavras={c.get('matched_terms', [])}")
        print('  ' + ' '.join(c['content'].split())[:230])
    print('\nSEÇÕES EXPERIMENTAIS (sem recortar):')
    for section in sec_selected:
        print(f"  {section['source_file']} | {section['section']} {section['title']} | trechos={section['source_chunks']}")
        print(
            f"    score={section['relevance_score']:.3f}"
            f" | relativo={section['relative_relevance']:.3f}"
            f" | palavras={section['content_matches']}"
            f" | título={section['title_matches']}"
        )
        
    print(f'Contexto por seções: {len(sec_context)} caracteres; total estimado com reservas: {sec_total}/{window}')
    print('Seções candidatas excluídas por relevância ou orçamento:')
    for section in sec_excluded:
        print(f"  {section['section']} {section['title']} | {section['excluded_reason']}")
    for warning in structure_warnings:
        print('AVISO:', warning)
    print('AVISO:', result['structural']['coverage_warning'])
    print(f"Tempo: {result['elapsed_seconds']} s | chamadas ao modelo gerador: 0")
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('question', nargs='?')
    parser.add_argument('--suite', action='store_true', help='Executa as quatro perguntas de comparação')
    parser.add_argument('--output', required=True, help='Novo arquivo JSON local; nunca sobrescreve')
    parser.add_argument('--candidates', type=int, default=20)
    parser.add_argument('--max-chunks', type=int, default=8)
    parser.add_argument('--max-corpus', type=int, default=5000)
    parser.add_argument('--chars-per-token', type=float, default=3.0)
    parser.add_argument('--margin', type=int, default=256)
    parser.add_argument(
        '--section-relative-min',
        type=float,
        default=0.75,
        help='Correspondência mínima relativa à melhor seção (0 a 1)',
    )
    args = parser.parse_args()
    if not 0 <= args.section_relative_min <= 1:
        parser.error('--section-relative-min deve estar entre 0 e 1.')    
    if bool(args.question) == bool(args.suite):
        parser.error('Informe uma pergunta OU --suite.')
    if min(args.candidates, args.max_chunks, args.max_corpus) < 1 or args.chars_per_token <= 0 or args.margin < 0:
        parser.error('Limites inválidos.')
    path = Path(args.output)
    # Reserva a saída antes de carregar embeddings e fazer consultas.
    with path.open('x', encoding='utf-8') as out:
        reports = []
        try:
            for question in (QUESTIONS if args.suite else [args.question.strip()]):
                reports.append(diagnose(question, args))
        finally:
            json.dump({'completed': len(reports), 'results': reports}, out, ensure_ascii=False, indent=2)
    print('\nRelatório completo:', path.resolve())


if __name__ == '__main__':
    main()
