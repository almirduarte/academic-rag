"""Unidades extrativas com proveniência; não faz ranking nem geração.

Não contém números de artigos, documentos ou perguntas específicos da suíte.
Condições entre alíneas são tratadas conservadoramente: inclui a primeira
alínea, ancestrais e definições finais. Referências externas são sinalizadas.
"""
from collections import defaultdict
import re

ARTICLE = re.compile(r'(?<!\w)Art\.\s*(\d{1,3})(?:[º°.]|(?=\s))\s*(?=[A-ZÁÀÂÃÉÊÍÓÔÕÚÜÇ])')
LETTER = re.compile(r'(?<!\S)([a-z])\)\s+')
REFERENCE = re.compile(r'\balínea\s+["\x27“]?([a-z])\b', re.I)
EXTERNAL = re.compile(r'\b(?:art\.?\s*\d|artigo\s+\d|alíneas\b|subalíneas?\b)', re.I)
DEFINITION = re.compile(r'\bOnde\s*:', re.I)


def reconstruct(rows, min_overlap=32):
    docs = defaultdict(list)
    seen = set()
    for row in rows:
        key = row['source_file'], row['chunk_index']
        if key in seen:
            raise ValueError(f'Chunk duplicado: {key}')
        seen.add(key)
        docs[row['source_file']].append(row)
    runs, warnings = [], []
    for source, chunks in sorted(docs.items()):
        text, spans, previous, run_no = '', [], None, 0
        for row in sorted(chunks, key=lambda r: r['chunk_index']):
            value = row['content'].strip()
            overlap = 0
            if previous is not None and row['chunk_index'] == previous + 1:
                matches = [n for n in range(min(len(text), len(value)), min_overlap - 1, -1)
                           if text.endswith(value[:n])]
                if len(matches) == 1:
                    overlap = matches[0]
            if spans and not overlap:
                runs.append(dict(source_file=source, run=run_no, text=text, spans=spans,
                                 indexed_end=False))
                warnings.append(f'{source}: quebra antes do chunk {row["chunk_index"]}')
                text, spans, run_no = '', [], run_no + 1
            start = len(text) - overlap
            text += value[overlap:]
            spans.append(dict(chunk=row['chunk_index'], start=start, end=len(text)))
            previous = row['chunk_index']
        if spans:
            runs.append(dict(source_file=source, run=run_no, text=text, spans=spans,
                             indexed_end=True))
    return runs, warnings


def source_spans(run, start, end):
    return [dict(chunk=s['chunk'], start=max(start, s['start']), end=min(end, s['end']))
            for s in run['spans'] if s['start'] < end and s['end'] > start]


def sections_from_runs(runs):
    # Reutiliza a convenção de títulos já testada pelo usuário.
    from .retrieval_sections import HEADING, valid_heading, heading_title
    sections = []
    for run in runs:
        text = run['text']
        numbered = [m for m in HEADING.finditer(text) if valid_heading(m)]
        articles = list(ARTICLE.finditer(text))
        # Formato de artigos só é adotado com sequência de pelo menos 2 inícios
        # crescentes. Uma referência isolada não vira limite de artigo.
        nums = [int(m[1]) for m in articles]
        use_articles = len(nums) >= 2 and all(a < b for a, b in zip(nums, nums[1:]))
        markers = ([(m.start(), f'Art. {m[1]}', m.group().strip(), 'article') for m in articles]
                   if use_articles else
                   [(m.start(), m['number'], heading_title(m), 'section') for m in numbered])
        if not markers or markers[0][0] > 0:
            markers.insert(0, (0, 'preâmbulo', 'Texto sem título reconhecido', 'unstructured'))
        for i, (start, number, title, kind) in enumerate(markers):
            end = markers[i + 1][0] if i + 1 < len(markers) else len(text)
            if not text[start:end].strip():
                continue
            # Remove A/O final indevidamente absorvido do início da prosa.
            if kind == 'section':
                title = re.sub(r'\s+[AO]$', '', title)
            identifier = f'{run["source_file"]}::{run["run"]}:{start}:{end}'
            sections.append(dict(id=identifier, source_file=run['source_file'], run=run['run'],
                                 section=number, title=title, kind=kind, start=start, end=end,
                                 content=text[start:end], source_spans=source_spans(run, start, end),
                                 boundary=('next_heading' if i + 1 < len(markers) else
                                           'indexed_end' if run['indexed_end'] else 'broken'),
                                 parent_id=None))
    # Hierarquia numérica apenas dentro do mesmo documento/bloco reconstruído.
    lookup = {(s['source_file'], s['run'], s['section']): s for s in sections if s['kind'] == 'section'}
    for s in sections:
        number = s['section']
        while '.' in number and s['kind'] == 'section':
            number = number.rsplit('.', 1)[0]
            parent = lookup.get((s['source_file'], s['run'], number))
            if parent:
                s['parent_id'] = parent['id']
                break
    return sections


