"""Seleção estrutural experimental sobre ranking já calculado.

Não lê gabaritos, respostas anteriores, números de seções nem palavras-chave
de perguntas. A pergunta participa apenas do orçamento e das definições.
"""
from collections import defaultdict
import math

from .definitions import enrich
from .core import estimate


def compact_context(index, ids):
    result = index.context(ids)
    documents = defaultdict(list)
    for part in result['parts']:
        documents[part['source_file']].append(part)
    sources, text = [], []
    for number, (source, parts) in enumerate(documents.items(), 1):
        text.append(f'[Fonte {number}] Arquivo: {source}\n' + '\n\n'.join(
            f'[Trecho {n}]\n{part["text"]}' for n, part in enumerate(parts, 1)))
        sources.append(dict(label=number, source_file=source, fragments=[
            dict(label=n, run=p['run'], start=p['start'], end=p['end'],
                 source_spans=p['source_spans']) for n, p in enumerate(parts, 1)]))
    result.update(context='\n\n'.join(text), sources=sources)
    return result


def choose(index, ranking, row, top_k=8, headroom=256):
    if top_k < 1 or headroom < 0:
        raise ValueError('Limites de seleção inválidos.')
    eligible = {c['unit_id'] for c in index.candidates}
    ids = [r['unit_id'] for r in ranking]
    if len(ids) != len(set(ids)) or any(uid not in eligible for uid in ids):
        raise ValueError('Ranking contém unidades duplicadas ou inelegíveis.')
    if any(not math.isfinite(r['score']) for r in ranking):
        raise ValueError('Score não finito.')
    if any(r['rank'] != i for i, r in enumerate(ranking, 1)):
        raise ValueError('Posições do ranking inconsistentes.')
    if any(a['score'] < b['score'] for a, b in zip(ranking, ranking[1:])):
        raise ValueError('Ranking fora da ordem de scores.')
    config = row['configuration']
    limit = config['context_window'] - headroom
    estimator = lambda text: estimate(row['question'], text, row['system_prompt'], config)
    if estimator('') > limit:
        raise ValueError('Prompt e reservas excedem o orçamento de seleção.')
    if not ranking:
        raise ValueError('Ranking vazio.')

    groups = defaultdict(list)
    for item in ranking[:top_k]:
        groups[index.unit_map[item['unit_id']]['section_id']].append(item)
    ordered = sorted(groups, key=lambda sid: (-len(groups[sid]), groups[sid][0]['rank'], sid))
    seeds = [sid for sid in ordered if len(groups[sid]) >= 2]
    fallback = not seeds
    if fallback:
        seeds = ordered[:1]

    # Uma seção homônima já recuperada pode descrever outra etapa do mesmo
    # documento. É uma hipótese estrutural, não uma prova de relevância.
    def title_key(sid):
        section = index.section_map[sid]
        return (section['source_file'], section['run'], ' '.join(section['title'].casefold().split()))
    companions = [sid for sid in ordered if sid not in seeds
                  and index.section_map[sid]['kind'] == 'section'
                  and any(index.section_map[seed]['kind'] == 'section'
                          and title_key(sid) == title_key(seed) for seed in seeds)]
    planned = seeds + companions
    eligible_children = defaultdict(list)
    for unit in index.units:
        if unit['id'] in eligible:
            eligible_children[unit['section_id']].append(unit['id'])

    selected, decisions = [], []
    for sid in planned:
        section = index.section_map[sid]
        whole = eligible_children[sid]
        proposed = list(dict.fromkeys(selected + whole))
        total = estimator(compact_context(index, proposed)['context'])
        decision = dict(section_id=sid, source_file=section['source_file'],
            section=section['section'], title=section['title'],
            hits=len(groups[sid]), ranks=[r['rank'] for r in groups[sid]],
            reason=('título igual no mesmo documento e bloco' if sid in companions else
                    'melhor resultado, sem seção com duas ocorrências' if fallback else
                    'duas ou mais unidades entre os primeiros candidatos'),
            whole_section_estimated_total=total, selected_ids=[], excluded_ids=[])
        if total <= limit:
            selected = proposed
            decision.update(mode='whole_section', selected_ids=whole)
        else:
            # Mantém alíneas completas com suas dependências. A seção fica
            # explicitamente parcial; não recorta conteúdo para fazê-la caber.
            decision['mode'] = 'retrieved_units_only'
            for item in groups[sid]:
                uid = item['unit_id']
                proposed = list(dict.fromkeys(selected + [uid]))
                cost = estimator(compact_context(index, proposed)['context'])
                if cost <= limit:
                    selected = proposed
                    decision['selected_ids'].append(uid)
                else:
                    decision['excluded_ids'].append(dict(unit_id=uid, reason='orçamento estimado', total=cost))
        decisions.append(decision)
    if not selected:
        raise ValueError('Nenhuma unidade completa coube; não será enviada uma consulta vazia.')
    packed = compact_context(index, selected)
    enriched = enrich(row['question'], packed['context'], packed['parts'], row['corpus'], estimator, limit)
    return dict(**packed, final_context=enriched['context'],
        definitions=enriched['definitions'], definitions_excluded=enriched['excluded'],
        selected_ranked_ids=selected, decisions=decisions,
        excluded_groups=[dict(section_id=sid, section=index.section_map[sid]['section'],
                              source_file=index.section_map[sid]['source_file'],
                              ranks=[r['rank'] for r in groups[sid]],
                              reason='ocorrência isolada sem título igual ao de uma seção priorizada')
                         for sid in ordered if sid not in planned],
        not_considered_after_top_k=max(0, len(ranking)-top_k),
        total_reserved_estimated=enriched['total_reserved_estimated'],
        parameters=dict(top_k=top_k, min_hits=2, same_title_companions=True,
                        packing_headroom=headroom, packing_limit=limit),
        limitations=['Limites de seções são heurísticos; fim indexado não comprova fim do PDF.',
                     'Seções com mais alíneas têm mais oportunidades de aparecer no top-k.',
                     'Título igual não garante mesma aplicabilidade normativa.',
                     'Referências externas e definições ambíguas podem continuar sem resolução.',
                     'Orçamento por caracteres, mesmo com folga, não garante encaixe no tokenizer.'])
