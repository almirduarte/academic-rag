from __future__ import annotations

import json
import sys
import time
import re
import logging
from dataclasses import dataclass

from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from app.config import settings
from app.db import get_chunk_window, search_similar_chunks, search_similar_summaries
from app.embeddings import embed_query, release_gpu_memory

logger = logging.getLogger(__name__)

def normalize_question(question: str) -> str:
    """Uniformiza apenas espaços externos e interrogações finais."""
    return re.sub(r"[?？\s]+$", "", question.strip())


def acronym_definition_target(question: str) -> str | None:
    """Reconhece pedidos curtos de definição, sem pedidos adicionais.

    Exige sigla em maiúsculas para não confundir palavras como 'curso'
    com siglas. Não altera a resposta de perguntas conceituais gerais.
    """
    match = re.fullmatch(
        r"(?i:(?:o que (?:é|significa)|qual (?:é )?o significado (?:de|da)|"
        r"o que quer dizer)\s+(?:(?:a )?sigla\s+)?)"
        r"(?P<acronym>[A-Z][A-Z0-9]{1,11})",
        normalize_question(question),
    )
    return match.group("acronym") if match else None


def build_context(chunks: list[dict], question: str) -> str:
    parts = []

    for i, chunk in enumerate(chunks, start=1):
        content = chunk["content"]

        parts.append(
            f"[Fonte {i}]\n"
            f"Arquivo: {chunk['source_file']}\n"
            f"Chunk: {chunk['chunk_index']}\n"
            f"Conteúdo: {content}"
        )

    return "\n".join(parts)

OUTPUT_LIMIT_WARNING = (
    "A resposta atingiu o limite de saída do modelo e pode estar incompleta. "
    "Itens ou explicações podem ter sido omitidos."
)


@dataclass(frozen=True)
class LLMResponse:
    answer: str
    done_reason: str | None

    @property
    def output_limit_reached(self) -> bool:
        return self.done_reason == "length"


def ask_local_llm(
    question: str,
    context: str,
    system_prompt: str | None = None,
) -> str:
    """Mantém o retorno textual usado pelo terminal e pelos resumos."""
    response = ask_local_llm_result(question, context, system_prompt)
    if response.output_limit_reached:
        print(f"AVISO: {OUTPUT_LIMIT_WARNING}", file=sys.stderr)
    return response.answer


def build_system_prompt(question: str, system_prompt: str | None = None) -> str:
    system = system_prompt or (
        "/no_think\n"
        "Você é um assistente acadêmico. Responda obrigatoriamente em português. "
        "Use somente o contexto fornecido. "
        "Quando a pergunta solicitar apenas o significado de uma sigla, "
        "responda diretamente com sua denominação. "
        "Acrescente explicação somente se necessária e sustentada pelo contexto. "
        "Não expanda outras siglas sem que sua denominação esteja explícita no contexto. "
        "Responda considerando o alcance completo da pergunta. "
        "Quando o objeto perguntado tiver partes, ciclos ou etapas, "
        "não apresente uma característica de apenas uma parte como se fosse do conjunto. "
        "Ao responder sobre a duração de um curso composto por etapas, "
        "informe a duração regular de cada etapa e, quando forem sucessivas "
        "e não se sobrepuserem, calcule a duração regular total. "
        "Diferencie a duração regular do prazo máximo permitido. "
        "Antes de finalizar, confira se alguma etapa descrita no contexto "
        "foi omitida da resposta. "
        "Se a pergunta permitir duas interpretações, esclareça ambas brevemente. "
        "Preserve os nomes e as siglas apresentados no documento. "
        "Quando a pergunta pedir uma lista, apresente todos os itens da seção pertinente, "
        "em uma linha curta por item. "
        "Não invente nem deduza números de artigos, alíneas, incisos ou fontes. "
        "As fontes consultadas serão informadas separadamente pelo programa. "
        "Se o contexto não trouxer a lista completa, informe essa limitação. "
        "Ao analisar uma situação concreta: "
        "- Compare os fatos apresentados com as condições expressas na norma. "
        "- Não considere condições semelhantes como equivalentes sem fundamento textual. "
        "- Não transforme uma possibilidade ou condição ainda não confirmada em fato. "
        "- Se o contexto não esclarecer como um detalhe relevante afeta a aplicação "
        " da regra, informe essa limitação. "
        "- Diferencie o que o documento estabelece da sua interpretação. "
        "- Cite artigos e alíneas exatamente como aparecem no contexto. "
        "- Não conclua aprovação, reprovação ou desligamento quando o contexto "
        " não fornecer fundamento suficiente para aplicar essa consequência ao caso."
    )

    # Preserva prompts próprios usados por resumos e outros chamadores.
    if system_prompt is None:
        question = normalize_question(question)
        acronym = acronym_definition_target(question)
        if acronym:
            system += (
                "\nEsta pergunta solicita somente a denominação da sigla "
                f"{acronym}. Responda em uma única frase curta, com a sigla "
                "e sua denominação explicitamente apresentada no contexto. "
                "Não acrescente hipóteses, fórmulas, exemplos, outras siglas "
                "ou explicações. Se a denominação não estiver explícita, "
                "informe que ela não foi encontrada no contexto. "
                "Se houver denominações conflitantes, informe a ambiguidade."
            )

    return system


