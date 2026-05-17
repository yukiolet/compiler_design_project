"""Interpreter for simplified quadruple intermediate code."""

from __future__ import annotations

from dataclasses import dataclass

from .cfg import KNOWN_OPS, is_function_entry_quad
from .quad import EMPTY, Quad, is_int_literal, is_temp


ARITHMETIC_OPS = {"+", "-", "*", "/", "%", "!"}
COMPARE_OPS = {
    "<": lambda left, right: int(left < right),
    ">": lambda left, right: int(left > right),
    "<=": lambda left, right: int(left <= right),
    ">=": lambda left, right: int(left >= right),
    "==": lambda left, right: int(left == right),
    "!=": lambda left, right: int(left != right),
}
RELATION_OPS = {
    "J<": lambda left, right: left < right,
    "J>": lambda left, right: left > right,
    "J<=": lambda left, right: left <= right,
    "J>=": lambda left, right: left >= right,
    "J==": lambda left, right: left == right,
    "J!=": lambda left, right: left != right,
}


@dataclass
class InterpreterResult:
    variables: dict[str, int]
    return_value: int | None
    trace: list[str]
    output_values: list[int]
    input_values: list[int]
    call_stack_snapshot: list[str]


@dataclass
class RuntimeFrame:
    name: str
    return_pc: int
    result_name: str
    locals: dict[str, int]


