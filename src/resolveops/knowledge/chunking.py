import hashlib
import re
from dataclasses import dataclass

from resolveops.knowledge.models import KnowledgeChunk, KnowledgeDocument

HEADING_PATTERN = re.compile(r"^(#{1,6})\s+(.+?)\s*$")


@dataclass(frozen=True)
class _Section:
    heading: str
    body: str


def chunk_document(
    document: KnowledgeDocument,
    *,
    max_characters: int = 1000,
    overlap_paragraphs: int = 1,
) -> list[KnowledgeChunk]:
    if max_characters < 200:
        raise ValueError("max_characters must be at least 200")
    if overlap_paragraphs < 0:
        raise ValueError("overlap_paragraphs cannot be negative")

    chunks: list[KnowledgeChunk] = []
    for section in _markdown_sections(document.content, document.title):
        prefix = f"{document.title}\n{section.heading}"
        available = max_characters - len(prefix) - 2
        if available < 80:
            raise ValueError("document title and heading leave too little room for chunk text")
        pieces = _paragraph_pieces(section.body, available)
        for body in _pack_pieces(pieces, available, overlap_paragraphs):
            text = f"{prefix}\n\n{body}".strip()
            content_sha256 = hashlib.sha256(text.encode("utf-8")).hexdigest()
            chunk_index = len(chunks)
            identity = f"{document.version_id}:{chunk_index}:{content_sha256}"
            chunk_id = f"KCH-{hashlib.sha256(identity.encode('utf-8')).hexdigest()[:24].upper()}"
            chunks.append(
                KnowledgeChunk(
                    chunk_id=chunk_id,
                    document_version_id=document.version_id,
                    chunk_index=chunk_index,
                    heading=section.heading,
                    text=text,
                    content_sha256=content_sha256,
                )
            )

    if not chunks:
        raise ValueError("knowledge document did not produce any chunks")
    return chunks


def _markdown_sections(content: str, document_title: str) -> list[_Section]:
    sections: list[_Section] = []
    heading_stack: list[str] = []
    body_lines: list[str] = []
    document_title_seen = False

    def finish_section() -> None:
        body = "\n".join(body_lines).strip()
        if body:
            heading = " > ".join(heading_stack) if heading_stack else "Overview"
            sections.append(_Section(heading=heading, body=body))
        body_lines.clear()

    for line in content.splitlines():
        match = HEADING_PATTERN.match(line)
        if match is None:
            body_lines.append(line)
            continue
        finish_section()
        level = len(match.group(1))
        heading_text = match.group(2).strip()
        if level == 1 and heading_text.casefold() == document_title.casefold():
            heading_stack.clear()
            document_title_seen = True
            continue
        effective_level = max(1, level - 1) if document_title_seen else level
        heading_stack[effective_level - 1 :] = [heading_text]

    finish_section()
    return sections


def _paragraph_pieces(body: str, max_characters: int) -> list[str]:
    paragraphs = [item.strip() for item in re.split(r"\n\s*\n", body) if item.strip()]
    pieces: list[str] = []
    for paragraph in paragraphs:
        remaining = paragraph
        while len(remaining) > max_characters:
            split_at = remaining.rfind(" ", 0, max_characters + 1)
            if split_at <= 0:
                split_at = max_characters
            pieces.append(remaining[:split_at].strip())
            remaining = remaining[split_at:].strip()
        if remaining:
            pieces.append(remaining)
    return pieces


def _pack_pieces(pieces: list[str], max_characters: int, overlap_paragraphs: int) -> list[str]:
    packed: list[str] = []
    current: list[str] = []
    for piece in pieces:
        candidate = "\n\n".join([*current, piece])
        if current and len(candidate) > max_characters:
            packed.append("\n\n".join(current))
            overlap = current[-overlap_paragraphs:] if overlap_paragraphs else []
            while overlap and len("\n\n".join([*overlap, piece])) > max_characters:
                overlap = overlap[1:]
            current = [*overlap, piece]
        else:
            current.append(piece)
    if current:
        packed.append("\n\n".join(current))
    return packed