def ask_local_llm_result(
    question: str,
    context: str,
    system_prompt: str | None = None,
) -> LLMResponse:
    system = build_system_prompt(question, system_prompt)
    if system_prompt is None:
        question = normalize_question(question)

    user_message = f"CONTEXTO:\n{context}\n\nPERGUNTA:\n{question}"

    def chamar_ollama(system_prompt: str, limite: int) -> dict:
        payload = {
            "model": settings.ollama_model,
            "stream": False,
            "think": False,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_message},
            ],
            "options": {
                "temperature": 0.0,
                "num_ctx": settings.ollama_num_ctx,
                "num_predict": limite,
            },
        }

        import hashlib
        import os

        serialized = json.dumps(
            payload,
            ensure_ascii=False,
            sort_keys=True,
        ).encode("utf-8")

        print(
            "[DIAG] "
            f"pid={os.getpid()} "
            f"modelo={payload['model']} "
            f"sha256={hashlib.sha256(serialized).hexdigest()} "
            f"options={payload.get('options')}",
            file=sys.stderr,
            flush=True,
        )
        
        request = Request(
            f"{settings.ollama_url}/api/chat",
            data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="POST",
        )

        try:
            with urlopen(
                request, timeout=settings.ollama_timeout_seconds
            ) as response:
                return json.loads(response.read().decode("utf-8"))
        except HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="replace")
            raise RuntimeError(
                f"Ollama respondeu HTTP {exc.code}: {detail}"
            ) from exc
        except URLError as exc:
            raise RuntimeError(
                f"Não foi possível acessar Ollama em {settings.ollama_url}. "
                "Verifique se o serviço está ativo e se o modelo foi baixado."
            ) from exc

    # Uma única chamada: não repete a geração ao atingir o limite.
    result = chamar_ollama(system, settings.ollama_num_predict)
    return LLMResponse(
        answer=result.get("message", {}).get("content", "").strip(),
        done_reason=result.get("done_reason"),
    )


