"""
Deterministic Source Content Ingestion & Evidence Chunking Module (S19).

Reads exact source code from checked-out repository snapshots,
excludes binary/large files, uses parsed AST entity boundaries when available
(with fallback to fixed line-window chunking), and produces deterministic,
traceable SourceChunk data objects.
"""
from __future__ import annotations
import hashlib
import os
from dataclasses import dataclass, asdict
from typing import List, Optional, Dict, Any, Tuple

from util import is_safe_relative_path

SOURCE_CHUNK_SCHEMA_VERSION = "1"
SOURCE_CHUNKER_VERSION = "1"

# Resource protection safeguards
MAX_SOURCE_FILE_SIZE_BYTES = 2 * 1024 * 1024  # 2 MB limit per file
MAX_CHUNK_LINE_COUNT = 100                    # Maximum lines in a single chunk
DEFAULT_WINDOW_LINE_COUNT = 50                 # Fallback line window
BINARY_CHECK_BYTES = 8000                      # Bytes sampled for binary check


def is_binary_bytes(data: bytes) -> bool:
    """Check if raw file bytes represent binary content."""
    sample = data[:BINARY_CHECK_BYTES]
    if b"\x00" in sample:
        return True
    return False


def infer_language_from_path(file_path: str) -> str:
    """Infer source code language from file extension."""
    lower = file_path.lower()
    if lower.endswith((".py", ".pyw")):
        return "python"
    elif lower.endswith(".java"):
        return "java"
    elif lower.endswith((".js", ".jsx")):
        return "javascript"
    elif lower.endswith((".ts", ".tsx")):
        return "typescript"
    elif lower.endswith((".c", ".h", ".cpp", ".hpp", ".cc")):
        return "cpp"
    elif lower.endswith(".go"):
        return "go"
    elif lower.endswith(".rs"):
        return "rust"
    elif lower.endswith((".json", ".toml", ".yaml", ".yml", ".md", ".xml", ".ini")):
        return "config"
    return "unknown"


def compute_chunk_hash(
    commit_sha: Optional[str],
    file_path: str,
    start_line: int,
    end_line: int,
    chunker_version: str,
    chunk_text: str,
) -> Tuple[str, str]:
    """
    Computes a deterministic hash and ID for a source chunk.
    Returns (chunk_hash, chunk_id).
    """
    raw_key = f"{commit_sha or ''}\n{file_path}\n{start_line}\n{end_line}\n{chunker_version}\n{chunk_text}"
    c_hash = hashlib.sha256(raw_key.encode("utf-8")).hexdigest()
    c_id = f"sc_{c_hash[:32]}"
    return c_hash, c_id


@dataclass
class SourceChunkData:
    chunk_id: str
    file_path: str
    start_line: int
    end_line: int
    chunk_text: str
    language: str
    entity_name: Optional[str] = None
    entity_type: Optional[str] = None
    provenance: str = "source_file:repository_checkout"
    chunk_hash: str = ""
    commit_sha: Optional[str] = None
    chunker_version: str = SOURCE_CHUNKER_VERSION
    schema_version: str = SOURCE_CHUNK_SCHEMA_VERSION

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


