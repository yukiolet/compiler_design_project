from dataclasses import dataclass
from typing import List, Optional, Set


@dataclass
class Token:
    lexeme: str
    code: int
    line: int


@dataclass
class Node:
    kind: str   # 'var', 'literal', 'call', 'other', 'error'
    line: int


class Parser:
    TYPE_WORDS = {"int", "float", "char", "void"}
    STMT_START = {"if", "while", "for", "do", "return", "break", "continue", "{"}
    BINARY_OPS = {
        "+", "-", "*", "/", "%", "<", ">", "<=", ">=", "==", "!=", "&&", "||"
    }
    PREFIX_OPS = {"+", "-", "!"}

    def __init__(self, tokens: List[Token]):
        self.tokens = tokens
        self.pos = 0
        self.errors = []
        self.error_lines = set()
        self.last_token_line = 1 if not tokens else tokens[0].line

        # 新增：记录是否正处于“由表达式错误触发的恢复状态”
        self.recovering_from_expr_error = False
        self.expr_error_line = -1

    def current(self) -> Optional[Token]:
        if self.pos < len(self.tokens):
            return self.tokens[self.pos]
        return None

    def lookahead(self, k=1) -> Optional[Token]:
        idx = self.pos + k
        if idx < len(self.tokens):
            return self.tokens[idx]
        return None

    def advance(self) -> Optional[Token]:
        tok = self.current()
        if tok is not None:
            self.last_token_line = tok.line
            self.pos += 1
        return tok

    def match(self, lexeme: str) -> bool:
        tok = self.current()
        if tok and tok.lexeme == lexeme:
            self.advance()
            return True
        return False

    def report(self, line: int, code: int):
        if line <= 0:
            line = 1
        if line not in self.error_lines:
            self.errors.append((line, code))
            self.error_lines.add(line)

    def has_error_on_line(self, line: int) -> bool:
        return line in self.error_lines

    def is_type(self, tok: Optional[Token]) -> bool:
        return tok is not None and tok.lexeme in self.TYPE_WORDS

    def is_identifier(self, tok: Optional[Token]) -> bool:
        if tok is None:
            return False
        if tok.code == 700:
            return True
        if tok.lexeme.isidentifier() and tok.lexeme not in self.TYPE_WORDS and tok.lexeme not in {
            "if", "else", "while", "for", "do", "return", "break", "continue", "const"
        }:
            return True
        return False

    def is_literal(self, tok: Optional[Token]) -> bool:
        if tok is None:
            return False
        if tok.code in {400, 500, 600}:
            return True
        if tok.lexeme and (tok.lexeme[0].isdigit() or tok.lexeme.startswith(("'", '"'))):
            return True
        return False

    def is_expr_start(self, tok: Optional[Token]) -> bool:
        if tok is None:
            return False
        return self.is_identifier(tok) or self.is_literal(tok) or tok.lexeme in {"(", "+", "-", "!"}

    def is_stmt_boundary(self, tok: Optional[Token]) -> bool:
        if tok is None:
            return True
        return (
            tok.lexeme == "}"
            or tok.lexeme in self.STMT_START
            or tok.lexeme == "const"
            or self.is_type(tok)
        )

    def begin_expr_error_recovery(self, line: int):
        self.recovering_from_expr_error = True
        self.expr_error_line = line

    def clear_expr_error_recovery_if_new_stmt(self):
        tok = self.current()
        if tok is None:
            self.recovering_from_expr_error = False
            self.expr_error_line = -1
            return
        if self.is_stmt_boundary(tok):
            self.recovering_from_expr_error = False
            self.expr_error_line = -1

    def sync_to(self, stop_lexemes: Set[str], stop_stmt_start=True):
        while self.current() is not None:
            tok = self.current()
            if tok.lexeme in stop_lexemes:
                return
            if stop_stmt_start and self.is_stmt_boundary(tok):
                return
            self.advance()

    def recover_after_expr_error(self, error_line: int, stop_tokens: Set[str]):
        self.begin_expr_error_recovery(error_line)

        while self.current() is not None:
            tok = self.current()

            if tok.lexeme in stop_tokens:
                return

            if tok.lexeme in {";", "}", ")"}:
                return

            if self.is_stmt_boundary(tok):
                return

            # 到了下一行，不再继续吞，防止误伤后面的新语句
            if tok.line > error_line:
                return

            self.advance()

    def should_report_missing_semicolon(self, start_line: int, expr_node: Optional[Node] = None) -> bool:
        tok = self.current()

        # 关键修正：
        # 只要当前处于表达式错误恢复状态，不额外报 202
        if self.recovering_from_expr_error:
            return False

        if tok is None:
            return True

        if expr_node is not None and expr_node.kind == "error":
            return False

        if self.is_stmt_boundary(tok):
            if self.has_error_on_line(start_line):
                return False
            return True

        if tok.line > start_line and self.has_error_on_line(start_line):
            return False

        return True

    def parse(self):
        while self.current() is not None:
            tok = self.current()

            # 每轮开始前，如果已经到了真正的新语句边界，就清恢复标记
            self.clear_expr_error_recovery_if_new_stmt()

            if tok.lexeme == "}":
                self.report(tok.line, 203)
                self.advance()
                continue
            if tok.lexeme == ")":
                self.report(tok.line, 206)
                self.advance()
                continue
            self.parse_external()
        self.errors.sort()

    def parse_external(self):
        self.clear_expr_error_recovery_if_new_stmt()

        start_tok = self.current()
        if start_tok is None:
            return

        start_line = start_tok.line
        if start_tok.lexeme == "const":
            self.advance()

        if not self.is_type(self.current()):
            self.advance()
            return

        self.advance()  # type

        if not self.is_identifier(self.current()):
            self.report(start_line, 201)
            self.sync_to({";", "}", "{"}, stop_stmt_start=False)
            self.match(";")
            return

        self.advance()  # ident

        if self.match("("):
            self.parse_param_list()
            if not self.match(")"):
                self.report(start_line, 208)
            self.parse_compound(required=True, start_line=start_line)
        else:
            self.parse_decl_rest(start_line)

    def parse_param_list(self):
        if self.current() is None or self.current().lexeme == ")":
            return

        while self.current() is not None and self.current().lexeme != ")":
            tok = self.current()
            param_line = tok.line

            if tok.lexeme == "const":
                self.advance()
                tok = self.current()

            if not self.is_type(tok):
                self.sync_to({",", ")"}, stop_stmt_start=False)
                if self.match(","):
                    continue
                return

            self.advance()

            if not self.is_identifier(self.current()):
                self.report(param_line, 201)
                self.sync_to({",", ")"}, stop_stmt_start=False)
                if self.match(","):
                    continue
                return

            self.advance()

            while self.match("["):
                expr = self.parse_expression(stop_tokens={"]"})
                if expr.kind == "error":
                    self.recover_after_expr_error(param_line, {"]", ",", ")"})
                if not self.match("]"):
                    self.sync_to({",", ")"}, stop_stmt_start=False)
                    break

            if self.match(","):
                continue
            else:
                break

    def parse_decl_rest(self, start_line: int):
        self.parse_optional_initializer(start_line)

        while self.match(","):
            if not self.is_identifier(self.current()):
                self.report(start_line, 201)
                self.sync_to({";"}, stop_stmt_start=False)
                break
            self.advance()
            self.parse_optional_initializer(start_line)

        if not self.match(";"):
            if self.should_report_missing_semicolon(start_line):
                self.report(start_line, 202)

    def parse_optional_initializer(self, start_line: int):
        if self.match("="):
            expr = self.parse_expression(stop_tokens={",", ";"})
            if expr.kind == "error":
                self.recover_after_expr_error(start_line, {",", ";"})

    def parse_compound(self, required: bool, start_line: int):
        if not self.match("{"):
            if required:
                self.report(start_line, 204)
            while self.current() is not None and self.current().lexeme != "}":
                self.parse_statement()
            return

        block_last_line = start_line
        while self.current() is not None and self.current().lexeme != "}":
            block_last_line = self.current().line
            self.parse_statement()

        if self.match("}"):
            return

        self.report(block_last_line, 205)

    def parse_statement(self):
        self.clear_expr_error_recovery_if_new_stmt()

        tok = self.current()
        if tok is None:
            return

        if tok.lexeme == "}":
            return

        if tok.lexeme == "{":
            self.parse_compound(required=False, start_line=tok.line)
            return

        if tok.lexeme == ")":
            self.report(tok.line, 206)
            self.advance()
            return

        if tok.lexeme == "if":
            self.parse_if()
            return
        if tok.lexeme == "while":
            self.parse_while()
            return
        if tok.lexeme == "for":
            self.parse_for()
            return
        if tok.lexeme == "do":
            self.parse_do_while()
            return
        if tok.lexeme == "return":
            self.parse_return()
            return
        if tok.lexeme in {"break", "continue"}:
            line = tok.line
            self.advance()
            if not self.match(";"):
                if self.should_report_missing_semicolon(line):
                    self.report(line, 202)
            return
        if tok.lexeme == "const" or self.is_type(tok):
            self.parse_local_decl()
            return

        self.parse_expr_stmt()

    def parse_local_decl(self):
        start_tok = self.current()
        start_line = start_tok.line

        if start_tok.lexeme == "const":
            self.advance()

        if not self.is_type(self.current()):
            self.sync_to({";"}, stop_stmt_start=False)
            self.match(";")
            return

        self.advance()

        if not self.is_identifier(self.current()):
            self.report(start_line, 201)
            self.sync_to({";"}, stop_stmt_start=False)
            self.match(";")
            return

        self.advance()
        self.parse_decl_rest(start_line)

    def parse_if(self):
        start_line = self.current().line
        self.advance()

        if not self.match("("):
            self.report(start_line, 207)
            expr = self.parse_expression(stop_tokens={")", ";", "{"})
            if expr.kind == "error":
                self.recover_after_expr_error(start_line, {")", ";", "{"})
        else:
            expr = self.parse_expression(stop_tokens={")"})
            if expr.kind == "error":
                self.recover_after_expr_error(start_line, {")"})

        if not self.match(")"):
            self.report(start_line, 208)

        self.parse_statement()

        if self.current() is not None and self.current().lexeme == "else":
            self.advance()
            self.parse_statement()

    def parse_while(self):
        start_line = self.current().line
        self.advance()

        if not self.match("("):
            self.report(start_line, 207)
            expr = self.parse_expression(stop_tokens={")", ";", "{"})
            if expr.kind == "error":
                self.recover_after_expr_error(start_line, {")", ";", "{"})
        else:
            expr = self.parse_expression(stop_tokens={")"})
            if expr.kind == "error":
                self.recover_after_expr_error(start_line, {")"})

        if not self.match(")"):
            self.report(start_line, 208)

        self.parse_statement()

    def parse_for(self):
        start_line = self.current().line
        self.advance()

        if not self.match("("):
            self.report(start_line, 207)
            self.parse_statement()
            return

        if self.current() is not None and self.current().lexeme != ";":
            expr = self.parse_expression(stop_tokens={";"})
            if expr.kind == "error":
                self.recover_after_expr_error(start_line, {";"})
        if not self.match(";"):
            if self.should_report_missing_semicolon(start_line):
                self.report(start_line, 202)

        if self.current() is not None and self.current().lexeme != ";":
            expr = self.parse_expression(stop_tokens={";"})
            if expr.kind == "error":
                self.recover_after_expr_error(start_line, {";"})
        if not self.match(";"):
            if self.should_report_missing_semicolon(start_line):
                self.report(start_line, 202)

        if self.current() is not None and self.current().lexeme != ")":
            expr = self.parse_expression(stop_tokens={")"})
            if expr.kind == "error":
                self.recover_after_expr_error(start_line, {")"})
        if not self.match(")"):
            self.report(start_line, 208)

        self.parse_statement()

    def parse_do_while(self):
        start_line = self.current().line
        self.advance()

        self.parse_statement()

        if self.current() is None or self.current().lexeme != "while":
            self.report(start_line, 212)
            self.sync_to({";", "}"}, stop_stmt_start=False)
            self.match(";")
            return

        self.advance()

        if not self.match("("):
            self.report(start_line, 207)
            expr = self.parse_expression(stop_tokens={")", ";"})
            if expr.kind == "error":
                self.recover_after_expr_error(start_line, {")", ";"})
        else:
            expr = self.parse_expression(stop_tokens={")"})
            if expr.kind == "error":
                self.recover_after_expr_error(start_line, {")"})

        if not self.match(")"):
            self.report(start_line, 208)

        if not self.match(";"):
            if self.should_report_missing_semicolon(start_line):
                self.report(start_line, 202)

    def parse_return(self):
        start_line = self.current().line
        self.advance()

        expr_node = None
        if self.current() is not None and self.current().lexeme != ";":
            expr_node = self.parse_expression(stop_tokens={";"})
            if expr_node.kind == "error":
                self.recover_after_expr_error(start_line, {";"})

        if not self.match(";"):
            if self.should_report_missing_semicolon(start_line, expr_node):
                self.report(start_line, 202)

    def parse_expr_stmt(self):
        start_line = self.current().line if self.current() else self.last_token_line

        if self.match(";"):
            return

        expr_node = self.parse_expression(stop_tokens={";"})

        if expr_node.kind == "error":
            self.recover_after_expr_error(start_line, {";"})

        if self.match(";"):
            return

        if self.should_report_missing_semicolon(start_line, expr_node):
            self.report(start_line, 202)

    def parse_expression(self, stop_tokens: Set[str]) -> Node:
        return self.parse_assignment(stop_tokens)

    def parse_assignment(self, stop_tokens: Set[str]) -> Node:
        left = self.parse_logical_or(stop_tokens | {"="})

        if self.current() is not None and self.current().lexeme == "=":
            eq_tok = self.current()
            self.advance()

            if left.kind != "var":
                self.report(left.line, 210)

            if self.current() is None or self.current().lexeme in stop_tokens or self.current().lexeme == ")":
                self.report(eq_tok.line, 211)
                return Node("error", eq_tok.line)

            right = self.parse_assignment(stop_tokens)
            if right.kind == "error":
                return Node("error", eq_tok.line)
            return Node("other", left.line)

        return left

    def parse_logical_or(self, stop_tokens: Set[str]) -> Node:
        node = self.parse_logical_and(stop_tokens | {"||"})
        while self.current() is not None and self.current().lexeme == "||":
            op = self.current()
            self.advance()
            if self.current() is None or self.current().lexeme in stop_tokens or self.current().lexeme == ")":
                self.report(op.line, 211)
                return Node("error", op.line)
            right = self.parse_logical_and(stop_tokens | {"||"})
            if node.kind == "error" or right.kind == "error":
                return Node("error", op.line)
            node = Node("other", node.line)
        return node

    def parse_logical_and(self, stop_tokens: Set[str]) -> Node:
        node = self.parse_equality(stop_tokens | {"&&"})
        while self.current() is not None and self.current().lexeme == "&&":
            op = self.current()
            self.advance()
            if self.current() is None or self.current().lexeme in stop_tokens or self.current().lexeme == ")":
                self.report(op.line, 211)
                return Node("error", op.line)
            right = self.parse_equality(stop_tokens | {"&&"})
            if node.kind == "error" or right.kind == "error":
                return Node("error", op.line)
            node = Node("other", node.line)
        return node

    def parse_equality(self, stop_tokens: Set[str]) -> Node:
        node = self.parse_relational(stop_tokens | {"==", "!="})
        while self.current() is not None and self.current().lexeme in {"==", "!="}:
            op = self.current()
            self.advance()
            if self.current() is None or self.current().lexeme in stop_tokens or self.current().lexeme == ")":
                self.report(op.line, 211)
                return Node("error", op.line)
            right = self.parse_relational(stop_tokens | {"==", "!="})
            if node.kind == "error" or right.kind == "error":
                return Node("error", op.line)
            node = Node("other", node.line)
        return node

    def parse_relational(self, stop_tokens: Set[str]) -> Node:
        node = self.parse_additive(stop_tokens | {"<", ">", "<=", ">="})
        while self.current() is not None and self.current().lexeme in {"<", ">", "<=", ">="}:
            op = self.current()
            self.advance()
            if self.current() is None or self.current().lexeme in stop_tokens or self.current().lexeme == ")":
                self.report(op.line, 211)
                return Node("error", op.line)
            right = self.parse_additive(stop_tokens | {"<", ">", "<=", ">="})
            if node.kind == "error" or right.kind == "error":
                return Node("error", op.line)
            node = Node("other", node.line)
        return node

    def parse_additive(self, stop_tokens: Set[str]) -> Node:
        node = self.parse_multiplicative(stop_tokens | {"+", "-"})
        while self.current() is not None and self.current().lexeme in {"+", "-"}:
            op = self.current()
            self.advance()
            if self.current() is None or self.current().lexeme in stop_tokens or self.current().lexeme == ")":
                self.report(op.line, 211)
                return Node("error", op.line)
            right = self.parse_multiplicative(stop_tokens | {"+", "-"})
            if node.kind == "error" or right.kind == "error":
                return Node("error", op.line)
            node = Node("other", node.line)
        return node

    def parse_multiplicative(self, stop_tokens: Set[str]) -> Node:
        node = self.parse_unary(stop_tokens | {"*", "/", "%"})
        while self.current() is not None and self.current().lexeme in {"*", "/", "%"}:
            op = self.current()
            self.advance()
            if self.current() is None or self.current().lexeme in stop_tokens or self.current().lexeme == ")":
                self.report(op.line, 211)
                return Node("error", op.line)
            right = self.parse_unary(stop_tokens | {"*", "/", "%"})
            if node.kind == "error" or right.kind == "error":
                return Node("error", op.line)
            node = Node("other", node.line)
        return node

    def parse_unary(self, stop_tokens: Set[str]) -> Node:
        tok = self.current()
        if tok is None:
            return Node("error", self.last_token_line)

        if tok.lexeme in self.PREFIX_OPS:
            op_line = tok.line
            self.advance()
            if self.current() is None or self.current().lexeme in stop_tokens or self.current().lexeme == ")":
                self.report(op_line, 211)
                return Node("error", op_line)
            return self.parse_unary(stop_tokens)

        return self.parse_primary(stop_tokens)

    def parse_primary(self, stop_tokens: Set[str]) -> Node:
        tok = self.current()
        if tok is None:
            return Node("error", self.last_token_line)

        if self.is_identifier(tok):
            ident_tok = tok
            self.advance()

            if self.match("("):
                if self.current() is not None and self.current().lexeme != ")":
                    while True:
                        arg = self.parse_expression(stop_tokens={",", ")"})
                        if arg.kind == "error":
                            self.recover_after_expr_error(ident_tok.line, {",", ")"})
                        if self.match(","):
                            continue
                        break

                if not self.match(")"):
                    self.report(ident_tok.line, 208)
                    return Node("error", ident_tok.line)

                return Node("call", ident_tok.line)

            return Node("var", ident_tok.line)

        if self.is_literal(tok):
            self.advance()
            return Node("literal", tok.line)

        if tok.lexeme == "(":
            l_line = tok.line
            self.advance()
            inner = self.parse_expression(stop_tokens={")"})
            if inner.kind == "error":
                self.recover_after_expr_error(l_line, {")"})
            if not self.match(")"):
                self.report(l_line, 208)
                return Node("error", l_line)
            if inner.kind == "error":
                return Node("error", l_line)
            return Node("other", l_line)

        if tok.lexeme == ")":
            return Node("error", tok.line)

        if tok.lexeme in self.BINARY_OPS:
            self.report(tok.line, 211)
            self.advance()
            return Node("error", tok.line)

        self.advance()
        return Node("error", tok.line)


def read_tokens(filename: str) -> List[Token]:
    tokens = []
    with open(filename, "r", encoding="utf-8") as f:
        for raw in f:
            line = raw.strip()
            if not line:
                continue
            parts = line.split()
            if len(parts) < 3:
                continue
            lexeme = parts[0]
            code = int(parts[-2])
            lineno = int(parts[-1])
            tokens.append(Token(lexeme, code, lineno))
    return tokens


def main():
    tokens = read_tokens("input.txt")
    parser = Parser(tokens)
    parser.parse()

    with open("output.txt", "w", encoding="utf-8") as f:
        for line, code in parser.errors:
            f.write(f"{line} {code}\n")


if __name__ == "__main__":
    main()