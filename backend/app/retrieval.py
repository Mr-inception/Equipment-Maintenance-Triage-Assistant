import logging
import math
import re
from collections import Counter
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

from .config import settings

logger = logging.getLogger("triage.retrieval")

_HEADER = re.compile(r"^##\s*\[([A-Za-z0-9.\-]+)\]\s*(.+)$")
_TOKEN = re.compile(r"[a-z0-9]+")
_STOPWORDS = {
    "a", "an", "and", "are", "as", "at", "be", "by", "for", "from", "in", "is",
    "it", "of", "on", "or", "the", "to", "with", "this", "that", "than", "any",
}


class RetrievalError(Exception):
    """Raised when the knowledge base cannot be loaded or searched."""


@dataclass(frozen=True)
class Chunk:
    id: str
    equipment_type: str
    title: str
    text: str
    source: str


@dataclass(frozen=True)
class Hit:
    chunk: Chunk
    score: float


def _tokens(text: str) -> list[str]:
    return [t for t in _TOKEN.findall(text.lower()) if t not in _STOPWORDS]


def default_kb_dir() -> Path:
    if settings.knowledge_base_dir:
        return Path(settings.knowledge_base_dir)
    return Path(__file__).resolve().parents[2] / "knowledge_base"


def parse_manual(path: Path) -> list[Chunk]:
    text = path.read_text(encoding="utf-8-sig")
    meta: dict[str, str] = {}
    chunks: list[Chunk] = []
    cur_id = cur_title = None
    cur_lines: list[str] = []

    def flush():
        if cur_id and "equipment_type" in meta:
            body = " ".join(l.strip() for l in cur_lines if l.strip())
            if body:
                chunks.append(
                    Chunk(cur_id, meta["equipment_type"], cur_title, body, path.name)
                )

    for line in text.splitlines():
        m = _HEADER.match(line.strip())
        if m:
            flush()
            cur_id, cur_title, cur_lines = m.group(1), m.group(2).strip(), []
        elif cur_id is None:
            if ":" in line:
                k, v = line.split(":", 1)
                meta[k.strip().lower()] = v.strip().lower() if k.strip().lower() == "equipment_type" else v.strip()
        else:
            cur_lines.append(line)
    flush()
    return chunks


class KnowledgeBase:
    K1 = 1.5
    B = 0.75

    def __init__(self, chunks: list[Chunk]):
        if not chunks:
            raise RetrievalError("Knowledge base contains no usable manual sections.")
        self.chunks = chunks
        self._doc_tokens = [_tokens(f"{c.title} {c.title} {c.text}") for c in chunks]
        self._tf = [Counter(t) for t in self._doc_tokens]
        self._avg_len = sum(len(t) for t in self._doc_tokens) / len(chunks)
        df: Counter = Counter()
        for tf in self._tf:
            df.update(tf.keys())
        n = len(chunks)
        self._idf = {t: math.log(1 + (n - d + 0.5) / (d + 0.5)) for t, d in df.items()}

    @classmethod
    def from_dir(cls, kb_dir: Path) -> "KnowledgeBase":
        if not kb_dir.is_dir():
            raise RetrievalError(f"Knowledge base folder not found: {kb_dir}")
        files = sorted(kb_dir.glob("*.md"))
        if not files:
            raise RetrievalError(f"No manual files (*.md) found in {kb_dir}")
        chunks: list[Chunk] = []
        for f in files:
            try:
                chunks.extend(parse_manual(f))
            except (OSError, UnicodeDecodeError) as exc:
                raise RetrievalError(f"Could not read manual {f.name}: {exc}") from exc
        logger.info("Loaded %d manual sections from %d files", len(chunks), len(files))
        return cls(chunks)

    def equipment_types(self) -> list[str]:
        return sorted({c.equipment_type for c in self.chunks})

    def search(self, query: str, equipment_type: Optional[str] = None, top_k: int = 5) -> list[Hit]:
        q_tokens = _tokens(query)
        if not q_tokens:
            return []
        wanted = equipment_type.strip().lower() if equipment_type else None
        hits: list[Hit] = []
        for i, chunk in enumerate(self.chunks):
            if wanted and chunk.equipment_type != wanted:
                continue
            tf, dl = self._tf[i], len(self._doc_tokens[i])
            score = 0.0
            for t in set(q_tokens):
                f = tf.get(t, 0)
                if f:
                    denom = f + self.K1 * (1 - self.B + self.B * dl / self._avg_len)
                    score += self._idf.get(t, 0.0) * f * (self.K1 + 1) / denom
            if score > 0:
                hits.append(Hit(chunk, round(score, 4)))
        hits.sort(key=lambda h: h.score, reverse=True)
        return hits[:top_k]


_cached: Optional[KnowledgeBase] = None


def get_knowledge_base() -> KnowledgeBase:
    global _cached
    if _cached is None:
        _cached = KnowledgeBase.from_dir(default_kb_dir())
    return _cached


def reset_cache() -> None:
    global _cached
    _cached = None
