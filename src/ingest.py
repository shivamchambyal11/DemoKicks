"""Ingest markdown docs -> heading-aware chunks -> embeddings -> Chroma.

Usage (run from the project root):
    python -m src.ingest --dry-run   # inspect chunks only; no model load, no DB writes
    python -m src.ingest             # (re)index all docs
    python -m src.ingest --reset     # drop the collection first (needed if embedding model changes)
"""
from __future__ import annotations

import argparse
import logging
import re
import sys
import time
from dataclasses import dataclass
from pathlib import Path

from src.config import settings, setup_logging

logger = logging.getLogger(__name__)

# Split on #, ##, ### headings. "####" and deeper stay inside the section body.
HEADING_RE = re.compile(r"^(#{1,3})\s+(.+?)\s*$")


@dataclass(frozen=True)
class Section:
    source: str       # file name, e.g. "returns.md"
    doc_title: str    # first "# " heading, falls back to file name
    section: str      # heading path, e.g. "Returns & Refunds > Sale items"
    body: str


@dataclass(frozen=True)
class Chunk:
    id: str
    text: str
    metadata: dict


# --------------------------------------------------------------------------- #
# 1) Markdown -> sections
# --------------------------------------------------------------------------- #
def parse_sections(source: str, text: str) -> list[Section]:
    """Split a markdown document into sections at #/##/### headings."""
    doc_title = source
    stack: list[tuple[int, str]] = []  # (level, title): current heading path
    buf: list[str] = []
    sections: list[Section] = []

    def flush() -> None:
        body = "\n".join(buf).strip()
        if body:  # headings with no body of their own (e.g. a bare "# Title") are skipped
            path = " > ".join(title for _, title in stack) or doc_title
            sections.append(Section(source, doc_title, path, body))
        buf.clear()

    for line in text.splitlines():
        match = HEADING_RE.match(line)
        if match:
            flush()
            level, title = len(match.group(1)), match.group(2)
            if level == 1 and doc_title == source:
                doc_title = title
            while stack and stack[-1][0] >= level:
                stack.pop()
            stack.append((level, title))
        else:
            buf.append(line)
    flush()
    return sections


# --------------------------------------------------------------------------- #
# 2) Section -> size-capped pieces with overlap
# --------------------------------------------------------------------------- #
def _hard_split(text: str, max_chars: int) -> list[str]:
    """Last resort for one huge line: cut on word boundaries."""
    parts: list[str] = []
    cur = ""
    for word in text.split():
        if cur and len(cur) + 1 + len(word) > max_chars:
            parts.append(cur)
            cur = word
        else:
            cur = f"{cur} {word}".strip()
    if cur:
        parts.append(cur)
    return parts


def _units(body: str, max_chars: int) -> list[str]:
    """Break a body into atomic units (paragraphs -> lines -> words), each <= max_chars."""
    units: list[str] = []
    for para in re.split(r"\n\s*\n", body):
        para = para.strip()
        if not para:
            continue
        if len(para) <= max_chars:
            units.append(para)
            continue
        for line in para.splitlines():
            line = line.strip()
            if not line:
                continue
            units.extend([line] if len(line) <= max_chars else _hard_split(line, max_chars))
    return units


def _tail(text: str, n: int) -> str:
    """Last ~n chars of `text`, trimmed to start on a word boundary."""
    if n <= 0:
        return ""
    if len(text) <= n:
        return text
    tail = text[-n:]
    match = re.search(r"\s", tail)
    return tail[match.end():].strip() if match else ""


def split_body(body: str, max_chars: int, overlap: int) -> list[str]:
    """Greedy-pack units into chunks <= max_chars, carrying `overlap` chars forward."""
    if len(body) <= max_chars:
        return [body]

    chunks: list[str] = []
    cur = ""
    for unit in _units(body, max_chars):
        candidate = f"{cur}\n\n{unit}" if cur else unit
        if len(candidate) <= max_chars:
            cur = candidate
            continue
        chunks.append(cur)
        carry = _tail(cur, overlap)
        # Only keep the overlap if the new unit still fits beside it.
        cur = f"{carry}\n\n{unit}" if carry and len(carry) + 2 + len(unit) <= max_chars else unit
    if cur:
        chunks.append(cur)
    return chunks


def build_chunks(source: str, text: str) -> list[Chunk]:
    stem = Path(source).stem
    chunks: list[Chunk] = []
    for sec in parse_sections(source, text):
        pieces = split_body(sec.body, settings.chunk_max_chars, settings.chunk_overlap_chars)
        for i, piece in enumerate(pieces):
            chunks.append(
                Chunk(
                    id=f"{stem}-{len(chunks):03d}",
                    # Heading path is part of the text: it is embedded AND shown to the LLM.
                    text=f"{sec.section}\n\n{piece}",
                    metadata={
                        "source": source,
                        "doc_title": sec.doc_title,
                        "section": sec.section,
                        "part": i + 1,
                        "parts": len(pieces),
                    },
                )
            )
    return chunks


