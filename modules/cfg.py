"""Basic block and control-flow graph analysis for quadruples."""

from __future__ import annotations

from dataclasses import dataclass, field

from .quad import EMPTY, Quad, format_quad, is_int_literal, is_symbol


COND_JUMPS = {"J<", "J>", "J<=", "J>=", "J==", "J!=", "jnz", "jz"}
ALL_JUMPS = COND_JUMPS | {"J", "j"}
KNOWN_OPS = {
    "=",
    "+",
    "-",
    "*",
    "/",
    "%",
    "!",
    "<",
    ">",
    "<=",
    ">=",
    "==",
    "!=",
    "J",
    "j",
    "jnz",
    "jz",
    "ret",
    "return",
    "para",
    "call",
    "main",
    "sys",
    "nop",
} | COND_JUMPS


def is_function_entry_quad(quad: Quad) -> bool:
    """Return True for function-entry markers such as (main, _, _, _)."""
    if quad.op == "main":
        return True
    if quad.op in KNOWN_OPS or not is_symbol(quad.op):
        return False
    fields = (quad.arg1, quad.arg2, quad.result)
    if all(field == EMPTY for field in fields):
        return True
    return all(field == EMPTY or is_symbol(field) for field in fields)


@dataclass
class BasicBlock:
    name: str
    quads: list[Quad]
    successors: set[str] = field(default_factory=set)
    predecessors: set[str] = field(default_factory=set)

    @property
    def start_index(self) -> int:
        return self.quads[0].index

    @property
    def end_index(self) -> int:
        return self.quads[-1].index


@dataclass
class CFGResult:
    blocks: list[BasicBlock]
    index_to_block: dict[int, str]


def build_cfg(quads: list[Quad]) -> CFGResult:
    if not quads:
        return CFGResult([], {})

    existing_indices = {quad.index for quad in quads}
    leaders = {quads[0].index}
    for pos, quad in enumerate(quads):
        if is_function_entry_quad(quad):
            leaders.add(quad.index)
        if quad.op in ALL_JUMPS and is_int_literal(quad.result):
            target = int(quad.result)
            if target in existing_indices:
                leaders.add(target)
            if pos + 1 < len(quads):
                leaders.add(quads[pos + 1].index)

    sorted_leaders = sorted(leaders)
    blocks: list[BasicBlock] = []
    for i, leader in enumerate(sorted_leaders):
        end = sorted_leaders[i + 1] if i + 1 < len(sorted_leaders) else None
        block_quads = [quad for quad in quads if quad.index >= leader and (end is None or quad.index < end)]
        if block_quads:
            blocks.append(BasicBlock(f"B{len(blocks)}", block_quads))

    index_to_block = {}
    for block in blocks:
        for quad in block.quads:
            index_to_block[quad.index] = block.name

    block_by_name = {block.name: block for block in blocks}
    for pos, block in enumerate(blocks):
        last = block.quads[-1]
        if last.op in {"J", "j"}:
            add_edge(block, block_by_name, index_to_block, int(last.result))
        elif last.op in COND_JUMPS:
            add_edge(block, block_by_name, index_to_block, int(last.result))
            if pos + 1 < len(blocks):
                block.successors.add(blocks[pos + 1].name)
        elif (
            last.op not in {"ret", "return", "sys"}
            and pos + 1 < len(blocks)
            and not is_function_entry_quad(blocks[pos + 1].quads[0])
        ):
            block.successors.add(blocks[pos + 1].name)

    for block in blocks:
        for succ in block.successors:
            block_by_name[succ].predecessors.add(block.name)

    return CFGResult(blocks, index_to_block)


def add_edge(
    block: BasicBlock,
    block_by_name: dict[str, BasicBlock],
    index_to_block: dict[int, str],
    target_index: int,
) -> None:
    target_block = index_to_block.get(target_index)
    if target_block in block_by_name:
        block.successors.add(target_block)


def render_basic_blocks(cfg: CFGResult) -> str:
    lines: list[str] = []
    for block in cfg.blocks:
        lines.append(f"{block.name} [{block.start_index}..{block.end_index}]")
        lines.append(f"  predecessors: {', '.join(sorted(block.predecessors)) or '-'}")
        lines.append(f"  successors: {', '.join(sorted(block.successors)) or '-'}")
        for quad in block.quads:
            lines.append(f"  {format_quad(quad)}")
        lines.append("")
    return "\n".join(lines)


def render_cfg_dot(cfg: CFGResult) -> str:
    lines = ["digraph CFG {", "  rankdir=TB;", '  node [shape=box, fontname="Consolas"];']
    for block in cfg.blocks:
        label_parts = [block.name]
        label_parts.extend(format_quad(quad).replace('"', '\\"') for quad in block.quads)
        label = "\\l".join(label_parts) + "\\l"
        lines.append(f'  {block.name} [label="{label}"];')
    for block in cfg.blocks:
        for succ in sorted(block.successors):
            lines.append(f"  {block.name} -> {succ};")
    lines.append("}")
    return "\n".join(lines) + "\n"
