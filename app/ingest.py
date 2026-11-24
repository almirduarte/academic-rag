from __future__ import annotations

import argparse
from pathlib import Path


from app.config import settings
from app.db import ensure_schema, get_source_files, insert_chunks
from app.embeddings import embed_documents


BASE_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = BASE_DIR / "data"


def read_pdf_text(path: Path) -> str:
    from app.document_text import extract_document
    return extract_document(path)[0]

def read_txt_text(path: Path) -> str:
    return path.read_text(encoding="utf-8").strip()


def chunk_text(text: str, chunk_size: int, overlap: int) -> list[str]:
    clean_text = " ".join(text.split())
    if not clean_text:
        return []
    if chunk_size <= 0 or overlap < 0 or overlap >= chunk_size:
        raise ValueError("Use chunk_size > 0 e overlap entre 0 e chunk_size - 1.")

    chunks: list[str] = []
    start = 0
    while start < len(clean_text):
        end = min(start + chunk_size, len(clean_text))
        chunk = clean_text[start:end].strip()
        if chunk:
            chunks.append(chunk)
        if end >= len(clean_text):
            break
        start = end - overlap
    return chunks


def load_documents() -> list[tuple[str, str]]:
    docs: list[tuple[str, str]] = []
    if not DATA_DIR.exists():
        return docs
    for path in sorted(DATA_DIR.glob("*")):
        if path.suffix.lower() == ".pdf":
            text = read_pdf_text(path)
        elif path.suffix.lower() == ".txt":
            text = read_txt_text(path)
        else:
            continue
        if text.strip():
            docs.append((path.name, text))
    return docs


def main() -> None:
    parser = argparse.ArgumentParser(description="Indexa documentos com embeddings E5 locais.")
    parser.add_argument(
        "--replace",
        action="store_true",
        help="Desativado: use app.documents para substituir uma fonte.",
    )
    args = parser.parse_args()

    if args.replace:
        raise SystemExit("Use python -m app.documents prepare/apply; --replace foi desativado.")

    documents = load_documents()
    if not documents:
        print(f"Nenhum PDF ou TXT com texto encontrado em {DATA_DIR}")
        return

    ensure_schema(settings.embedding_dimensions)

    if not args.replace:
        fontes_existentes = get_source_files()
        quantidade_original = len(documents)

        documents = [
            (source_file, text)
            for source_file, text in documents
            if source_file not in fontes_existentes
        ]

        ignorados = quantidade_original - len(documents)
        if ignorados:
            print(f"Documentos já indexados ignorados: {ignorados}")

        if not documents:
            print("Nenhum documento novo para ingerir.")
            return
        
    print(f"Documentos encontrados: {len(documents)}")
    total_chunks = 0
    for source_file, text in documents:
        chunks = chunk_text(text, settings.chunk_size, settings.chunk_overlap)
        if not chunks:
            continue
        print(f"- {source_file}: {len(chunks)} chunks")
        vectors = embed_documents(chunks)
        insert_chunks(
            (source_file, index, chunk, vectors[index])
            for index, chunk in enumerate(chunks)
        )
        total_chunks += len(chunks)

    print(f"Ingestão local concluída. Total de chunks gravados: {total_chunks}")


if __name__ == "__main__":
    main()
