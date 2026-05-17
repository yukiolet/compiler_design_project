"""Direct interpreter for the small C-like AST used by the course project."""

from __future__ import annotations

from dataclasses import dataclass


class ReturnSignal(Exception):
    def __init__(self, value: int):
        self.value = value


class BreakSignal(Exception):
    pass


class ContinueSignal(Exception):
    pass


@dataclass
class SourceExecutionResult:
    variables: dict[str, int]
    return_value: int | None
    trace: list[str]
    output_values: list[int]


class SourceInterpreter:
    """Execute the parsed class-C AST directly for result verification.

    The interpreter intentionally covers the teaching subset used by the
    project front end: integer variables, assignments, arithmetic, relations,
    logical operators, if/while/for/do-while, break/continue/return and simple
    function calls.
    """

    def __init__(self, root, input_values: list[int] | None = None, max_steps: int = 10000):
        self.root = root
        self.max_steps = max_steps
        self.input_values = list(input_values or [])
        self.input_pos = 0
        self.steps = 0
        self.functions = self.collect_functions(root)
        self.scopes: list[dict[str, int]] = []
        self.trace: list[str] = []
        self.output_values: list[int] = []

    def run(self) -> SourceExecutionResult:
        if "main" not in self.functions:
            raise RuntimeError("Source interpreter cannot find main function")
        try:
            value = self.call_function("main", [])
        except ReturnSignal as signal:
            value = signal.value
        variables = dict(self.scopes[-1]) if self.scopes else {}
        return SourceExecutionResult(variables, value, list(self.trace), list(self.output_values))

    def collect_functions(self, root) -> dict[str, object]:
        functions: dict[str, object] = {}
        for child in getattr(root, "children", []):
            if getattr(child, "kind", "") == "FunctionDef":
                functions[self.function_name(child)] = child
        return functions

    def call_function(self, name: str, args: list[int]) -> int:
        if name == "read":
            value = self.input_values[self.input_pos] if self.input_pos < len(self.input_values) else 0
            self.input_pos += 1
            self.trace.append(f"call read() -> {value}")
            return value
        if name == "write":
            value = args[0] if args else 0
            self.output_values.append(value)
            self.trace.append(f"call write({value})")
            return 0
        if name not in self.functions:
            self.trace.append(f"external call {name}() -> 0")
            return 0

        function = self.functions[name]
        params = self.function_params(function)
        frame = {param: args[i] if i < len(args) else 0 for i, param in enumerate(params)}
        self.scopes.append(frame)
        self.trace.append(f"enter {name}({', '.join(f'{p}={frame[p]}' for p in params)})")

        try:
            body = self.function_body(function)
            self.exec_stmt(body, create_scope=False)
            value = 0
        except ReturnSignal as signal:
            value = signal.value

        if name == "main":
            self.trace.append(f"leave main -> {value}")
            return value

        self.scopes.pop()
        self.trace.append(f"leave {name} -> {value}")
        return value

    def function_name(self, node) -> str:
        parts = str(getattr(node, "value", "")).split()
        return parts[-1] if parts else "unknown"

    def function_params(self, node) -> list[str]:
        params: list[str] = []
        for child in getattr(node, "children", []):
            if getattr(child, "kind", "") == "Param":
                params.append(self.declared_name(child))
        return params

    def function_body(self, node):
        for child in getattr(node, "children", []):
            if getattr(child, "kind", "") == "Compound":
                return child
        raise RuntimeError(f"Function {self.function_name(node)} has no body")

    def exec_stmt(self, node, create_scope: bool = True) -> None:
        self.tick(node)
        kind = getattr(node, "kind", "")
        if kind == "Compound":
            if create_scope:
                self.scopes.append({})
            try:
                for child in getattr(node, "children", []):
                    self.exec_stmt(child)
            finally:
                if create_scope:
                    self.scopes.pop()
        elif kind in {"VarDecl", "ConstDecl"}:
            name = self.declared_name(node)
            value = self.eval_expr(node.children[0]) if getattr(node, "children", []) else 0
            self.declare(name, value)
            self.trace.append(f"declare {name} = {value}")
        elif kind == "ExprStmt":
            for child in getattr(node, "children", []):
                self.eval_expr(child)
        elif kind == "ReturnStmt":
            value = self.eval_expr(node.children[0]) if getattr(node, "children", []) else 0
            self.trace.append(f"return {value}")
            raise ReturnSignal(value)
        elif kind == "IfStmt":
            children = getattr(node, "children", [])
            cond = self.eval_expr(children[0]) if children else 0
            self.trace.append(f"if condition -> {cond}")
            if cond and len(children) >= 2:
                self.exec_stmt(children[1])
            elif not cond and len(children) >= 3:
                self.exec_stmt(children[2])
        elif kind == "WhileStmt":
            self.exec_while(node)
        elif kind == "ForStmt":
            self.exec_for(node)
        elif kind == "DoWhileStmt":
            self.exec_do_while(node)
        elif kind == "BreakStmt":
            self.trace.append("break")
            raise BreakSignal()
        elif kind == "ContinueStmt":
            self.trace.append("continue")
            raise ContinueSignal()
        elif kind in {"FunctionDef", "FunctionDecl", "Param"}:
            return
        else:
            for child in getattr(node, "children", []):
                self.exec_stmt(child)

    def exec_while(self, node) -> None:
        cond, body = node.children[0], node.children[1]
        while self.eval_expr(cond):
            self.trace.append("while condition -> 1")
            try:
                self.exec_stmt(body)
            except ContinueSignal:
                continue
            except BreakSignal:
                break
        self.trace.append("while condition -> 0")

    def exec_for(self, node) -> None:
        init_stmt, cond_stmt, update_stmt, body = node.children[:4]
        self.exec_stmt(init_stmt)
        while True:
            cond = self.eval_expr(cond_stmt.children[0]) if getattr(cond_stmt, "children", []) else 1
            self.trace.append(f"for condition -> {cond}")
            if not cond:
                break
            try:
                self.exec_stmt(body)
            except ContinueSignal:
                pass
            except BreakSignal:
                break
            self.exec_stmt(update_stmt)

    def exec_do_while(self, node) -> None:
        body, cond = node.children[0], node.children[1]
        while True:
            try:
                self.exec_stmt(body)
            except ContinueSignal:
                pass
            except BreakSignal:
                break
            value = self.eval_expr(cond)
            self.trace.append(f"do while condition -> {value}")
            if not value:
                break

    def eval_expr(self, node) -> int:
        self.tick(node)
        kind = getattr(node, "kind", "")
        if kind == "Leaf":
            return self.leaf_value(str(getattr(node, "value", "")))
        if kind == "Call":
            args = [self.eval_expr(child) for child in getattr(node, "children", [])]
            return self.call_function(str(getattr(node, "value", "")), args)
        if kind == "ExprStmt":
            value = 0
            for child in getattr(node, "children", []):
                value = self.eval_expr(child)
            return value
        if kind == "Op":
            return self.eval_op(node)
        value = 0
        for child in getattr(node, "children", []):
            value = self.eval_expr(child)
        return value

    def eval_op(self, node) -> int:
        op = str(getattr(node, "value", ""))
        children = getattr(node, "children", [])
        if op == "=":
            name = self.lvalue_name(children[0])
            value = self.eval_expr(children[1]) if len(children) >= 2 else 0
            self.assign(name, value)
            self.trace.append(f"{name} = {value}")
            return value
        if len(children) == 1:
            value = self.eval_expr(children[0])
            if op == "-":
                return -value
            if op == "!":
                return int(not value)
            return value

        left = self.eval_expr(children[0])
        if op == "&&":
            return int(bool(left) and bool(self.eval_expr(children[1])))
        if op == "||":
            return int(bool(left) or bool(self.eval_expr(children[1])))
        right = self.eval_expr(children[1])

        if op == "+":
            return left + right
        if op == "-":
            return left - right
        if op == "*":
            return left * right
        if op == "/":
            if right == 0:
                raise ZeroDivisionError("Division by zero in source interpreter")
            return int(left / right)
        if op == "%":
            if right == 0:
                raise ZeroDivisionError("Modulo by zero in source interpreter")
            return left % right
        if op == ">":
            return int(left > right)
        if op == "<":
            return int(left < right)
        if op == ">=":
            return int(left >= right)
        if op == "<=":
            return int(left <= right)
        if op == "==":
            return int(left == right)
        if op == "!=":
            return int(left != right)
        raise ValueError(f"Unsupported source operator: {op}")

    def leaf_value(self, value: str) -> int:
        if self.is_int_literal(value):
            return int(value, 0)
        return self.lookup(value)

    def declare(self, name: str, value: int) -> None:
        if not self.scopes:
            self.scopes.append({})
        self.scopes[-1][name] = value

    def assign(self, name: str, value: int) -> None:
        for scope in reversed(self.scopes):
            if name in scope:
                scope[name] = value
                return
        self.declare(name, value)

    def lookup(self, name: str) -> int:
        for scope in reversed(self.scopes):
            if name in scope:
                return scope[name]
        return 0

    def lvalue_name(self, node) -> str:
        if getattr(node, "kind", "") == "Leaf":
            return str(getattr(node, "value", ""))
        raise ValueError("Left side of assignment must be an identifier")

    def declared_name(self, node) -> str:
        parts = str(getattr(node, "value", "")).split()
        return parts[-1] if parts else "unknown"

    def is_int_literal(self, value: str) -> bool:
        try:
            int(value, 0)
            return True
        except ValueError:
            return False

    def tick(self, node) -> None:
        self.steps += 1
        if self.steps > self.max_steps:
            line = getattr(node, "line", "?")
            raise RuntimeError(f"Source interpreter stopped near line {line}: possible infinite loop")


