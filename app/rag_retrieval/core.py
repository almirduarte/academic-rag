"""Corpus, candidatos e montagem de contexto; sem gabaritos ou chamadas externas."""
import math
from .evidence_units import reconstruct, sections_from_runs, split_units, bundle


class Corpus:
    def __init__(self, rows):
        self.runs, self.warnings = reconstruct(rows)
        self.sections = sections_from_runs(self.runs)
        self.units = split_units(self.sections)
        self.section_map = {s['id']: s for s in self.sections}
        self.unit_map = {u['id']: u for u in self.units}
        self.candidates = []
        self.omitted = []
        for u in self.units:
            s = self.section_map[u['section_id']]
            item = dict(unit_id=u['id'], source_file=s['source_file'],
                        section=s['section'], title=s['title'], label=u['label'],
                        source_chunks=sorted({p['chunk'] for p in s['source_spans']
                                              if p['start'] < u['end'] and p['end'] > u['start']}))
            if s['kind'] == 'unstructured' or s['boundary'] == 'broken':
                self.omitted.append({**item, 'reason': s['kind'] if s['kind'] == 'unstructured' else 'broken'})
                continue
            # Título e corpo apenas; dependências acrescentadas após a ordenação.
            item['passage'] = f"{s['section']} — {s['title']}\n{u['content'].strip()}"
            self.candidates.append(item)

    def context(self, ids):
        return bundle(ids, self.units, self.sections, self.runs)


def pool_ids(candidates, chunks):
    keys = {(c['source_file'], c['chunk_index']) for c in chunks}
    return {c['unit_id'] for c in candidates
            if any((c['source_file'], i) in keys for i in c['source_chunks'])}


def ranked(candidates, scores, allowed=None):
    if len(candidates) != len(scores) or any(not math.isfinite(float(s)) for s in scores):
        raise ValueError('Scores ausentes, excedentes ou não finitos.')
    rows = [{**c, 'score': float(s)} for c, s in zip(candidates, scores)
            if allowed is None or c['unit_id'] in allowed]
    rows.sort(key=lambda r: (-r['score'], r['unit_id']))
    return [{**r, 'rank': i} for i, r in enumerate(rows, 1)]


def estimate(question, context, system, config):
    ratio = config['chars_per_token']
    if not math.isfinite(ratio) or ratio <= 0:
        raise ValueError('chars_per_token inválido.')
    text = system + '\nCONTEXTO:\n' + context + '\n\nPERGUNTA:\n' + question
    return math.ceil(len(text) / ratio) + config['output_reserved'] + config['margin_reserved']


def pack(index, ranking, question, system, config, top_k):
    if estimate(question, '', system, config) > config['context_window']:
        raise ValueError('Prompt e reservas já ultrapassam a janela sem contexto.')
    selected, excluded = [], []
    for item in ranking[:top_k]:
        proposed = selected + [item['unit_id']]
        ctx = index.context(proposed)
        cost = estimate(question, ctx['context'], system, config)
        if cost <= config['context_window']:
            selected = proposed
        else:
            excluded.append(dict(unit_id=item['unit_id'], reason='orçamento estimado', total=cost))
    result = index.context(selected)
    return {**result, 'selected_ranked_ids': selected, 'excluded_budget': excluded,
            'top_k': top_k, 'not_considered_after_top_k': max(0, len(ranking) - top_k),
            'total_reserved_estimated': estimate(question, result['context'], system, config)}


def check_lengths(lengths, maximum):
    too_long = [(i, n) for i, n in enumerate(lengths) if n > maximum]
    if too_long:
        raise ValueError(f'{len(too_long)} pares excedem --max-length {maximum}; maior={max(lengths)}. '
                         'Nenhum bloco foi truncado. Aumente o limite somente após avaliar memória.')


def validate_snapshot(report):
    rows = report.get('results', [])
    if not rows:
        raise ValueError('Snapshot sem resultados.')
    for row in rows:
        for name in ('corpus', 'question', 'system_prompt', 'configuration', 'baseline',
                     'vector_candidates', 'lexical_candidates'):
            if name not in row:
                raise ValueError(f'Snapshot incompleto: falta {name}. Use snapshot-completo-v2.')
        if not isinstance(row['system_prompt'], str) or not row['corpus']:
            raise ValueError('Corpus ou prompt ausente.')
        c = row['configuration']
        if c['context_window'] <= 0 or c['output_reserved'] <= 0 or c['margin_reserved'] < 0:
            raise ValueError('Orçamento inválido.')
    return rows
