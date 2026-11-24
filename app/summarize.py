from __future__ import annotations
from pathlib import Path

import re
import sys
import time

from app.db import get_document_chunks
from app.query import ask_local_llm


SOURCE_FILE = "a-republica-platao.pdf"
OVERLAP = 150
BATCH_CHARS = 7000

ROMAN_BOOKS = {
    "I": 1, "II": 2, "III": 3, "IV": 4, "V": 5,
    "VI": 6, "VII": 7, "VIII": 8, "IX": 9, "X": 10,
}
BOOK_MARKER = re.compile(
    r"\bLIVRO\s+(VIII|VII|VI|V|IV|III|II|IX|X|I)\b",
    re.IGNORECASE,
)

MAP_PROMPT = (
    "/no_think\n"
    "O trecho pertence a A República, de Platão, Livro II. "
    "Responda em português e use somente o trecho. "
    "Registre até três ideias importantes. Para cada uma, identifique "
    "quem a apresenta e se é um desafio, uma proposta, uma objeção "
    "ou uma conclusão. Não atribua a Sócrates a fala de outro personagem. "
    "Não transforme uma hipótese em conclusão. Inclua uma frase curta "
    "copiada literalmente do trecho como evidência. Se o autor ou o papel "
    "não estiver claro, diga 'não identificado'. "
    "os rótulos [FALANTE: ...] vieram dos marcadores explícitos do texto; "
    "preserve-os. Se a fala relatar a opinião de terceiros — por exemplo, "
    "“eles dirão” —, diferencie essa opinião da posição do personagem que está falando."
)

FINAL_PROMPT = (
    "/no_think\n"
    "Responda em português, usando somente as notas fornecidas. "
    "Escreva uma síntese panorâmica de 200 a 300 palavras sobre os temas, "
    "argumentos e desenvolvimento da discussão. Preserve as divergências "
    "entre os personagens. Não atribua uma opinião a Sócrates se as notas "
    "a identificarem como fala de outro personagem. Não acrescente conclusões "
    "ou fatos que não constem nas notas; omita o que estiver incerto."
)

SPEAKER_MARKER = re.compile(
    r"(?<!\w)(Sócrates|Glauco|Adimanto)\s*[—–-]\s*",
    re.IGNORECASE,
)


def annotate_speakers(text: str) -> str:
    matches = list(SPEAKER_MARKER.finditer(text))
    if not matches:
        return text

    parts = []

    if matches[0].start() > 0:
        parts.append(
            "[TRECHO SEM MARCADOR DE FALA]\n"
            + text[:matches[0].start()].strip()
        )

    for index, match in enumerate(matches):
        end = (
            matches[index + 1].start()
            if index + 1 < len(matches)
            else len(text)
        )
        speaker = match.group(1).capitalize()
        speech = text[match.end():end].strip()
        parts.append(f"[FALANTE: {speaker}]\n{speech}")

    return "\n\n".join(parts)

def reconstruct_text(chunks: list[dict]) -> str:
    if not chunks:
        return ""

    text = chunks[0]["content"]

    for chunk in chunks[1:]:
        content = chunk["content"]
        overlap = min(OVERLAP, len(text), len(content))

        # Ajusta a sobreposição caso o corte tenha removido espaços.
        while overlap > 0 and not text.endswith(content[:overlap]):
            overlap -= 1

        text += content[overlap:]

    return text


def extract_book(text: str, book_number: int) -> str:
    matches = list(BOOK_MARKER.finditer(text))

    for index, match in enumerate(matches):
        roman = match.group(1).upper()
        if ROMAN_BOOKS[roman] != book_number:
            continue

        end = len(text)
        if index + 1 < len(matches):
            end = matches[index + 1].start()

        return text[match.start():end].strip()

    raise ValueError(f"Não encontrei o marcador do Livro {book_number}.")


def split_text(text: str) -> list[str]:
    parts = []
    start = 0

    while start < len(text):
        end = min(start + BATCH_CHARS, len(text))

        if end < len(text):
            boundary = text.rfind(" ", start + 3000, end)
            if boundary > start:
                end = boundary

        parts.append(text[start:end].strip())
        start = end

    return [part for part in parts if part]


def main() -> None:
    started = time.perf_counter()
    book_number = int(sys.argv[1]) if len(sys.argv) > 1 else 1

    stage_started = time.perf_counter()
    chunks = get_document_chunks(SOURCE_FILE, 0, 10000)
    if not chunks:
        raise RuntimeError(f"Não encontrei chunks para {SOURCE_FILE}.")

    text = reconstruct_text(chunks)
    book_text = annotate_speakers(extract_book(text, book_number))
    batches = split_text(book_text)
    prepared = time.perf_counter()

    print(f"Livro: {book_number}")
    print(f"Chunks lidos: {len(chunks)}")
    print(f"Blocos para síntese: {len(batches)}")
    print(f"Preparação do texto: {prepared - stage_started:.2f} s")

    notes = []
    notes_path = Path("data/summaries") / f"livro-{book_number:02d}-notas.md"
    notes_path.parent.mkdir(parents=True, exist_ok=True)
    synthesis_started = time.perf_counter()

    for index, batch in enumerate(batches, start=1):
        batch_started = time.perf_counter()
        print(f"Processando bloco {index}/{len(batches)}...", flush=True)

        note = ask_local_llm(
            "Faça uma nota das ideias centrais deste trecho.",
            batch,
            system_prompt=MAP_PROMPT,
        )
        notes.append(f"Bloco {index}:\n{note}")
        notes_path.write_text("\n\n".join(notes), encoding="utf-8")

        print(
            f"  Bloco {index}: {time.perf_counter() - batch_started:.2f} s",
            flush=True,
        )

    notes_finished = time.perf_counter()
    print("Consolidando as notas...", flush=True)

    answer = ask_local_llm(
        f"Faça uma síntese panorâmica do Livro {book_number}.",
        "\n\n".join(notes),
        system_prompt=FINAL_PROMPT,
    )

    finished = time.perf_counter()

    print("\n=== SÍNTESE DO LIVRO ===\n")
    print(answer)
    print("\n=== TEMPOS ===")
    print(f"Preparação do texto: {prepared - stage_started:.2f} s")
    print(f"Notas dos blocos:    {notes_finished - synthesis_started:.2f} s")
    print(f"Consolidação:        {finished - notes_finished:.2f} s")
    print(f"Tempo total:         {finished - started:.2f} s")


if __name__ == "__main__":
    main()
