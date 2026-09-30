import re
import unicodedata

from resolveops.knowledge.models import KnowledgeDocument

UNTRUSTED_INSTRUCTION_PATTERNS = (
    re.compile(
        r"\b(ignore|disregard|override|forget)\s+(all\s+|any\s+|the\s+)?(previous|prior|system|developer)\s+instructions?\b",
        re.IGNORECASE,
    ),
    re.compile(
        r"\b(reveal|print|return|expose)\s+(the\s+)?(system|developer)\s+prompt\b", re.IGNORECASE
    ),
    re.compile(r"\b(call|invoke|execute|run)\s+(a\s+|the\s+)?tool\b", re.IGNORECASE),
    re.compile(
        r"\b(exfiltrate|upload|send)\b.{0,80}\b(secret|token|credential|api[ -]?key)\b",
        re.IGNORECASE,
    ),
    re.compile(r"<\s*script\b", re.IGNORECASE),
    re.compile(r"\bjavascript\s*:", re.IGNORECASE),
    re.compile(r"\]\(\s*data\s*:", re.IGNORECASE),
)


class KnowledgeSecurityError(ValueError):
    pass


def validate_knowledge_security(document: KnowledgeDocument) -> None:
    content = document.content
    if "<!--" in content or "-->" in content:
        raise KnowledgeSecurityError("knowledge content contains hidden HTML comments")
    if any(unicodedata.category(character) == "Cf" for character in content):
        raise KnowledgeSecurityError("knowledge content contains unsafe invisible controls")
    if any(pattern.search(content) for pattern in UNTRUSTED_INSTRUCTION_PATTERNS):
        raise KnowledgeSecurityError("knowledge content contains an unsafe instruction pattern")
