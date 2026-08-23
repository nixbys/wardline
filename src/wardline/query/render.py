"""View-only response shaping (report 4.7 anti-exfiltration): answers carry a
watermark and only ever expose cited snippets, never full raw documents.
"""

from __future__ import annotations


def watermark(session_id: str, answer_text: str) -> str:
    if not answer_text:
        return answer_text
    return f"{answer_text}\n\n— session {session_id}"
