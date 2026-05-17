import re


class ASTNode:
    def __init__(self, raw_text, ast_line_no=0):
        self.raw_text = raw_text.strip()
        self.ast_line_no = ast_line_no
        self.children = []
        self.parent = None
        self.src_line = self.extract_src_line()
        self.kind, self.info = self.parse_raw()

    def add_child(self, child):
        child.parent = self
        self.children.append(child)

    def extract_src_line(self):
        m = re.search(r'\[(\d+)\]\s*$', self.raw_text)
        if m:
            return int(m.group(1))
        return None

    def text_without_line(self):
        return re.sub(r'\[\d+\]\s*$', '', self.raw_text).strip()

    def parse_raw(self):
        text = self.text_without_line()

        m = re.match(r'^FunctionDecl\s*\(\s*(\w+)\s+(\w+)\s*\)$', text)
        if m:
            return 'FunctionDecl', {'return_type': m.group(1), 'name': m.group(2)}

        m = re.match(r'^FunctionDef\s*\(\s*(\w+)\s+(\w+)\s*\)$', text)
        if m:
            return 'FunctionDef', {'return_type': m.group(1), 'name': m.group(2)}

        m = re.match(r'^Param\s*\(\s*(\w+)\s+(\w+)\s*\)$', text)
        if m:
            return 'Param', {'type': m.group(1), 'name': m.group(2)}

        m = re.match(r'^VarDecl\s*\(\s*(\w+)\s+(\w+)\s*\)$', text)
        if m:
            return 'VarDecl', {'type': m.group(1), 'name': m.group(2)}

        m = re.match(r'^VarDecl\s*\(\s*(\w+)\s*\)$', text)
        if m:
            return 'VarDecl', {'type': m.group(1)}

        m = re.match(r'^ConstDecl\s*\(\s*(\w+)\s+(\w+)\s*\)$', text)
        if m:
            return 'ConstDecl', {'type': m.group(1), 'name': m.group(2)}

        m = re.match(r'^ConstDecl\s*\(\s*(\w+)\s*\)$', text)
        if m:
            return 'ConstDecl', {'type': m.group(1)}

        m = re.match(r'^(VarDef|ConstDef)\s*\(\s*(\w+)\s+(\w+)\s*\)$', text)
        if m:
            return m.group(1), {'type': m.group(2), 'name': m.group(3)}

        m = re.match(r'^(VarDef|ConstDef)\s*\(\s*(\w+)\s*\)$', text)
        if m:
            return m.group(1), {'name': m.group(2)}

        m = re.match(r'^(Call|FuncCall|CallStmt|CallExpr)\s*\(\s*(\w+)\s*\)$', text)
        if m:
            return 'Call', {'name': m.group(2)}

        keywords = {
            'Program', 'Compound', 'ReturnStmt', 'BreakStmt',
            'WhileStmt', 'ForStmt', 'DoWhileStmt',
            'SwitchStmt', 'CaseStmt', 'DefaultStmt',
            'IfStmt', 'AssignStmt', 'ExprStmt'
        }
        if text in keywords:
            return text, {}

        if text in ['+', '-', '*', '/', '=', '==', '!=', '<', '>', '<=', '>=']:
            return 'Operator', {'op': text}

        return 'Atom', {'text': text}

    def end_line(self):
        vals = []
        if self.src_line is not None:
            vals.append(self.src_line)
        for ch in self.children:
            v = ch.end_line()
            if v is not None:
                vals.append(v)
        return max(vals) if vals else None


def parse_ast_file(filename):
    with open(filename, 'r', encoding='utf-8') as f:
        lines = [line.rstrip('\n') for line in f if line.strip()]

    if not lines:
        return None

    root = None
    stack = []

    for idx, line in enumerate(lines, start=1):
        indent = len(line) - len(line.lstrip(' '))
        node = ASTNode(line.strip(), idx)

        while stack and stack[-1][0] >= indent:
            stack.pop()

        if not stack:
            root = node
        else:
            stack[-1][1].add_child(node)

        stack.append((indent, node))

    return root


class Scope:
    def __init__(self, level, parent=None, owner='global'):
        self.level = level
        self.parent = parent
        self.owner = owner
        self.vars = {}
        self.consts = {}

    def lookup_current(self, name):
        if name in self.vars:
            return 'var', self.vars[name]
        if name in self.consts:
            return 'const', self.consts[name]
        return None

    def lookup(self, name):
        cur = self
        while cur:
            if name in cur.vars:
                return 'var', cur.vars[name]
            if name in cur.consts:
                return 'const', cur.consts[name]
            cur = cur.parent
        return None


