import json
from pathlib import Path

KB_PATH = Path(__file__).resolve().parent.parent.parent / "docs" / "poc" / "sample_knowledge_base.json"
CONFIDENCE_THRESHOLD = 0.7

with open(KB_PATH, encoding="utf-8") as f:
    _KB = json.load(f)


def search(question: str) -> dict | None:
    """
    질문에 키워드가 매칭되는 지식베이스 항목을 반환.
    매칭되는 항목이 없으면 None.
    """
    for entry in _KB.values():
        if not isinstance(entry, dict):
            continue  # _notice처럼 메타데이터성 문자열 항목은 건너뜀
        if any(keyword in question for keyword in entry.get("keywords", [])):
            return entry
    return None
