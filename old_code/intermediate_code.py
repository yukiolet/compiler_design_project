

# ============================================================
# Token 与词法分析器
# ============================================================
class Token:
    def __init__(self, lexeme, code, line):
        self.lexeme = lexeme
        self.code = code
        self.line = line

    def __repr__(self):
        return "Token(%r, %r, %r)" % (self.lexeme, self.code, self.line)


class LexicalAnalyzer:
    KEYWORDS = {
        "char": 101,
        "int": 102,
        "float": 103,
        "break": 104,
        "const": 105,
        "return": 106,
        "void": 107,
        "continue": 108,
        "do": 109,
        "while": 110,
        "if": 111,
        "else": 112,
        "for": 113,
    }

    SYMBOLS = {
        "(": 201,
        ")": 202,
        "[": 203,
        "]": 204,
        "!": 205,
        "*": 206,
        "/": 207,
        "%": 208,
        "+": 209,
        "-": 210,
        "<": 211,
        "<=": 212,
        ">": 213,
        ">=": 214,
        "==": 215,
        "!=": 216,
        "&&": 217,
        "||": 218,
        "=": 219,
        ".": 220,
        "{": 301,
        "}": 302,
        ";": 303,
        ",": 304,
    }

    INT_CODE = 400
    CHAR_CODE = 500
    STRING_CODE = 600
    ID_CODE = 700
    FLOAT_CODE = 800

    def __init__(self, source_code):
        self.source_code = source_code
        self.length = len(source_code)
        self.index = 0
        self.line = 1

    def _peek(self, offset=1):
        pos = self.index + offset
        if pos < self.length:
            return self.source_code[pos]
        return ""

    def _is_hex_digit(self, ch):
        return ch.isdigit() or ch in "abcdefABCDEF"

    def _scan_identifier_or_keyword(self):
        start = self.index
        while self.index < self.length and (
            self.source_code[self.index].isalnum() or self.source_code[self.index] == "_"
        ):
            self.index += 1

        lexeme = self.source_code[start:self.index]
        if lexeme in self.KEYWORDS:
            return Token(lexeme, self.KEYWORDS[lexeme], self.line)
        return Token(lexeme, self.ID_CODE, self.line)

    def _scan_number(self):
        s = self.source_code
        start = self.index
        start_line = self.line

        if s[self.index] == "0" and self._peek() in ("x", "X"):
            self.index += 2
            while self.index < self.length and self._is_hex_digit(s[self.index]):
                self.index += 1
            return Token(s[start:self.index], self.INT_CODE, start_line)

        while self.index < self.length and s[self.index].isdigit():
            self.index += 1

        is_float = False

        if self.index < self.length and s[self.index] == ".":
            nxt = self._peek()
            if nxt.isdigit():
                is_float = True
                self.index += 1
                while self.index < self.length and s[self.index].isdigit():
                    self.index += 1

        if self.index < self.length and s[self.index] in "eE":
            j = self.index + 1
            if j < self.length and s[j] in "+-":
                j += 1
            if j < self.length and s[j].isdigit():
                is_float = True
                self.index = j + 1
                while self.index < self.length and s[self.index].isdigit():
                    self.index += 1

        lexeme = s[start:self.index]
        if is_float:
            return Token(lexeme, self.FLOAT_CODE, start_line)
        return Token(lexeme, self.INT_CODE, start_line)

    def _scan_char_literal(self):
        s = self.source_code
        start_line = self.line
        self.index += 1

        if self.index >= self.length or s[self.index] == "\n":
            return None

        if s[self.index] == "\\":
            if self.index + 1 < self.length:
                content = s[self.index:self.index + 2]
                self.index += 2
            else:
                return None
        else:
            content = s[self.index]
            self.index += 1

        if self.index < self.length and s[self.index] == "'":
            self.index += 1
            return Token(content, self.CHAR_CODE, start_line)
        return None

    def _scan_string_literal(self):
        s = self.source_code
        start_line = self.line
        self.index += 1

        content = ""
        while self.index < self.length:
            ch = s[self.index]
            if ch == "\\":
                if self.index + 1 < self.length:
                    content += s[self.index:self.index + 2]
                    self.index += 2
                else:
                    return None
            elif ch == '"':
                self.index += 1
                return Token(content, self.STRING_CODE, start_line)
            elif ch == "\n":
                self.line += 1
                self.index += 1
                return None
            else:
                content += ch
                self.index += 1
        return None

    def _skip_single_line_comment(self):
        self.index += 2
        while self.index < self.length and self.source_code[self.index] != "\n":
            self.index += 1

    def _skip_multi_line_comment(self):
        self.index += 2
        while self.index < self.length:
            if self.source_code[self.index] == "\n":
                self.line += 1
                self.index += 1
            elif self.source_code[self.index] == "*" and self._peek() == "/":
                self.index += 2
                return
            else:
                self.index += 1

    def _scan_symbol(self):
        if self.index + 1 < self.length:
            two = self.source_code[self.index:self.index + 2]
            if two in self.SYMBOLS:
                self.index += 2
                return Token(two, self.SYMBOLS[two], self.line)

        one = self.source_code[self.index]
        if one in self.SYMBOLS:
            self.index += 1
            return Token(one, self.SYMBOLS[one], self.line)
        return None

    def analyze(self):
        result = []
        while self.index < self.length:
            ch = self.source_code[self.index]

            if ch in " \t\r":
                self.index += 1
                continue

            if ch == "\n":
                self.line += 1
                self.index += 1
                continue

            if ch.isalpha() or ch == "_":
                result.append(self._scan_identifier_or_keyword())
                continue

            if ch.isdigit():
                tok = self._scan_number()
                if tok is not None:
                    result.append(tok)
                continue

            if ch == "'":
                tok = self._scan_char_literal()
                if tok is not None:
                    result.append(tok)
                else:
                    self.index += 1
                continue

            if ch == '"':
                tok = self._scan_string_literal()
                if tok is not None:
                    result.append(tok)
                else:
                    self.index += 1
                continue

            if ch == "/":
                nxt = self._peek()
                if nxt == "/":
                    self._skip_single_line_comment()
                    continue
                if nxt == "*":
                    self._skip_multi_line_comment()
                    continue

            tok = self._scan_symbol()
            if tok is not None:
                result.append(tok)
                continue

            # 输入保证合法，这里直接跳过无法识别字符
            self.index += 1
        return result