# --------------------------------------------------------------------------- #
# 3) Chroma
# --------------------------------------------------------------------------- #
def get_collection(reset: bool = False):
    """Single place that builds the collection, so ingest and retrieval can never
    disagree about the embedding model. rag.py will import this."""
    import chromadb  # lazy: keeps --dry-run fast
    from chromadb.utils import embedding_functions

    settings.chroma_dir.mkdir(parents=True, exist_ok=True)
    client = chromadb.PersistentClient(path=str(settings.chroma_dir))

    if reset:
        try:
            client.delete_collection(settings.collection_name)
            logger.info("Dropped collection '%s'", settings.collection_name)
        except Exception:  # exception type differs across chromadb versions
            logger.debug("Nothing to drop; collection '%s' did not exist", settings.collection_name)

    embed_fn = embedding_functions.SentenceTransformerEmbeddingFunction(
        model_name=settings.embedding_model
    )
    collection = client.get_or_create_collection(
        name=settings.collection_name,
        embedding_function=embed_fn,
        metadata={"hnsw:space": "cosine", "embedding_model": settings.embedding_model},
    )

    stored_model = (collection.metadata or {}).get("embedding_model")
    if stored_model and stored_model != settings.embedding_model:
        raise RuntimeError(
            f"Collection was built with '{stored_model}' but config says "
            f"'{settings.embedding_model}'. Re-run with --reset."
        )
    return collection


# --------------------------------------------------------------------------- #
# 4) Pipeline
# --------------------------------------------------------------------------- #
def read_docs(docs_dir: Path) -> dict[str, str]:
    if not docs_dir.is_dir():
        raise FileNotFoundError(f"Docs directory not found: {docs_dir}")
    files = sorted(docs_dir.glob("*.md"))
    if not files:
        raise FileNotFoundError(f"No .md files found in {docs_dir}")
    return {f.name: f.read_text(encoding="utf-8") for f in files}


def ingest(reset: bool = False, dry_run: bool = False) -> int:
    start = time.perf_counter()
    docs = read_docs(settings.docs_dir)

    all_chunks: dict[str, list[Chunk]] = {}
    for name, text in docs.items():
        chunks = build_chunks(name, text)
        if not chunks:
            logger.warning("%s produced 0 chunks (empty or heading-only file?), skipping", name)
            continue
        all_chunks[name] = chunks
        lengths = [len(c.text) for c in chunks]
        logger.info(
            "%-12s %2d chunks | chars min/avg/max = %d/%d/%d",
            name, len(chunks), min(lengths), sum(lengths) // len(lengths), max(lengths),
        )

    total = sum(len(v) for v in all_chunks.values())
    if total == 0:
        raise RuntimeError("Nothing to index: no chunks were produced")

    if dry_run:
        for chunks in all_chunks.values():
            for c in chunks:
                m = c.metadata
                print(f"\n--- {c.id} | {m['section']} (part {m['part']}/{m['parts']}) | {len(c.text)} chars")
                print(c.text)
        logger.info("Dry run complete: %d chunks, nothing written", total)
        return total

    collection = get_collection(reset=reset)

    # Remove chunks of docs that no longer exist on disk.
    existing = collection.get(include=["metadatas"])["metadatas"] or []
    for stale in {m["source"] for m in existing} - set(all_chunks):
        collection.delete(where={"source": stale})
        logger.info("Removed stale chunks of deleted doc '%s'", stale)

    # Replace each file's chunks wholesale: idempotent re-runs, no duplicates.
    for name, chunks in all_chunks.items():
        collection.delete(where={"source": name})
        collection.add(
            ids=[c.id for c in chunks],
            documents=[c.text for c in chunks],
            metadatas=[c.metadata for c in chunks],
        )

    logger.info(
        "Indexed %d chunks from %d docs in %.1fs | collection now holds %d chunks",
        total, len(all_chunks), time.perf_counter() - start, collection.count(),
    )
    return total


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Build the DemoKicks knowledge-base index.")
    parser.add_argument("--reset", action="store_true", help="drop the collection before indexing")
    parser.add_argument("--dry-run", action="store_true", help="print chunks, do not embed or write")
    args = parser.parse_args(argv)

    setup_logging()
    try:
        ingest(reset=args.reset, dry_run=args.dry_run)
    except Exception:
        logger.exception("Ingestion failed")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())