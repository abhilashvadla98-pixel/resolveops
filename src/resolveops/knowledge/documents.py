import tomllib
from pathlib import Path

from pydantic import ValidationError

from resolveops.knowledge.models import KnowledgeDocument


class KnowledgeDocumentError(ValueError):
    pass


def load_knowledge_document(path: Path, *, source_path: str | None = None) -> KnowledgeDocument:
    try:
        raw_text = path.read_text(encoding="utf-8")
    except OSError as exc:
        raise KnowledgeDocumentError(f"cannot read knowledge document {path}") from exc
    return parse_knowledge_document(
        raw_text,
        source_path=source_path or path.as_posix(),
    )


def parse_knowledge_document(raw_text: str, *, source_path: str) -> KnowledgeDocument:
    normalized = raw_text.replace("\r\n", "\n").replace("\r", "\n")
    lines = normalized.splitlines()
    if not lines or lines[0].strip() != "+++":
        raise KnowledgeDocumentError("knowledge document must start with TOML front matter")

    try:
        closing_index = next(
            index for index, line in enumerate(lines[1:], start=1) if line.strip() == "+++"
        )
    except StopIteration as exc:
        raise KnowledgeDocumentError("knowledge document front matter is not closed") from exc

    front_matter_text = "\n".join(lines[1:closing_index])
    content = "\n".join(lines[closing_index + 1 :]).strip()
    if not content:
        raise KnowledgeDocumentError("knowledge document body cannot be empty")

    try:
        metadata = tomllib.loads(front_matter_text)
    except tomllib.TOMLDecodeError as exc:
        raise KnowledgeDocumentError("knowledge document front matter is invalid TOML") from exc

    try:
        return KnowledgeDocument(
            **metadata,
            source_path=source_path,
            content=content,
        )
    except ValidationError as exc:
        raise KnowledgeDocumentError(f"invalid knowledge document metadata: {exc}") from exc