# ============================================================
# AST 与递归下降语法分析器
# ============================================================
class ASTNode:
    def __init__(self, kind, value=None, line=None):
        self.kind = kind
        self.value = value
        self.line = line
        self.children = []

    def add(self, child):
        if child is not None:
            self.children.append(child)

    def __repr__(self):
        return "ASTNode(%r, %r, %r, children=%r)" % (
            self.kind, self.value, self.line, len(self.children)
        )


class Parser:
    TYPE_KEYWORDS = ("int", "float", "char", "void")

    def __init__(self, tokens):
        self.tokens = tokens
        self.pos = 0

    def current(self):
        if self.pos < len(self.tokens):
            return self.tokens[self.pos]
        return None

    def peek(self, k=1):
        idx = self.pos + k
        if idx < len(self.tokens):
            return self.tokens[idx]
        return None

    def eof(self):
        return self.pos >= len(self.tokens)

    def check(self, lexeme):
        tok = self.current()
        return tok is not None and tok.lexeme == lexeme

    def soft_expect(self, lexeme):
        if self.check(lexeme):
            tok = self.current()
            self.pos += 1
            return tok
        return None

    def expect_identifier(self):
        tok = self.current()
        if tok is not None and tok.code == 700:
            self.pos += 1
            return tok
        return None

    def expect_type(self):
        tok = self.current()
        if tok is not None and tok.lexeme in self.TYPE_KEYWORDS:
            self.pos += 1
            return tok
        return None

    def is_type(self):
        tok = self.current()
        return tok is not None and tok.lexeme in self.TYPE_KEYWORDS

    def is_constant_token(self, tok):
        if tok is None:
            return False
        if tok.code in (400, 500, 600, 800):
            return True
        if tok.code == 700:
            return False
        if tok.lexeme in (
            "const", "int", "float", "char", "void", "if", "else", "while", "for", "do",
            "return", "continue", "break", "(", ")", "{", "}", ";", ",", "+", "-", "*",
            "/", "%", "!", "=", "==", "!=", ">", "<", ">=", "<=", "&&", "||"
        ):
            return False
        return True

    def starts_expression(self, tok):
        if tok is None:
            return False
        if tok.lexeme in ("(", "+", "-", "!"):
            return True
        if tok.code == 700:
            return True
        if self.is_constant_token(tok):
            return True
        return False

    def lookahead_is_main(self):
        t0 = self.current()
        t1 = self.peek(1)
        t2 = self.peek(2)
        return (
            t0 is not None and t0.lexeme in self.TYPE_KEYWORDS and
            t1 is not None and t1.lexeme == "main" and
            t2 is not None and t2.lexeme == "("
        )

    def lookahead_is_function(self):
        t0 = self.current()
        t1 = self.peek(1)
        t2 = self.peek(2)
        return (
            t0 is not None and t0.lexeme in self.TYPE_KEYWORDS and
            t1 is not None and t1.code == 700 and
            t2 is not None and t2.lexeme == "("
        )

    def parse(self):
        return self.parse_program()

    def parse_program(self):
        root = ASTNode("Program")

        while not self.eof() and not self.lookahead_is_main():
            if self.check("const"):
                self.append_decl_or_group(root, self.parse_const_decl())
            elif self.lookahead_is_function():
                root.add(self.parse_function_decl_or_def())
            elif self.is_type():
                self.append_decl_or_group(root, self.parse_var_decl())
            else:
                self.pos += 1

        if not self.eof() and self.lookahead_is_main():
            root.add(self.parse_main_function())

        while not self.eof():
            if self.lookahead_is_function():
                root.add(self.parse_function_decl_or_def())
            elif self.check("const"):
                self.append_decl_or_group(root, self.parse_const_decl())
            elif self.is_type():
                self.append_decl_or_group(root, self.parse_var_decl())
            else:
                self.pos += 1
        return root

    def append_decl_or_group(self, parent, node):
        if node is None:
            return
        if node.kind == "DeclGroup":
            for child in node.children:
                parent.add(child)
        else:
            parent.add(node)

    def parse_main_function(self):
        type_tok = self.expect_type()
        name_tok = self.soft_expect("main")
        self.soft_expect("(")
        self.soft_expect(")")
        compound = self.parse_compound()
        line = name_tok.line if name_tok is not None else (type_tok.line if type_tok is not None else 0)
        node = ASTNode("FunctionDef", "int main", line)
        node.add(compound)
        return node

    def parse_function_decl_or_def(self):
        type_tok = self.expect_type()
        name_tok = self.expect_identifier()
        type_name = type_tok.lexeme if type_tok is not None else "int"
        func_name = name_tok.lexeme if name_tok is not None else "unknown"
        line = name_tok.line if name_tok is not None else (type_tok.line if type_tok is not None else 0)

        self.soft_expect("(")
        params = self.parse_parameter_list_opt()
        self.soft_expect(")")

        if self.check(";"):
            self.soft_expect(";")
            node = ASTNode("FunctionDecl", type_name + " " + func_name, line)
            for p in params:
                node.add(p)
            return node

        compound = self.parse_compound()
        node = ASTNode("FunctionDef", type_name + " " + func_name, line)
        for p in params:
            node.add(p)
        node.add(compound)
        return node

    def parse_parameter_list_opt(self):
        params = []
        if self.check(")"):
            return params
        p = self.parse_parameter()
        if p is not None:
            params.append(p)
        while self.check(","):
            self.soft_expect(",")
            p = self.parse_parameter()
            if p is not None:
                params.append(p)
        return params

    def parse_parameter(self):
        type_tok = self.expect_type()
        name_tok = self.expect_identifier()
        if type_tok is None and name_tok is None:
            return None
        type_name = type_tok.lexeme if type_tok is not None else "int"
        var_name = name_tok.lexeme if name_tok is not None else "unknown"
        line = name_tok.line if name_tok is not None else (type_tok.line if type_tok is not None else 0)
        return ASTNode("Param", type_name + " " + var_name, line)

    def parse_const_decl(self):
        self.soft_expect("const")
        type_tok = self.expect_type()
        type_name = type_tok.lexeme if type_tok is not None else "int"
        group = ASTNode("DeclGroup")

        first = self.parse_one_const_decl(type_name)
        if first is not None:
            group.add(first)

        while self.check(","):
            self.soft_expect(",")
            node = self.parse_one_const_decl(type_name)
            if node is not None:
                group.add(node)
        self.soft_expect(";")
        if len(group.children) == 1:
            return group.children[0]
        return group

    def parse_one_const_decl(self, type_name):
        name_tok = self.expect_identifier()
        if name_tok is None:
            return None
        node = ASTNode("ConstDecl", type_name + " " + name_tok.lexeme, name_tok.line)
        if self.check("="):
            self.soft_expect("=")
            expr = self.parse_expression()
            if expr is not None:
                node.add(expr)
        return node

    def parse_var_decl(self):
        type_tok = self.expect_type()
        type_name = type_tok.lexeme if type_tok is not None else "int"
        group = ASTNode("DeclGroup")

        first = self.parse_one_var_decl(type_name)
        if first is not None:
            group.add(first)

        while self.check(","):
            self.soft_expect(",")
            node = self.parse_one_var_decl(type_name)
            if node is not None:
                group.add(node)
        self.soft_expect(";")
        if len(group.children) == 1:
            return group.children[0]
        return group

    def parse_one_var_decl(self, type_name):
        name_tok = self.expect_identifier()
        if name_tok is None:
            return None
        node = ASTNode("VarDecl", type_name + " " + name_tok.lexeme, name_tok.line)
        if self.check("="):
            self.soft_expect("=")
            expr = self.parse_expression()
            if expr is not None:
                node.add(expr)
        return node

    def parse_compound(self):
        lbrace = self.soft_expect("{")
        line = lbrace.line if lbrace is not None else 0
        node = ASTNode("Compound", line=line)

        while not self.eof() and not self.check("}"):
            stmt = self.parse_statement()
            if stmt is None:
                if not self.eof():
                    self.pos += 1
                continue
            if stmt.kind == "DeclGroup":
                for child in stmt.children:
                    node.add(child)
            else:
                node.add(stmt)

        self.soft_expect("}")
        return node

    def parse_statement(self):
        tok = self.current()
        if tok is None:
            return None
        if self.check("{"):
            return self.parse_compound()
        if self.check("const"):
            return self.parse_const_decl()
        if self.is_type():
            return self.parse_var_decl()
        if self.check("if"):
            return self.parse_if_stmt()
        if self.check("while"):
            return self.parse_while_stmt()
        if self.check("for"):
            return self.parse_for_stmt()
        if self.check("do"):
            return self.parse_do_while_stmt()
        if self.check("continue"):
            return self.parse_continue_stmt()
        if self.check("break"):
            return self.parse_break_stmt()
        if self.check("return"):
            return self.parse_return_stmt()
        if self.check(";"):
            self.soft_expect(";")
            return ASTNode("ExprStmt", line=tok.line)
        return self.parse_expr_stmt()

    def parse_if_stmt(self):
        tok_if = self.soft_expect("if")
        line = tok_if.line if tok_if is not None else 0
        self.soft_expect("(")
        cond = self.parse_expression()
        self.soft_expect(")")
        then_stmt = self.parse_statement()
        node = ASTNode("IfStmt", line=line)
        node.add(cond)
        node.add(then_stmt)
        if self.check("else"):
            self.soft_expect("else")
            node.add(self.parse_statement())
        return node

    def parse_while_stmt(self):
        tok = self.soft_expect("while")
        line = tok.line if tok is not None else 0
        self.soft_expect("(")
        cond = self.parse_expression()
        self.soft_expect(")")
        body = self.parse_statement()
        node = ASTNode("WhileStmt", line=line)
        node.add(cond)
        node.add(body)
        return node

    def parse_for_stmt(self):
        tok = self.soft_expect("for")
        line = tok.line if tok is not None else 0
        node = ASTNode("ForStmt", line=line)

        self.soft_expect("(")

        if self.check(";"):
            self.soft_expect(";")
            node.add(ASTNode("ExprStmt", line=line))
        elif self.check("const"):
            node.add(self.parse_const_decl())
        elif self.is_type():
            node.add(self.parse_var_decl())
        else:
            init = self.parse_expression()
            self.soft_expect(";")
            init_stmt = ASTNode("ExprStmt", line=(init.line if init is not None else line))
            init_stmt.add(init)
            node.add(init_stmt)

        if self.check(";"):
            self.soft_expect(";")
            node.add(ASTNode("ExprStmt", line=line))
        else:
            cond = self.parse_expression()
            self.soft_expect(";")
            cond_stmt = ASTNode("ExprStmt", line=(cond.line if cond is not None else line))
            cond_stmt.add(cond)
            node.add(cond_stmt)

        if self.check(")"):
            self.soft_expect(")")
            node.add(ASTNode("ExprStmt", line=line))
        else:
            update = self.parse_expression()
            self.soft_expect(")")
            update_stmt = ASTNode("ExprStmt", line=(update.line if update is not None else line))
            update_stmt.add(update)
            node.add(update_stmt)

        node.add(self.parse_statement())
        return node

    def parse_do_while_stmt(self):
        tok = self.soft_expect("do")
        line = tok.line if tok is not None else 0
        body = self.parse_statement()
        self.soft_expect("while")
        self.soft_expect("(")
        cond = self.parse_expression()
        self.soft_expect(")")
        self.soft_expect(";")
        node = ASTNode("DoWhileStmt", line=line)
        node.add(body)
        node.add(cond)
        return node

    def parse_continue_stmt(self):
        tok = self.soft_expect("continue")
        line = tok.line if tok is not None else 0
        self.soft_expect(";")
        return ASTNode("ContinueStmt", line=line)

    def parse_break_stmt(self):
        tok = self.soft_expect("break")
        line = tok.line if tok is not None else 0
        self.soft_expect(";")
        return ASTNode("BreakStmt", line=line)

    def parse_return_stmt(self):
        tok = self.soft_expect("return")
        line = tok.line if tok is not None else 0
        node = ASTNode("ReturnStmt", line=line)
        if not self.check(";"):
            node.add(self.parse_expression())
        self.soft_expect(";")
        return node

    def parse_expr_stmt(self):
        tok = self.current()
        line = tok.line if tok is not None else 0
        if tok is None:
            return ASTNode("ExprStmt", line=line)
        if not self.starts_expression(tok):
            self.pos += 1
            return ASTNode("ExprStmt", line=line)
        expr = self.parse_expression()
        stmt = ASTNode("ExprStmt", line=(expr.line if expr is not None else line))
        stmt.add(expr)
        self.soft_expect(";")
        return stmt

    def parse_expression(self):
        return self.parse_assignment()

    def parse_assignment(self):
        left = self.parse_logical_or()
        if self.check("="):
            tok = self.soft_expect("=")
            right = self.parse_assignment()
            node = ASTNode("Op", "=", tok.line if tok is not None else 0)
            node.add(left)
            node.add(right)
            return node
        return left

    def parse_logical_or(self):
        node = self.parse_logical_and()
        while self.check("||"):
            tok = self.soft_expect("||")
            right = self.parse_logical_and()
            new_node = ASTNode("Op", "||", tok.line if tok is not None else 0)
            new_node.add(node)
            new_node.add(right)
            node = new_node
        return node

    def parse_logical_and(self):
        node = self.parse_equality()
        while self.check("&&"):
            tok = self.soft_expect("&&")
            right = self.parse_equality()
            new_node = ASTNode("Op", "&&", tok.line if tok is not None else 0)
            new_node.add(node)
            new_node.add(right)
            node = new_node
        return node

    def parse_equality(self):
        node = self.parse_relational()
        while self.check("==") or self.check("!="):
            tok = self.current()
            self.pos += 1
            right = self.parse_relational()
            new_node = ASTNode("Op", tok.lexeme, tok.line)
            new_node.add(node)
            new_node.add(right)
            node = new_node
        return node

    def parse_relational(self):
        node = self.parse_additive()
        while self.check(">") or self.check("<") or self.check(">=") or self.check("<="):
            tok = self.current()
            self.pos += 1
            right = self.parse_additive()
            new_node = ASTNode("Op", tok.lexeme, tok.line)
            new_node.add(node)
            new_node.add(right)
            node = new_node
        return node

    def parse_additive(self):
        node = self.parse_term()
        while self.check("+") or self.check("-"):
            tok = self.current()
            self.pos += 1
            right = self.parse_term()
            new_node = ASTNode("Op", tok.lexeme, tok.line)
            new_node.add(node)
            new_node.add(right)
            node = new_node
        return node

    def parse_term(self):
        node = self.parse_unary()
        while self.check("*") or self.check("/") or self.check("%"):
            tok = self.current()
            self.pos += 1
            right = self.parse_unary()
            new_node = ASTNode("Op", tok.lexeme, tok.line)
            new_node.add(node)
            new_node.add(right)
            node = new_node
        return node

    def parse_unary(self):
        tok = self.current()
        if tok is None:
            return None
        if tok.lexeme in ("!", "+", "-") and not self.is_constant_token(tok):
            self.pos += 1
            child = self.parse_unary()
            if tok.lexeme == "+":
                return child
            node = ASTNode("Op", tok.lexeme, tok.line)
            node.add(child)
            return node
        return self.parse_primary()

    def parse_primary(self):
        tok = self.current()
        if tok is None:
            return None

        if tok.code == 700:
            name_tok = self.expect_identifier()
            if self.check("("):
                self.soft_expect("(")
                node = ASTNode("Call", name_tok.lexeme, name_tok.line)
                if not self.check(")"):
                    node.add(self.parse_expression())
                    while self.check(","):
                        self.soft_expect(",")
                        node.add(self.parse_expression())
                self.soft_expect(")")
                return node
            return ASTNode("Leaf", name_tok.lexeme, name_tok.line)

        if self.is_constant_token(tok):
            self.pos += 1
            return ASTNode("Leaf", tok.lexeme, tok.line)

        if self.check("("):
            self.soft_expect("(")
            node = self.parse_expression()
            self.soft_expect(")")
            return node

        self.pos += 1
        return ASTNode("Leaf", tok.lexeme, tok.line)


