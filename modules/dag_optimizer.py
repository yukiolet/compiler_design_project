"""Local DAG-style optimization for basic blocks."""

from __future__ import annotations

from dataclasses import dataclass

from .cfg import ALL_JUMPS, CFGResult, build_cfg
from .quad import EMPTY, Quad, format_quad, is_int_literal, is_temp


COMMUTATIVE_OPS = {"+", "*"}
ARITHMETIC_OPS = {"+", "-", "*", "/", "%"}
COMPARE_OPS = {"<", ">", "<=", ">=", "==", "!="}


@dataclass
class OptimizationResult:
    optimized_quads: list[Quad]
    dag_report: str
    compare_report: str


class DAGOptimizer:
    def __init__(self, cfg: CFGResult):
        self.cfg = cfg
        self.next_index = 0
        self.optimized: list[Quad] = []
        self.dag_lines: list[str] = []
        self.compare_lines: list[str] = []

    def optimize(self) -> OptimizationResult:
        for block in self.cfg.blocks:
            before = list(block.quads)
            after = self.optimize_block(block.name, before)
            self.compare_lines.append(f"{block.name}")
            self.compare_lines.append("Before:")
            self.compare_lines.extend(f"  {format_quad(quad)}" for quad in before)
            self.compare_lines.append("After:")
            self.compare_lines.extend(f"  {format_quad(quad)}" for quad in after)
            self.compare_lines.append("")
            self.optimized.extend(after)
        self.optimized = self.renumber_and_retarget(self.optimized)
        self.optimized = self.enhance_optimization(self.optimized)
        self.compare_lines.append("Enhanced optimization:")
        self.compare_lines.extend(f"  {format_quad(quad)}" for quad in self.optimized)
        self.compare_lines.append("")
        return OptimizationResult(
            optimized_quads=self.optimized,
            dag_report="\n".join(self.dag_lines) + "\n",
            compare_report="\n".join(self.compare_lines) + "\n",
        )

    def optimize_block(self, block_name: str, quads: list[Quad]) -> list[Quad]:
        expr_table: dict[tuple[str, str, str], str] = {}
        aliases: dict[str, str] = {}
        dag_nodes: dict[str, dict] = {}
        value_node: dict[str, str] = {}
        output: list[Quad] = []
        self.dag_lines.append(f"{block_name} DAG nodes:")

        for quad in quads:
            if quad.op in ARITHMETIC_OPS or quad.op in COMPARE_OPS:
                arg1 = aliases.get(quad.arg1, quad.arg1)
                arg2 = aliases.get(quad.arg2, quad.arg2)
                simplified = self.simplify(quad.op, arg1, arg2, quad.result)
                if simplified is not None:
                    new_quad = self.new_quad("=", simplified, EMPTY, quad.result, quad.index)
                    output.append(new_quad)
                    self.set_alias_if_safe(aliases, quad.result, simplified)
                    self.attach_label(dag_nodes, value_node, simplified, quad.result)
                    self.dag_lines.append(f"  simplify {quad.result} = {quad.op}({arg1}, {arg2}) -> {simplified}")
                    continue

                key = self.expr_key(quad.op, arg1, arg2)
                if key in expr_table:
                    source = expr_table[key]
                    output.append(self.new_quad("=", source, EMPTY, quad.result, quad.index))
                    self.set_alias_if_safe(aliases, quad.result, source)
                    self.attach_label(dag_nodes, value_node, source, quad.result)
                    self.dag_lines.append(f"  reuse {quad.result} -> {source} for {quad.op}({arg1}, {arg2})")
                else:
                    expr_table[key] = quad.result
                    output.append(self.new_quad(quad.op, arg1, arg2, quad.result, quad.index))
                    self.create_expr_node(dag_nodes, value_node, quad.op, arg1, arg2, quad.result)
                    self.dag_lines.append(f"  create {quad.result} = {quad.op}({arg1}, {arg2})")
            elif quad.op == "=":
                source = aliases.get(quad.arg1, quad.arg1)
                output.append(self.new_quad("=", source, EMPTY, quad.result, quad.index))
                self.invalidate_target(expr_table, quad.result)
                self.invalidate_aliases(aliases, quad.result)
                self.set_alias_if_safe(aliases, quad.result, source)
                self.attach_label(dag_nodes, value_node, source, quad.result)
            else:
                output.append(self.new_quad(quad.op, aliases.get(quad.arg1, quad.arg1), aliases.get(quad.arg2, quad.arg2), quad.result, quad.index))
                if quad.op in ALL_JUMPS or quad.op in {"ret", "return"}:
                    expr_table.clear()
        output = self.remove_overwritten_assignments(output)
        output = self.propagate_copies_and_remove_dead_temps(output)
        self.render_dag_table(dag_nodes)
        self.dag_lines.append("")
        return output

    def simplify(self, op: str, arg1: str, arg2: str, result: str) -> str | None:
        if op == "+" and arg2 == "0":
            return arg1
        if op == "+" and arg1 == "0":
            return arg2
        if op == "-" and arg2 == "0":
            return arg1
        if op == "*" and arg2 == "1":
            return arg1
        if op == "*" and arg1 == "1":
            return arg2
        if op == "*" and (arg1 == "0" or arg2 == "0"):
            return "0"
        if op == "/" and arg2 == "1":
            return arg1
        if op == "%" and arg2 == "1":
            return "0"
        if is_int_literal(arg1) and is_int_literal(arg2):
            left = int(arg1)
            right = int(arg2)
            if op == "+":
                return str(left + right)
            if op == "-":
                return str(left - right)
            if op == "*":
                return str(left * right)
            if op == "/" and right != 0:
                return str(int(left / right))
            if op == "%" and right != 0:
                return str(left % right)
            if op == "<":
                return str(int(left < right))
            if op == ">":
                return str(int(left > right))
            if op == "<=":
                return str(int(left <= right))
            if op == ">=":
                return str(int(left >= right))
            if op == "==":
                return str(int(left == right))
            if op == "!=":
                return str(int(left != right))
        return None

    def expr_key(self, op: str, arg1: str, arg2: str) -> tuple[str, str, str]:
        if op in COMMUTATIVE_OPS and arg2 < arg1:
            arg1, arg2 = arg2, arg1
        return op, arg1, arg2

    def invalidate_target(self, expr_table: dict[tuple[str, str, str], str], target: str) -> None:
        stale = [key for key, result in expr_table.items() if target in key or result == target]
        for key in stale:
            del expr_table[key]

    def invalidate_aliases(self, aliases: dict[str, str], target: str) -> None:
        stale = [name for name, source in aliases.items() if name == target or source == target]
        for name in stale:
            del aliases[name]

    def set_alias_if_safe(self, aliases: dict[str, str], target: str, source: str) -> None:
        aliases.pop(target, None)
        if is_temp(target) and (is_temp(source) or is_int_literal(source)):
            aliases[target] = source

    def ensure_leaf_node(self, dag_nodes: dict[str, dict], value_node: dict[str, str], value: str) -> str:
        if value in value_node:
            return value_node[value]
        node_id = f"N{len(dag_nodes) + 1}"
        dag_nodes[node_id] = {"kind": "leaf", "op": value, "children": [], "labels": [value]}
        value_node[value] = node_id
        return node_id

    def remove_label(self, dag_nodes: dict[str, dict], label: str) -> None:
        for node in dag_nodes.values():
            if label in node["labels"]:
                node["labels"].remove(label)

    def attach_label(self, dag_nodes: dict[str, dict], value_node: dict[str, str], source: str, label: str) -> None:
        node_id = self.ensure_leaf_node(dag_nodes, value_node, source)
        self.remove_label(dag_nodes, label)
        if label not in dag_nodes[node_id]["labels"]:
            dag_nodes[node_id]["labels"].append(label)
        value_node[label] = node_id

    def create_expr_node(
        self,
        dag_nodes: dict[str, dict],
        value_node: dict[str, str],
        op: str,
        arg1: str,
        arg2: str,
        label: str,
    ) -> str:
        left = self.ensure_leaf_node(dag_nodes, value_node, arg1)
        right = self.ensure_leaf_node(dag_nodes, value_node, arg2)
        node_id = f"N{len(dag_nodes) + 1}"
        dag_nodes[node_id] = {"kind": "expr", "op": op, "children": [left, right], "labels": []}
        self.remove_label(dag_nodes, label)
        dag_nodes[node_id]["labels"].append(label)
        value_node[label] = node_id
        return node_id

    def render_dag_table(self, dag_nodes: dict[str, dict]) -> None:
        if not dag_nodes:
            self.dag_lines.append("  no arithmetic DAG nodes")
            return
        self.dag_lines.append("  Node table:")
        for node_id, node in dag_nodes.items():
            labels = ",".join(node["labels"]) if node["labels"] else "-"
            children = ",".join(node["children"]) if node["children"] else "-"
            self.dag_lines.append(f"    {node_id}: op={node['op']}, labels={labels}, children={children}")

    def remove_overwritten_assignments(self, quads: list[Quad]) -> list[Quad]:
        keep = [True] * len(quads)
        for i, quad in enumerate(quads):
            target = self.defined_name(quad)
            if target is None:
                continue
            used_before_redefine = False
            overwritten = False
            for later in quads[i + 1:]:
                if target in self.used_names(later):
                    used_before_redefine = True
                    break
                if self.defined_name(later) == target:
                    overwritten = True
                    break
            if overwritten and not used_before_redefine:
                keep[i] = False
                self.dag_lines.append(f"  delete dead assignment to {target}: {format_quad(quad)}")

        compacted = [quad for quad, should_keep in zip(quads, keep) if should_keep]
        return compacted

    def propagate_copies_and_remove_dead_temps(self, quads: list[Quad]) -> list[Quad]:
        propagated = self.propagate_temp_copies(quads)
        folded = self.fold_single_use_temp_results(propagated)
        compacted = self.remove_unused_temp_definitions(folded)
        return compacted

    def propagate_temp_copies(self, quads: list[Quad]) -> list[Quad]:
        aliases: dict[str, str] = {}
        output: list[Quad] = []

        for quad in quads:
            arg1 = self.resolve_alias(aliases, quad.arg1)
            arg2 = self.resolve_alias(aliases, quad.arg2)

            if quad.op == "=":
                self.invalidate_aliases(aliases, quad.result)
                if is_temp(quad.result):
                    if not is_temp(arg1) and not is_int_literal(arg1):
                        output.append(self.new_quad("=", arg1, EMPTY, quad.result, quad.index))
                        continue
                    aliases[quad.result] = arg1
                    self.dag_lines.append(f"  propagate copy {quad.result} -> {arg1}")
                    continue
                if arg1 == quad.result:
                    self.dag_lines.append(f"  delete self assignment: {format_quad(quad)}")
                    continue
                output.append(self.new_quad("=", arg1, EMPTY, quad.result, quad.index))
                continue

            if quad.op in ARITHMETIC_OPS:
                self.invalidate_aliases(aliases, quad.result)
                output.append(self.new_quad(quad.op, arg1, arg2, quad.result, quad.index))
                continue

            output.append(self.new_quad(quad.op, arg1, arg2, quad.result, quad.index))

        return output

    def fold_single_use_temp_results(self, quads: list[Quad]) -> list[Quad]:
        use_counts = self.temp_use_counts(quads)
        output: list[Quad] = []
        i = 0
        while i < len(quads):
            quad = quads[i]
            if (
                quad.op in ARITHMETIC_OPS
                and is_temp(quad.result)
                and use_counts.get(quad.result, 0) == 1
                and i + 1 < len(quads)
                and quads[i + 1].op == "="
                and quads[i + 1].arg1 == quad.result
                and not is_temp(quads[i + 1].result)
            ):
                output.append(self.new_quad(quad.op, quad.arg1, quad.arg2, quads[i + 1].result, quad.index))
                self.dag_lines.append(f"  fold single-use temp {quad.result} into {quads[i + 1].result}")
                i += 2
                continue
            output.append(quad)
            i += 1
        return output

    def remove_unused_temp_definitions(self, quads: list[Quad]) -> list[Quad]:
        use_counts = self.temp_use_counts(quads)
        output: list[Quad] = []
        for quad in quads:
            target = self.defined_name(quad)
            if target is not None and is_temp(target) and use_counts.get(target, 0) == 0:
                self.dag_lines.append(f"  delete unused temp definition: {format_quad(quad)}")
                continue
            output.append(quad)
        return output

    def temp_use_counts(self, quads: list[Quad]) -> dict[str, int]:
        counts: dict[str, int] = {}
        for quad in quads:
            for value in self.used_names(quad):
                if is_temp(value):
                    counts[value] = counts.get(value, 0) + 1
        return counts

    def resolve_alias(self, aliases: dict[str, str], value: str) -> str:
        seen = set()
        while value in aliases and value not in seen:
            seen.add(value)
            value = aliases[value]
        return value

    def defined_name(self, quad: Quad) -> str | None:
        if quad.op in ARITHMETIC_OPS or quad.op in COMPARE_OPS or quad.op == "=":
            return None if quad.result == EMPTY else quad.result
        return None

    def used_names(self, quad: Quad) -> set[str]:
        values: set[str] = set()
        if quad.op in ARITHMETIC_OPS or quad.op in COMPARE_OPS:
            values.update({quad.arg1, quad.arg2})
        elif quad.op == "=":
            values.add(quad.arg1)
        elif quad.op in {"ret", "return"}:
            values.add(quad.arg1 if quad.arg1 != EMPTY else quad.result)
        elif quad.op in ALL_JUMPS:
            values.update({quad.arg1, quad.arg2})
        return {value for value in values if value != EMPTY and not is_int_literal(value)}

    def new_quad(self, op: str, arg1: str, arg2: str, result: str, index: int | None = None) -> Quad:
        quad = Quad(self.next_index if index is None else index, op, arg1, arg2, result)
        self.next_index += 1
        return quad

    def renumber_and_retarget(self, quads: list[Quad]) -> list[Quad]:
        old_indices = [quad.index for quad in quads]
        exact_map = {old_index: new_index for new_index, old_index in enumerate(old_indices)}

        def map_target(target: str) -> str:
            if not is_int_literal(target):
                return target
            old_target = int(target)
            if old_target in exact_map:
                return str(exact_map[old_target])
            for old_index in old_indices:
                if old_index >= old_target:
                    return str(exact_map[old_index])
            return str(len(quads))

        renumbered: list[Quad] = []
        for new_index, quad in enumerate(quads):
            result = map_target(quad.result) if quad.op in ALL_JUMPS else quad.result
            renumbered.append(Quad(new_index, quad.op, quad.arg1, quad.arg2, result))
        return renumbered

    def enhance_optimization(self, quads: list[Quad]) -> list[Quad]:
        cfg = build_cfg(quads)
        enhanced: list[Quad] = []
        for block in cfg.blocks:
            propagated = self.propagate_constants_and_copies(block.quads)
            compacted = self.remove_local_dead_code(propagated)
            enhanced.extend(compacted)
        return self.renumber_and_retarget(enhanced)

    def propagate_constants_and_copies(self, quads: list[Quad]) -> list[Quad]:
        constants: dict[str, str] = {}
        aliases: dict[str, str] = {}
        output: list[Quad] = []

        for quad in quads:
            arg1 = self.resolve_value(constants, aliases, quad.arg1)
            arg2 = self.resolve_value(constants, aliases, quad.arg2)

            if quad.op == "=":
                output.append(Quad(quad.index, "=", arg1, EMPTY, quad.result))
                self.record_value(constants, aliases, quad.result, arg1)
                continue

            if quad.op in ARITHMETIC_OPS or quad.op in COMPARE_OPS:
                simplified = self.simplify(quad.op, arg1, arg2, quad.result)
                if simplified is not None:
                    value = self.resolve_value(constants, aliases, simplified)
                    output.append(Quad(quad.index, "=", value, EMPTY, quad.result))
                    self.record_value(constants, aliases, quad.result, value)
                else:
                    output.append(Quad(quad.index, quad.op, arg1, arg2, quad.result))
                    self.forget_value(constants, aliases, quad.result)
                continue

            if quad.op in ALL_JUMPS:
                output.append(Quad(quad.index, quad.op, arg1, arg2, quad.result))
                continue

            if quad.op == "para":
                output.append(Quad(quad.index, quad.op, arg1, quad.arg2, quad.result))
                continue

            if quad.op == "call":
                output.append(quad)
                self.forget_value(constants, aliases, quad.result)
                continue

            if quad.op in {"ret", "return"}:
                result = self.resolve_value(constants, aliases, quad.result)
                output.append(Quad(quad.index, quad.op, arg1, arg2, result))
                continue

            output.append(quad)

        return output

    def remove_local_dead_code(self, quads: list[Quad]) -> list[Quad]:
        live: set[str] = set()
        keep: list[Quad] = []

        for quad in reversed(quads):
            target = self.defined_name(quad)
            if self.has_side_effect(quad) or target is None:
                keep.append(quad)
                live.update(self.enhanced_used_names(quad))
                continue

            if target in live:
                live.discard(target)
                live.update(self.enhanced_used_names(quad))
                keep.append(quad)
            else:
                self.dag_lines.append(f"  delete dead definition: {format_quad(quad)}")

        keep.reverse()
        return keep

    def resolve_value(self, constants: dict[str, str], aliases: dict[str, str], value: str) -> str:
        value = self.resolve_alias(aliases, value)
        return constants.get(value, value)

    def record_value(
        self,
        constants: dict[str, str],
        aliases: dict[str, str],
        target: str,
        value: str,
    ) -> None:
        self.forget_value(constants, aliases, target)
        if target == EMPTY:
            return
        if is_int_literal(value):
            constants[target] = value
        elif is_temp(target) and not is_temp(value):
            return
        elif value != EMPTY:
            aliases[target] = value

    def forget_value(self, constants: dict[str, str], aliases: dict[str, str], target: str) -> None:
        if target == EMPTY:
            return
        constants.pop(target, None)
        stale_aliases = [name for name, source in aliases.items() if name == target or source == target]
        for name in stale_aliases:
            aliases.pop(name, None)

    def has_side_effect(self, quad: Quad) -> bool:
        if quad.op in ARITHMETIC_OPS or quad.op in COMPARE_OPS or quad.op == "=":
            return False
        return True

    def enhanced_used_names(self, quad: Quad) -> set[str]:
        values: set[str] = set()
        if quad.op in ARITHMETIC_OPS or quad.op in COMPARE_OPS:
            values.update({quad.arg1, quad.arg2})
        elif quad.op == "=":
            values.add(quad.arg1)
        elif quad.op in {"ret", "return"}:
            values.add(quad.arg1 if quad.arg1 != EMPTY else quad.result)
        elif quad.op in ALL_JUMPS:
            values.update({quad.arg1, quad.arg2})
        elif quad.op == "para":
            values.add(quad.arg1)
        return {value for value in values if value != EMPTY and not is_int_literal(value)}