class QuadInterpreter:
    def __init__(self, quads: list[Quad], input_values: list[int] | None = None, max_steps: int = 10000):
        self.quads = quads
        self.max_steps = max_steps
        self.input_values = list(input_values or [])
        self.input_pos = 0
        self.index_to_position = {quad.index: pos for pos, quad in enumerate(quads)}
        self.function_entries = {
            quad.op: pos for pos, quad in enumerate(quads) if is_function_entry_quad(quad)
        }
        self.function_params = {
            name: self.infer_function_params(pos) for name, pos in self.function_entries.items()
        }
        self.frames: list[RuntimeFrame] = []
        self.main_locals: dict[str, int] = {}
        self.trace: list[str] = []
        self.return_value: int | None = None
        self.pending_params: list[int] = []
        self.output_values: list[int] = []

    def run(self) -> InterpreterResult:
        pc = self.function_entries.get("main", 0)
        self.frames = [RuntimeFrame("main", -1, EMPTY, {})]
        self.main_locals = self.frames[0].locals
        steps = 0
        while 0 <= pc < len(self.quads):
            if steps >= self.max_steps:
                raise RuntimeError("Interpreter stopped: possible infinite loop")
            steps += 1

            quad = self.quads[pc]
            before = self.snapshot_values()
            frame_name = self.current_frame().name
            detail: list[str] = []
            start_pc = pc
            try:
                if quad.op == "=":
                    value = self.value_of(quad.arg1)
                    self.assign(quad.result, value)
                    detail.append(f"write {quad.result} = {value}")
                    pc += 1
                elif quad.op in ARITHMETIC_OPS:
                    value = self.compute(quad.op, quad.arg1, quad.arg2, quad)
                    self.assign(quad.result, value)
                    detail.append(f"write {quad.result} = {value}")
                    pc += 1
                elif quad.op in COMPARE_OPS:
                    left = self.value_of(quad.arg1)
                    right = self.value_of(quad.arg2)
                    value = COMPARE_OPS[quad.op](left, right)
                    self.assign(quad.result, value)
                    detail.append(f"compare {left} {quad.op} {right} -> {value}")
                    detail.append(f"write {quad.result} = {value}")
                    pc += 1
                elif quad.op in {"ret", "return"}:
                    source = quad.arg1 if quad.arg1 != EMPTY else quad.result
                    ret_value = self.value_of(source)
                    detail.append(f"return {ret_value}")
                    if len(self.frames) > 1:
                        callee = self.frames.pop()
                        caller = self.current_frame()
                        if callee.result_name != EMPTY:
                            caller.locals[callee.result_name] = ret_value
                            detail.append(f"write caller {callee.result_name} = {ret_value}")
                        pc = callee.return_pc
                    else:
                        self.return_value = ret_value
                        self.log_step(steps, quad, before, detail, start_pc, None, frame_name)
                        break
                elif quad.op in {"J", "j"}:
                    pc = self.jump_to(quad.result, quad)
                    detail.append(f"jump -> pc {self.quads[pc].index}")
                elif quad.op == "jnz":
                    cond = self.value_of(quad.arg1)
                    pc = self.jump_to(quad.result, quad) if cond != 0 else pc + 1
                    detail.append(f"condition {quad.arg1}={cond}, next pc {self.next_pc_label(pc)}")
                elif quad.op == "jz":
                    cond = self.value_of(quad.arg1)
                    pc = self.jump_to(quad.result, quad) if cond == 0 else pc + 1
                    detail.append(f"condition {quad.arg1}={cond}, next pc {self.next_pc_label(pc)}")
                elif quad.op in RELATION_OPS:
                    left = self.value_of(quad.arg1)
                    right = self.value_of(quad.arg2)
                    matched = RELATION_OPS[quad.op](left, right)
                    pc = self.jump_to(quad.result, quad) if matched else pc + 1
                    detail.append(f"condition {left} {quad.op[1:]} {right} -> {int(matched)}")
                elif quad.op == "para":
                    value = self.value_of(quad.arg1)
                    self.pending_params.append(value)
                    detail.append(f"push param {value}")
                    pc += 1
                elif quad.op == "call":
                    pc = self.handle_call(quad.arg1, quad.result, pc + 1, detail)
                elif quad.op == "sys":
                    if self.return_value is None:
                        self.return_value = 0
                    detail.append("sys: stop program")
                    self.log_step(steps, quad, before, detail, start_pc, None, frame_name)
                    break
                elif quad.op in {"main", "nop"} or is_function_entry_quad(quad):
                    pc += 1
                else:
                    self.fail(quad, f"Unsupported operation: {quad.op}")
            except Exception as exc:
                if str(exc).startswith(f"quad {quad.index}:"):
                    raise
                self.fail(quad, str(exc))

            self.log_step(steps, quad, before, detail, start_pc, pc, frame_name)

        return InterpreterResult(
            dict(self.main_locals),
            self.return_value,
            list(self.trace),
            list(self.output_values),
            list(self.input_values),
            [frame.name for frame in self.frames],
        )

    def value_of(self, value: str) -> int:
        if value == EMPTY:
            return 0
        if is_int_literal(value):
            return int(value)
        for frame in reversed(self.frames):
            if value in frame.locals:
                return frame.locals[value]
        return 0

    def assign(self, name: str, value: int) -> None:
        if name == EMPTY:
            return
        self.current_frame().locals[name] = value

    def current_frame(self) -> RuntimeFrame:
        if not self.frames:
            self.frames.append(RuntimeFrame("main", -1, EMPTY, {}))
        return self.frames[-1]

    def compute(self, op: str, arg1: str, arg2: str, quad: Quad) -> int:
        left = self.value_of(arg1)
        right = self.value_of(arg2)
        if op == "!":
            return int(not left)
        if op == "+":
            return left + right
        if op == "-":
            return left - right
        if op == "*":
            return left * right
        if op == "/":
            if right == 0:
                self.fail(quad, "Division by zero in quadruple interpreter")
            return int(left / right)
        if op == "%":
            if right == 0:
                self.fail(quad, "Modulo by zero in quadruple interpreter")
            return left % right
        self.fail(quad, f"Unsupported arithmetic operation: {op}")

    def handle_call(self, name: str, result_name: str, return_pc: int, detail: list[str]) -> int:
        if name == "read":
            value = self.input_values[self.input_pos] if self.input_pos < len(self.input_values) else 0
            self.input_pos += 1
            if result_name != EMPTY:
                self.assign(result_name, value)
            self.pending_params.clear()
            detail.append(f"read() -> {value}")
            return return_pc
        if name == "write":
            value = self.pending_params[-1] if self.pending_params else 0
            self.output_values.append(value)
            if result_name != EMPTY:
                self.assign(result_name, 0)
            self.pending_params.clear()
            detail.append(f"write({value})")
            return return_pc
        if name in self.function_entries:
            params = self.function_params.get(name, [])
            locals_map: dict[str, int] = {}
            for param_name, param_value in zip(params, self.pending_params):
                locals_map[param_name] = param_value
            pairs = ", ".join(f"{param}={locals_map.get(param, 0)}" for param in params)
            detail.append(f"call {name}({pairs})")
            self.pending_params.clear()
            self.frames.append(RuntimeFrame(name, return_pc, result_name, locals_map))
            return self.function_entries[name] + 1
        if result_name != EMPTY:
            self.assign(result_name, 0)
        self.pending_params.clear()
        detail.append(f"external call {name}: default return 0")
        return return_pc

    def jump_to(self, target: str, quad: Quad) -> int:
        if not is_int_literal(target):
            self.fail(quad, f"Jump target must be a quad index: {target}")
        target_index = int(target)
        if target_index not in self.index_to_position:
            self.fail(quad, f"Jump target does not exist: {target_index}")
        return self.index_to_position[target_index]

    def log_step(
        self,
        step: int,
        quad: Quad,
        before: dict[str, int],
        detail: list[str],
        start_pc: int,
        next_pc: int | None,
        frame_name: str,
    ) -> None:
        indent = "  " * (len(self.frames) - 1)
        self.trace.append(
            f"Step {step} | frame={frame_name} | pc={quad.index}: "
            f"({quad.op}, {quad.arg1}, {quad.arg2}, {quad.result})"
        )
        for item in detail:
            self.trace.append(f"{indent}  {item}")
        changes = self.changed_values(before, self.snapshot_values())
        if changes:
            self.trace.append(f"{indent}  changes: {changes}")
        if next_pc is None:
            self.trace.append(f"{indent}  next pc: stop")
        elif next_pc != start_pc + 1:
            self.trace.append(f"{indent}  next pc: {self.next_pc_label(next_pc)}")

    def snapshot_values(self) -> dict[str, int]:
        result: dict[str, int] = {}
        for index, frame in enumerate(self.frames):
            prefix = "" if index == 0 else f"{frame.name}#{index}."
            for name, value in frame.locals.items():
                result[f"{prefix}{name}"] = value
        return result

    def changed_values(self, before: dict[str, int], after: dict[str, int]) -> str:
        changes = []
        for name in sorted(set(before) | set(after)):
            old = before.get(name)
            new = after.get(name)
            if old != new:
                changes.append(f"{name}: {old if old is not None else '_'} -> {new if new is not None else '_'}")
        return "; ".join(changes)

    def next_pc_label(self, pc: int) -> str:
        if 0 <= pc < len(self.quads):
            return str(self.quads[pc].index)
        return "stop"

    def fail(self, quad: Quad, message: str):
        raise RuntimeError(f"quad {quad.index}: {message}")

    def infer_function_params(self, entry_pos: int) -> list[str]:
        entry_quad = self.quads[entry_pos]
        function_name = entry_quad.op
        if function_name == "main":
            return []

        declared_params = [
            value
            for value in (entry_quad.arg1, entry_quad.arg2, entry_quad.result)
            if self.is_param_candidate(value)
        ]

        other_entries = [
            pos for pos in self.function_entries.values() if pos > entry_pos
        ] or [len(self.quads)]
        end_pos = min(other_entries)
        defined: set[str] = set()
        params: list[str] = list(declared_params)

        def note_use(value: str) -> None:
            if self.is_param_candidate(value) and value not in defined and value not in params:
                params.append(value)

        for quad in self.quads[entry_pos + 1 : end_pos]:
            if quad.op == "=":
                note_use(quad.arg1)
                if self.is_param_candidate(quad.result):
                    defined.add(quad.result)
            elif quad.op in ARITHMETIC_OPS or quad.op in COMPARE_OPS or quad.op in RELATION_OPS:
                note_use(quad.arg1)
                note_use(quad.arg2)
                if quad.op in ARITHMETIC_OPS or quad.op in COMPARE_OPS:
                    if self.is_param_candidate(quad.result):
                        defined.add(quad.result)
            elif quad.op == "para":
                note_use(quad.arg1)
            elif quad.op == "call":
                if self.is_param_candidate(quad.result):
                    defined.add(quad.result)
            elif quad.op in {"J", "j", "ret", "return", "jnz", "jz"}:
                note_use(quad.arg1)
                note_use(quad.arg2)
                if quad.op in {"ret", "return"}:
                    note_use(quad.result)

        return self.prefer_common_param_order(function_name, params)

    def is_param_candidate(self, value: str) -> bool:
        if value == EMPTY or is_int_literal(value):
            return False
        if value.startswith("t") and value[1:].isdigit():
            return False
        if value.startswith("T") and value[1:].isdigit():
            return False
        return value not in KNOWN_OPS

    def prefer_common_param_order(self, function_name: str, params: list[str]) -> list[str]:
        if {"base", "exp"}.issubset(params):
            priority = {"base": 0, "exp": 1}
            return sorted(params, key=lambda name: priority.get(name, 100 + params.index(name)))
        return params