def select_context_chunks(
    question: str,
    hits: list[dict],
    summaries: list[dict],
) -> list[dict]:
    import unicodedata

    def terms(text: str) -> set[str]:
        text = unicodedata.normalize("NFKD", text.casefold())
        text = "".join(c for c in text if not unicodedata.combining(c))
        ignored = {
            "qual", "quais", "quanto", "quantos", "como", "onde",
            "para", "pelo", "pela", "pelos", "pelas", "sobre",
            "esta", "estao", "esse", "essa", "esses", "essas",
            "uma", "umas", "dos", "das", "que",
        }
        return {
            word.rstrip("s")[:5]
            for word in re.findall(r"[a-z]+", text)
            if len(word) >= 3 and word not in ignored
        }

    question_terms = terms(question)
    candidates = []

    for summary in summaries:
        for paragraph in re.split(r"\n\s*\n", summary["content"]):
            references = re.findall(
                r"\[chunk\s+(\d+)\]",
                paragraph,
                flags=re.IGNORECASE,
            )
            score = len(question_terms & terms(paragraph))
            if references and score:
                candidates.append((score, summary["source_file"], references))

    # Procura uma seção cujo título corresponda à pergunta.
    # Exemplo de estrutura reconhecida: 3.4. CANCELAMENTO DE MATRÍCULA
    section_pattern = re.compile(
        r"(?<![\w.])"
        r"(?P<number>\d+\.\d+)\.\s+"
        r"(?P<title>[A-ZÀ-Ý][A-ZÀ-Ý \t–—-]*[A-ZÀ-Ý])"
    )

    section_candidates = []

    for hit in hits:
        for match in section_pattern.finditer(hit["content"]):
            title_terms = terms(match.group("title"))
            score = len(question_terms & title_terms)

            # Exige pelo menos duas palavras relevantes em comum.
            if score >= 2 and title_terms <= question_terms:
                section_candidates.append(
                    (score, hit, match.group("number"))
                )

    if section_candidates:
        _, anchor, section_number = max(
            section_candidates,
            key=lambda item: item[0],
        )

        window = get_chunk_window(
            source_file=anchor["source_file"],
            first_index=anchor["chunk_index"],
            last_index=anchor["chunk_index"] + 5,
        )

        section_chunks = []
        section_started = False
        section_finished = False

        for chunk in window:
            content = chunk["content"]
            headings = list(section_pattern.finditer(content))

            if not section_started:
                start_heading = next(
                    (
                        heading
                        for heading in headings
                        if heading.group("number") == section_number
                    ),
                    None,
                )
                if start_heading is None:
                    continue

                content = content[start_heading.start():]
                section_started = True

            # O mesmo título pode reaparecer por causa da sobreposição.
            next_heading = next(
                (
                    heading
                    for heading in section_pattern.finditer(content)
                    if heading.group("number") != section_number
                ),
                None,
            )

            if next_heading is not None:
                content = content[:next_heading.start()]
                section_finished = True

            if content.strip():
                section_chunks.append({
                    **chunk,
                    "content": content.strip(),
                })

            if section_finished:
                break

        if section_started and section_finished:
            return section_chunks

        # Evita apresentar uma seção incompleta como se estivesse completa.
        raise RuntimeError(
            f"A seção {section_number} foi localizada, mas seu término "
            "não foi encontrado na janela de seis trechos."
        )

    chunks = []
    seen = set()

    def add(chunk: dict) -> None:
        key = (chunk["source_file"], chunk["chunk_index"])
        if key not in seen:
            seen.add(key)
            chunks.append(chunk)

    if candidates:
        _, source_file, references = max(
            candidates,
            key=lambda candidate: candidate[0],
        )
        indexes = list(dict.fromkeys(int(ref) for ref in references))[:4]
        for index in indexes:
            for chunk in get_chunk_window(source_file, index, index):
                add(chunk)

    for hit in hits[:3]:
        add(hit)

    return chunks[:5]


class NoContextError(RuntimeError):
    """Não há trechos documentais disponíveis para responder."""


from app.document_lock import catalog_read

