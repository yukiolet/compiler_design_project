class Token:
    def __init__(self, lexeme, code, line):
        self.lexeme = lexeme
        self.code = code
        self.line = line


class ASTNode:
    def __init__(self, kind, value=None, line=None):
        self.kind = kind
        self.value = value
        self.line = line
        self.children = []

    def add(self, child):
        if child is not None:
            self.children.append(child)


class Parser:
    TYPE_KEYWORDS = ("int", "float", "char", "void")

    def __init__(self, tokens):
        self.tokens = tokens
        self.pos = 0

    # ==================== 基础工具 ====================
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

    def match(self, lexeme):
        if self.check(lexeme):
            tok = self.current()
            self.pos += 1
            return tok
        return None

    def soft_expect(self, lexeme):
        if self.check(lexeme):
            tok = self.current()
            self.pos += 1
            return tok
        return None

    def is_type(self):
        tok = self.current()
        return tok is not None and tok.lexeme in self.TYPE_KEYWORDS

    def is_identifier(self):
        tok = self.current()
        return tok is not None and tok.code == 700

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

    def is_constant_token(self, tok):
        if tok is None:
            return False

        # 常见常量编码：整数、浮点、字符、字符串
        if tok.code in (400, 500, 600, 800):
            return True

        # 再做一层保守兜底
        if tok.code == 700:
            return False

        if tok.lexeme in (
            "const", "int", "float", "char", "void",
            "if", "else", "while", "for", "do",
            "return", "continue", "break",
            "(", ")", "{", "}", ";", ",",
            "+", "-", "*", "/", "!", "=",
            "==", "!=", ">", "<", ">=", "<=",
            "&&", "||"
        ):
            return False

        return True

    def starts_expression(self, tok):
        if tok is None:
            return False
        if tok.lexeme in ("(", "-", "!"):
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
            t0 is not None and t0.lexeme == "int" and
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

    # ==================== 总入口 ====================
    def parse(self):
        return self.parse_program()

    def parse_program(self):
        root = ASTNode("Program")

        # main 之前：全局声明/函数声明/函数定义
        while not self.eof() and not self.lookahead_is_main():
            if self.check("const"):
                node = self.parse_const_decl()
                self.append_decl_or_group(root, node)
            elif self.lookahead_is_function():
                root.add(self.parse_function_decl_or_def())
            elif self.is_type():
                node = self.parse_var_decl()
                self.append_decl_or_group(root, node)
            else:
                # 容错：跳过一个 token，避免直接崩
                self.pos += 1

        # main
        if not self.eof() and self.lookahead_is_main():
            root.add(self.parse_main_function())

        # main 后剩余函数
        while not self.eof():
            if self.lookahead_is_function():
                root.add(self.parse_function_decl_or_def())
            else:
                self.pos += 1

        return root

    def append_decl_or_group(self, parent, node):
        if node is None:
            return
        if node.kind == "DeclGroup":
            i = 0
            while i < len(node.children):
                parent.add(node.children[i])
                i += 1
        else:
            parent.add(node)

    # ==================== 函数 ====================
    def parse_main_function(self):
        type_tok = self.soft_expect("int")
        name_tok = self.soft_expect("main")
        self.soft_expect("(")
        self.soft_expect(")")
        compound = self.parse_compound()

        line = 0
        if name_tok is not None:
            line = name_tok.line
        elif type_tok is not None:
            line = type_tok.line

        node = ASTNode("FunctionDef", "int main", line)
        node.add(compound)
        return node

    def parse_function_decl_or_def(self):
        type_tok = self.expect_type()
        name_tok = self.expect_identifier()

        type_name = "int"
        func_name = "unknown"
        line = 0

        if type_tok is not None:
            type_name = type_tok.lexeme
            line = type_tok.line
        if name_tok is not None:
            func_name = name_tok.lexeme
            line = name_tok.line

        self.soft_expect("(")
        params = self.parse_parameter_list_opt()
        self.soft_expect(")")

        if self.check(";"):
            self.soft_expect(";")
            node = ASTNode("FunctionDecl", type_name + " " + func_name, line)
            i = 0
            while i < len(params):
                node.add(params[i])
                i += 1
            return node
        else:
            compound = self.parse_compound()
            node = ASTNode("FunctionDef", type_name + " " + func_name, line)
            i = 0
            while i < len(params):
                node.add(params[i])
                i += 1
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

        type_name = "int"
        var_name = "unknown"
        line = 0

        if type_tok is not None:
            type_name = type_tok.lexeme
            line = type_tok.line
        if name_tok is not None:
            var_name = name_tok.lexeme
            line = name_tok.line

        return ASTNode("Param", type_name + " " + var_name, line)

    # ==================== 声明 ====================
    def parse_const_decl(self):
        self.soft_expect("const")
        type_tok = self.expect_type()

        type_name = "int"
        if type_tok is not None:
            type_name = type_tok.lexeme

        group = ASTNode("DeclGroup")
        first = self.parse_one_const_decl(type_name)
        if first is not None:
            group.add(first)

        while self.check(","):
            self.soft_expect(",")
            node = self.parse_one_const_decl(type_name)
            if node is not None:
                group.add(node)

        # 容错：有分号就吃掉，没有也不报错
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
        type_name = "int"
        if type_tok is not None:
            type_name = type_tok.lexeme

        group = ASTNode("DeclGroup")

        first = self.parse_one_var_decl(type_name)
        if first is not None:
            group.add(first)

        while self.check(","):
            self.soft_expect(",")
            node = self.parse_one_var_decl(type_name)
            if node is not None:
                group.add(node)

        # 关键容错：
        # 如果变量初始化后出现奇怪 token（比如 2.5 后面的 f），
        # 不强制要求当前位置必须是 ; 或 ,，这样后续 token 可以被当作普通语句继续分析
        if self.check(";"):
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

    # ==================== 复合语句 ====================
    def parse_compound(self):
        lbrace = self.soft_expect("{")
        line = 0
        if lbrace is not None:
            line = lbrace.line

        node = ASTNode("Compound", line=line)

        # 容错：直到遇到 } 或 EOF
        while not self.eof() and not self.check("}"):
            stmt = self.parse_statement()
            if stmt is None:
                # 避免死循环
                if not self.eof():
                    self.pos += 1
                continue

            if stmt.kind == "DeclGroup":
                i = 0
                while i < len(stmt.children):
                    node.add(stmt.children[i])
                    i += 1
            else:
                node.add(stmt)

        self.soft_expect("}")
        return node

    # ==================== 语句 ====================
    def parse_statement(self):
        tok = self.current()
        if tok is None:
            return None

        if self.check("{"):
            return self.parse_compound()
        elif self.check("const"):
            return self.parse_const_decl()
        elif self.is_type():
            return self.parse_var_decl()
        elif self.check("if"):
            return self.parse_if_stmt()
        elif self.check("while"):
            return self.parse_while_stmt()
        elif self.check("for"):
            return self.parse_for_stmt()
        elif self.check("do"):
            return self.parse_do_while_stmt()
        elif self.check("continue"):
            return self.parse_continue_stmt()
        elif self.check("break"):
            return self.parse_break_stmt()
        elif self.check("return"):
            return self.parse_return_stmt()
        elif self.check(";"):
            self.soft_expect(";")
            return ASTNode("ExprStmt", line=tok.line)
        elif self.check(","):
            # 容错：把裸逗号当空表达式
            self.soft_expect(",")
            return ASTNode("ExprStmt", line=tok.line)
        else:
            return self.parse_expr_stmt()

    def parse_if_stmt(self):
        tok_if = self.soft_expect("if")
        line = 0
        if tok_if is not None:
            line = tok_if.line

        self.soft_expect("(")
        cond = self.parse_expression()
        self.soft_expect(")")
        then_stmt = self.parse_statement()

        node = ASTNode("IfStmt", line=line)
        if cond is not None:
            node.add(cond)
        if then_stmt is not None:
            node.add(then_stmt)

        if self.check("else"):
            self.soft_expect("else")
            else_stmt = self.parse_statement()
            if else_stmt is not None:
                node.add(else_stmt)

        return node

    def parse_while_stmt(self):
        tok = self.soft_expect("while")
        line = 0
        if tok is not None:
            line = tok.line

        self.soft_expect("(")
        cond = self.parse_expression()
        self.soft_expect(")")
        body = self.parse_statement()

        node = ASTNode("WhileStmt", line=line)
        if cond is not None:
            node.add(cond)
        if body is not None:
            node.add(body)
        return node

    def parse_for_stmt(self):
        tok = self.soft_expect("for")
        line = 0
        if tok is not None:
            line = tok.line

        # 标准 for 优先
        if self.check("("):
            self.soft_expect("(")

            node = ASTNode("ForStmt", line=line)

            # init
            if self.check(";"):
                self.soft_expect(";")
                node.add(ASTNode("ExprStmt", line=line))
            else:
                init = self.parse_expression()
                self.soft_expect(";")
                init_stmt = ASTNode("ExprStmt", line=(init.line if init is not None else line))
                if init is not None:
                    init_stmt.add(init)
                node.add(init_stmt)

            # cond
            if self.check(";"):
                self.soft_expect(";")
                node.add(ASTNode("ExprStmt", line=line))
            else:
                cond = self.parse_expression()
                self.soft_expect(";")
                cond_stmt = ASTNode("ExprStmt", line=(cond.line if cond is not None else line))
                if cond is not None:
                    cond_stmt.add(cond)
                node.add(cond_stmt)

            # update
            if self.check(")"):
                self.soft_expect(")")
                node.add(ASTNode("ExprStmt", line=line))
            else:
                update = self.parse_expression()
                self.soft_expect(")")
                update_stmt = ASTNode("ExprStmt", line=(update.line if update is not None else line))
                if update is not None:
                    update_stmt.add(update)
                node.add(update_stmt)

            body = self.parse_statement()
            if body is not None:
                node.add(body)
            return node

        # 容错：如果 for 后面不规范，就退化成普通 ExprStmt
        expr_stmt = ASTNode("ExprStmt", line=line)
        expr_stmt.add(ASTNode("Leaf", "for", line))
        return expr_stmt

    def parse_do_while_stmt(self):
        tok = self.soft_expect("do")
        line = 0
        if tok is not None:
            line = tok.line

        body = self.parse_statement()

        self.soft_expect("while")
        self.soft_expect("(")
        cond = self.parse_expression()
        self.soft_expect(")")
        self.soft_expect(";")

        node = ASTNode("DoWhileStmt", line=line)
        if body is not None:
            node.add(body)
        if cond is not None:
            node.add(cond)
        return node

    def parse_continue_stmt(self):
        tok = self.soft_expect("continue")
        line = 0
        if tok is not None:
            line = tok.line
        self.soft_expect(";")
        return ASTNode("ContinueStmt", line=line)

    def parse_break_stmt(self):
        tok = self.soft_expect("break")
        line = 0
        if tok is not None:
            line = tok.line
        self.soft_expect(";")
        return ASTNode("BreakStmt", line=line)

    def parse_return_stmt(self):
        tok = self.soft_expect("return")
        line = 0
        if tok is not None:
            line = tok.line

        node = ASTNode("ReturnStmt", line=line)

        if not self.check(";"):
            expr = self.parse_expression()
            if expr is not None:
                node.add(expr)

        self.soft_expect(";")
        return node

    def parse_expr_stmt(self):
        tok = self.current()
        line = 0
        if tok is not None:
            line = tok.line

        # 空表达式
        if tok is None:
            return ASTNode("ExprStmt", line=line)

        if self.check(";"):
            self.soft_expect(";")
            return ASTNode("ExprStmt", line=line)

        # 不像表达式开头，则容错消费一个 token
        if not self.starts_expression(tok):
            if self.check(","):
                self.soft_expect(",")
                return ASTNode("ExprStmt", line=line)

            # 对孤立奇怪 token 做兜底
            self.pos += 1
            node = ASTNode("ExprStmt", line=line)
            if tok.lexeme not in ("{", "}", "(", ")", ";", ","):
                node.add(ASTNode("Leaf", tok.lexeme, tok.line))
            return node

        expr = self.parse_expression()
        stmt = ASTNode("ExprStmt", line=(expr.line if expr is not None else line))
        if expr is not None:
            stmt.add(expr)

        if self.check(";"):
            self.soft_expect(";")

        return stmt

    # ==================== 表达式 ====================
    # 优先级：
    # assignment (=, 右结合)
    # logical_or
    # logical_and
    # equality
    # relational
    # additive
    # term
    # unary
    # primary

    def parse_expression(self):
        return self.parse_assignment()

    def parse_assignment(self):
        left = self.parse_logical_or()
        if self.check("="):
            tok = self.soft_expect("=")
            right = self.parse_assignment()
            line = 0
            if tok is not None:
                line = tok.line
            node = ASTNode("Op", "=", line)
            if left is not None:
                node.add(left)
            if right is not None:
                node.add(right)
            return node
        return left

    def parse_logical_or(self):
        node = self.parse_logical_and()
        while self.check("||"):
            tok = self.soft_expect("||")
            right = self.parse_logical_and()
            line = 0
            if tok is not None:
                line = tok.line
            new_node = ASTNode("Op", "||", line)
            if node is not None:
                new_node.add(node)
            if right is not None:
                new_node.add(right)
            node = new_node
        return node

    def parse_logical_and(self):
        node = self.parse_equality()
        while self.check("&&"):
            tok = self.soft_expect("&&")
            right = self.parse_equality()
            line = 0
            if tok is not None:
                line = tok.line
            new_node = ASTNode("Op", "&&", line)
            if node is not None:
                new_node.add(node)
            if right is not None:
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
            if node is not None:
                new_node.add(node)
            if right is not None:
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
            if node is not None:
                new_node.add(node)
            if right is not None:
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
            if node is not None:
                new_node.add(node)
            if right is not None:
                new_node.add(right)
            node = new_node
        return node

    def parse_term(self):
        node = self.parse_unary()
        while self.check("*") or self.check("/"):
            tok = self.current()
            self.pos += 1
            right = self.parse_unary()
            new_node = ASTNode("Op", tok.lexeme, tok.line)
            if node is not None:
                new_node.add(node)
            if right is not None:
                new_node.add(right)
            node = new_node
        return node

    def parse_unary(self):
        tok = self.current()
        if tok is None:
            return None

        # 只有真正的运算符 ! 才按一元运算处理
        # 如果是字符常量 '!'，应当在 parse_primary 里作为常量处理
        if tok.lexeme == "!" and not self.is_constant_token(tok):
            tok = self.soft_expect("!")
            child = self.parse_unary()
            line = 0
            if tok is not None:
                line = tok.line
            node = ASTNode("Op", "!", line)
            if child is not None:
                node.add(child)
            return node

        # 同理，只有真正的减号才按一元负号处理
        if tok.lexeme == "-" and not self.is_constant_token(tok):
            tok = self.soft_expect("-")
            child = self.parse_unary()
            line = 0
            if tok is not None:
                line = tok.line
            node = ASTNode("Op", "-", line)
            if child is not None:
                node.add(child)
            return node

        return self.parse_primary()
    def parse_primary(self):
        tok = self.current()
        if tok is None:
            return None

        # 标识符 / 函数调用
        if tok.code == 700:
            name_tok = self.expect_identifier()
            if name_tok is None:
                return None

            if self.check("("):
                self.soft_expect("(")
                node = ASTNode("Call", name_tok.lexeme, name_tok.line)

                if not self.check(")"):
                    arg = self.parse_expression()
                    if arg is not None:
                        node.add(arg)

                    while self.check(","):
                        self.soft_expect(",")
                        arg = self.parse_expression()
                        if arg is not None:
                            node.add(arg)

                self.soft_expect(")")
                return node
            else:
                return ASTNode("Leaf", name_tok.lexeme, name_tok.line)

        # 常量
        if self.is_constant_token(tok):
            self.pos += 1
            return ASTNode("Leaf", tok.lexeme, tok.line)

        # 括号表达式
        if self.check("("):
            self.soft_expect("(")
            node = self.parse_expression()
            self.soft_expect(")")
            return node

        # 容错：把未知 token 作为叶子节点吃掉，避免崩
        self.pos += 1
        return ASTNode("Leaf", tok.lexeme, tok.line)


