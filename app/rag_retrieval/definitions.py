"""Extração conservadora de denominações seguidas de siglas entre parênteses.

Somente iniciais alinhadas, conectores portugueses e citações literais. Não
consulta perguntas de avaliação, respostas do Qwen ou dicionário de siglas.
"""
from collections import Counter, defaultdict
import re
import unicodedata

CONNECTORS = set('a o as os de da do das dos e para por em no na nos nas ao aos com'.split())
WORD = re.compile(r'[^\W\d_]+', re.UNICODE)
PAREN = re.compile(r'\((?P<short>[A-Z][A-Z-]{1,11})\)')
TOKEN = re.compile(r'(?<![\w-])[A-Z][A-Z-]{1,11}\d*(?![\w-])')
BOUNDARY = re.compile(r'[.;:!?()\n]')


def norm(text):
    text = ''.join(c for c in unicodedata.normalize('NFD', text) if not unicodedata.combining(c))
    return ' '.join(text.casefold().split())


def extract(rows):
    definitions = []
    seen = set()
    for row in rows:
        text = row['content']
        for match in PAREN.finditer(text):
            short = match['short']
            letters = short.replace('-', '')
            prefix_start = max(0, match.start() - 240)
            prefix = text[prefix_start:match.start()]
            boundaries = list(BOUNDARY.finditer(prefix))
            if boundaries:
                prefix_start += boundaries[-1].end()
                prefix = text[prefix_start:match.start()]
            words = list(WORD.finditer(prefix))[-16:]
            # Testa sufixos completos; conectores não contribuem para a sigla.
            for i in range(len(words) - 1, -1, -1):
                phrase_words = words[i:]
                if norm(phrase_words[0].group()) in CONNECTORS:
                    continue
                initials = ''.join(norm(w.group())[0] for w in phrase_words
                                   if norm(w.group()) not in CONNECTORS)
                if initials != letters.casefold():
                    continue
                start = prefix_start + phrase_words[0].start()
                end = match.end()
                long_form = text[start:match.start()].strip()
                key = (row['source_file'], short, norm(long_form.strip(' \"\'“”‘’')))
                if key not in seen:
                    definitions.append(dict(acronym=short, long_form=long_form,
                        quote=text[start:end], source_file=row['source_file'],
                        chunk_index=row['chunk_index'], start=start, end=end))
                    seen.add(key)
                break
    return definitions


def candidates(question, parts, corpus):
    definitions = extract(corpus)
    by_source_short = defaultdict(list)
    for d in definitions:
        by_source_short[(d['source_file'], d['acronym'])].append(d)
    source_text = defaultdict(str)
    for part in parts:
        source_text[part['source_file']] += '\n' + part['text']
    # O mapeamento MG4 -> MG apenas localiza uma definição. Não afirma o
    # significado de 4 nem produz uma definição nova para a variável inteira.
    query_tokens = Counter(TOKEN.findall(question))
    found, excluded = [], []
    for source, text in sorted(source_text.items()):
        tokens = Counter(TOKEN.findall(text))
        known = {short for src, short in by_source_short if src == source}
        matches = defaultdict(Counter)
        for token, count in (tokens + query_tokens).items():
            base = token if token in known else re.sub(r'\d+$', '', token)
            matches[base][token] += count
        for acronym, occurrences in sorted(matches.items()):
            ds = by_source_short.get((source, acronym), [])
            info = dict(acronym=acronym, source_file=source, occurrences=dict(occurrences))
            if not ds:
                excluded.append({**info, 'reason': 'sem definição explícita reconhecida no mesmo documento'})
                continue
            if len(ds) != 1:
                excluded.append({**info, 'reason': 'definições divergentes no mesmo documento', 'definitions': ds})
                continue
            d = ds[0]
            if norm(d['quote']) in norm(text):
                excluded.append({**info, 'reason': 'definição já presente no contexto', 'definition': d})
                continue
            in_question = any(t in query_tokens for t in occurrences)
            indexed = any(re.search(r'\d+$', t) for t in occurrences)
            priority = (0 if in_question else 1 if indexed else 2, -sum(occurrences.values()), acronym, source)
            found.append({**d, 'occurrences': dict(occurrences), 'priority': priority})
    return sorted(found, key=lambda d: d['priority']), excluded


def render(definitions):
    if not definitions:
        return ''
    return '\n\nDEFINIÇÕES EXTRAÍDAS DO CORPUS\n' + '\n\n'.join(
        f'[Definição {i}] Arquivo: {d["source_file"]} | Chunk: {d["chunk_index"]}\n{d["quote"]}'
        for i, d in enumerate(definitions, 1))


def enrich(question, context, parts, corpus, estimate, window):
    selected, over_budget = [], []
    ranked, excluded = candidates(question, parts, corpus)
    included_meanings = set()
    for definition in ranked:
        meaning = (definition['acronym'], norm(definition['long_form'].strip(' \"\'“”‘’')))
        if meaning in included_meanings:
            excluded.append({**definition, 'reason': 'mesma definição já acrescentada de outra fonte'})
            continue
        proposed = selected + [definition]
        total = estimate(context + render(proposed))
        if total <= window:
            selected = proposed
            included_meanings.add(meaning)
        else:
            over_budget.append({**definition, 'reason': 'orçamento estimado', 'proposed_total': total})
    enriched = context + render(selected)
    assert enriched.startswith(context)
    return dict(context=enriched, definitions=selected, excluded=excluded + over_budget,
                total_reserved_estimated=estimate(enriched), changed=bool(selected),
                method='Iniciais das palavras da denominação, sem conectores; mesma fonte; '
                       'conflitos rejeitados; query, variáveis numeradas e frequência definem a prioridade.')
