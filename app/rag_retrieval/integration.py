"""Ponte com a aplicação. Chamadores devem manter catalog_read durante o uso."""
import time

from .service import retrieve, lexical_rank


def collect(question):
    from app import query, db
    from .bge import score_pairs
    original = question.strip()
    question = query.normalize_question(original)
    if not question:
        raise ValueError('Informe uma pergunta.')
    started = time.perf_counter()
    vector = query.embed_query(question)
    query.release_gpu_memory()
    embedded = time.perf_counter()
    data = db.read_retrieval_snapshot(question, vector, candidates=20, max_corpus=5000)
    if not data['corpus']:
        raise query.NoContextError('Nenhum conteúdo encontrado na base documental.')
    row = dict(data, question=question, system_prompt=query.build_system_prompt(question),
               lexical_candidates=lexical_rank(data['corpus'], data['query_lexemes'], 20),
               configuration=dict(context_window=query.settings.ollama_num_ctx,
                   output_reserved=query.settings.ollama_num_predict,
                   margin_reserved=256, chars_per_token=3.0))
    result = retrieve(row, score_pairs)
    searched = time.perf_counter()
    result.update(question=original, normalized_question=question,
                  started=started, embedded=embedded, searched=searched)
    return result


def run_bge_query(question):
    from app import query
    result = collect(question)
    response = query.ask_local_llm_result(result['normalized_question'], result['context'])
    finished = time.perf_counter()
    warnings = list(result['warnings'])
    warnings.append('Modo BGE experimental: a fidelidade da resposta gerada exige conferência nas fontes.')
    if response.output_limit_reached:
        warnings.append(query.OUTPUT_LIMIT_WARNING)
    return dict(question=result['question'], model=query.settings.ollama_model,
                answer=response.answer, output_limit_reached=response.output_limit_reached,
                warnings=warnings, sources=result['sources'],
                timings_seconds=dict(embedding=round(result['embedded']-result['started'], 3),
                    search=round(result['searched']-result['embedded'], 3),
                    generation_and_context=round(finished-result['searched'], 3),
                    total=round(finished-result['started'], 3)))