# ==================== 输出 AST ====================
def ast_lines(node, indent=0):
    lines = []
    prefix = "  " * indent

    if node is None:
        return lines

    if node.kind == "DeclGroup":
        i = 0
        while i < len(node.children):
            lines.extend(ast_lines(node.children[i], indent))
            i += 1
        return lines

    if node.kind == "Program":
        lines.append(prefix + "Program")
        i = 0
        while i < len(node.children):
            lines.extend(ast_lines(node.children[i], indent + 1))
            i += 1

    elif node.kind == "FunctionDef" or node.kind == "FunctionDecl":
        lines.append(prefix + "%s(%s)[%d]" % (node.kind, node.value, node.line))
        i = 0
        while i < len(node.children):
            lines.extend(ast_lines(node.children[i], indent + 1))
            i += 1

    elif node.kind == "Param":
        lines.append(prefix + "Param(%s)[%d]" % (node.value, node.line))

    elif node.kind == "ConstDecl" or node.kind == "VarDecl":
        lines.append(prefix + "%s(%s)[%d]" % (node.kind, node.value, node.line))
        i = 0
        while i < len(node.children):
            lines.extend(ast_lines(node.children[i], indent + 1))
            i += 1

    elif node.kind == "Compound":
        lines.append(prefix + "Compound")
        i = 0
        while i < len(node.children):
            lines.extend(ast_lines(node.children[i], indent + 1))
            i += 1

    elif node.kind == "IfStmt" or node.kind == "WhileStmt" or node.kind == "DoWhileStmt":
        lines.append(prefix + node.kind)
        i = 0
        while i < len(node.children):
            lines.extend(ast_lines(node.children[i], indent + 1))
            i += 1

    elif node.kind == "ForStmt":
        lines.append(prefix + "ForStmt")
        i = 0
        while i < len(node.children):
            child = node.children[i]
            if i < 3 and child.kind == "ExprStmt":
                if len(child.children) == 0:
                    lines.append("  " * (indent + 1) + "ExprStmt")
                else:
                    j = 0
                    while j < len(child.children):
                        lines.extend(ast_lines(child.children[j], indent + 1))
                        j += 1
            else:
                lines.extend(ast_lines(child, indent + 1))
            i += 1

    elif node.kind == "ReturnStmt":
        lines.append(prefix + "ReturnStmt[%d]" % node.line)
        i = 0
        while i < len(node.children):
            lines.extend(ast_lines(node.children[i], indent + 1))
            i += 1

    elif node.kind == "ContinueStmt":
        lines.append(prefix + "ContinueStmt[%d]" % node.line)

    elif node.kind == "BreakStmt":
        lines.append(prefix + "BreakStmt[%d]" % node.line)

    elif node.kind == "ExprStmt":
        lines.append(prefix + "ExprStmt")
        i = 0
        while i < len(node.children):
            lines.extend(ast_lines(node.children[i], indent + 1))
            i += 1

    elif node.kind == "Call":
        lines.append(prefix + "Call(%s)[%d]" % (node.value, node.line))
        i = 0
        while i < len(node.children):
            lines.extend(ast_lines(node.children[i], indent + 1))
            i += 1

    elif node.kind == "Op":
        lines.append(prefix + "%s[%d]" % (node.value, node.line))
        i = 0
        while i < len(node.children):
            lines.extend(ast_lines(node.children[i], indent + 1))
            i += 1

    elif node.kind == "Leaf":
        lines.append(prefix + "%s[%d]" % (node.value, node.line))

    else:
        lines.append(prefix + node.kind)
        i = 0
        while i < len(node.children):
            lines.extend(ast_lines(node.children[i], indent + 1))
            i += 1

    return lines


# ==================== 主程序 ====================
if __name__ == '__main__':
    tokens = []

    with open('input.txt', 'r') as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            parts = line.split()
            if len(parts) < 3:
                continue

            lexeme = parts[0].strip()
            try:
                code = int(parts[1].strip())
            except:
                code = 0
            try:
                line_no = int(parts[2].strip())
            except:
                line_no = 0

            tokens.append(Token(lexeme, code, line_no))

    parser = Parser(tokens)
    ast = parser.parse()

    lines = ast_lines(ast)

    cleaned = []
    i = 0
    while i < len(lines):
        cleaned.append(lines[i].rstrip())
        i += 1

    with open("output.txt", "w") as f:
        f.write("\n".join(cleaned))
        f.write("\n")