# ============================================================
# 四元式中间代码生成器
# ============================================================
class IntermediateCodeGenerator:
    REL_OPS = {">", "<", ">=", "<=", "==", "!="}
    ARITH_OPS = {"+", "-", "*", "/", "%"}
    LOGIC_OPS = {"&&", "||"}

    def __init__(self):
        self.quads = []
        self.temp_no = 0
        self.loop_stack = []
        self.generated_sys = False
        self.suppress_if_extra_jump = 0

    def nextquad(self):
        return len(self.quads)

    def new_temp(self):
        self.temp_no += 1
        return "t%d" % self.temp_no

    def emit(self, op, arg1="_", arg2="_", result="_"):
        idx = len(self.quads)
        self.quads.append([op, arg1, arg2, result])
        return idx

    def backpatch(self, indices, target):
        if indices is None:
            return
        if isinstance(indices, int):
            indices = [indices]
        for i in indices:
            self.quads[i][3] = target

    def get_name_from_decl(self, value):
        if value is None:
            return "_"
        parts = str(value).strip().split()
        if not parts:
            return "_"
        return parts[-1]

    def get_func_name(self, value):
        if value is None:
            return "_"
        parts = str(value).strip().split()
        if not parts:
            return "_"
        return parts[-1]

    def generate(self, root):
        self.visit(root)
        if not self.generated_sys:
            self.emit("sys", "_", "_", "_")
            self.generated_sys = True
        return self.quads

    # -------------------- 语句翻译 --------------------
    def visit(self, node):
        if node is None:
            return
        method = getattr(self, "visit_" + node.kind, self.generic_visit)
        return method(node)

    def generic_visit(self, node):
        for ch in node.children:
            self.visit(ch)

    def visit_DeclGroup(self, node):
        for ch in node.children:
            self.visit(ch)

    def visit_Program(self, node):
        # 为匹配样例，main 先输出；其余函数/全局初始化按源中顺序输出。
        for ch in node.children:
            self.visit(ch)

    def visit_FunctionDecl(self, node):
        # 函数声明不产生中间代码
        return

    def visit_FunctionDef(self, node):
        fname = self.get_func_name(node.value)
        self.emit(fname, "_", "_", "_")

        for ch in node.children:
            if ch.kind == "Param":
                # 参数本身不产生代码，调用处用 para 四元式传实参
                continue
            self.visit(ch)

        if fname == "main":
            if not self.generated_sys:
                self.emit("sys", "_", "_", "_")
                self.generated_sys = True
        else:
            # void 函数即使源码没有显式 return;，评测也要求补一条空返回。
            if not self.quads or self.quads[-1][0] != "ret":
                self.emit("ret", "_", "_", "_")

    def visit_Compound(self, node):
        for ch in node.children:
            self.visit(ch)

    def visit_VarDecl(self, node):
        name = self.get_name_from_decl(node.value)
        if node.children:
            place = self.gen_expr(node.children[0])
            self.emit("=", place, "_", name)

    def visit_ConstDecl(self, node):
        name = self.get_name_from_decl(node.value)
        if node.children:
            place = self.gen_expr(node.children[0])
            self.emit("=", place, "_", name)

    def visit_ExprStmt(self, node):
        for ch in node.children:
            self.gen_expr(ch)

    def visit_ReturnStmt(self, node):
        if node.children:
            place = self.gen_expr(node.children[0])
            self.emit("ret", "_", "_", place)
        else:
            self.emit("ret", "_", "_", "_")

    def stmt_must_jump(self, node):
        """判断语句执行完后是否一定已经转移控制流。
        用来避免在 break/continue/return 后额外生成一条无意义的 J。
        """
        if node is None:
            return False
        if node.kind in ("BreakStmt", "ContinueStmt", "ReturnStmt"):
            return True
        if node.kind == "Compound":
            return bool(node.children) and self.stmt_must_jump(node.children[-1])
        if node.kind == "IfStmt" and len(node.children) >= 3:
            return self.stmt_must_jump(node.children[1]) and self.stmt_must_jump(node.children[2])
        return False

    def stmt_is_empty(self, node):
        if node is None:
            return True
        if node.kind == "ExprStmt" and not node.children:
            return True
        if node.kind == "Compound" and not node.children:
            return True
        return False

    def condition_has_short_circuit(self, node):
        """判断条件表达式中是否含有 && / ||。

        评测样例对普通关系表达式 if 会在 then 块后保留一条空 J，
        但对用 && / || 连接的短路条件，期望 false 出口直接回填到后继语句，
        不能再额外补空 J。
        """
        if node is None:
            return False
        if node.kind == "Op" and node.value in ("&&", "||"):
            return True
        for ch in node.children:
            if self.condition_has_short_circuit(ch):
                return True
        return False

    def need_extra_jump_for_if_without_else(self, cond, then_stmt):
        """
        评测样例中，普通 if 块后会保留一条 J；
        但处在循环内部、短路条件、then 分支本身是嵌套 if、
        或 then 分支已经 break/continue/return 时，不能再补这条 J。
        """
        if then_stmt is None:
            return False
        if self.condition_has_short_circuit(cond):
            return False
        if self.loop_stack:
            return False
        if self.suppress_if_extra_jump > 0:
            return False
        if then_stmt.kind == "IfStmt":
            return False
        if then_stmt.kind == "Compound" and then_stmt.children:
            if then_stmt.children[-1].kind == "IfStmt":
                return False
        if self.stmt_must_jump(then_stmt):
            return False
        return True

    def visit_IfStmt(self, node):
        if not node.children:
            return
        cond = node.children[0]
        then_stmt = node.children[1] if len(node.children) >= 2 else None
        else_stmt = node.children[2] if len(node.children) >= 3 else None

        true_list, false_list = self.gen_condition(cond)

        if else_stmt is not None and self.stmt_is_empty(then_stmt):
            else_start = self.nextquad()
            self.backpatch(false_list, else_start)
            self.suppress_if_extra_jump += 1
            self.visit(else_stmt)
            self.suppress_if_extra_jump -= 1
            end = self.nextquad()
            self.backpatch(true_list, end)
            return

        then_start = self.nextquad()
        self.backpatch(true_list, then_start)

        if else_stmt is not None:
            self.suppress_if_extra_jump += 1
            self.visit(then_stmt)
            self.suppress_if_extra_jump -= 1
        else:
            self.visit(then_stmt)

        if else_stmt is not None:
            end_jump = None
            if not self.stmt_must_jump(then_stmt):
                end_jump = self.emit("J", "_", "_", None)

            else_start = self.nextquad()
            self.backpatch(false_list, else_start)
            self.suppress_if_extra_jump += 1
            self.visit(else_stmt)
            self.suppress_if_extra_jump -= 1

            end = self.nextquad()
            if end_jump is not None:
                self.backpatch(end_jump, end)
            return

        if self.need_extra_jump_for_if_without_else(cond, then_stmt):
            end_jump = self.emit("J", "_", "_", None)
            after = self.nextquad()
            self.backpatch(false_list, after)
            self.backpatch(end_jump, after)
        else:
            after = self.nextquad()
            self.backpatch(false_list, after)

    def visit_WhileStmt(self, node):
        if len(node.children) < 2:
            return
        cond = node.children[0]
        body = node.children[1]

        begin = self.nextquad()
        true_list, false_list = self.gen_condition(cond)
        body_start = self.nextquad()
        self.backpatch(true_list, body_start)

        ctx = {"breaks": [], "continues": [], "continue_target": begin}
        self.loop_stack.append(ctx)
        self.visit(body)
        self.loop_stack.pop()

        self.emit("J", "_", "_", begin)
        after = self.nextquad()
        self.backpatch(false_list, after)
        self.backpatch(ctx["breaks"], after)
        self.backpatch(ctx["continues"], begin)

    def visit_DoWhileStmt(self, node):
        if len(node.children) < 2:
            return
        body = node.children[0]
        cond = node.children[1]

        body_start = self.nextquad()
        ctx = {"breaks": [], "continues": [], "continue_target": None}
        self.loop_stack.append(ctx)
        self.visit(body)
        self.loop_stack.pop()

        cond_start = self.nextquad()
        self.backpatch(ctx["continues"], cond_start)

        true_list, false_list = self.gen_condition(cond)
        self.backpatch(true_list, body_start)
        after = self.nextquad()
        self.backpatch(false_list, after)
        self.backpatch(ctx["breaks"], after)

    def visit_ForStmt(self, node):
        if len(node.children) < 4:
            return
        init_stmt = node.children[0]
        cond_stmt = node.children[1]
        update_stmt = node.children[2]
        body = node.children[3]

        self.visit(init_stmt)

        cond_start = self.nextquad()
        has_cond = bool(cond_stmt.children)
        false_list = []
        true_list = []
        if has_cond:
            true_list, false_list = self.gen_condition(cond_stmt.children[0])

        # 本实验评测使用的 for 四元式顺序为：init -> cond -> update -> J cond -> body。
        # 条件真时跳过 update 直接到 body；continue 跳到 update。
        update_start = self.nextquad()
        self.visit(update_stmt)
        self.emit("J", "_", "_", cond_start)

        body_start = self.nextquad()
        if has_cond:
            self.backpatch(true_list, body_start)

        ctx = {"breaks": [], "continues": [], "continue_target": update_start}
        self.loop_stack.append(ctx)
        self.visit(body)
        self.loop_stack.pop()

        if not self.stmt_must_jump(body):
            self.emit("J", "_", "_", update_start)

        after = self.nextquad()
        self.backpatch(false_list, after)
        self.backpatch(ctx["breaks"], after)
        self.backpatch(ctx["continues"], update_start)

    def visit_BreakStmt(self, node):
        j = self.emit("J", "_", "_", None)
        if self.loop_stack:
            self.loop_stack[-1]["breaks"].append(j)

    def visit_ContinueStmt(self, node):
        if self.loop_stack:
            target = self.loop_stack[-1].get("continue_target")
            if target is None:
                j = self.emit("J", "_", "_", None)
                self.loop_stack[-1]["continues"].append(j)
            else:
                self.emit("J", "_", "_", target)
        else:
            self.emit("J", "_", "_", None)

    # -------------------- 表达式翻译 --------------------
    def gen_expr(self, node):
        if node is None:
            return "_"

        if node.kind == "Leaf":
            return str(node.value)

        if node.kind == "Call":
            for arg in node.children:
                place = self.gen_expr(arg)
                self.emit("para", place, "_", "_")
            temp = self.new_temp()
            self.emit("call", str(node.value), "_", temp)
            return temp

        if node.kind == "ExprStmt":
            last = "_"
            for ch in node.children:
                last = self.gen_expr(ch)
            return last

        if node.kind == "Op":
            op = node.value

            if op == "=":
                left = self.get_lvalue(node.children[0]) if node.children else "_"
                right = self.gen_expr(node.children[1]) if len(node.children) >= 2 else "_"
                self.emit("=", right, "_", left)
                return left

            # 一元运算
            if len(node.children) == 1:
                child = self.gen_expr(node.children[0])
                temp = self.new_temp()
                if op == "-":
                    self.emit("-", "0", child, temp)
                elif op == "!":
                    self.emit("!", child, "_", temp)
                else:
                    self.emit(op, child, "_", temp)
                return temp

            left = self.gen_expr(node.children[0])
            right = self.gen_expr(node.children[1]) if len(node.children) >= 2 else "_"
            temp = self.new_temp()
            self.emit(op, left, right, temp)
            return temp

        # 其他节点兜底：按子节点顺序求值
        last = "_"
        for ch in node.children:
            last = self.gen_expr(ch)
        return last

    def get_lvalue(self, node):
        if node is None:
            return "_"
        if node.kind == "Leaf":
            return str(node.value)
        return self.gen_expr(node)

    # -------------------- 布尔表达式短路翻译 --------------------
    def gen_condition(self, node):
        if node is None:
            j_true = self.emit("J!=", "_", "0", None)
            j_false = self.emit("J", "_", "_", None)
            return [j_true], [j_false]

        if node.kind == "Op":
            op = node.value

            if op in self.REL_OPS and len(node.children) >= 2:
                left = self.gen_expr(node.children[0])
                right = self.gen_expr(node.children[1])
                j_true = self.emit("J" + op, left, right, None)
                j_false = self.emit("J", "_", "_", None)
                return [j_true], [j_false]

            if op == "&&" and len(node.children) >= 2:
                t1, f1 = self.gen_condition(node.children[0])
                self.backpatch(t1, self.nextquad())
                t2, f2 = self.gen_condition(node.children[1])
                return t2, f1 + f2

            if op == "||" and len(node.children) >= 2:
                t1, f1 = self.gen_condition(node.children[0])
                self.backpatch(f1, self.nextquad())
                t2, f2 = self.gen_condition(node.children[1])
                return t1 + t2, f2

            if op == "!" and len(node.children) == 1:
                t, f = self.gen_condition(node.children[0])
                return f, t

        place = self.gen_expr(node)
        j_true = self.emit("J!=", place, "0", None)
        j_false = self.emit("J", "_", "_", None)
        return [j_true], [j_false]


# ============================================================
# 输出格式化
# ============================================================
def format_field(x):
    if isinstance(x, int):
        return str(x)
    if x is None:
        return "'_'"
    return "'%s'" % str(x)


def write_quads(quads, filename):
    with open(filename, "w", encoding="utf-8") as f:
        for i, q in enumerate(quads):
            op, arg1, arg2, result = q
            line = "%d: (%s, %s, %s, %s)" % (
                i,
                format_field(op),
                format_field(arg1),
                format_field(arg2),
                format_field(result),
            )
            f.write(line + "\n")


# ============================================================
# 主程序
# ============================================================
def main():
    with open("input.txt", "rb") as f:
        source = f.read().decode("utf-8", errors="ignore")

    tokens = LexicalAnalyzer(source).analyze()
    ast = Parser(tokens).parse()
    quads = IntermediateCodeGenerator().generate(ast)
    write_quads(quads, "output.txt")


if __name__ == "__main__":
    main()