def chunk_single_file(
    repo_root: str,
    rel_path: str,
    commit_sha: Optional[str] = None,
    parse_result: Optional[Any] = None,
) -> List[SourceChunkData]:
    """
    Ingests and chunk a single source file cleanly.
    Returns a list of SourceChunkData objects.
    """
    if not is_safe_relative_path(rel_path, repo_root):
        return []

    abs_path = os.path.normpath(os.path.join(repo_root, rel_path))
    if not os.path.isfile(abs_path):
        return []

    # Check file size limit
    try:
        file_size = os.path.getsize(abs_path)
        if file_size > MAX_SOURCE_FILE_SIZE_BYTES or file_size == 0:
            return []
    except OSError:
        return []

    # Read bytes and check for binary content
    try:
        with open(abs_path, "rb") as fh:
            raw_bytes = fh.read()
    except OSError:
        return []

    if is_binary_bytes(raw_bytes):
        return []

    # Decode text safely
    try:
        text = raw_bytes.decode("utf-8")
    except UnicodeDecodeError:
        text = raw_bytes.decode("latin-1", errors="replace")

    lines = text.splitlines()
    total_lines = len(lines)
    if total_lines == 0:
        return []

    language = infer_language_from_path(rel_path)
    chunks: List[SourceChunkData] = []
    covered_lines = set()

    # 1. Entity-aware chunking from AST parse results
    entities: List[Dict[str, Any]] = []
    if parse_result:
        # Collect functions
        for f in getattr(parse_result, "functions", []):
            if getattr(f, "start_line", None) and getattr(f, "end_line", None):
                entities.append({
                    "name": f.name,
                    "type": "function",
                    "start": f.start_line,
                    "end": f.end_line,
                    "provenance": getattr(f, "provenance", "AST-walk"),
                })
        # Collect classes
        for c in getattr(parse_result, "classes", []):
            if getattr(c, "start_line", None) and getattr(c, "end_line", None):
                entities.append({
                    "name": c.name,
                    "type": "class",
                    "start": c.start_line,
                    "end": c.end_line,
                    "provenance": getattr(c, "provenance", "AST-walk"),
                })

    # Sort entities by line length ascending (smaller inner functions first) then start line
    entities.sort(key=lambda e: (e["end"] - e["start"], e["start"]))

    for ent in entities:
        s_line = max(1, ent["start"])
        e_line = min(total_lines, ent["end"])
        if s_line > e_line:
            continue

        # Subdivide large entities if they exceed MAX_CHUNK_LINE_COUNT
        ent_line_count = e_line - s_line + 1
        if ent_line_count <= MAX_CHUNK_LINE_COUNT:
            sub_windows = [(s_line, e_line)]
        else:
            sub_windows = []
            curr = s_line
            while curr <= e_line:
                w_end = min(curr + DEFAULT_WINDOW_LINE_COUNT - 1, e_line)
                sub_windows.append((curr, w_end))
                curr = w_end + 1

        for w_start, w_end in sub_windows:
            chunk_lines = lines[w_start - 1 : w_end]
            chunk_text = "\n".join(chunk_lines)
            prov = f"source_file:entity_chunk:{ent['provenance']}"
            c_hash, c_id = compute_chunk_hash(
                commit_sha, rel_path, w_start, w_end, SOURCE_CHUNKER_VERSION, chunk_text
            )

            chunks.append(
                SourceChunkData(
                    chunk_id=c_id,
                    file_path=rel_path,
                    start_line=w_start,
                    end_line=w_end,
                    chunk_text=chunk_text,
                    language=language,
                    entity_name=ent["name"],
                    entity_type=ent["type"],
                    provenance=prov,
                    chunk_hash=c_hash,
                    commit_sha=commit_sha,
                )
            )
            for line_idx in range(w_start, w_end + 1):
                covered_lines.add(line_idx)

    # 2. Window fallback for uncovered code lines
    uncovered_ranges: List[Tuple[int, int]] = []
    curr_start = None
    for line_num in range(1, total_lines + 1):
        if line_num not in covered_lines:
            if curr_start is None:
                curr_start = line_num
        else:
            if curr_start is not None:
                uncovered_ranges.append((curr_start, line_num - 1))
                curr_start = None
    if curr_start is not None:
        uncovered_ranges.append((curr_start, total_lines))

    for u_start, u_end in uncovered_ranges:
        curr = u_start
        while curr <= u_end:
            w_end = min(curr + DEFAULT_WINDOW_LINE_COUNT - 1, u_end)
            chunk_lines = lines[curr - 1 : w_end]
            chunk_text = "\n".join(chunk_lines)
            prov = "source_file:window_chunk"
            c_hash, c_id = compute_chunk_hash(
                commit_sha, rel_path, curr, w_end, SOURCE_CHUNKER_VERSION, chunk_text
            )

            chunks.append(
                SourceChunkData(
                    chunk_id=c_id,
                    file_path=rel_path,
                    start_line=curr,
                    end_line=w_end,
                    chunk_text=chunk_text,
                    language=language,
                    entity_name=None,
                    entity_type="window",
                    provenance=prov,
                    chunk_hash=c_hash,
                    commit_sha=commit_sha,
                )
            )
            curr = w_end + 1

    # Sort final chunks strictly by start line
    chunks.sort(key=lambda c: (c.start_line, c.end_line))
    return chunks


def generate_repository_chunks(
    repo_root: str,
    parse_results: List[Any],
    commit_sha: Optional[str] = None,
) -> List[Dict[str, Any]]:
    """
    Generates deterministic source chunks across an entire repository snapshot.
    Returns a list of serializable chunk dictionaries.
    """
    all_chunks: List[SourceChunkData] = []
    parse_map = {r.file: r for r in parse_results if hasattr(r, "file")}

    # Process all parsed files first
    for rel_path, parse_res in sorted(parse_map.items()):
        if getattr(parse_res, "parse_error", None):
            continue
        chunks = chunk_single_file(repo_root, rel_path, commit_sha=commit_sha, parse_result=parse_res)
        all_chunks.extend(chunks)

    # Sort chunks deterministically by file_path then start_line
    all_chunks.sort(key=lambda c: (c.file_path, c.start_line, c.end_line))
    return [c.to_dict() for c in all_chunks]