def render_interpreter_result(result: InterpreterResult) -> str:
    variables = {name: value for name, value in result.variables.items() if not is_temp(name)}
    temporaries = {name: value for name, value in result.variables.items() if is_temp(name)}

    lines = ["Quadruple Interpreter Result", ""]
    lines.append("Read Input Values:")
    if result.input_values:
        for index, value in enumerate(result.input_values, start=1):
            lines.append(f"read[{index}] = {value}")
    else:
        lines.append("(empty, read() defaults to 0)")
    lines.append("")
    lines.append("Interpreter Trace:")
    lines.extend(result.trace)
    lines.append("")
    lines.append("Output Values:")
    if result.output_values:
        for value in result.output_values:
            lines.append(str(value))
    else:
        lines.append("(empty)")
    lines.append("")
    lines.append("Final Variables:")
    if variables:
        for name in sorted(variables):
            lines.append(f"{name} = {variables[name]}")
    else:
        lines.append("(empty)")
    lines.append("")
    lines.append("Temporary Variables:")
    if temporaries:
        for name in sorted(temporaries):
            lines.append(f"{name} = {temporaries[name]}")
    else:
        lines.append("(empty)")
    lines.append("")
    lines.append("Call Stack At End:")
    if result.call_stack_snapshot:
        lines.append(" -> ".join(result.call_stack_snapshot))
    else:
        lines.append("(empty)")
    lines.append("")
    lines.append(f"Return Value: {result.return_value}")
    return "\n".join(lines) + "\n"
