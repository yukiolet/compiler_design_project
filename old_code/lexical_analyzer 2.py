class LexicalErrorAnalyzer:
    ERROR_ILLEGAL_CHAR = 101
    ERROR_BAD_LEXEME = 102
    ERROR_UNCLOSED_COMMENT = 103
    ERROR_UNCLOSED_CHAR = 104
    ERROR_UNCLOSED_STRING = 105

    def __init__(self, text):
        self.text = text
        self.n = len(text)
        self.i = 0
        self.line = 1
        self.errors = []
        self.error_lines = set()   # 每行只输出第一个错误

        self.double_symbols = {
            "<=", ">=", "==", "!=", "&&", "||"
        }

        self.single_symbols = {
            "(", ")", "[", "]", "{", "}", ";", ",",
            "+", "-", "*", "/", "%", "<", ">", "=", "!", "."
        }

    def peek(self, k=1):
        p = self.i + k
        if p < self.n:
            return self.text[p]
        return ""

    def add_error(self, line, code):
        if line not in self.error_lines:
            self.errors.append((line, code))
            self.error_lines.add(line)

    def is_digit(self, ch):
        return '0' <= ch <= '9'

    def is_letter(self, ch):
        return ('a' <= ch <= 'z') or ('A' <= ch <= 'Z')

    def is_ident_start(self, ch):
        return self.is_letter(ch) or ch == '_'

    def is_ident_char(self, ch):
        return self.is_letter(ch) or self.is_digit(ch) or ch == '_'

    def is_hex_digit(self, ch):
        return self.is_digit(ch) or ('a' <= ch <= 'f') or ('A' <= ch <= 'F')

    def scan_identifier(self):
        """
        合法标识符：字母或下划线开头，后接字母/数字/下划线
        所以 hex_lower 是合法的，不应报错。
        """
        while self.i < self.n and self.is_ident_char(self.text[self.i]):
            self.i += 1

    def scan_number(self):
        """
        处理：
        1. 十进制整数
        2. 八进制整数（0开头，只能0-7）
        3. 十六进制整数（0x/0X开头）
        4. 浮点数
        5. 指数形式
        非法情况 -> 102
        """
        s = self.text
        start_line = self.line
        start = self.i

        # 十六进制：0x...
        if s[self.i] == '0' and self.peek() in ('x', 'X'):
            self.i += 2  # skip 0x
            cnt = 0
            while self.i < self.n and self.is_hex_digit(s[self.i]):
                self.i += 1
                cnt += 1

            # 0x 后没有十六进制数字
            if cnt == 0:
                self.add_error(start_line, self.ERROR_BAD_LEXEME)
                return

            # 十六进制后还跟标识符字符，不合法
            if self.i < self.n and self.is_ident_char(s[self.i]):
                while self.i < self.n and self.is_ident_char(s[self.i]):
                    self.i += 1
                self.add_error(start_line, self.ERROR_BAD_LEXEME)
            return

        # 读整数部分
        while self.i < self.n and self.is_digit(s[self.i]):
            self.i += 1

        int_part = s[start:self.i]

        # 八进制非法：0开头且不是浮点/指数时出现8或9
        if len(int_part) > 1 and int_part[0] == '0':
            if self.i >= self.n or s[self.i] not in ".eE":
                for ch in int_part[1:]:
                    if ch in "89":
                        while self.i < self.n and self.is_ident_char(s[self.i]):
                            self.i += 1
                        self.add_error(start_line, self.ERROR_BAD_LEXEME)
                        return

        # 小数部分
        if self.i < self.n and s[self.i] == '.':
            # 小数点后没有数字：20.
            if self.i + 1 >= self.n or (not self.is_digit(s[self.i + 1])):
                self.i += 1
                while self.i < self.n and (
                    self.is_ident_char(s[self.i]) or s[self.i] == '.'
                ):
                    self.i += 1
                self.add_error(start_line, self.ERROR_BAD_LEXEME)
                return

            self.i += 1
            while self.i < self.n and self.is_digit(s[self.i]):
                self.i += 1

            # 多个小数点：1.2.3
            if self.i < self.n and s[self.i] == '.':
                while self.i < self.n and (
                    self.is_ident_char(s[self.i]) or s[self.i] == '.'
                ):
                    self.i += 1
                self.add_error(start_line, self.ERROR_BAD_LEXEME)
                return

        # 指数部分
        if self.i < self.n and s[self.i] in 'eE':
            self.i += 1
            if self.i < self.n and s[self.i] in '+-':
                self.i += 1

            if self.i >= self.n or (not self.is_digit(s[self.i])):
                while self.i < self.n and (
                    self.is_ident_char(s[self.i]) or s[self.i] == '.'
                ):
                    self.i += 1
                self.add_error(start_line, self.ERROR_BAD_LEXEME)
                return

            while self.i < self.n and self.is_digit(s[self.i]):
                self.i += 1

        # 数字后面紧跟标识符字符：12abc
        if self.i < self.n and self.is_ident_char(s[self.i]):
            while self.i < self.n and self.is_ident_char(s[self.i]):
                self.i += 1
            self.add_error(start_line, self.ERROR_BAD_LEXEME)

    def scan_char(self):
        """
        合法：
            'a'
            '\\n'
        102：
            ''
            'ab'
        104：
            缺少闭合 '
        """
        s = self.text
        start_line = self.line
        self.i += 1  # skip '

        if self.i >= self.n or s[self.i] == '\n':
            self.add_error(start_line, self.ERROR_UNCLOSED_CHAR)
            return

        j = self.i
        while j < self.n and s[j] != "'" and s[j] != '\n':
            j += 1

        if j >= self.n or s[j] == '\n':
            self.i = j
            self.add_error(start_line, self.ERROR_UNCLOSED_CHAR)
            return

        content = s[self.i:j]
        self.i = j + 1

        if len(content) == 0:
            self.add_error(start_line, self.ERROR_BAD_LEXEME)
            return

        if content[0] == '\\':
            if len(content) != 2:
                self.add_error(start_line, self.ERROR_BAD_LEXEME)
            return

        if len(content) != 1:
            self.add_error(start_line, self.ERROR_BAD_LEXEME)

    def scan_string(self):
        s = self.text
        start_line = self.line
        self.i += 1  # skip "

        while self.i < self.n:
            ch = s[self.i]
            if ch == '\\':
                self.i += 1
                if self.i < self.n:
                    self.i += 1
            elif ch == '"':
                self.i += 1
                return
            elif ch == '\n':
                self.add_error(start_line, self.ERROR_UNCLOSED_STRING)
                self.line += 1
                self.i += 1
                return
            else:
                self.i += 1

        self.add_error(start_line, self.ERROR_UNCLOSED_STRING)

    def skip_single_comment(self):
        self.i += 2
        while self.i < self.n and self.text[self.i] != '\n':
            self.i += 1

    def skip_multi_comment(self):
        start_line = self.line
        self.i += 2
        while self.i < self.n:
            if self.text[self.i] == '\n':
                self.line += 1
                self.i += 1
            elif self.text[self.i] == '*' and self.peek() == '/':
                self.i += 2
                return
            else:
                self.i += 1
        self.add_error(start_line, self.ERROR_UNCLOSED_COMMENT)

    def analyze(self):
        while self.i < self.n:
            ch = self.text[self.i]

            if ch in ' \t\r':
                self.i += 1
                continue

            if ch == '\n':
                self.line += 1
                self.i += 1
                continue

            # 标识符/关键字：仅允许 ASCII 字母/数字/下划线
            if self.is_ident_start(ch):
                self.scan_identifier()
                continue

            # 数字
            if self.is_digit(ch):
                self.scan_number()
                continue

            # 字符常量
            if ch == "'":
                self.scan_char()
                continue

            # 字符串
            if ch == '"':
                self.scan_string()
                continue

            # 注释 / 除号
            if ch == '/':
                nxt = self.peek()
                if nxt == '/':
                    self.skip_single_comment()
                    continue
                elif nxt == '*':
                    self.skip_multi_comment()
                    continue
                else:
                    self.i += 1
                    continue

            # 双字符运算符
            if self.i + 1 < self.n:
                two = self.text[self.i:self.i + 2]
                if two in self.double_symbols:
                    self.i += 2
                    continue

            # 单字符运算符/界符
            if ch in self.single_symbols:
                self.i += 1
                continue

            # 其他都算非法字符，包括中文、#、@
            self.add_error(self.line, self.ERROR_ILLEGAL_CHAR)
            self.i += 1

        return self.errors


if __name__ == "__main__":
    # 保留非法字符，不能 ignore
    with open("1.txt", "rb") as f:
        code = f.read().decode("utf-8")

    analyzer = LexicalErrorAnalyzer(code)
    errors = analyzer.analyze()

    with open("error.txt", "w") as f:
        for line_no, err_code in errors:
            s = "%d %d" % (line_no, err_code)
            print(s)
            f.write(s + "\n")