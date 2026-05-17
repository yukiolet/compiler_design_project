"""Convert quadruples to teaching-oriented LLVM IR.

The converter intentionally keeps the IR small and readable for a compiler
course project: ordinary variables live in stack slots, temporary variables are
SSA values, and control flow is emitted with explicit labels and branches.
"""

from __future__ import annotations

from dataclasses import dataclass

from .cfg import COND_JUMPS, build_cfg, is_function_entry_quad
from .quad import EMPTY, Quad, is_int_literal, is_symbol, is_temp


ARITH_TO_LLVM = {"+": "add", "-": "sub", "*": "mul", "/": "sdiv", "%": "srem"}
CMP_ASSIGN_TO_LLVM = {
    "<": "slt",
    ">": "sgt",
    "<=": "sle",
    ">=": "sge",
    "==": "eq",
    "!=": "ne",
}
CMP_TO_LLVM = {
    "J<": "slt",
    "J>": "sgt",
    "J<=": "sle",
    "J>=": "sge",
    "J==": "eq",
    "J!=": "ne",
}


@dataclass
class FunctionUnit:
    name: str
    quads: list[Quad]
    params: list[str]


class LLVMConverter:
    def __init__(self, quads: list[Quad]):
        self.quads = quads
        self.temp_counter = 1
        self.cmp_counter = 1
        self.lines: list[str] = []
        self.pending_params: list[str] = []
        self.current_cfg = None

    def convert(self) -> str:
        self.lines = []
        self.temp_counter = 1
        self.cmp_counter = 1
        functions = self.split_functions()
        defined_names = {function.name for function in functions}

        prelude = self.runtime_prelude()
        if prelude:
            self.lines.extend(prelude)
            self.lines.append("")

        for declaration in self.collect_external_declarations(defined_names):
            self.lines.append(declaration)
        if self.lines and self.lines[-1] != "":
            self.lines.append("")

        for function in functions:
            self.emit_function(function)
            self.lines.append("")

        for runtime in self.runtime_definitions():
            self.lines.extend(runtime)
            self.lines.append("")

        while self.lines and self.lines[-1] == "":
            self.lines.pop()
        return "\n".join(self.lines) + "\n"

    def split_functions(self) -> list[FunctionUnit]:
        if not self.quads:
            return [FunctionUnit("main", [], [])]

        raw_functions: list[tuple[str, list[Quad]]] = []
        current_name = "main"
        current_quads: list[Quad] = []
        has_explicit_entry = False

        for quad in self.quads:
            if is_function_entry_quad(quad):
                has_explicit_entry = True
                if current_quads:
                    raw_functions.append((current_name, current_quads))
                current_name = "main" if quad.op == "main" else quad.op
                current_quads = [quad]
            else:
                current_quads.append(quad)

        if current_quads:
            raw_functions.append((current_name, current_quads))

        if not has_explicit_entry:
            raw_functions = [("main", self.quads)]

        call_param_counts = self.collect_call_param_counts()
        return [
            FunctionUnit(name, quads, self.infer_params(name, quads, call_param_counts.get(name, 0)))
            for name, quads in raw_functions
        ]

    def collect_call_param_counts(self) -> dict[str, int]:
        counts: dict[str, int] = {}
        pending = 0
        for quad in self.quads:
            if quad.op == "para":
                pending += 1
            elif quad.op == "call":
                counts[quad.arg1] = max(counts.get(quad.arg1, 0), pending)
                pending = 0
            elif quad.op != "nop":
                pending = pending
        return counts

    def infer_params(self, name: str, quads: list[Quad], expected_count: int) -> list[str]:
        if name == "main":
            return []

        if quads and is_function_entry_quad(quads[0]):
            declared_params = [
                value
                for value in (quads[0].arg1, quads[0].arg2, quads[0].result)
                if self.is_variable(value)
            ]
        else:
            declared_params = []

        defined: set[str] = set()
        params: list[str] = list(declared_params)
        for quad in quads:
            if is_function_entry_quad(quad):
                continue
            for value in self.read_operands(quad):
                if self.is_variable(value) and value not in defined and value not in params:
                    params.append(value)
            for value in self.write_operands(quad):
                if self.is_variable(value):
                    defined.add(value)

        if expected_count > 0:
            return params[:expected_count]
        return params

    def emit_function(self, function: FunctionUnit) -> None:
        self.pending_params = []
        self.current_cfg = build_cfg(function.quads)
        params_text = ", ".join(f"i32 %arg_{param}" for param in function.params)
        self.lines.append(f"define i32 @{function.name}({params_text}) {{")
        self.lines.append("entry:")

        variables = sorted(self.collect_variables(function.quads) | set(function.params))
        for name in variables:
            self.lines.append(f"  %{name} = alloca i32")
        for param in function.params:
            self.lines.append(f"  store i32 %arg_{param}, ptr %{param}")

        if self.current_cfg.blocks:
            self.lines.append(f"  br label %{self.label_for_block(self.current_cfg.blocks[0])}")
            for block in self.current_cfg.blocks:
                self.lines.append(f"{self.label_for_block(block)}:")
                for quad in block.quads:
                    self.emit_quad(quad)
                self.emit_fallthrough_if_needed(block)
        else:
            self.lines.append("  ret i32 0")
        self.lines.append("}")

    def collect_variables(self, quads: list[Quad]) -> set[str]:
        variables: set[str] = set()
        for quad in quads:
            if quad.op in {"main", "sys", "nop"} or is_function_entry_quad(quad):
                continue
            for value in self.read_operands(quad) + self.write_operands(quad):
                if self.is_variable(value):
                    variables.add(value)
        return variables

    def read_operands(self, quad: Quad) -> list[str]:
        if quad.op == "=":
            return [quad.arg1]
        if quad.op in ARITH_TO_LLVM or quad.op in CMP_ASSIGN_TO_LLVM or quad.op in COND_JUMPS:
            return [quad.arg1, quad.arg2]
        if quad.op in {"ret", "return"}:
            return [quad.arg1 if quad.arg1 != EMPTY else quad.result]
        if quad.op == "para":
            return [quad.arg1]
        return []

    def write_operands(self, quad: Quad) -> list[str]:
        if quad.op == "=" or quad.op in ARITH_TO_LLVM or quad.op in CMP_ASSIGN_TO_LLVM:
            return [quad.result]
        if quad.op == "call":
            return [quad.result]
        return []

    def is_variable(self, value: str) -> bool:
        return is_symbol(value) and not is_temp(value)

    def emit_quad(self, quad: Quad) -> None:
        if quad.op == "=":
            value = self.value_ref(quad.arg1)
            if self.is_variable(quad.result):
                self.lines.append(f"  store i32 {value}, ptr %{quad.result}")
            elif is_temp(quad.result):
                self.lines.append(f"  %{quad.result} = add i32 {value}, 0")
        elif quad.op in ARITH_TO_LLVM:
            left = self.value_ref(quad.arg1)
            right = self.value_ref(quad.arg2)
            self.lines.append(f"  %{quad.result} = {ARITH_TO_LLVM[quad.op]} i32 {left}, {right}")
        elif quad.op in CMP_ASSIGN_TO_LLVM:
            left = self.value_ref(quad.arg1)
            right = self.value_ref(quad.arg2)
            cmp_name = self.new_cmp()
            self.lines.append(f"  %{cmp_name} = icmp {CMP_ASSIGN_TO_LLVM[quad.op]} i32 {left}, {right}")
            self.lines.append(f"  %{quad.result} = zext i1 %{cmp_name} to i32")
        elif quad.op in {"J", "j"}:
            self.lines.append(f"  br label %{self.block_for_index(int(quad.result))}")
        elif quad.op in {"jnz", "jz"}:
            cond = self.value_ref(quad.arg1)
            cmp_name = self.new_cmp()
            true_label = self.block_for_index(int(quad.result))
            false_label = self.next_block_after(quad.index) or true_label
            self.lines.append(f"  %{cmp_name} = icmp ne i32 {cond}, 0")
            if quad.op == "jnz":
                self.lines.append(f"  br i1 %{cmp_name}, label %{true_label}, label %{false_label}")
            else:
                self.lines.append(f"  br i1 %{cmp_name}, label %{false_label}, label %{true_label}")
        elif quad.op in COND_JUMPS:
            left = self.value_ref(quad.arg1)
            right = self.value_ref(quad.arg2)
            cmp_name = self.new_cmp()
            true_label = self.block_for_index(int(quad.result))
            false_label = self.next_block_after(quad.index) or true_label
            self.lines.append(f"  %{cmp_name} = icmp {CMP_TO_LLVM[quad.op]} i32 {left}, {right}")
            self.lines.append(f"  br i1 %{cmp_name}, label %{true_label}, label %{false_label}")
        elif quad.op in {"ret", "return"}:
            source = quad.arg1 if quad.arg1 != EMPTY else quad.result
            self.lines.append(f"  ret i32 {self.value_ref(source)}")
        elif quad.op == "call":
            if quad.arg1 == "read":
                self.emit_call_result(quad.result, "call i32 @read()")
            elif quad.arg1 == "write":
                arg = self.value_ref(self.pending_params[-1]) if self.pending_params else "0"
                self.lines.append(f"  call void @write(i32 {arg})")
                self.pending_params.clear()
            else:
                args = [self.value_ref(param) for param in self.pending_params]
                arg_text = ", ".join(f"i32 {arg}" for arg in args)
                call_expr = f"call i32 @{quad.arg1}({arg_text})"
                self.emit_call_result(quad.result, call_expr)
                self.pending_params.clear()
        elif quad.op == "para":
            self.pending_params.append(quad.arg1)
        elif quad.op in {"main", "sys", "nop"} or is_function_entry_quad(quad):
            return

    def emit_fallthrough_if_needed(self, block) -> None:
        last = block.quads[-1]
        if last.op in {"J", "j", "ret", "return"} or last.op in COND_JUMPS:
            return
        if last.op == "sys":
            if not self.block_has_terminator(block.quads[:-1]):
                self.lines.append("  ret i32 0")
            return
        if block.successors:
            target = self.label_for_block_name(sorted(block.successors)[0])
            self.lines.append(f"  br label %{target}")
        else:
            self.lines.append("  ret i32 0")

    def block_has_terminator(self, quads: list[Quad]) -> bool:
        return any(quad.op in {"J", "j", "ret", "return"} or quad.op in COND_JUMPS for quad in quads)

    def emit_call_result(self, result: str, call_expr: str) -> None:
        if result == EMPTY:
            self.lines.append(f"  {call_expr}")
        elif self.is_variable(result):
            temp = self.new_temp()
            self.lines.append(f"  %{temp} = {call_expr}")
            self.lines.append(f"  store i32 %{temp}, ptr %{result}")
        elif is_temp(result):
            self.lines.append(f"  %{result} = {call_expr}")
        else:
            self.lines.append(f"  {call_expr}")

    def value_ref(self, value: str) -> str:
        if value == EMPTY:
            return "0"
        if is_int_literal(value):
            return value
        if is_temp(value):
            return f"%{value}"
        if self.is_variable(value):
            temp = self.new_temp()
            self.lines.append(f"  %{temp} = load i32, ptr %{value}")
            return f"%{temp}"
        return value

    def collect_external_declarations(self, defined_names: set[str]) -> list[str]:
        declarations: list[str] = []
        call_param_counts = self.collect_call_param_counts()
        for name in sorted(call_param_counts):
            if name in {"read", "write"} or name in defined_names:
                continue
            params = ", ".join("i32" for _ in range(call_param_counts[name]))
            declarations.append(f"declare i32 @{name}({params})")
        return declarations

    def runtime_prelude(self) -> list[str]:
        return []

    def runtime_definitions(self) -> list[list[str]]:
        definitions: list[list[str]] = []
        if self.uses_read():
            definitions.append([
                "define i32 @read() {",
                "entry:",
                "  ret i32 0",
                "}",
            ])
        if self.uses_write():
            definitions.append([
                "define void @write(i32 %x) {",
                "entry:",
                "  ret void",
                "}",
            ])
        return definitions

    def uses_read(self) -> bool:
        return any(quad.op == "call" and quad.arg1 == "read" for quad in self.quads)

    def uses_write(self) -> bool:
        return any(quad.op == "call" and quad.arg1 == "write" for quad in self.quads)

    def label_for_block(self, block) -> str:
        return f"L{block.start_index}"

    def block_for_index(self, index: int) -> str:
        return self.label_for_index(index)

    def label_for_block_name(self, block_name: str) -> str:
        for block in self.current_cfg.blocks:
            if block.name == block_name:
                return self.label_for_block(block)
        return block_name

    def label_for_index(self, index: int) -> str:
        block_name = self.current_cfg.index_to_block[index]
        for block in self.current_cfg.blocks:
            if block.name == block_name:
                return self.label_for_block(block)
        return f"L{index}"

    def next_block_after(self, quad_index: int) -> str | None:
        for block_pos, block in enumerate(self.current_cfg.blocks):
            if any(quad.index == quad_index for quad in block.quads):
                if block_pos + 1 < len(self.current_cfg.blocks):
                    return self.label_for_block(self.current_cfg.blocks[block_pos + 1])
        return None

    def new_temp(self) -> str:
        name = f"v{self.temp_counter}"
        self.temp_counter += 1
        return name

    def new_cmp(self) -> str:
        name = f"cmp{self.cmp_counter}"
        self.cmp_counter += 1
        return name
