"""Structure-aware Python code parser for Ragna."""

from __future__ import annotations

import ast
import logging
import uuid
from typing import Dict, List

logger = logging.getLogger(__name__)


def parse_repository(files: List[Dict[str, str]]) -> List[Dict[str, object]]:
    """Parse repository files into structured code chunks.

    Args:
        files: List of file records from repo_loader.

    Returns:
        List of chunk dictionaries with code structure metadata.
    """
    chunks: List[Dict[str, object]] = []
    for record in files:
        if record.get("language") != "python":
            continue
        file_path = record.get("file_path", "")
        content = record.get("content", "")
        chunks.extend(_parse_python_file(file_path, content))

    logger.info("Parsed %d chunks", len(chunks))
    return chunks


def _parse_python_file(file_path: str, content: str) -> List[Dict[str, object]]:
    """Parse a Python file into function/class/method chunks.

    Falls back to a single file chunk on parse failure.
    """
    try:
        tree = ast.parse(content)
    except SyntaxError as exc:
        logger.warning("Failed to parse %s: %s", file_path, exc)
        return [_file_chunk(file_path, content)]

    lines = content.splitlines()
    chunks: List[Dict[str, object]] = []

    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            chunks.append(
                _function_chunk(
                    file_path=file_path,
                    node=node,
                    lines=lines,
                    class_name="",
                    chunk_type="function",
                )
            )
        elif isinstance(node, ast.ClassDef):
            chunks.append(
                _class_chunk(
                    file_path=file_path,
                    node=node,
                    lines=lines,
                )
            )

            for class_node in node.body:
                if isinstance(class_node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    chunks.append(
                        _function_chunk(
                            file_path=file_path,
                            node=class_node,
                            lines=lines,
                            class_name=node.name,
                            chunk_type="method",
                        )
                    )

    if not chunks:
        chunks.append(_file_chunk(file_path, content))

    return chunks


def _class_chunk(
    *,
    file_path: str,
    node: ast.ClassDef,
    lines: List[str],
) -> Dict[str, object]:
    """Build a class chunk dictionary from an AST node."""
    start_line = getattr(node, "lineno", 1)
    end_line = getattr(node, "end_lineno", start_line)
    code = "\n".join(lines[start_line - 1 : end_line]) if lines else ""

    return {
        "chunk_id": str(uuid.uuid4()),
        "file_path": file_path,
        "type": "class",
        "name": getattr(node, "name", ""),
        "class_name": getattr(node, "name", ""),
        "function_name": "",
        "code": code,
        "start_line": start_line,
        "end_line": end_line,
    }


def _function_chunk(
    *,
    file_path: str,
    node: ast.AST,
    lines: List[str],
    class_name: str,
    chunk_type: str,
) -> Dict[str, object]:
    """Build a function or method chunk dictionary from an AST node."""
    start_line = getattr(node, "lineno", 1)
    decorator_lines = [getattr(dec, "lineno", start_line) for dec in getattr(node, "decorator_list", [])]
    if decorator_lines:
        start_line = min([start_line, *decorator_lines])
    end_line = getattr(node, "end_lineno", start_line)
    code = "\n".join(lines[start_line - 1 : end_line]) if lines else ""
    function_name = getattr(node, "name", "")

    return {
        "chunk_id": str(uuid.uuid4()),
        "file_path": file_path,
        "type": chunk_type,
        "name": function_name,
        "class_name": class_name,
        "function_name": function_name,
        "code": code,
        "start_line": start_line,
        "end_line": end_line,
    }


def _file_chunk(file_path: str, content: str) -> Dict[str, object]:
    """Fallback chunk for entire file."""
    total_lines = content.splitlines()
    end_line = len(total_lines) if total_lines else 1

    return {
        "chunk_id": str(uuid.uuid4()),
        "file_path": file_path,
        "type": "file",
        "name": "",
        "class_name": "",
        "function_name": "",
        "code": content,
        "start_line": 1,
        "end_line": end_line,
    }
