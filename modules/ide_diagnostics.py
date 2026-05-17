"""Realtime diagnostics for the class-C source editor.

This module keeps the 4.3 IDE checks outside the Qt UI layer.  The UI only
passes source text in and displays the returned report.
"""

from __future__ import annotations

from dataclasses import dataclass
import importlib.util
from pathlib import Path
import re
from typing import Callable


def load_module(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Cannot load module: {path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@dataclass(frozen=True)
class Diagnostic:
    category: str
    line: int
    code: int
    message: str


class CLikeIdeDiagnostics:
    def __init__(
        self,
        old_code_dir: Path,
        output_dir_provider: Callable[[], Path],
        ast_renderer: Callable[[object], str],
    ) -> None:
        self.old_code_dir = old_code_dir
        self.output_dir_provider = output_dir_provider
        self.ast_renderer = ast_renderer
        self.ir_module = load_module("ide_intermediate_code", old_code_dir / "intermediate_code.py")
        self.lex_error_module = load_module("ide_lexical_error_analyzer", old_code_dir / "lexical_analyzer 2.py")
        self.parse_error_module = load_module("ide_parser_error_analyzer", old_code_dir / "parser - error-analyzer.py")

    def analyze(self, source: str) -> str:
        diagnostics = self.collect(source)
        return self.render_report(diagnostics)

    def collect(self, source: str) -> list[Diagnostic]:
        if not source.strip():
            return []

        diagnostics: list[Diagnostic] = []
        lexical_errors = self.lex_error_module.LexicalErrorAnalyzer(source).analyze()
        diagnostics.extend(
            Diagnostic("Lexical", line, code, self.lexical_error_message(code))
            for line, code in lexical_errors
            if not self.is_comment_only_line(source, line)
        )

        diagnostics.extend(self.lightweight_syntax_checks(source))

        tokens = self.ir_module.LexicalAnalyzer(source).analyze()
        parser = self.parse_error_module.Parser(tokens)
        parser.parse()
        syntax_errors = self.filter_syntax_errors(source, parser.errors)
        existing_syntax = {(item.line, item.code) for item in diagnostics if item.category == "Syntax"}
        diagnostics.extend(
            Diagnostic("Syntax", line, code, self.syntax_error_message(code))
            for line, code in syntax_errors
            if (line, code) not in existing_syntax
        )

        has_blocking_errors = any(item.category in {"Lexical", "Syntax"} for item in diagnostics)
        if not has_blocking_errors:
            diagnostics.extend(self.semantic_checks(source, tokens))

        return sorted(diagnostics, key=lambda item: (item.line, item.category, item.code))

    def lightweight_syntax_checks(self, source: str) -> list[Diagnostic]:
        diagnostics: list[Diagnostic] = []
        lines = source.splitlines()
        brace_depth = 0
        paren_depth = 0
        for index, raw_line in enumerate(lines, start=1):
            code = self.strip_line_comment(raw_line).strip()
            if not code:
                continue
            paren_depth += code.count("(") - code.count(")")
            brace_depth += code.count("{") - code.count("}")
            if brace_depth < 0:
                diagnostics.append(Diagnostic("Syntax", index, 203, self.syntax_error_message(203)))
                brace_depth = 0
            if self.needs_semicolon(code) and not code.endswith(";"):
                diagnostics.append(Diagnostic("Syntax", index, 202, self.syntax_error_message(202)))

        if brace_depth > 0:
            diagnostics.append(Diagnostic("Syntax", len(lines), 205, self.syntax_error_message(205)))
        if paren_depth > 0:
            diagnostics.append(Diagnostic("Syntax", len(lines), 208, self.syntax_error_message(208)))
        elif paren_depth < 0:
            diagnostics.append(Diagnostic("Syntax", len(lines), 206, self.syntax_error_message(206)))
        return diagnostics

    def needs_semicolon(self, code: str) -> bool:
        if code.endswith((";", "{", "}")):
            return False
        if re.match(r"^(if|while|for|else|do)\b", code):
            return False
        if re.match(r"^(?:const\s+)?(?:int|void|float|char)\s+[A-Za-z_]\w*\s*\(", code):
            return False
        if re.match(r"^(?:const\s+)?(?:int|void|float|char)\s+[A-Za-z_]\w*\s*\([^{};]*\)\s*$", code):
            return False
        if code in {"else"}:
            return False
        return bool(
            re.match(r"^(?:const\s+)?(?:int|float|char)\s+[^;]+$", code)
            or re.match(r"^[A-Za-z_]\w*\s*=", code)
            or re.match(r"^return\b", code)
            or re.match(r"^[A-Za-z_]\w*\s*\(.*\)$", code)
        )

    def filter_syntax_errors(self, source: str, errors: list[tuple[int, int]]) -> list[tuple[int, int]]:
        if not errors:
            return []
        lines = source.splitlines()
        prototype_lines = self.function_prototype_lines(source)
        filtered: list[tuple[int, int]] = []
        for line, code in errors:
            if self.is_comment_only_line(source, line):
                continue
            if line in prototype_lines and code in {202, 204}:
                continue
            if code == 202 and self.line_starts_function_definition(lines, line):
                continue
            if code == 204 and self.line_starts_function_definition(lines, line):
                continue
            filtered.append((line, code))
        return filtered

    def function_prototype_lines(self, source: str) -> set[int]:
        prototype_lines: set[int] = set()
        pattern = re.compile(
            r"^\s*(?:const\s+)?(?:int|void|float|char)\s+[A-Za-z_]\w*\s*\([^{};]*\)\s*;\s*(?://.*)?$"
        )
        for index, line in enumerate(source.splitlines(), start=1):
            if pattern.match(line):
                prototype_lines.add(index)
        return prototype_lines

    def line_starts_function_definition(self, lines: list[str], line: int) -> bool:
        if line <= 0 or line > len(lines):
            return False
        current = self.strip_line_comment(lines[line - 1]).strip()
        pattern = re.compile(r"^(?:const\s+)?(?:int|void|float|char)\s+[A-Za-z_]\w*\s*\([^{};]*\)\s*$")
        if not pattern.match(current):
            return False
        next_lines = [self.strip_line_comment(item).strip() for item in lines[line:] if self.strip_line_comment(item).strip()]
        return bool(next_lines and next_lines[0].startswith("{"))

    def semantic_checks(self, source: str, tokens) -> list[Diagnostic]:
        diagnostics: list[Diagnostic] = []
        try:
            ast_root = self.ir_module.Parser(tokens).parse()
            ast_lines = self.ast_renderer(ast_root)
            ast_path = self.output_dir_provider() / "_ide_ast.txt"
            ast_path.parent.mkdir(parents=True, exist_ok=True)
            ast_path.write_text(ast_lines, encoding="utf-8")
            semantic_module = load_module("ide_semantic_analyzer_runtime", self.old_code_dir / "semantic_analyzer.py")
            semantic_root = semantic_module.parse_ast_file(ast_path)
            analyzer = semantic_module.SemanticAnalyzer(semantic_root)
            analyzer.write_outputs = lambda: None
            analyzer.analyze()
            semantic_errors = self.filter_semantic_errors(source, analyzer.errors)
            diagnostics.extend(
                Diagnostic("Semantic", line, code, self.semantic_error_message(code))
                for line, code in semantic_errors
            )
        except Exception as exc:
            diagnostics.append(Diagnostic("Semantic", 1, 0, f"语义分析暂不可用：{exc}"))
        return diagnostics

    def filter_semantic_errors(self, source: str, errors: list[tuple[int, int]]) -> list[tuple[int, int]]:
        if not errors:
            return []
        void_ranges = self.void_function_ranges_without_return(source)
        function_lines = self.known_function_lines(source)
        visible_function_calls = self.visible_function_call_lines(source)
        filtered: list[tuple[int, int]] = []
        for line, code in errors:
            if code == 307 and any(start <= line <= end for start, end in void_ranges):
                continue
            if code == 304 and (line in function_lines or line in visible_function_calls):
                continue
            filtered.append((line, code))
        return filtered

    def known_function_lines(self, source: str) -> set[int]:
        lines: set[int] = set()
        for signature in self.collect_function_signatures(source).values():
            lines.update(signature["lines"])
        return lines

    def visible_function_call_lines(self, source: str) -> set[int]:
        signatures = self.collect_function_signatures(source)
        known_names = set(signatures) | {"read", "write"}
        call_lines: set[int] = set()
        call_pattern = re.compile(r"\b([A-Za-z_]\w*)\s*\(")
        keywords = {"if", "while", "for", "switch", "return", "sizeof"}
        for index, raw_line in enumerate(source.splitlines(), start=1):
            code = self.strip_line_comment(raw_line)
            if self.is_function_header_or_prototype(code):
                continue
            for match in call_pattern.finditer(code):
                name = match.group(1)
                if name in known_names and name not in keywords:
                    call_lines.add(index)
        return call_lines

    def collect_function_signatures(self, source: str) -> dict[str, dict]:
        signatures: dict[str, dict] = {}
        header = re.compile(
            r"^\s*(?:const\s+)?(?P<rtype>int|void|float|char)\s+"
            r"(?P<name>[A-Za-z_]\w*)\s*\((?P<params>[^()]*)\)\s*(?P<end>[;{]?)"
        )
        lines = source.splitlines()
        for index, raw_line in enumerate(lines, start=1):
            code = self.strip_line_comment(raw_line).strip()
            match = header.match(code)
            if not match:
                continue
            name = match.group("name")
            if name not in signatures:
                signatures[name] = {
                    "return_type": match.group("rtype"),
                    "params": self.normalize_param_list(match.group("params")),
                    "lines": set(),
                }
            signatures[name]["lines"].add(index)
        return signatures

    def is_function_header_or_prototype(self, line: str) -> bool:
        return bool(
            re.match(
                r"^\s*(?:const\s+)?(?:int|void|float|char)\s+[A-Za-z_]\w*\s*\([^()]*\)\s*(?:[;{]?)\s*$",
                line.strip(),
            )
        )

    def normalize_param_list(self, params: str) -> tuple[str, ...]:
        params = params.strip()
        if not params or params == "void":
            return ()
        result = []
        for item in params.split(","):
            words = item.strip().split()
            result.append(words[0] if words else "")
        return tuple(result)

    def void_function_ranges_without_return(self, source: str) -> list[tuple[int, int]]:
        lines = source.splitlines()
        ranges: list[tuple[int, int]] = []
        header = re.compile(r"^\s*void\s+[A-Za-z_]\w*\s*\([^{};]*\)\s*$")
        index = 0
        while index < len(lines):
            if not header.match(self.strip_line_comment(lines[index]).strip()):
                index += 1
                continue
            open_index = index + 1
            while open_index < len(lines) and not self.strip_line_comment(lines[open_index]).strip():
                open_index += 1
            if open_index >= len(lines) or not self.strip_line_comment(lines[open_index]).strip().startswith("{"):
                index += 1
                continue
            depth = 0
            has_return = False
            end_index = open_index
            for scan in range(open_index, len(lines)):
                code = self.strip_line_comment(lines[scan])
                if re.search(r"\breturn\b", code):
                    has_return = True
                depth += code.count("{") - code.count("}")
                if depth == 0:
                    end_index = scan
                    break
            if not has_return:
                ranges.append((index + 1, end_index + 1))
            index = end_index + 1
        return ranges

    def render_report(self, diagnostics: list[Diagnostic]) -> str:
        lines = ["IDE Realtime Diagnostics", ""]
        if diagnostics:
            lines.append("发现的问题：")
            for item in diagnostics:
                lines.append(f"[{item.category}] Line {item.line}: {item.message} (code {item.code})")
            lines.append("")
            lines.append("修改建议：")
            seen: set[tuple[int, str, int]] = set()
            for item in diagnostics:
                key = (item.line, item.category, item.code)
                if key in seen:
                    continue
                seen.add(key)
                lines.append(f"- Line {item.line}: {self.fix_suggestion(item.category, item.code)}")
        else:
            lines.append("No lexical, syntax, or semantic errors.")
        lines.extend([
            "",
            "IDE Features:",
            "- 关键字/函数名高亮",
            "- 自动缩进",
            "- 实时词法、语法、语义诊断",
        ])
        return "\n".join(lines) + "\n"

    def strip_line_comment(self, line: str) -> str:
        return line.split("//", 1)[0]

    def is_comment_only_line(self, source: str, line: int) -> bool:
        lines = source.splitlines()
        if line <= 0 or line > len(lines):
            return False
        stripped = lines[line - 1].strip()
        return stripped.startswith("//") or not stripped

    def lexical_error_message(self, code: int) -> str:
        return {
            101: "非法字符",
            102: "非法单词或数字格式",
            103: "多行注释未闭合",
            104: "字符常量未闭合",
            105: "字符串常量未闭合",
        }.get(code, "词法错误")

    def syntax_error_message(self, code: int) -> str:
        return {
            201: "缺少标识符",
            202: "缺少分号 ;",
            203: "多余的右花括号 }",
            204: "函数体缺少左花括号 {",
            205: "复合语句缺少右花括号 }",
            206: "多余或不匹配的右括号 )",
            207: "条件或表达式缺少左括号 (",
            208: "缺少右括号 )",
            210: "赋值语句左侧不是合法变量",
            211: "表达式缺少操作数",
            212: "do while 语句缺少 while",
        }.get(code, "语法错误")

    def semantic_error_message(self, code: int) -> str:
        return {
            301: "变量必须先初始化或声明后使用",
            302: "变量重复定义",
            303: "常量不能被赋值",
            304: "函数重复定义或声明冲突",
            305: "函数调用参数不匹配",
            307: "非 void 函数必须返回值",
        }.get(code, "语义错误")

    def fix_suggestion(self, category: str, code: int) -> str:
        if category == "Lexical":
            return {
                101: "删除非法字符，或把中文说明放入 // 注释中。",
                102: "检查数字、字符常量或标识符拼写。",
                103: "补上 */ 结束多行注释。",
                104: "补上字符常量右侧单引号。",
                105: "补上字符串右侧双引号。",
            }.get(code, "检查该行词法拼写。")
        if category == "Syntax":
            return {
                201: "补充变量名或函数名。",
                202: "在语句末尾补充分号。",
                203: "删除多余的 } 或检查前面是否缺少 {。",
                204: "在函数声明后补充 { ... } 函数体。",
                205: "补充缺失的 }。",
                206: "检查括号配对。",
                207: "给 if/while/for 条件补充左括号。",
                208: "补充右括号 )。",
                210: "赋值号左边应为变量名。",
                211: "补充表达式缺失的操作数。",
                212: "do 语句后补充 while 条件。",
            }.get(code, "检查该行语法结构。")
        return {
            301: "先声明并初始化变量，再使用变量。",
            302: "删除重复声明，或改用新的变量名。",
            303: "不要给 const 常量重新赋值。",
            304: "检查函数名、返回类型和参数列表是否一致。",
            305: "检查函数调用实参数量和类型。",
            307: "给非 void 函数补充 return 语句。",
        }.get(code, "检查语义约束。")
