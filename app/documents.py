"""Correção de uma fonte: inspect, prepare, apply e restore. Sem histórico consultável."""
from __future__ import annotations
import argparse
import hashlib
import json
import math
import os
from pathlib import Path
import shutil

from app.document_text import extract_document, make_chunks, reading_map


def dump(path, value):
    with path.open('x', encoding='utf-8') as f:
        json.dump(value, f, ensure_ascii=False, indent=2, allow_nan=False)
    path.chmod(0o600)


def validate(data, dimensions):
    if not data['chunks']:
        raise ValueError('Pacote sem trechos.')
    if [c['chunk_index'] for c in data['chunks']] != list(range(len(data['chunks']))):
        raise ValueError('Índices dos trechos não são contíguos e únicos.')
    for item in data['chunks'] + data['summaries']:
        vector = item['embedding']
        if not item['content'].strip() or len(vector) != dimensions:
            raise ValueError('Conteúdo vazio ou dimensão de embedding incompatível.')
        if not all(isinstance(x, (float,int)) and math.isfinite(x) for x in vector):
            raise ValueError('Embedding inválido.')
        if not any(vector):
            raise ValueError('Embedding nulo.')


def package(args):
    path = Path(args.file).resolve()
    text, metadata = extract_document(path)
    from app.config import settings
    chunks = make_chunks(text, settings.chunk_size, settings.chunk_overlap)
    source = args.source or path.name
    if source != Path(source).name or source in ('', '.', '..') or '\\' in source:
        raise ValueError('source deve ser apenas o nome do arquivo, sem diretórios.')
    if Path(source).suffix.lower() != path.suffix.lower():
        raise ValueError('source deve manter a extensão do arquivo.')
    folder = Path(args.output).resolve()
    data_dir = Path(__file__).resolve().parent.parent / 'data'
    if folder == data_dir or data_dir in folder.parents:
        raise ValueError('Use um diretório de preparação fora de data/.')
    folder.mkdir(mode=0o700, parents=True, exist_ok=False)
    (folder/'texto-extraido.txt').write_text(text, encoding='utf-8')
    summary = reading_map(text, chunks)
    (folder/'mapa.md').write_text(summary, encoding='utf-8')
    dump(folder/'chunks.json', chunks)
    shutil.copyfile(path, folder/source)
    metadata.update(source_file=source, chunks=len(chunks), chunk_size=settings.chunk_size,
                    chunk_overlap=settings.chunk_overlap, embedding_model=settings.embedding_model,
                    embedding_dimensions=settings.embedding_dimensions)
    dump(folder/'extracao.json',metadata)
    print(json.dumps(metadata, ensure_ascii=False, indent=2))
    if args.command == 'inspect':
        print('Inspeção concluída. Banco e modelos não foram acessados.')
        return
    from app.documents_store import read_snapshot
    from app.embeddings import embed_documents, release_gpu_memory
    before = read_snapshot(args.replace_source)
    if not before['chunks']:
        raise ValueError('Fonte a substituir não foi encontrada; nada foi alterado.')
    # Backup persistido antes de embeddings e antes de qualquer escrita no banco.
    dump(folder/'backup.json', before)
    vectors = embed_documents([c['content'] for c in chunks] + [summary])
    release_gpu_memory()
    if len(vectors) != len(chunks)+1:
        raise ValueError('Quantidade de embeddings incorreta.')
    after = {'source_file': source,
             'chunks': [dict(chunk_index=c['chunk_index'],content=c['content'],embedding=v)
                        for c,v in zip(chunks,vectors)],
             'summaries': [dict(summary_type='work',book_number=None,content=summary,embedding=vectors[-1])]}
    validate(after,settings.embedding_dimensions)
    dump(folder/'replacement.json',after)
    # O manifesto é escrito por último. Pacote interrompido nunca é aplicável.
    hashes = {p.name:hashlib.sha256(p.read_bytes()).hexdigest()
              for p in folder.iterdir() if p.is_file()}
    dump(folder/'manifest.json',{'format':1,'files':hashes,'metadata':metadata})
    print(f'Preparado: {folder}. Revise texto-extraido.txt e mapa.md antes de aplicar.')


def load_package(folder):
    manifest = json.loads((folder/'manifest.json').read_text())
    if manifest.get('format') != 1:
        raise ValueError('Formato de pacote desconhecido.')
    for name, digest in manifest['files'].items():
        if Path(name).name != name or name in ('.','..'):
            raise ValueError('Nome inválido no manifesto.')
        p = folder/name
        if p.is_symlink() or hashlib.sha256(p.read_bytes()).hexdigest() != digest:
            raise ValueError(f'Arquivo alterado após preparação: {name}')
    for name in ['backup.json','replacement.json','extracao.json','texto-extraido.txt','mapa.md']:
        if name not in manifest['files']:
            raise ValueError('Pacote incompleto.')
    before=json.loads((folder/'backup.json').read_text())
    after=json.loads((folder/'replacement.json').read_text())
    from app.config import settings
    if manifest['metadata']['embedding_model'] != settings.embedding_model:
        raise ValueError('Modelo de embeddings foi alterado desde a preparação.')
    if manifest['metadata']['source_file'] != after['source_file']:
        raise ValueError('Identificação da fonte incompatível com o manifesto.')
    if after['source_file'] not in manifest['files']:
        raise ValueError('Arquivo documental ausente do pacote.')
    validate(after,settings.embedding_dimensions)
    return before,after


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    sub=parser.add_subparsers(dest='command',required=True)
    for command in ['inspect','prepare']:
        p=sub.add_parser(command)
        p.add_argument('--file',required=True)
        p.add_argument('--source',help='Nome limpo que aparecerá nas fontes, com extensão.')
        p.add_argument('--output',required=True,help='Diretório novo, privado e fora de data/.')
        if command=='prepare':
            p.add_argument('--replace-source',required=True,help='source_file exato existente no banco.')
    for command in ['apply','restore']:
        p=sub.add_parser(command)
        p.add_argument('--package',required=True)
        p.add_argument('--api-stopped',required=True,action='store_true',
                       help='Confirma que a API e outros gravadores foram parados.')
    args=parser.parse_args()
    os.umask(0o077)
    try:
        if args.command in ('inspect','prepare'):
            package(args)
        else:
            from app.documents_store import replace_atomic
            before,after=load_package(Path(args.package).resolve())
            if args.command=='restore':
                replace_atomic(after,before)
            else:
                replace_atomic(before,after)
            print('Transação confirmada. Confira os arquivos em data/ e reinicie a API.')
    except Exception as exc:
        raise SystemExit(f'ERRO: {exc}') from exc

if __name__=='__main__':
    main()
