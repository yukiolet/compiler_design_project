class Token:
    def __init__(self, lexeme, token_type, line):
        self.lexeme = lexeme
        self.token_type = token_type
        self.line = line

    def __str__(self):
        return "%-15s %-5s %s" % (self.lexeme, self.token_type, self.line)


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
            return self.KEYWORDS[lexeme], lexeme, self.line
        return self.ID_CODE, lexeme, self.line

    def _scan_number(self):
        s = self.source_code
        start = self.index
        start_line = self.line

        # 十六进制整数：0x1A2F / 0xffaa
        if s[self.index] == "0" and self._peek() in ("x", "X"):
            self.index += 2  # 跳过 0x
            while self.index < self.length and self._is_hex_digit(s[self.index]):
                self.index += 1
            lexeme = s[start:self.index]
            return self.INT_CODE, lexeme, start_line

        # 十进制 / 八进制形式（按题目测试，前导0也仍输出400）
        while self.index < self.length and s[self.index].isdigit():
            self.index += 1

        is_float = False

        # 小数部分
        if self.index < self.length and s[self.index] == ".":
            nxt = self._peek()
            if nxt.isdigit():
                is_float = True
                self.index += 1
                while self.index < self.length and s[self.index].isdigit():
                    self.index += 1

        # 指数部分
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
            return self.FLOAT_CODE, lexeme, start_line
        return self.INT_CODE, lexeme, start_line

    def _scan_char_literal(self):
        # 'A' 输出 A, '\n' 输出 \n
        s = self.source_code
        start_line = self.line
        self.index += 1  # skip '

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
            return self.CHAR_CODE, content, start_line

        return None

    def _scan_string_literal(self):
        # "Hello World" 输出 Hello World
        s = self.source_code
        start_line = self.line
        self.index += 1  # skip "

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
                return self.STRING_CODE, content, start_line
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
                return self.SYMBOLS[two], two, self.line

        one = self.source_code[self.index]
        if one in self.SYMBOLS:
            self.index += 1
            return self.SYMBOLS[one], one, self.line

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
                token = self._scan_number()
                if token is not None:
                    result.append(token)
                continue

            if ch == "'":
                token = self._scan_char_literal()
                if token is not None:
                    result.append(token)
                else:
                    self.index += 1
                continue

            if ch == '"':
                token = self._scan_string_literal()
                if token is not None:
                    result.append(token)
                else:
                    self.index += 1
                continue

            if ch == "/":
                nxt = self._peek()
                if nxt == "/":
                    self._skip_single_line_comment()
                    continue
                elif nxt == "*":
                    self._skip_multi_line_comment()
                    continue

            token = self._scan_symbol()
            if token is not None:
                result.append(token)
                continue

            self.index += 1

        return result


if __name__ == "__main__":
    with open("1.txt", "rb") as f:
        test_code = f.read().decode("utf-8", errors="ignore")

    analyzer = LexicalAnalyzer(test_code)
    result = analyzer.analyze()

    with open("result.txt", "w") as f:
        for code, content, row in result:
            t = Token(content, code, row)
            print(t)
            f.write(str(t) + "\n")