def render_source_execution(result: SourceExecutionResult) -> str:
    lines = ["Source Execution Trace:"]
    lines.extend(result.trace)
    lines.append("")
    lines.append("Source Final Variables:")
    if result.variables:
        for name in sorted(result.variables):
            lines.append(f"{name} = {result.variables[name]}")
    else:
        lines.append("(empty)")
    lines.append("")
    lines.append("Source Output Values:")
    if result.output_values:
        for value in result.output_values:
            lines.append(str(value))
    else:
        lines.append("(empty)")
    lines.append("")
    lines.append(f"Source Return Value: {result.return_value}")
    return "\n".join(lines) + "\n"


def render_execution_compare(source_result: SourceExecutionResult, quad_result) -> str:
    source_return = source_result.return_value
    quad_return = quad_result.return_value
    output_matched = source_result.output_values == getattr(quad_result, "output_values", [])
    matched = source_return == quad_return and output_matched
    lines = [
        "Execution Result Comparison:",
        f"Source return value: {source_return}",
        f"Quad return value:   {quad_return}",
        f"Return check: {'PASS' if source_return == quad_return else 'FAIL'}",
        f"Source output values: {source_result.output_values or '[]'}",
        f"Quad output values:   {getattr(quad_result, 'output_values', []) or '[]'}",
        f"Output check: {'PASS' if output_matched else 'FAIL'}",
        f"Overall check: {'PASS' if matched else 'FAIL'}",
        "",
        "Source variables:",
    ]
    if source_result.variables:
        for name in sorted(source_result.variables):
            lines.append(f"{name} = {source_result.variables[name]}")
    else:
        lines.append("(empty)")
    lines.extend(["", "Quad variables with the same names:"])
    if source_result.variables:
        for name in sorted(source_result.variables):
            lines.append(f"{name} = {quad_result.variables.get(name, 0)}")
    else:
        lines.append("(empty)")
    return "\n".join(lines) + "\n"
