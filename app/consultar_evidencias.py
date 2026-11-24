"""Consulta de evidências com E5+BGE, sem geração, registros ou alterações no banco."""
import argparse

from app.document_lock import catalog_read


@catalog_read()
def inspect(question):
    from app.rag_retrieval.integration import collect
    return collect(question)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('question')
    args = parser.parse_args()
    result = inspect(args.question)
    print('PERGUNTA:', result['question'])
    print('Candidatos pontuados pelo BGE:', result['candidate_count'])
    for d in result['selection']['decisions']:
        print(f"{d['source_file']} | {d['section']} {d['title']} | {d['mode']}")
    for warning in result['warnings']:
        print('AVISO:', warning)
    print('\nEVIDÊNCIAS ORIGINAIS SELECIONADAS:\n' + result['context'])
    print('\nTotal estimado com reservas:', result['selection']['total_reserved_estimated'])
    print('Tempo (inclui embeddings, busca e BGE):', round(result['searched']-result['started'], 3), 's')
    print('Chamadas ao gerador: 0')


if __name__ == '__main__':
    main()
