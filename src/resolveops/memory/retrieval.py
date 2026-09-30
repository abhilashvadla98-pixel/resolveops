from typing import Protocol

from resolveops.memory.models import ReviewedResolutionMemory


class ReviewedMemoryRetriever(Protocol):
    def retrieve(
        self, *, tenant_id: str, issue_type: str, limit: int = 5
    ) -> list[ReviewedResolutionMemory]: ...


def select_applicable_memories(
    retriever: ReviewedMemoryRetriever,
    *,
    tenant_id: str,
    issue_types: list[str],
    current_policy_versions: dict[str, int],
    limit: int = 5,
) -> list[ReviewedResolutionMemory]:
    """Return reviewed examples only when every cited policy version is still current."""
    if not current_policy_versions:
        return []
    selected: list[ReviewedResolutionMemory] = []
    seen: set[str] = set()
    for issue_type in dict.fromkeys(issue_types):
        for memory in retriever.retrieve(tenant_id=tenant_id, issue_type=issue_type, limit=limit):
            versions_match = all(
                current_policy_versions.get(document_id) == version
                for document_id, version in memory.policy_versions.items()
            )
            if memory.memory_id in seen or not versions_match:
                continue
            selected.append(memory)
            seen.add(memory.memory_id)
            if len(selected) >= limit:
                return selected
    return selected


def issue_types_from_tool_results(results: list[dict[str, object]]) -> list[str]:
    issue_types: list[str] = []
    for result in results:
        data = result.get("data")
        if not isinstance(data, dict):
            continue
        issues = data.get("issues")
        if not isinstance(issues, list):
            continue
        for issue in issues:
            if not isinstance(issue, dict):
                continue
            issue_type = issue.get("issue_type")
            if isinstance(issue_type, str) and issue_type:
                issue_types.append(issue_type)
    return list(dict.fromkeys(issue_types))