def split_units(sections):
    units = []
    for section in sections:
        text, base = section['content'], section['start']
        marks = list(LETTER.finditer(text))
        valid = (section['kind'] == 'section' and section['boundary'] != 'broken' and marks
                 and [m[1] for m in marks] == [chr(97 + i) for i in range(len(marks))])
        footer = None
        if valid:
            # Definições finais conservadas como dependência de todas as alíneas.
            definition = DEFINITION.search(text, marks[-1].end())
            if definition:
                footer = (base + definition.start(), section['end'])
        for i in range(len(marks) if valid else 1):
            start = base + marks[i].start() if valid else base
            end = (base + marks[i + 1].start() if valid and i + 1 < len(marks)
                   else footer[0] if footer else section['end'])
            label = marks[i][1] if valid else None
            body = text[start-base:end-base]
            dependencies = []
            if valid:
                dependencies.append((base, base + marks[0].start()))
                if i > 0:
                    first_end = base + marks[1].start() if len(marks) > 1 else end
                    dependencies.append((base + marks[0].start(), first_end))
                if footer:
                    dependencies.append(footer)
            units.append(dict(id=section['id'] + (f':{label}' if label else ':whole'),
                              section_id=section['id'], label=label, start=start, end=end,
                              dependencies=dependencies, content=body,
                              referenced_letters=REFERENCE.findall(body),
                              reference_warning=bool(EXTERNAL.search(body))))
    return units


def merge_ranges(ranges):
    merged = []
    for start, end in sorted(set(ranges)):
        if end <= start:
            continue
        if merged and start <= merged[-1][1]:
            merged[-1] = (merged[-1][0], max(end, merged[-1][1]))
        else:
            merged.append((start, end))
    return merged


def bundle(unit_ids, units, sections, runs):
    unit_map = {u['id']: u for u in units}
    sec_map = {s['id']: s for s in sections}
    run_map = {(r['source_file'], r['run']): r for r in runs}
    letters = {(u['section_id'], u['label']): u for u in units if u['label']}
    ranges, warnings, visited = defaultdict(list), [], set()
    pending = list(unit_ids)
    while pending:
        uid = pending.pop()
        if uid in visited:
            continue
        visited.add(uid)
        u = unit_map[uid]
        s = sec_map[u['section_id']]
        key = s['source_file'], s['run']
        ranges[key].extend([(u['start'], u['end']), *u['dependencies']])
        # Referência singular só pode ser resolvida localmente se não houver
        # indício de referência a outro artigo; demais casos são sinalizados.
        for letter in u['referenced_letters']:
            ref = letters.get((u['section_id'], letter))
            if ref and not u['reference_warning']:
                pending.append(ref['id'])
            else:
                warnings.append(f'{uid}: referência não resolvida à alínea {letter}')
        if u['reference_warning']:
            warnings.append(f'{uid}: referências normativas exigem conferência')
        parent_id = s['parent_id']
        while parent_id:
            parent = sec_map[parent_id]
            ranges[key].append((parent['start'], parent['end']))
            parent_id = parent['parent_id']
        if s['boundary'] == 'broken':
            warnings.append(f'{uid}: unidade com continuidade interrompida')
    parts = []
    for key, values in sorted(ranges.items()):
        run = run_map[key]
        for start, end in merge_ranges(values):
            parts.append(dict(source_file=key[0], run=key[1], start=start, end=end,
                              text=run['text'][start:end], source_spans=source_spans(run, start, end)))
    context = '\n\n'.join(f'[Fonte {i}] {p["source_file"]} | bloco {p["run"]} '
                            f'| caracteres {p["start"]}:{p["end"]}\n{p["text"]}'
                            for i, p in enumerate(parts, 1))
    return dict(context=context, parts=parts, warnings=sorted(set(warnings)),
                unit_ids=sorted(visited))