class SemanticAnalyzer:
    def __init__(self, root):
        self.root = root
        self.errors = []
        self.error_lines = set()

        self.global_scope = Scope(0, None, 'global')
        self.current_scope = self.global_scope

        self.const_entries = []
        self.var_entries = []
        self.function_entries = []

        self.functions = {}

        self.current_function = None
        self.loop_depth = 0
        self.switch_depth = 0

        self.const_name_fallback = set()

    def add_error(self, line, code):
        if line is None:
            return
        if line in self.error_lines:
            return
        self.errors.append((line, code))
        self.error_lines.add(line)

    def same_signature(self, a_ret, a_params, b_ret, b_params):
        if a_ret != b_ret:
            return False
        if len(a_params) != len(b_params):
            return False
        for x, y in zip(a_params, b_params):
            if x['type'] != y['type']:
                return False
        return True

    def is_identifier_name(self, text):
        return re.match(r'^[A-Za-z_]\w*$', text) is not None

    def looks_like_const_name(self, text):
        return re.match(r'^[A-Z_][A-Z0-9_]*$', text) is not None

    def enter_scope(self, owner='block'):
        self.current_scope = Scope(
            self.current_scope.level + 1,
            self.current_scope,
            owner
        )

    def exit_scope(self):
        if self.current_scope.parent:
            self.current_scope = self.current_scope.parent

    def add_var_entry(self, name, typ, line, init_text=''):
        entry = {
            'name': name,
            'type': typ,
            'scope': self.current_scope.level,
            'line': line,
            'init': init_text
        }
        self.current_scope.vars[name] = entry
        self.var_entries.append(entry)

    def add_const_entry(self, name, typ, line, value_text=''):
        entry = {
            'name': name,
            'type': typ,
            'scope': self.current_scope.level,
            'line': line,
            'value': value_text
        }
        self.current_scope.consts[name] = entry
        self.const_entries.append(entry)
        self.const_name_fallback.add(name)

    def scan_const_fallback(self):
        def dfs(node):
            if node is None:
                return

            if node.kind in ('ConstDecl', 'ConstDef'):
                name = node.info.get('name')
                if name and self.is_identifier_name(name):
                    self.const_name_fallback.add(name.strip())
                self.collect_identifier_atoms(node, self.const_name_fallback)

            for ch in node.children:
                dfs(ch)

        dfs(self.root)

    def collect_identifier_atoms(self, node, out_set):
        if node is None:
            return
        if node.kind == 'Atom':
            text = node.info['text'].strip()
            if self.is_identifier_name(text):
                out_set.add(text)
        for ch in node.children:
            self.collect_identifier_atoms(ch, out_set)

    def register_function(self, name, return_type, params, line, is_definition):
        if name not in self.functions:
            self.functions[name] = {'decl': None, 'def': None}

        info = self.functions[name]

        if not is_definition:
            if info['decl'] is not None:
                self.add_error(line, 303)
                return False
            if info['def'] is not None:
                self.add_error(line, 303)
                return False

            info['decl'] = {
                'return_type': return_type,
                'params': params,
                'line': line
            }
            self.function_entries.append({
                'name': name,
                'return_type': return_type,
                'params': params,
                'line': line
            })
            return True

        if info['def'] is not None:
            self.add_error(line, 303)
            return False

        if info['decl'] is not None:
            decl = info['decl']
            if not self.same_signature(
                decl['return_type'], decl['params'],
                return_type, params
            ):
                self.add_error(line, 303)
                return False

        info['def'] = {
            'return_type': return_type,
            'params': params,
            'line': line
        }
        self.function_entries.append({
            'name': name,
            'return_type': return_type,
            'params': params,
            'line': line
        })
        return True

    def function_visible_before(self, name, call_line):
        if name not in self.functions:
            return None

        info = self.functions[name]
        cand = []

        if info['decl'] is not None and info['decl']['line'] < call_line:
            cand.append(info['decl'])

        if info['def'] is not None and info['def']['line'] < call_line:
            cand.append(info['def'])

        if not cand:
            return None

        cand.sort(key=lambda x: x['line'])
        return cand[0]

    def infer_literal_type(self, text):
        if re.match(r'^\d+\.\d+$', text):
            return 'float'
        if re.match(r'^\d+$', text):
            return 'int'
        if re.match(r"^'.'$", text):
            return 'char'
        if re.match(r'^".*"$', text):
            return 'string'
        if re.match(r'^[A-Z]$', text):
            return 'char'
        return None

    def extract_lvalue_name(self, node):
        if node is None:
            return None

        if node.kind == 'Atom':
            text = node.info['text'].strip()
            if self.is_identifier_name(text):
                return text
            return None

        if len(node.children) == 1:
            return self.extract_lvalue_name(node.children[0])

        names = []

        def collect_names(x):
            if x is None:
                return
            if x.kind == 'Atom':
                t = x.info['text'].strip()
                if self.is_identifier_name(t):
                    names.append(t)
                return
            for c in x.children:
                collect_names(c)

        collect_names(node)
        if len(names) == 1:
            return names[0]

        return None

    def eval_expr_type(self, node):
        if node is None:
            return 'unknown'

        if node.kind == 'Atom':
            text = node.info['text'].strip()

            lit = self.infer_literal_type(text)
            if lit is not None:
                return lit

            found = self.current_scope.lookup(text)
            if not found:
                self.add_error(node.src_line, 302)
                return 'unknown'
            return found[1]['type']

        if node.kind == 'Call':
            fname = node.info['name']
            finfo = self.function_visible_before(fname, node.src_line)

            if finfo is None:
                self.add_error(node.src_line, 304)
                for ch in node.children:
                    self.eval_expr_type(ch)
                return 'unknown'

            args = node.children
            params = finfo['params']

            if len(args) != len(params):
                self.add_error(node.src_line, 305)
            else:
                for arg_node, p in zip(args, params):
                    at = self.eval_expr_type(arg_node)
                    if at != 'unknown' and at != p['type']:
                        self.add_error(node.src_line, 306)
                        break

            return finfo['return_type']

        if node.kind == 'Operator':
            op = node.info['op']

            if op == '=':
                if len(node.children) >= 2:
                    left = node.children[0]
                    right = node.children[1]

                    left_type = 'unknown'
                    left_name = self.extract_lvalue_name(left)

                    if left_name is not None:
                        found = self.current_scope.lookup(left_name)
                        if not found:
                            if left_name in self.const_name_fallback or self.looks_like_const_name(left_name):
                                self.add_error(left.src_line, 309)
                            else:
                                self.add_error(left.src_line, 302)
                        else:
                            cate, entry = found
                            left_type = entry['type']
                            if cate == 'const':
                                self.add_error(left.src_line, 309)
                    else:
                        left_type = self.eval_expr_type(left)

                    right_type = self.eval_expr_type(right)
                    return left_type if left_type != 'unknown' else right_type

                return 'unknown'

            if op in ['+', '-', '*', '/']:
                if len(node.children) == 1:
                    return self.eval_expr_type(node.children[0])

                if len(node.children) >= 2:
                    t1 = self.eval_expr_type(node.children[0])
                    t2 = self.eval_expr_type(node.children[1])

                    if t1 == 'unknown' or t2 == 'unknown':
                        return 'unknown'

                    if t1 != t2:
                        self.add_error(node.src_line, 310)
                        return 'unknown'

                    return t1

            if op in ['==', '!=', '<', '>', '<=', '>=']:
                for ch in node.children:
                    self.eval_expr_type(ch)
                return 'int'

        if node.kind == 'AssignStmt':
            if len(node.children) >= 2:
                fake = ASTNode('=[0]')
                fake.kind = 'Operator'
                fake.info = {'op': '='}
                fake.children = [node.children[0], node.children[1]]
                return self.eval_expr_type(fake)

        if node.kind == 'ReturnStmt':
            if not node.children:
                return 'void'
            return self.eval_expr_type(node.children[0])

        last = 'unknown'
        for ch in node.children:
            last = self.eval_expr_type(ch)
        return last

    def collect_returns(self, node, arr):
        if node is None:
            return
        if node.kind == 'ReturnStmt':
            arr.append(node)
        for ch in node.children:
            self.collect_returns(ch, arr)

    def case_has_break(self, node):
        if node.kind == 'BreakStmt':
            return True
        for ch in node.children:
            if self.case_has_break(ch):
                return True
        return False

    def analyze(self):
        if self.root:
            self.scan_const_fallback()
            self.visit(self.root)
        self.errors.sort(key=lambda x: x[0])
        self.write_outputs()

    def visit(self, node):
        fn = getattr(self, f'visit_{node.kind}', self.generic_visit)
        fn(node)

    def generic_visit(self, node):
        for ch in node.children:
            self.visit(ch)

    def visit_Program(self, node):
        for ch in node.children:
            self.visit(ch)

    def extract_function_parts(self, node):
        params = []
        body = None
        for ch in node.children:
            if ch.kind == 'Param':
                params.append({
                    'name': ch.info['name'],
                    'type': ch.info['type'],
                    'line': ch.src_line
                })
            elif ch.kind == 'Compound':
                body = ch
        return params, body

    def handle_function(self, node, force_definition=False):
        fname = node.info['name']
        rtype = node.info['return_type']
        fline = node.src_line

        params, body = self.extract_function_parts(node)
        is_definition = force_definition or (body is not None)

        ok = self.register_function(fname, rtype, params, fline, is_definition)

        if not is_definition or body is None:
            return
        if not ok:
            return

        saved_function = self.current_function
        self.current_function = {
            'name': fname,
            'return_type': rtype,
            'line': fline
        }

        self.enter_scope(owner=f'function:{fname}')

        for p in params:
            if self.current_scope.lookup_current(p['name']):
                self.add_error(p['line'], 301)
            else:
                self.add_var_entry(p['name'], p['type'], p['line'], 'param')

        self.visit(body)

        end_line = body.end_line() if body else node.end_line()
        returns = []
        self.collect_returns(body, returns)

        if rtype == 'void':
            if returns:
                self.add_error(end_line, 307)
        else:
            if not returns:
                self.add_error(end_line, 307)
            else:
                bad = False
                for ret in returns:
                    if not ret.children:
                        bad = True
                        break
                    rt = self.eval_expr_type(ret.children[0])
                    if rt != 'unknown' and rt != rtype:
                        bad = True
                        break
                if bad:
                    self.add_error(end_line, 307)

        self.exit_scope()
        self.current_function = saved_function

    def visit_FunctionDecl(self, node):
        self.handle_function(node, force_definition=False)

    def visit_FunctionDef(self, node):
        self.handle_function(node, force_definition=True)

    def visit_Compound(self, node):
        if node.parent and node.parent.kind in ('FunctionDecl', 'FunctionDef'):
            for ch in node.children:
                self.visit(ch)
            return

        self.enter_scope('compound')
        for ch in node.children:
            self.visit(ch)
        self.exit_scope()

    def visit_Param(self, node):
        pass

    def visit_VarDecl(self, node):
        name = node.info.get('name')
        typ = node.info.get('type')
        line = node.src_line

        if name is not None and typ is not None:
            init_text = node.children[0].text_without_line() if node.children else ''

            if self.current_scope.lookup_current(name):
                self.add_error(line, 301)
                return

            if node.children:
                self.eval_expr_type(node.children[0])

            self.add_var_entry(name, typ, line, init_text)
            return

        if typ is not None and node.children:
            first = node.children[0]

            if first.kind == 'Atom':
                child_name = first.info['text'].strip()
                if self.is_identifier_name(child_name):
                    if self.current_scope.lookup_current(child_name):
                        self.add_error(first.src_line or line, 301)
                        return

                    if first.children:
                        self.eval_expr_type(first.children[0])
                        init_text = first.children[0].text_without_line()
                    elif len(node.children) >= 2:
                        self.eval_expr_type(node.children[1])
                        init_text = node.children[1].text_without_line()
                    else:
                        init_text = ''

                    self.add_var_entry(child_name, typ, first.src_line or line, init_text)
                    return

        for ch in node.children:
            self.visit(ch)

    def visit_ConstDecl(self, node):
        name = node.info.get('name')
        typ = node.info.get('type')
        line = node.src_line

        if name is not None and typ is not None:
            value_text = node.children[0].text_without_line() if node.children else ''

            if self.current_scope.lookup_current(name):
                self.add_error(line, 301)
                return

            if node.children:
                self.eval_expr_type(node.children[0])

            self.add_const_entry(name, typ, line, value_text)
            return

        if typ is not None and node.children:
            first = node.children[0]

            if first.kind == 'Atom':
                child_name = first.info['text'].strip()
                if self.is_identifier_name(child_name):
                    if self.current_scope.lookup_current(child_name):
                        self.add_error(first.src_line or line, 301)
                        return

                    if first.children:
                        self.eval_expr_type(first.children[0])
                        value_text = first.children[0].text_without_line()
                    elif len(node.children) >= 2:
                        self.eval_expr_type(node.children[1])
                        value_text = node.children[1].text_without_line()
                    else:
                        value_text = ''

                    self.add_const_entry(child_name, typ, first.src_line or line, value_text)
                    return

        for ch in node.children:
            self.visit(ch)

    def visit_VarDef(self, node):
        name = node.info.get('name')
        typ = node.info.get('type')
        line = node.src_line

        if typ is None and node.parent and node.parent.kind == 'VarDecl':
            typ = node.parent.info.get('type')

        if name is not None:
            name = name.strip()

        if name is None or typ is None or (not self.is_identifier_name(name)):
            for ch in node.children:
                self.visit(ch)
            return

        if self.current_scope.lookup_current(name):
            self.add_error(line, 301)
            return

        if node.children:
            self.eval_expr_type(node.children[0])

        init_text = node.children[0].text_without_line() if node.children else ''
        self.add_var_entry(name, typ, line, init_text)

    def visit_ConstDef(self, node):
        name = node.info.get('name')
        typ = node.info.get('type')
        line = node.src_line

        if typ is None and node.parent and node.parent.kind == 'ConstDecl':
            typ = node.parent.info.get('type')

        if name is not None:
            name = name.strip()

        if name is None or typ is None or (not self.is_identifier_name(name)):
            for ch in node.children:
                self.visit(ch)
            return

        if self.current_scope.lookup_current(name):
            self.add_error(line, 301)
            return

        if node.children:
            self.eval_expr_type(node.children[0])

        value_text = node.children[0].text_without_line() if node.children else ''
        self.add_const_entry(name, typ, line, value_text)

    def visit_AssignStmt(self, node):
        self.eval_expr_type(node)

    def visit_ExprStmt(self, node):
        for ch in node.children:
            self.eval_expr_type(ch)

    def visit_ReturnStmt(self, node):
        for ch in node.children:
            self.eval_expr_type(ch)

    def visit_BreakStmt(self, node):
        if self.loop_depth <= 0 and self.switch_depth <= 0:
            self.add_error(node.src_line, 308)

    def visit_WhileStmt(self, node):
        self.loop_depth += 1
        for ch in node.children:
            self.visit(ch)
        self.loop_depth -= 1

    def visit_ForStmt(self, node):
        self.loop_depth += 1
        for ch in node.children:
            self.visit(ch)
        self.loop_depth -= 1

    def visit_DoWhileStmt(self, node):
        self.loop_depth += 1
        for ch in node.children:
            self.visit(ch)
        self.loop_depth -= 1

    def visit_SwitchStmt(self, node):
        self.switch_depth += 1
        for ch in node.children:
            self.visit(ch)
        self.switch_depth -= 1

    def visit_CaseStmt(self, node):
        for ch in node.children:
            self.visit(ch)
        if not self.case_has_break(node):
            self.add_error(node.end_line(), 308)

    def visit_Call(self, node):
        self.eval_expr_type(node)

    def visit_Operator(self, node):
        self.eval_expr_type(node)

    def visit_Atom(self, node):
        pass

    def write_outputs(self):
        with open('output.txt', 'w', encoding='utf-8') as f:
            for line, code in self.errors:
                f.write(f'{line} {code}\n')

        with open('const.txt', 'w', encoding='utf-8') as f:
            f.write('name\ttype\tvalue\tscope\tline\n')
            for e in self.const_entries:
                f.write(f"{e['name']}\t{e['type']}\t{e['value']}\t{e['scope']}\t{e['line']}\n")

        with open('var.txt', 'w', encoding='utf-8') as f:
            f.write('name\ttype\tinit\tscope\tline\n')
            for e in self.var_entries:
                f.write(f"{e['name']}\t{e['type']}\t{e['init']}\t{e['scope']}\t{e['line']}\n")

        with open('function.txt', 'w', encoding='utf-8') as f:
            f.write('name\treturn_type\tparam_count\tparam_types\tline\n')
            for e in self.function_entries:
                param_types = ','.join(p['type'] for p in e['params'])
                f.write(
                    f"{e['name']}\t{e['return_type']}\t{len(e['params'])}\t{param_types}\t{e['line']}\n"
                )


def main():
    root = parse_ast_file('input.txt')
    analyzer = SemanticAnalyzer(root)
    analyzer.analyze()


if __name__ == '__main__':
    main()