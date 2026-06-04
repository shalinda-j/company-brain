"""Paragraph-aware chunking. Keeps related text together, falls back to a
sliding window for very long paragraphs. Works fine on Unicode (Sinhala) text.
"""

from __future__ import annotations


def _window(text: str, size: int, overlap: int) -> list[str]:
    if len(text) <= size:
        return [text]
    chunks: list[str] = []
    start = 0
    step = max(1, size - overlap)
    while start < len(text):
        chunks.append(text[start : start + size])
        start += step
    return chunks


def chunk_text(text: str, size: int = 1000, overlap: int = 150) -> list[str]:
    text = (text or "").strip()
    if not text:
        return []
    paragraphs = [p.strip() for p in text.split("\n\n") if p.strip()]
    chunks: list[str] = []
    buf = ""
    for para in paragraphs:
        if len(para) > size:
            if buf:
                chunks.append(buf)
                buf = ""
            chunks.extend(_window(para, size, overlap))
            continue
        if not buf:
            buf = para
        elif len(buf) + 2 + len(para) <= size:
            buf += "\n\n" + para
        else:
            chunks.append(buf)
            buf = para
    if buf:
        chunks.append(buf)
    return chunks