@catalog_read()
def run_query(question: str) -> dict:
    """Fluxo RAG compartilhado pelo terminal e pela API.

    Autenticação, registro do usuário e fila HTTP pertencem à API.
    """
    original_question = question.strip()
    question = normalize_question(original_question)
    if not question:
        raise ValueError("Informe uma pergunta.")
    # Opt-in por processo; o modo padrão conserva o fluxo anterior.
    import os
    retrieval_mode = os.environ.get("RAG_RETRIEVAL", "legacy")
    if retrieval_mode == "bge":
        from app.rag_retrieval.integration import run_bge_query
        return run_bge_query(original_question)
    if retrieval_mode != "legacy":
        raise ValueError("RAG_RETRIEVAL deve ser legacy ou bge.")
    started = time.perf_counter()
    question_embedding = embed_query(question)
    release_gpu_memory()
    embedded = time.perf_counter()

    summary_hits = search_similar_summaries(question_embedding, 1)
    hits = search_similar_chunks(
        question_embedding,
        max(settings.top_k, 8),
    )
    if not hits and not summary_hits:
        raise NoContextError(
            "Nenhum conteúdo encontrado na base documental.",
        )

    chunks = select_context_chunks(question, hits, summary_hits)

    if not chunks:
        raise NoContextError(
            "Nenhum trecho original encontrado para a consulta.",
        )

    # Procura definições no próprio documento, sem nome ou índice fixo.
    from app.documents_store import get_definition_chunks
    selected = "\n".join(c["content"] for c in chunks)
    if re.search(r"\b(?:CE|CPE)\b", selected):
        seen = {(c["source_file"], c["chunk_index"]) for c in chunks}
        for source in dict.fromkeys(c["source_file"] for c in chunks):
            source_text = "\n".join(c["content"] for c in chunks if c["source_file"] == source)
            if "Ciclo Escolar (CE)" in source_text and "Ciclo Pós-Escolar (CPE)" in source_text:
                continue
            for definition in get_definition_chunks(source):
                key = (definition["source_file"], definition["chunk_index"])
                if key not in seen:
                    chunks.append(definition)
                    seen.add(key)

    context = build_context(chunks, question)
    searched = time.perf_counter()

    logger.info(
        "Trechos enviados ao modelo: %s",
        [(chunk["source_file"], chunk["chunk_index"]) for chunk in chunks],
    )

    llm_response = ask_local_llm_result(question, context)
    finished = time.perf_counter()
    return {
        "question": original_question,
        "model": settings.ollama_model,
        "answer": llm_response.answer,
        "output_limit_reached": llm_response.output_limit_reached,
        "warnings": [OUTPUT_LIMIT_WARNING] if llm_response.output_limit_reached else [],
        "sources": [
            {"file": chunk["source_file"], "chunk": chunk["chunk_index"]}
            for chunk in chunks
        ],
        "timings_seconds": {
            "embedding": round(embedded - started, 3),
            "search": round(searched - embedded, 3),
            "generation_and_context": round(finished - searched, 3),
            "total": round(finished - started, 3),
        },
    }


def main() -> None:
    if len(sys.argv) < 2:
        print('Uso: python -m app.query "Sua pergunta aqui"')
        return
    try:
        result = run_query(" ".join(sys.argv[1:]))
    except (ValueError, RuntimeError, TimeoutError) as exc:
        print(f"ERRO: {exc}", file=sys.stderr)
        raise SystemExit(1) from exc

    print("Modelo configurado:", result["model"])
    timings = result["timings_seconds"]
    print(f"embedding pergunta : {timings['embedding']:.3f}s")
    print(f"busca/contexto     : {timings['search']:.3f}s")
    print(f"geração local      : {timings['generation_and_context']:.3f}s")
    print(f"total              : {timings['total']:.3f}s")
    print("\n=== PERGUNTA ===")
    print(result["question"])
    print("\n=== TRECHOS RECUPERADOS ===")
    for source in result["sources"]:
        print(f"- {source['file']} | chunk {source['chunk']}")
    print("\n=== RESPOSTA LOCAL ===")
    for warning in result["warnings"]:
        print(f"AVISO: {warning}")
    print(result["answer"])


if __name__ == "__main__":
    main()
