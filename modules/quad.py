"""Quadruple parsing and formatting utilities."""

from __future__ import annotations

from dataclasses import dataclass
import ast
import re
from pathlib import Path


EMPTY = "_"


@dataclass(frozen=True)
class Quad:
    index: int
    op: str
    arg1: str
    arg2: str
    result: str

    def fields(self) -> tuple[str, str, str, str]:
        return self.op, self.arg1, self.arg2, self.result


def clean_field(value: object) -> str:
    if value is None:
        return EMPTY
    text = str(value).strip()
    if len(text) >= 2 and text[0] == text[-1] and text[0] in {"'", '"'}:
        text = text[1:-1]
    return text or EMPTY


def is_empty(value: str) -> bool:
    return clean_field(value) == EMPTY


def is_int_literal(value: str) -> bool:
    return re.fullmatch(r"[+-]?\d+", clean_field(value)) is not None


def is_temp(value: str) -> bool:
    return re.fullmatch(r"[tT]\d+", clean_field(value)) is not None


def is_symbol(value: str) -> bool:
    text = clean_field(value)
    return text != EMPTY and not is_int_literal(text)


def parse_quad_line(line: str, fallback_index: int) -> Quad | None:
    text = line.strip()
    if not text or text.startswith("#") or text.startswith("//"):
        return None

    match = re.match(r"^(?:(\d+)\s*:\s*)?[\(\[](.*)[\)\]]\s*$", text)
    if not match:
        raise ValueError(f"Invalid quadruple line: {line}")

    index = int(match.group(1)) if match.group(1) is not None else fallback_index
    body = match.group(2)

    try:
        raw_parts = ast.literal_eval("(" + body + ")")
        parts = [clean_field(part) for part in raw_parts]
    except Exception:
        parts = [clean_field(part) for part in body.split(",")]

    if len(parts) != 4:
        raise ValueError(f"Quadruple must have 4 fields: {line}")
    return Quad(index, parts[0], parts[1], parts[2], parts[3])


def read_quads(path: str | Path) -> list[Quad]:
    quads: list[Quad] = []
    for line in Path(path).read_text(encoding="utf-8").splitlines():
        quad = parse_quad_line(line, len(quads))
        if quad is not None:
            quads.append(quad)
    return quads


def format_quad(quad: Quad, index: int | None = None) -> str:
    q_index = quad.index if index is None else index
    return f"{q_index}: ({quad.op}, {quad.arg1}, {quad.arg2}, {quad.result})"


def write_quads(path: str | Path, quads: list[Quad]) -> None:
    Path(path).write_text(
        "\n".join(format_quad(quad, i) for i, quad in enumerate(quads)) + "\n",
        encoding="utf-8",
    )
