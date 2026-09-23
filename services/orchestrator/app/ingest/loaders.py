"""Turn whatever the stakeholder had lying around into cited Evidence rows.

Provenance is not optional. Every chunk keeps a locator (page, timestamp,
paragraph) so a story written six stages later can point back at the sentence
that justified it.
"""
from __future__ import annotations

import io
import re
from dataclasses import dataclass
from pathlib import Path

import httpx
from bs4 import BeautifulSoup


@dataclass
class Chunk:
    content: str
    locator: str


def _split(text: str, locator_prefix: str, max_chars: int = 1400) -> list[Chunk]:
    paras = [p.strip() for p in re.split(r"\n\s*\n", text) if p.strip()]
    chunks: list[Chunk] = []
    buf, start = "", 1
    for i, p in enumerate(paras, start=1):
        if len(buf) + len(p) > max_chars and buf:
            chunks.append(Chunk(buf.strip(), f"{locator_prefix}¶{start}-{i-1}"))
            buf, start = "", i
        buf += p + "\n\n"
    if buf.strip():
        chunks.append(Chunk(buf.strip(), f"{locator_prefix}¶{start}-{len(paras)}"))
    return chunks


def load_text(text: str) -> list[Chunk]:
    return _split(text, "")


def load_pdf(data: bytes) -> list[Chunk]:
    from pypdf import PdfReader

    reader = PdfReader(io.BytesIO(data))
    out: list[Chunk] = []
    for n, page in enumerate(reader.pages, start=1):
        body = (page.extract_text() or "").strip()
        if body:
            out.extend(_split(body, f"p.{n} "))
    return out


def load_docx(data: bytes) -> list[Chunk]:
    """Paragraphs and tables, in document order.

    A business requirements document keeps its requirements, stakeholders and
    data volumes in tables; reading paragraphs alone dropped all of them.
    """
    import docx
    from docx.table import Table
    from docx.text.paragraph import Paragraph

    doc = docx.Document(io.BytesIO(data))
    parts: list[str] = []
    for child in doc.element.body.iterchildren():
        tag = child.tag.rsplit("}", 1)[-1]
        if tag == "p":
            text = Paragraph(child, doc).text.strip()
            if text:
                parts.append(text)
        elif tag == "tbl":
            rows = []
            for row in Table(child, doc).rows:
                cells = []
                for cell in row.cells:
                    value = " ".join(cell.text.split())
                    if not cells or cells[-1] != value:  # merged cells repeat
                        cells.append(value)
                rows.append(" | ".join(cells))
            if rows:
                parts.append("\n".join(rows))
    return _split("\n\n".join(parts), "")


async def load_url(url: str) -> list[Chunk]:
    async with httpx.AsyncClient(follow_redirects=True, timeout=30) as client:
        resp = await client.get(url, headers={"User-Agent": "Poiesis/1.0"})
        resp.raise_for_status()
    soup = BeautifulSoup(resp.text, "html.parser")
    for tag in soup(["script", "style", "nav", "footer", "aside"]):
        tag.decompose()
    return _split(soup.get_text("\n"), "")


def load_audio(path: Path) -> list[Chunk]:
    """Local Whisper. A recorded stakeholder call is a first-class requirement source."""
    from faster_whisper import WhisperModel

    model = WhisperModel("base", device="auto", compute_type="int8")
    segments, _ = model.transcribe(str(path), vad_filter=True)
    out: list[Chunk] = []
    buf, start = "", None
    for seg in segments:
        if start is None:
            start = seg.start
        buf += seg.text
        if len(buf) > 900:
            out.append(Chunk(buf.strip(), f"{_ts(start)}–{_ts(seg.end)}"))
            buf, start = "", None
    if buf.strip():
        out.append(Chunk(buf.strip(), f"{_ts(start or 0)}–end"))
    return out


def _ts(seconds: float) -> str:
    m, s = divmod(int(seconds), 60)
    return f"{m:02d}:{s:02d}"


async def describe_image(path: Path) -> list[Chunk]:
    """Whiteboard photos and architecture diagrams carry more intent than the email did."""
    import base64

    import litellm

    from ..config import settings

    s = settings()
    b64 = base64.b64encode(path.read_bytes()).decode()
    model = s.poiesis_model_vision if s.poiesis_llm_profile == "local" else "anthropic/claude-sonnet-5"
    kwargs = {"api_base": s.ollama_base_url} if s.poiesis_llm_profile == "local" else {"api_key": s.anthropic_api_key}
    resp = await litellm.acompletion(
        model=model,
        messages=[{
            "role": "user",
            "content": [
                {"type": "text", "text":
                 "Transcribe this diagram or photo exactly: every box, label, arrow direction, "
                 "annotation and handwritten note. Then state what system or process it depicts. "
                 "Do not invent anything that is not visible."},
                {"type": "image_url", "image_url": {"url": f"data:image/png;base64,{b64}"}},
            ],
        }],
        max_tokens=2000,
        **kwargs,
    )
    return [Chunk(resp.choices[0].message.content or "", "diagram")]
