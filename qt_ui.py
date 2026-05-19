"""PySide6 interface for the compiler design course project."""

from __future__ import annotations

import importlib.util
from pathlib import Path
import re
import shutil
import subprocess
import sys

from PySide6.QtCore import QPointF, QRect, QRectF, QSize, Qt, QTimer
from PySide6.QtGui import QColor, QFont, QImage, QPainter, QPainterPath, QPen, QSyntaxHighlighter, QTextCharFormat
from PySide6.QtWidgets import (
    QApplication,
    QComboBox,
    QFileDialog,
    QFrame,
    QGraphicsPathItem,
    QGraphicsRectItem,
    QGraphicsScene,
    QGraphicsSimpleTextItem,
    QGraphicsTextItem,
    QGraphicsView,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMainWindow,
    QMessageBox,
    QPushButton,
    QPlainTextEdit,
    QTabWidget,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from modules.cfg import CFGResult, build_cfg, render_basic_blocks, render_cfg_dot
from modules.dag_optimizer import DAGOptimizer
from modules.ide_diagnostics import CLikeIdeDiagnostics
from modules.interpreter import QuadInterpreter, render_interpreter_result
from modules.llvm_converter import LLVMConverter
from modules.quad import EMPTY, Quad, format_quad, read_quads, write_quads
from modules.source_interpreter import (
    SourceInterpreter,
    render_execution_compare,
    render_source_execution,
)


BASE_DIR = Path(__file__).resolve().parent
INPUT_DIR = BASE_DIR / "input"
OUTPUT_DIR = BASE_DIR / "output"
OLD_CODE_DIR = BASE_DIR / "old_code"
KEEP_ASPECT_RATIO = getattr(Qt, "KeepAspectRatio", Qt.AspectRatioMode.KeepAspectRatio)

DEFAULT_SOURCE = """int main() {
    int a;
    int b;
    int c;
    a = 10;
    b = 20;
    c = a + b;
    return c;
}
"""


def make_font(family: str, size: int, bold: bool = False) -> QFont:
    font = QFont(family, size)
    font.setBold(bold)
    return font


def load_module(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Cannot load module: {path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class CLikeHighlighter(QSyntaxHighlighter):
    KEYWORDS = {
        "char", "const", "int", "float", "void", "if", "else", "while",
        "for", "do", "return", "break", "continue",
    }

    def __init__(self, document):
        super().__init__(document)
        self.keyword_format = self.make_format("#2563eb", bold=True)
        self.function_format = self.make_format("#0f766e", bold=True)
        self.number_format = self.make_format("#b45309")
        self.string_format = self.make_format("#be123c")
        self.comment_format = self.make_format("#15803d", italic=True)

    def make_format(self, color: str, bold: bool = False, italic: bool = False) -> QTextCharFormat:
        fmt = QTextCharFormat()
        fmt.setForeground(QColor(color))
        fmt.setFontWeight(QFont.Bold if bold else QFont.Normal)
        fmt.setFontItalic(italic)
        return fmt

    def highlightBlock(self, text: str) -> None:
        for match in re.finditer(r"\b[A-Za-z_]\w*\b", text):
            word = match.group(0)
            if word in self.KEYWORDS:
                self.setFormat(match.start(), len(word), self.keyword_format)

        for match in re.finditer(r"\b[A-Za-z_]\w*(?=\s*\()", text):
            word = match.group(0)
            if word not in self.KEYWORDS:
                self.setFormat(match.start(), len(word), self.function_format)

        for match in re.finditer(r"\b(?:0[xX][0-9a-fA-F]+|\d+)\b", text):
            self.setFormat(match.start(), len(match.group(0)), self.number_format)

        for match in re.finditer(r'"(?:\\.|[^"\\])*"|\'(?:\\.|[^\'\\])*\'', text):
            self.setFormat(match.start(), len(match.group(0)), self.string_format)

        comment_start = text.find("//")
        if comment_start >= 0:
            self.setFormat(comment_start, len(text) - comment_start, self.comment_format)


class CSourceEditor(QPlainTextEdit):
    def __init__(self) -> None:
        super().__init__()
        self.line_number_area = LineNumberArea(self)
        self.blockCountChanged.connect(self.update_line_number_area_width)
        self.updateRequest.connect(self.update_line_number_area)
        self.cursorPositionChanged.connect(self.highlight_current_line)
        self.update_line_number_area_width()
        self.highlight_current_line()

    def line_number_area_width(self) -> int:
        digits = len(str(max(1, self.blockCount())))
        return 18 + self.fontMetrics().horizontalAdvance("9") * digits

    def update_line_number_area_width(self) -> None:
        self.setViewportMargins(self.line_number_area_width(), 0, 0, 0)

    def update_line_number_area(self, rect: QRect, dy: int) -> None:
        if dy:
            self.line_number_area.scroll(0, dy)
        else:
            self.line_number_area.update(0, rect.y(), self.line_number_area.width(), rect.height())
        if rect.contains(self.viewport().rect()):
            self.update_line_number_area_width()

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        content_rect = self.contentsRect()
        self.line_number_area.setGeometry(
            QRect(content_rect.left(), content_rect.top(), self.line_number_area_width(), content_rect.height())
        )

    def line_number_area_paint_event(self, event) -> None:
        painter = QPainter(self.line_number_area)
        painter.fillRect(event.rect(), QColor("#f1f5f9"))
        painter.setPen(QColor("#64748b"))
        painter.setFont(QFont("Consolas", 9))

        block = self.firstVisibleBlock()
        block_number = block.blockNumber()
        top = int(self.blockBoundingGeometry(block).translated(self.contentOffset()).top())
        bottom = top + int(self.blockBoundingRect(block).height())
        width = self.line_number_area.width() - 6

        while block.isValid() and top <= event.rect().bottom():
            if block.isVisible() and bottom >= event.rect().top():
                number = str(block_number + 1)
                painter.drawText(0, top, width, self.fontMetrics().height(), Qt.AlignRight, number)
            block = block.next()
            top = bottom
            bottom = top + int(self.blockBoundingRect(block).height())
            block_number += 1

    def highlight_current_line(self) -> None:
        if self.isReadOnly():
            return
        selection = QTextEdit.ExtraSelection()
        selection.format.setBackground(QColor("#eff6ff"))
        selection.format.setProperty(QTextCharFormat.FullWidthSelection, True)
        selection.cursor = self.textCursor()
        selection.cursor.clearSelection()
        self.setExtraSelections([selection])

    def keyPressEvent(self, event) -> None:
        if event.key() in (Qt.Key_Return, Qt.Key_Enter):
            cursor = self.textCursor()
            current_text = cursor.block().text()
            indent = re.match(r"\s*", current_text).group(0)
            if current_text.rstrip().endswith("{"):
                indent += "    "
            super().keyPressEvent(event)
            self.insertPlainText(indent)
            return
        super().keyPressEvent(event)


class LineNumberArea(QWidget):
    def __init__(self, editor: CSourceEditor) -> None:
        super().__init__(editor)
        self.editor = editor

    def sizeHint(self) -> QSize:
        return QSize(self.editor.line_number_area_width(), 0)

    def paintEvent(self, event) -> None:
        self.editor.line_number_area_paint_event(event)


class CompilerQtUI(QMainWindow):
    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle("编译原理课程设计 - 四元式分析系统")
        self.resize(1280, 820)
        self.setMinimumSize(1080, 680)

        self.quads: list[Quad] = []
        self.generated_quads: list[Quad] = []
        self.quad_source = "file"
        self.cfg: CFGResult | None = None
        self.text_tabs: dict[str, QPlainTextEdit] = {}
        self.ir_module = load_module("ui_intermediate_code", OLD_CODE_DIR / "intermediate_code.py")
        self.ide_diagnostics = CLikeIdeDiagnostics(OLD_CODE_DIR, self.output_dir, self.render_ast_lines)

        self.input_combo = QComboBox()
        self.interpreter_input_edit = QLineEdit()
        self.output_edit = QLineEdit(str(OUTPUT_DIR / "qt_ui"))
        self.status_label = QLabel("请选择四元式输入文件，然后执行分析。")
        self.tabs = QTabWidget()
        self.source_tab = QWidget()
        self.source_editor = CSourceEditor()
        self.source_diagnostics_box = QPlainTextEdit()
        self.source_highlighter = CLikeHighlighter(self.source_editor.document())
        self.ide_timer = QTimer(self)
        self.ide_timer.setSingleShot(True)
        self.ide_timer.setInterval(350)
        self.ide_timer.timeout.connect(self.update_ide_diagnostics)
        self.source_editor.textChanged.connect(self.schedule_ide_diagnostics)
        self.cfg_scene = QGraphicsScene()
        self.cfg_view = QGraphicsView(self.cfg_scene)
        self.cfg_zoom = 1.0
        self.optimized_cfg_scene = QGraphicsScene()
        self.optimized_cfg_view = QGraphicsView(self.optimized_cfg_scene)
        self.optimized_cfg_zoom = 1.0
        self.dag_scene = QGraphicsScene()
        self.dag_view = QGraphicsView(self.dag_scene)
        self.dag_zoom = 1.0

        self.build_ui()
        self.apply_style()
        self.load_input_files()
        self.source_editor.setPlainText(DEFAULT_SOURCE)
        self.load_input_preview()
        self.update_ide_diagnostics()

    def build_ui(self) -> None:
        central = QWidget()
        root = QHBoxLayout(central)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)
        self.setCentralWidget(central)

        sidebar = QFrame()
        sidebar.setObjectName("sidebar")
        sidebar.setFixedWidth(330)
        sidebar_layout = QVBoxLayout(sidebar)
        sidebar_layout.setContentsMargins(22, 24, 22, 20)
        sidebar_layout.setSpacing(12)

        title = QLabel("四元式分析系统")
        title.setObjectName("title")
        subtitle = QLabel("解释执行 · LLVM IR · CFG · DAG 优化")
        subtitle.setObjectName("subtitle")
        sidebar_layout.addWidget(title)
        sidebar_layout.addWidget(subtitle)
        sidebar_layout.addSpacing(14)

        sidebar_layout.addWidget(self.section_label("输入文件"))
        input_row = QHBoxLayout()
        self.input_combo.currentTextChanged.connect(self.load_input_preview)
        input_row.addWidget(self.input_combo, 1)
        browse_input = QPushButton("浏览")
        browse_input.clicked.connect(self.browse_input)
        input_row.addWidget(browse_input)
        sidebar_layout.addLayout(input_row)

        sidebar_layout.addWidget(self.section_label("read 输入"))
        self.interpreter_input_edit.setPlaceholderText("例如：5 10 20")
        self.interpreter_input_edit.setMinimumHeight(34)
        self.interpreter_input_edit.setFont(QFont("Consolas", 9))
        sidebar_layout.addWidget(self.interpreter_input_edit)

        sidebar_layout.addWidget(self.section_label("输出目录"))
        output_row = QHBoxLayout()
        output_row.addWidget(self.output_edit, 1)
        browse_output = QPushButton("选择")
        browse_output.clicked.connect(self.browse_output)
        output_row.addWidget(browse_output)
        sidebar_layout.addLayout(output_row)

        sidebar_layout.addSpacing(10)
        for text, slot, primary in [
            ("源码生成并全流程", self.run_source_full_pipeline, True),
            ("四元式文件全流程", self.run_all, False),
            ("解释执行", self.run_interpreter, False),
            ("生成 LLVM IR", self.run_llvm, False),
            ("验证 LLVM IR", self.run_llvm_verify, False),
            ("基本块 / CFG", self.run_cfg, False),
            ("DAG 局部优化", self.run_dag, False),
            ("打开源码文件", self.browse_source, False),
            ("格式化源码", self.format_source_code, False),
            ("清除结果", self.clear_results, False),
            ("重新载入输入", self.load_input_preview, False),
        ]:
            button = QPushButton(text)
            button.setObjectName("primaryButton" if primary else "sideButton")
            button.clicked.connect(slot)
            button.setMinimumHeight(38)
            sidebar_layout.addWidget(button)

        sidebar_layout.addStretch(1)
        note = QLabel("完整流程：类 C 源码 -> 生成四元式 -> 源码/四元式执行对比 -> LLVM IR -> CFG -> DAG 优化。")
        note.setObjectName("note")
        note.setWordWrap(True)
        sidebar_layout.addWidget(note)

        content = QWidget()
        content_layout = QVBoxLayout(content)
        content_layout.setContentsMargins(18, 18, 18, 14)
        content_layout.setSpacing(12)

        header = QFrame()
        header.setObjectName("header")
        header_layout = QHBoxLayout(header)
        header_layout.setContentsMargins(18, 12, 18, 12)
        header_title = QLabel("编译中间代码处理流程")
        header_title.setObjectName("headerTitle")
        header_layout.addWidget(header_title)
        header_layout.addStretch(1)
        self.status_label.setObjectName("status")
        header_layout.addWidget(self.status_label)
        content_layout.addWidget(header)

        self.build_tabs()
        content_layout.addWidget(self.tabs, 1)

        root.addWidget(sidebar)
        root.addWidget(content, 1)

    def build_tabs(self) -> None:
        for name in [
            "类C源码",
            "输入四元式",
            "Source Verify",
            "解释执行",
            "LLVM IR",
            "LLVM Verify",
            "基本块",
            "CFG DOT",
            "CFG 图",
            "DAG 分析",
            "DAG 图",
            "优化四元式",
            "优化后基本块",
            "优化后 CFG DOT",
            "优化后 CFG 图",
            "优化对比",
        ]:
            if name == "类C源码":
                source_layout = QVBoxLayout(self.source_tab)
                source_layout.setContentsMargins(0, 0, 0, 0)
                source_layout.setSpacing(0)
                self.source_editor.setLineWrapMode(QPlainTextEdit.NoWrap)
                self.source_editor.setFont(QFont("Consolas", 11))
                source_layout.addWidget(self.source_editor, 1)
                self.source_diagnostics_box.setReadOnly(True)
                self.source_diagnostics_box.setLineWrapMode(QPlainTextEdit.NoWrap)
                self.source_diagnostics_box.setFont(QFont("Consolas", 9))
                self.source_diagnostics_box.setMaximumHeight(150)
                self.source_diagnostics_box.setObjectName("diagnosticsBox")
                source_layout.addWidget(self.source_diagnostics_box)
                self.tabs.addTab(self.source_tab, name)
            elif name == "CFG 图":
                cfg_tab = QWidget()
                cfg_layout = QVBoxLayout(cfg_tab)
                cfg_layout.setContentsMargins(8, 8, 8, 8)
                cfg_layout.setSpacing(8)

                toolbar = QHBoxLayout()
                toolbar.addWidget(QLabel("CFG 图可拖动查看"))
                toolbar.addStretch(1)
                for text, slot in [
                    ("放大", self.zoom_cfg_in),
                    ("缩小", self.zoom_cfg_out),
                    ("重置", self.reset_cfg_zoom),
                    ("保存图片", self.save_cfg_image),
                ]:
                    button = QPushButton(text)
                    button.setObjectName("toolbarButton")
                    button.clicked.connect(slot)
                    toolbar.addWidget(button)
                cfg_layout.addLayout(toolbar)

                self.cfg_view.setRenderHint(QPainter.Antialiasing, True)
                self.cfg_view.setDragMode(QGraphicsView.ScrollHandDrag)
                self.cfg_view.setBackgroundBrush(QColor("#ffffff"))
                cfg_layout.addWidget(self.cfg_view, 1)
                self.tabs.addTab(cfg_tab, name)
            elif name == "优化后 CFG 图":
                optimized_cfg_tab = QWidget()
                optimized_cfg_layout = QVBoxLayout(optimized_cfg_tab)
                optimized_cfg_layout.setContentsMargins(8, 8, 8, 8)
                optimized_cfg_layout.setSpacing(8)

                toolbar = QHBoxLayout()
                toolbar.addWidget(QLabel("优化后 CFG 图可拖动查看"))
                toolbar.addStretch(1)
                for text, slot in [
                    ("放大", self.zoom_optimized_cfg_in),
                    ("缩小", self.zoom_optimized_cfg_out),
                    ("重置", self.reset_optimized_cfg_zoom),
                    ("保存图片", self.save_optimized_cfg_image),
                ]:
                    button = QPushButton(text)
                    button.setObjectName("toolbarButton")
                    button.clicked.connect(slot)
                    toolbar.addWidget(button)
                optimized_cfg_layout.addLayout(toolbar)

                self.optimized_cfg_view.setRenderHint(QPainter.Antialiasing, True)
                self.optimized_cfg_view.setDragMode(QGraphicsView.ScrollHandDrag)
                self.optimized_cfg_view.setBackgroundBrush(QColor("#ffffff"))
                optimized_cfg_layout.addWidget(self.optimized_cfg_view, 1)
                self.tabs.addTab(optimized_cfg_tab, name)
            elif name == "DAG 图":
                dag_tab = QWidget()
                dag_layout = QVBoxLayout(dag_tab)
                dag_layout.setContentsMargins(8, 8, 8, 8)
                dag_layout.setSpacing(8)

                toolbar = QHBoxLayout()
                toolbar.addWidget(QLabel("DAG 图红框表示公共子表达式复用节点"))
                toolbar.addStretch(1)
                for text, slot in [
                    ("放大", self.zoom_dag_in),
                    ("缩小", self.zoom_dag_out),
                    ("重置", self.reset_dag_zoom),
                    ("保存图片", self.save_dag_image),
                ]:
                    button = QPushButton(text)
                    button.setObjectName("toolbarButton")
                    button.clicked.connect(slot)
                    toolbar.addWidget(button)
                dag_layout.addLayout(toolbar)

                self.dag_view.setRenderHint(QPainter.Antialiasing, True)
                self.dag_view.setDragMode(QGraphicsView.ScrollHandDrag)
                self.dag_view.setBackgroundBrush(QColor("#ffffff"))
                dag_layout.addWidget(self.dag_view, 1)
                self.tabs.addTab(dag_tab, name)
            else:
                editor = QPlainTextEdit()
                editor.setReadOnly(True)
                editor.setLineWrapMode(QPlainTextEdit.NoWrap)
                editor.setFont(QFont("Consolas", 10))
                self.text_tabs[name] = editor
                self.tabs.addTab(editor, name)

    def section_label(self, text: str) -> QLabel:
        label = QLabel(text)
        label.setObjectName("sectionLabel")
        return label

    def apply_style(self) -> None:
        self.setStyleSheet(
            """
            QMainWindow {
                background: #eef2f7;
            }
            #sidebar {
                background: #111827;
                border: none;
            }
            #title {
                color: #ffffff;
                font-size: 22px;
                font-weight: 700;
            }
            #subtitle {
                color: #a7b3c7;
                font-size: 12px;
            }
            #sectionLabel {
                color: #d1d5db;
                font-size: 12px;
                font-weight: 700;
                margin-top: 8px;
            }
            #note {
                color: #b8c1d1;
                line-height: 1.4;
            }
            QComboBox, QLineEdit {
                min-height: 34px;
                border: 1px solid #334155;
                border-radius: 6px;
                padding: 0 9px;
                color: #f8fafc;
                background: #1f2937;
                selection-background-color: #2563eb;
            }
            QLineEdit::placeholder {
                color: #94a3b8;
            }
            QPushButton {
                border: none;
                border-radius: 6px;
                padding: 8px 12px;
                color: #e5e7eb;
                background: #273449;
                font-weight: 600;
            }
            QPushButton:hover {
                background: #334155;
            }
            QPushButton:pressed {
                background: #1d4ed8;
            }
            #primaryButton {
                color: #ffffff;
                background: #2563eb;
                font-size: 14px;
            }
            #primaryButton:hover {
                background: #1d4ed8;
            }
            #sideButton {
                text-align: left;
            }
            #toolbarButton {
                background: #eef2ff;
                color: #1e3a8a;
                border: 1px solid #bfdbfe;
                padding: 6px 12px;
                text-align: center;
            }
            #toolbarButton:hover {
                background: #dbeafe;
            }
            #header {
                background: #ffffff;
                border: 1px solid #d8dee9;
                border-radius: 8px;
            }
            #headerTitle {
                color: #111827;
                font-size: 18px;
                font-weight: 700;
            }
            #status {
                color: #475569;
            }
            QTabWidget::pane {
                background: #ffffff;
                border: 1px solid #d8dee9;
                border-radius: 8px;
            }
            QTabBar::tab {
                background: #e5eaf2;
                color: #334155;
                padding: 9px 14px;
                margin-right: 2px;
                border-top-left-radius: 6px;
                border-top-right-radius: 6px;
            }
            QTabBar::tab:selected {
                background: #ffffff;
                color: #111827;
                font-weight: 700;
            }
            QPlainTextEdit {
                background: #ffffff;
                color: #111827;
                border: none;
                padding: 10px;
                selection-background-color: #bfdbfe;
            }
            #diagnosticsBox {
                background: #f8fafc;
                color: #334155;
                border-top: 1px solid #d8dee9;
                padding: 8px 10px;
            }
            QGraphicsView {
                border: none;
            }
            """
        )

    def load_input_files(self) -> None:
        self.input_combo.clear()
        if INPUT_DIR.exists():
            for path in sorted(INPUT_DIR.glob("*.txt")):
                self.input_combo.addItem(str(path))

    def current_input_path(self) -> Path:
        return Path(self.input_combo.currentText())

    def output_dir(self) -> Path:
        path = Path(self.output_edit.text())
        path.mkdir(parents=True, exist_ok=True)
        return path

    def browse_input(self) -> None:
        file_path, _ = QFileDialog.getOpenFileName(
            self,
            "选择四元式输入文件",
            str(INPUT_DIR),
            "Text Files (*.txt);;All Files (*)",
        )
        if file_path:
            if self.input_combo.findText(file_path) < 0:
                self.input_combo.addItem(file_path)
            self.input_combo.setCurrentText(file_path)
            self.load_input_preview()

    def browse_output(self) -> None:
        directory = QFileDialog.getExistingDirectory(self, "选择输出目录", str(OUTPUT_DIR))
        if directory:
            self.output_edit.setText(directory)

    def set_text(self, tab: str, content: str) -> None:
        self.text_tabs[tab].setPlainText(content)

    def load_quads(self) -> list[Quad]:
        if self.quad_source == "source" and self.generated_quads:
            self.quads = self.generated_quads
            return self.quads
        path = self.current_input_path()
        quads = read_quads(path)
        if not quads:
            raise RuntimeError(f"输入文件没有可解析的四元式：{path}")
        self.quad_source = "file"
        self.quads = quads
        return quads

    def load_input_preview(self) -> None:
        try:
            self.quad_source = "file"
            path = self.current_input_path()
            if path.exists():
                self.set_text("输入四元式", path.read_text(encoding="utf-8"))
                self.status_label.setText(f"已载入：{path.name}")
            else:
                self.set_text("输入四元式", "")
                self.status_label.setText("输入文件不存在。")
        except Exception as exc:
            self.show_error(exc)

    def interpreter_inputs(self) -> list[int]:
        text = self.interpreter_input_edit.text()
        if not text.strip():
            return []
        values: list[int] = []
        for token in re.split(r"[\s,;]+", text.strip()):
            if not token:
                continue
            try:
                values.append(int(token, 0))
            except ValueError as exc:
                raise RuntimeError(f"read 输入只能包含整数，无法解析：{token}") from exc
        return values

    def browse_source(self) -> None:
        file_path, _ = QFileDialog.getOpenFileName(
            self,
            "打开类 C 源码",
            str(BASE_DIR),
            "C Files (*.c *.txt);;All Files (*)",
        )
        if file_path:
            self.source_editor.setPlainText(Path(file_path).read_text(encoding="utf-8"))
            self.tabs.setCurrentWidget(self.source_tab)
            self.status_label.setText(f"已打开源码：{Path(file_path).name}")

    def schedule_ide_diagnostics(self) -> None:
        self.ide_timer.start()

    def update_ide_diagnostics(self) -> None:
        source = self.source_editor.toPlainText()
        diagnostics = self.ide_diagnostics.analyze(source)
        self.source_diagnostics_box.setPlainText(diagnostics)
        try:
            (self.output_dir() / "ide_diagnostics.txt").write_text(diagnostics, encoding="utf-8")
        except Exception:
            pass

    def render_ast_lines(self, root) -> str:
        parser_module = load_module("ui_parser_for_ide_ast", OLD_CODE_DIR / "parser.py")
        return "\n".join(line.rstrip() for line in parser_module.ast_lines(root)) + "\n"

    def format_source_code(self) -> None:
        formatted = self.format_c_like_source(self.source_editor.toPlainText())
        self.source_editor.blockSignals(True)
        self.source_editor.setPlainText(formatted)
        self.source_editor.blockSignals(False)
        self.update_ide_diagnostics()
        self.status_label.setText("源码缩进格式化完成。")

    def format_c_like_source(self, source: str) -> str:
        indent = 0
        result: list[str] = []
        for raw_line in source.splitlines():
            stripped = raw_line.strip()
            if not stripped:
                result.append("")
                continue
            if stripped.startswith("}"):
                indent = max(0, indent - 1)
            result.append("    " * indent + stripped)
            opens = stripped.count("{")
            closes = stripped.count("}")
            indent = max(0, indent + opens - closes)
        return "\n".join(result) + "\n"

    def run_source_full_pipeline(self) -> None:
        try:
            self.compile_source_to_quads()
            self.run_interpreter(show_done=False)
            self.run_llvm(show_done=False)
            self.run_cfg(show_done=False)
            self.run_dag(show_done=False)
            self.status_label.setText(f"源码到四元式完整分析流程完成：{self.output_dir()}")
        except Exception as exc:
            self.show_error(exc)

    def compile_source_to_quads(self) -> list[Quad]:
        source = self.source_editor.toPlainText()
        if not source.strip():
            raise RuntimeError("类 C 源码为空")

        tokens = self.ir_module.LexicalAnalyzer(source).analyze()
        ast_root = self.ir_module.Parser(tokens).parse()
        raw_quads = self.ir_module.IntermediateCodeGenerator().generate(ast_root)
        quads = self.to_quad_objects(raw_quads, ast_root)
        quad_text = self.render_quads(quads)

        read_inputs = self.interpreter_inputs()
        source_result = SourceInterpreter(ast_root, input_values=read_inputs).run()
        quad_result = QuadInterpreter(quads, input_values=read_inputs).run()
        source_text = render_source_execution(source_result)
        quad_text_result = render_interpreter_result(quad_result)
        compare_text = render_execution_compare(source_result, quad_result)
        validation_text = (
            compare_text
            + "\n"
            + "=" * 72
            + "\n\n"
            + source_text
            + "\n"
            + "=" * 72
            + "\n\n"
            + quad_text_result
        )

        self.generated_quads = quads
        self.quad_source = "source"
        self.quads = quads
        self.set_text("输入四元式", quad_text)
        self.set_text("Source Verify", validation_text)

        out = self.output_dir()
        (out / "source.c").write_text(source, encoding="utf-8")
        (out / "generated_quads.txt").write_text(quad_text, encoding="utf-8")
        (out / "source_execution.txt").write_text(source_text, encoding="utf-8")
        (out / "quad_execution_from_source.txt").write_text(quad_text_result, encoding="utf-8")
        (out / "execution_compare.txt").write_text(compare_text, encoding="utf-8")
        return quads

    def render_quads(self, quads: list[Quad]) -> str:
        return "\n".join(format_quad(quad) for quad in quads) + "\n"

    def to_quad_objects(self, quads, ast_root=None) -> list[Quad]:
        function_params = self.extract_function_params(ast_root) if ast_root is not None else {}
        result: list[Quad] = []
        for index, quad in enumerate(quads):
            op, arg1, arg2, target = quad
            clean_op = self.clean_quad_field(op)
            params = function_params.get(clean_op, [])
            if params and self.clean_quad_field(arg1) == EMPTY and self.clean_quad_field(arg2) == EMPTY and self.clean_quad_field(target) == EMPTY:
                arg1 = params[0] if len(params) > 0 else EMPTY
                arg2 = params[1] if len(params) > 1 else EMPTY
                target = params[2] if len(params) > 2 else EMPTY
            result.append(
                Quad(
                    index,
                    clean_op,
                    self.clean_quad_field(arg1),
                    self.clean_quad_field(arg2),
                    self.clean_quad_field(target),
                )
            )
        return result

    def extract_function_params(self, root) -> dict[str, list[str]]:
        params_by_function: dict[str, list[str]] = {}
        if root is None:
            return params_by_function
        for child in getattr(root, "children", []):
            if getattr(child, "kind", "") != "FunctionDef":
                continue
            name = self.ast_function_name(child)
            params = []
            for param in getattr(child, "children", []):
                if getattr(param, "kind", "") == "Param":
                    params.append(self.ast_declared_name(param))
            if name and params:
                params_by_function[name] = params
        return params_by_function

    def ast_function_name(self, node) -> str:
        parts = str(getattr(node, "value", "")).split()
        return parts[-1] if parts else ""

    def ast_declared_name(self, node) -> str:
        parts = str(getattr(node, "value", "")).split()
        return parts[-1] if parts else ""

    def clean_quad_field(self, value) -> str:
        if value is None:
            return EMPTY
        text = str(value).strip()
        return text if text else EMPTY

    def run_all(self) -> None:
        try:
            self.quad_source = "file"
            self.set_quad_file_verify_placeholder()
            self.run_interpreter(show_done=False)
            self.run_llvm(show_done=False)
            self.run_cfg(show_done=False)
            self.run_dag(show_done=False)
            self.status_label.setText(f"全部执行完成：{self.output_dir()}")
        except Exception as exc:
            self.show_error(exc)

    def run_interpreter(self, show_done: bool = True) -> None:
        try:
            result = QuadInterpreter(self.load_quads(), input_values=self.interpreter_inputs()).run()
            content = render_interpreter_result(result)
            self.set_text("解释执行", content)
            (self.output_dir() / "interpreter_result.txt").write_text(content, encoding="utf-8")
            if self.quad_source == "file":
                self.set_quad_file_verify_result(content)
            if show_done:
                self.status_label.setText("解释执行完成。")
        except Exception as exc:
            self.show_error(exc)

    def set_quad_file_verify_placeholder(self) -> None:
        content = (
            "Quad File Verify\n\n"
            "当前流程使用的是四元式文件输入，没有类 C 源码 AST，因此不能进行 Source vs Quad 对比。\n"
            "系统将对本次四元式执行结果进行独立验证展示。\n"
        )
        self.set_text("Source Verify", content)
        (self.output_dir() / "execution_compare.txt").write_text(content, encoding="utf-8")

    def set_quad_file_verify_result(self, interpreter_text: str) -> None:
        content = (
            "Quad File Verify\n\n"
            "当前流程使用的是四元式文件输入，没有类 C 源码 AST，因此不能进行 Source vs Quad 对比。\n"
            "下面展示本次四元式解释器的实际执行结果，可用于验证 3.2 解释执行功能。\n\n"
            + "=" * 72
            + "\n\n"
            + interpreter_text
        )
        self.set_text("Source Verify", content)
        (self.output_dir() / "execution_compare.txt").write_text(content, encoding="utf-8")

    def run_llvm(self, show_done: bool = True) -> None:
        try:
            content = LLVMConverter(self.load_quads(), input_values=self.interpreter_inputs()).convert()
            self.set_text("LLVM IR", content)
            (self.output_dir() / "llvm_ir.ll").write_text(content, encoding="utf-8")
            if show_done:
                self.status_label.setText("LLVM IR 生成完成。")
        except Exception as exc:
            self.show_error(exc)

    def run_llvm_verify(self, show_done: bool = True) -> None:
        try:
            out = self.output_dir()
            out.mkdir(parents=True, exist_ok=True)
            llvm_path = out / "llvm_ir.ll"
            self.run_llvm(show_done=False)
            if not llvm_path.exists() or not llvm_path.read_text(encoding="utf-8").strip():
                raise RuntimeError("LLVM IR 尚未生成，请先检查输入四元式或源码生成流程。")

            clang_path = self.find_clang()
            if not clang_path:
                content = self.render_llvm_verify_missing_clang()
                self.set_text("LLVM Verify", content)
                (out / "llvm_verify.txt").write_text(content, encoding="utf-8")
                self.tabs.setCurrentWidget(self.text_tabs["LLVM Verify"])
                self.status_label.setText("LLVM 验证失败：未找到 clang。")
                return

            obj_path = out / "llvm_ir.obj"
            exe_path = out / "llvm_ir.exe"
            compile_command = [clang_path, "-c", str(llvm_path), "-o", str(obj_path)]
            compile_result = subprocess.run(
                compile_command,
                cwd=str(BASE_DIR),
                capture_output=True,
                text=True,
                timeout=30,
            )

            obj_passed = compile_result.returncode == 0 and obj_path.exists()
            link_command = [clang_path, str(llvm_path), "-o", str(exe_path)]
            link_result = None
            run_result = None
            if obj_passed:
                link_result = subprocess.run(
                    link_command,
                    cwd=str(BASE_DIR),
                    capture_output=True,
                    text=True,
                    timeout=30,
                )
                if link_result.returncode == 0 and exe_path.exists():
                    run_result = subprocess.run(
                        [str(exe_path)],
                        cwd=str(BASE_DIR),
                        capture_output=True,
                        text=True,
                        timeout=10,
                    )

            content = self.render_llvm_verify_result(
                compile_command,
                compile_result,
                obj_passed,
                link_command,
                link_result,
                run_result,
                llvm_path,
                obj_path,
                exe_path,
            )
            self.set_text("LLVM Verify", content)
            (out / "llvm_verify.txt").write_text(content, encoding="utf-8")
            self.tabs.setCurrentWidget(self.text_tabs["LLVM Verify"])
            if show_done:
                if obj_passed:
                    self.status_label.setText("LLVM 外部验证通过：已生成 obj，并已尝试链接运行 exe。")
                else:
                    self.status_label.setText("LLVM 外部验证失败：请查看 LLVM Verify 页签。")
        except subprocess.TimeoutExpired as exc:
            content = "LLVM Verify\n\nResult: FAIL\nReason: clang 验证超时。\n"
            self.set_text("LLVM Verify", content)
            (self.output_dir() / "llvm_verify.txt").write_text(content, encoding="utf-8")
            self.status_label.setText("LLVM 外部验证超时。")
        except Exception as exc:
            self.show_error(exc)

    def find_clang(self) -> str | None:
        path_clang = shutil.which("clang")
        if path_clang:
            return path_clang

        candidates: list[Path] = [
            Path("E:/app/vs2022/VC/Tools/Llvm/bin/clang.exe"),
            Path("E:/app/vs2022/VC/Tools/Llvm/x64/bin/clang.exe"),
            Path("C:/Program Files/Microsoft Visual Studio/2026/BuildTools/VC/Tools/Llvm/bin/clang.exe"),
            Path("C:/Program Files/Microsoft Visual Studio/2026/BuildTools/VC/Tools/Llvm/x64/bin/clang.exe"),
            Path("C:/Program Files/Microsoft Visual Studio/2022/BuildTools/VC/Tools/Llvm/bin/clang.exe"),
            Path("C:/Program Files/Microsoft Visual Studio/2022/BuildTools/VC/Tools/Llvm/x64/bin/clang.exe"),
        ]

        vswhere_paths = [
            Path("C:/Program Files (x86)/Microsoft Visual Studio/Installer/vswhere.exe"),
            Path("C:/Program Files/Microsoft Visual Studio/Installer/vswhere.exe"),
        ]
        for vswhere in vswhere_paths:
            if not vswhere.exists():
                continue
            try:
                result = subprocess.run(
                    [str(vswhere), "-products", "*", "-property", "installationPath"],
                    capture_output=True,
                    text=True,
                    timeout=10,
                )
            except Exception:
                continue
            for line in result.stdout.splitlines():
                install = Path(line.strip())
                if install:
                    candidates.extend([
                        install / "VC/Tools/Llvm/bin/clang.exe",
                        install / "VC/Tools/Llvm/x64/bin/clang.exe",
                    ])

        for root in [Path("E:/app"), Path("C:/Program Files/Microsoft Visual Studio")]:
            if not root.exists():
                continue
            for pattern in ["*/VC/Tools/Llvm/bin/clang.exe", "*/VC/Tools/Llvm/x64/bin/clang.exe"]:
                candidates.extend(root.glob(pattern))

        for candidate in candidates:
            if candidate.exists():
                return str(candidate)
        return None

    def render_llvm_verify_missing_clang(self) -> str:
        return (
            "LLVM Verify\n\n"
            "Result: FAIL\n"
            "Reason: 未找到 clang.exe。\n\n"
            "解决方法：\n"
            "1. 打开 Visual Studio Installer，确认已安装 C++ Clang Compiler for Windows。\n"
            "2. 或者从 Visual Studio 2026 Developer Command Prompt 启动本 UI。\n"
            "3. 也可以在 Developer Command Prompt 中手动执行：\n\n"
            f"   cd /d {BASE_DIR}\n"
            "   clang -c output\\qt_ui\\llvm_ir.ll -o output\\qt_ui\\llvm_ir.obj\n"
            "   clang output\\qt_ui\\llvm_ir.ll -o output\\qt_ui\\llvm_ir.exe\n"
            "   output\\qt_ui\\llvm_ir.exe\n"
        )

    def render_llvm_verify_result(
        self,
        compile_command: list[str],
        compile_result: subprocess.CompletedProcess,
        obj_passed: bool,
        link_command: list[str],
        link_result: subprocess.CompletedProcess | None,
        run_result: subprocess.CompletedProcess | None,
        llvm_path: Path,
        obj_path: Path,
        exe_path: Path,
    ) -> str:
        compile_command_text = self.format_command(compile_command)
        link_command_text = self.format_command(link_command)
        link_passed = link_result is not None and link_result.returncode == 0 and exe_path.exists()
        run_completed = run_result is not None
        full_passed = obj_passed and link_passed and run_completed
        return (
            "LLVM Verify\n\n"
            f"Input IR: {llvm_path}\n"
            f"Output OBJ: {obj_path}\n"
            f"Output EXE: {exe_path}\n\n"
            "Step 9: clang -c 生成目标文件\n"
            f"Command: {compile_command_text}\n"
            f"Return code: {compile_result.returncode}\n"
            f"Result: {'PASS' if obj_passed else 'FAIL'}\n\n"
            "Step 10: clang 链接生成 exe\n"
            f"Command: {link_command_text}\n"
            f"Return code: {link_result.returncode if link_result is not None else 'SKIP'}\n"
            f"Result: {'PASS' if link_passed else ('FAIL' if link_result is not None else 'SKIP')}\n\n"
            "Step 10: 运行 exe\n"
            f"Command: {exe_path}\n"
            f"Exit code: {run_result.returncode if run_result is not None else 'SKIP'}\n"
            f"Result: {'COMPLETED' if run_completed else 'SKIP'}\n\n"
            f"Overall Result: {'FULL PASS' if full_passed else ('OBJ PASS' if obj_passed else 'FAIL')}\n\n"
            "说明：\n"
            "- Step 9 PASS 表示生成的 LLVM IR 已被 clang 接受，并成功编译为目标文件 .obj。\n"
            "- Step 10 PASS 表示该 IR 进一步完成链接并生成 .exe；运行 exe 的 Exit code 可能就是 main 的返回值，不一定必须为 0。\n"
            "- warning 不等于失败；只要 Return code 为 0 且对应文件存在，即可作为验证通过证据。\n"
            "- read() 会使用 UI 左侧 read 输入生成的固定输入序列；write() 为教学用最小桩函数，不在控制台打印，但不影响返回值验证。\n\n"
            "Step 9 stdout:\n"
            f"{compile_result.stdout.strip() or '(empty)'}\n\n"
            "Step 9 stderr:\n"
            f"{compile_result.stderr.strip() or '(empty)'}\n\n"
            "Step 10 link stdout:\n"
            f"{link_result.stdout.strip() if link_result and link_result.stdout.strip() else '(empty)'}\n\n"
            "Step 10 link stderr:\n"
            f"{link_result.stderr.strip() if link_result and link_result.stderr.strip() else '(empty)'}\n\n"
            "Step 10 run stdout:\n"
            f"{run_result.stdout.strip() if run_result and run_result.stdout.strip() else '(empty)'}\n\n"
            "Step 10 run stderr:\n"
            f"{run_result.stderr.strip() if run_result and run_result.stderr.strip() else '(empty)'}\n"
        )

    def format_command(self, command: list[str]) -> str:
        return " ".join(f'"{part}"' if " " in part else part for part in command)

    def run_cfg(self, show_done: bool = True) -> None:
        try:
            self.cfg = build_cfg(self.load_quads())
            blocks = render_basic_blocks(self.cfg)
            dot = render_cfg_dot(self.cfg)
            self.set_text("基本块", blocks)
            self.set_text("CFG DOT", dot)
            self.draw_cfg(self.cfg)
            out = self.output_dir()
            (out / "basic_blocks.txt").write_text(blocks, encoding="utf-8")
            (out / "cfg.dot").write_text(dot, encoding="utf-8")
            if show_done:
                self.status_label.setText("基本块和 CFG 构建完成。")
        except Exception as exc:
            self.show_error(exc)

    def run_dag(self, show_done: bool = True) -> None:
        try:
            cfg = build_cfg(self.load_quads())
            self.cfg = cfg
            optimization = DAGOptimizer(cfg).optimize()
            optimized_text = "\n".join(format_quad(quad, i) for i, quad in enumerate(optimization.optimized_quads)) + "\n"
            optimized_cfg = build_cfg(optimization.optimized_quads)
            optimized_blocks = render_basic_blocks(optimized_cfg)
            optimized_dot = render_cfg_dot(optimized_cfg)
            self.set_text("DAG 分析", optimization.dag_report)
            self.set_text("优化四元式", optimized_text)
            self.set_text("优化后基本块", optimized_blocks)
            self.set_text("优化后 CFG DOT", optimized_dot)
            self.set_text("优化对比", optimization.compare_report)
            self.draw_dag(cfg)
            self.draw_optimized_cfg(optimized_cfg)
            out = self.output_dir()
            write_quads(out / "optimized_quads.txt", optimization.optimized_quads)
            (out / "dag_blocks.txt").write_text(optimization.dag_report, encoding="utf-8")
            (out / "compare_report.txt").write_text(optimization.compare_report, encoding="utf-8")
            (out / "optimized_basic_blocks.txt").write_text(optimized_blocks, encoding="utf-8")
            (out / "optimized_cfg.dot").write_text(optimized_dot, encoding="utf-8")
            if show_done:
                self.status_label.setText("DAG 局部优化和优化后 CFG 构建完成。")
        except Exception as exc:
            self.show_error(exc)

    def clear_results(self) -> None:
        for tab in [
            "Source Verify",
            "解释执行",
            "LLVM IR",
            "LLVM Verify",
            "基本块",
            "CFG DOT",
            "DAG 分析",
            "优化四元式",
            "优化后基本块",
            "优化后 CFG DOT",
            "优化对比",
        ]:
            self.set_text(tab, "")
        self.cfg_scene.clear()
        self.optimized_cfg_scene.clear()
        self.dag_scene.clear()
        self.cfg = None
        self.status_label.setText("结果已清除，可以继续测试下一组数据。")

    def zoom_cfg_in(self) -> None:
        self.cfg_zoom = min(self.cfg_zoom * 1.2, 3.0)
        self.apply_cfg_zoom()

    def zoom_cfg_out(self) -> None:
        self.cfg_zoom = max(self.cfg_zoom / 1.2, 0.6)
        self.apply_cfg_zoom()

    def reset_cfg_zoom(self) -> None:
        self.cfg_zoom = 1.25
        self.apply_cfg_zoom()

    def apply_cfg_zoom(self) -> None:
        self.cfg_view.resetTransform()
        self.cfg_view.scale(self.cfg_zoom, self.cfg_zoom)

    def zoom_optimized_cfg_in(self) -> None:
        self.optimized_cfg_zoom = min(self.optimized_cfg_zoom * 1.2, 3.0)
        self.apply_optimized_cfg_zoom()

    def zoom_optimized_cfg_out(self) -> None:
        self.optimized_cfg_zoom = max(self.optimized_cfg_zoom / 1.2, 0.6)
        self.apply_optimized_cfg_zoom()

    def reset_optimized_cfg_zoom(self) -> None:
        self.optimized_cfg_zoom = 1.25
        self.apply_optimized_cfg_zoom()

    def apply_optimized_cfg_zoom(self) -> None:
        self.optimized_cfg_view.resetTransform()
        self.optimized_cfg_view.scale(self.optimized_cfg_zoom, self.optimized_cfg_zoom)

    def zoom_dag_in(self) -> None:
        self.dag_zoom = min(self.dag_zoom * 1.2, 3.0)
        self.apply_dag_zoom()

    def zoom_dag_out(self) -> None:
        self.dag_zoom = max(self.dag_zoom / 1.2, 0.6)
        self.apply_dag_zoom()

    def reset_dag_zoom(self) -> None:
        self.dag_zoom = 1.15
        self.apply_dag_zoom()

    def apply_dag_zoom(self) -> None:
        self.dag_view.resetTransform()
        self.dag_view.scale(self.dag_zoom, self.dag_zoom)

    def save_cfg_image(self) -> None:
        self.save_scene_image(self.cfg_scene, "cfg_graph.png")

    def save_optimized_cfg_image(self) -> None:
        self.save_scene_image(self.optimized_cfg_scene, "optimized_cfg_graph.png")

    def save_dag_image(self) -> None:
        self.save_scene_image(self.dag_scene, "dag_graph.png")

    def save_scene_image(self, scene: QGraphicsScene, default_name: str) -> None:
        if scene.itemsBoundingRect().isEmpty():
            QMessageBox.information(self, "没有可保存的图", "请先生成图形结果。")
            return
        default_path = self.output_dir() / default_name
        file_path, _ = QFileDialog.getSaveFileName(
            self,
            "保存图片",
            str(default_path),
            "PNG Image (*.png)",
        )
        if not file_path:
            return
        rect = scene.itemsBoundingRect().adjusted(-30, -30, 30, 30)
        image = QImage(int(rect.width()), int(rect.height()), QImage.Format_ARGB32)
        image.fill(QColor("#ffffff"))
        painter = QPainter(image)
        scene.render(painter, QRectF(image.rect()), rect)
        painter.end()
        image.save(file_path)
        self.status_label.setText(f"图片已保存：{file_path}")

    def draw_cfg(self, cfg: CFGResult) -> None:
        self.draw_cfg_scene(cfg, self.cfg_scene, self.cfg_view, optimized=False)

    def draw_optimized_cfg(self, cfg: CFGResult) -> None:
        self.draw_cfg_scene(cfg, self.optimized_cfg_scene, self.optimized_cfg_view, optimized=True)

    def draw_cfg_scene(self, cfg: CFGResult, scene: QGraphicsScene, view: QGraphicsView, optimized: bool) -> None:
        scene.clear()
        if not cfg.blocks:
            return

        positions: dict[str, QRectF] = {}
        levels: dict[str, int] = {}
        margin_x = 80
        margin_y = 82
        component_gap = 100
        gap_x = 88
        gap_y = 120
        max_width = 0
        max_height = margin_y

        title_text = "Optimized CFG Control Flow Graph" if optimized else "CFG Control Flow Graph"
        title = QGraphicsSimpleTextItem(title_text)
        title.setFont(make_font("Arial", 17, True))
        title.setBrush(QColor("#111827"))
        title.setPos(margin_x, 20)
        scene.addItem(title)

        current_component_x = margin_x
        for component in self.cfg_components(cfg):
            component_levels = self.compute_component_levels(component)
            levels.update(component_levels)
            rows: dict[int, list] = {}
            for block in component:
                rows.setdefault(component_levels.get(block.name, 0), []).append(block)

            row_sizes: dict[int, list[tuple[int, int]]] = {}
            row_widths: dict[int, int] = {}
            row_heights: dict[int, int] = {}
            component_width = 0
            for level, blocks in rows.items():
                sizes = [self.block_size(block) for block in blocks]
                row_sizes[level] = sizes
                row_width = sum(size[0] for size in sizes) + gap_x * max(0, len(sizes) - 1)
                row_height = max(size[1] for size in sizes)
                row_widths[level] = row_width
                row_heights[level] = row_height
                component_width = max(component_width, row_width)

            current_y = margin_y
            for level in sorted(rows):
                blocks = rows[level]
                sizes = row_sizes[level]
                current_x = current_component_x + (component_width - row_widths[level]) / 2
                row_height = row_heights[level]
                for block, (width, height) in zip(blocks, sizes):
                    rect = QRectF(current_x, current_y, width, height)
                    positions[block.name] = rect
                    self.add_block_item(block, rect, scene)
                    current_x += width + gap_x
                    max_width = max(max_width, current_x)
                current_y += row_height + gap_y
            max_height = max(max_height, current_y)
            current_component_x += component_width + component_gap

        for block in cfg.blocks:
            for succ in sorted(block.successors):
                if succ not in positions:
                    continue
                self.add_edge_item(
                    positions[block.name],
                    positions[succ],
                    levels[block.name],
                    levels[succ],
                    scene,
                    positions,
                )

        scene.setSceneRect(0, 0, max_width + margin_x, max_height + margin_y)
        if optimized:
            self.optimized_cfg_zoom = 1.0
            self.apply_optimized_cfg_zoom()
        else:
            self.cfg_zoom = 1.0
            self.apply_cfg_zoom()
        view.centerOn(scene.itemsBoundingRect().center())

    def cfg_components(self, cfg: CFGResult) -> list[list]:
        neighbors = {block.name: set(block.successors) | set(block.predecessors) for block in cfg.blocks}
        visited: set[str] = set()
        components: list[list] = []
        for block in cfg.blocks:
            if block.name in visited:
                continue
            stack = [block.name]
            names: set[str] = set()
            while stack:
                name = stack.pop()
                if name in visited:
                    continue
                visited.add(name)
                names.add(name)
                stack.extend(sorted(neighbors.get(name, set()) - visited, reverse=True))
            components.append([item for item in cfg.blocks if item.name in names])
        return components

    def compute_component_levels(self, blocks: list) -> dict[str, int]:
        block_order = {block.name: pos for pos, block in enumerate(blocks)}
        names = set(block_order)
        levels = {block.name: 0 for block in blocks}
        changed = True
        while changed:
            changed = False
            for block in blocks:
                for succ in sorted(block.successors):
                    if succ not in names or block_order[succ] <= block_order[block.name]:
                        continue
                    next_level = levels[block.name] + 1
                    if next_level > levels[succ]:
                        levels[succ] = next_level
                        changed = True
        return levels

    def compute_levels(self, cfg: CFGResult) -> dict[str, int]:
        if not cfg.blocks:
            return {}
        block_order = {block.name: pos for pos, block in enumerate(cfg.blocks)}
        levels = {block.name: 0 for block in cfg.blocks}

        changed = True
        while changed:
            changed = False
            for block in cfg.blocks:
                for succ in sorted(block.successors):
                    if block_order[succ] <= block_order[block.name]:
                        continue
                    next_level = levels[block.name] + 1
                    if next_level > levels[succ]:
                        levels[succ] = next_level
                        changed = True
        return levels

    def block_size(self, block) -> tuple[int, int]:
        lines = [format_quad(quad) for quad in block.quads]
        max_chars = max([len(block.name)] + [len(line) for line in lines])
        width = max(330, min(720, max_chars * 10 + 78))
        height = max(120, 56 + len(lines) * 26)
        return width, height

    def add_block_item(self, block, rect: QRectF, scene: QGraphicsScene) -> None:
        item = QGraphicsRectItem(rect)
        item.setBrush(QColor("#ffffff"))
        item.setPen(QPen(QColor("#111111"), 1.4))
        scene.addItem(item)

        name = QGraphicsSimpleTextItem(block.name)
        name.setFont(make_font("Arial", 16, True))
        name.setBrush(QColor("#000000"))
        name_rect = name.boundingRect()
        name.setPos(rect.left() + (rect.width() - name_rect.width()) / 2, rect.top() + 5)
        scene.addItem(name)

        y = rect.top() + 42
        for quad in block.quads:
            line = QGraphicsSimpleTextItem(format_quad(quad))
            line.setFont(QFont("Consolas", 13))
            line.setBrush(QColor("#000000"))
            line.setPos(rect.left() + 14, y)
            scene.addItem(line)
            y += 25

    def add_edge_item(
        self,
        start: QRectF,
        end: QRectF,
        start_level: int,
        end_level: int,
        scene: QGraphicsScene,
        positions: dict[str, QRectF],
    ) -> None:
        path = QPainterPath()
        is_back_edge = end_level < start_level
        is_same_level = end_level == start_level

        if is_back_edge:
            use_left = start.center().x() <= end.center().x()
            if use_left:
                start_point = QPointF(start.left(), start.center().y())
                end_point = QPointF(end.left(), end.center().y())
                side_x = self.free_side_x(positions, start, end, left=True)
                arrow_direction = "right"
            else:
                start_point = QPointF(start.right(), start.center().y())
                end_point = QPointF(end.right(), end.center().y())
                side_x = self.free_side_x(positions, start, end, left=False)
                arrow_direction = "left"
            path.moveTo(start_point)
            path.cubicTo(
                QPointF(side_x, start.center().y()),
                QPointF(side_x, end.center().y()),
                end_point,
            )
        elif is_same_level:
            if start.center().x() <= end.center().x():
                start_point = QPointF(start.right(), start.center().y())
                end_point = QPointF(end.left(), end.center().y())
                arrow_direction = "right"
            else:
                start_point = QPointF(start.left(), start.center().y())
                end_point = QPointF(end.right(), end.center().y())
                arrow_direction = "left"
            middle_y = min(start.top(), end.top()) - 34
            path.moveTo(start_point)
            path.cubicTo(
                QPointF(start_point.x(), middle_y),
                QPointF(end_point.x(), middle_y),
                end_point,
            )
        else:
            start_point = QPointF(start.center().x(), start.bottom())
            end_point = QPointF(end.center().x(), end.top())
            path.moveTo(start_point)
            if end_level - start_level == 1:
                path.lineTo(end_point)
            elif abs(start.center().x() - end.center().x()) < 28:
                path.lineTo(end_point)
            else:
                side_x = self.free_side_x(positions, start, end, left=start.center().x() > end.center().x())
                lower_y = start.bottom() + 34
                upper_y = end.top() - 34
                path.lineTo(QPointF(start.center().x(), lower_y))
                path.lineTo(QPointF(side_x, lower_y))
                path.lineTo(QPointF(side_x, upper_y))
                path.lineTo(QPointF(end.center().x(), upper_y))
                path.lineTo(end_point)
            arrow_direction = "down"
        item = QGraphicsPathItem(path)
        item.setPen(QPen(QColor("#111111"), 1.5))
        scene.addItem(item)
        self.add_arrow_head(end_point, arrow_direction, scene)

    def free_side_x(self, positions: dict[str, QRectF], start: QRectF, end: QRectF, left: bool) -> float:
        if left:
            return min(start.left(), end.left()) - 42
        return max(start.right(), end.right()) + 42

    def add_arrow_head(self, point: QPointF, direction: str, scene: QGraphicsScene) -> None:
        arrow = QPainterPath()
        arrow.moveTo(point)
        if direction == "right":
            arrow.lineTo(point.x() - 10, point.y() - 6)
            arrow.lineTo(point.x() - 10, point.y() + 6)
        elif direction == "left":
            arrow.lineTo(point.x() + 10, point.y() - 6)
            arrow.lineTo(point.x() + 10, point.y() + 6)
        else:
            arrow.lineTo(point.x() - 6, point.y() - 10)
            arrow.lineTo(point.x() + 6, point.y() - 10)
        arrow.closeSubpath()
        item = QGraphicsPathItem(arrow)
        item.setBrush(QColor("#111111"))
        item.setPen(QPen(QColor("#111111"), 1.0))
        scene.addItem(item)

    def draw_dag(self, cfg: CFGResult) -> None:
        self.dag_scene.clear()
        title = QGraphicsSimpleTextItem("Basic Block DAG")
        title.setFont(make_font("Arial", 18, True))
        title.setBrush(QColor("#111827"))
        title.setPos(80, 24)
        self.dag_scene.addItem(title)

        y = 82
        max_width = 900
        for block in cfg.blocks:
            graph = self.build_dag_graph(block.quads)
            block_width, block_height = self.draw_dag_block(block.name, graph, 80, y)
            max_width = max(max_width, block_width + 160)
            y += block_height + 86

        self.dag_scene.setSceneRect(0, 0, max_width, max(720, y + 80))
        self.dag_zoom = 1.15
        self.apply_dag_zoom()
        self.dag_view.centerOn(330, 220)

    def build_dag_graph(self, quads: list[Quad]) -> dict:
        arithmetic_ops = {"+", "-", "*", "/"}
        commutative_ops = {"+", "*"}
        nodes: dict[str, dict] = {}
        expr_table: dict[tuple[str, str, str], str] = {}
        aliases: dict[str, str] = {}
        next_id = 1

        def resolve(value: str) -> str:
            return aliases.get(value, value)

        def expr_key(op: str, left: str, right: str) -> tuple[str, str, str]:
            if op in commutative_ops and right < left:
                left, right = right, left
            return op, left, right

        for quad in quads:
            if quad.op in arithmetic_ops:
                left = resolve(quad.arg1)
                right = resolve(quad.arg2)
                key = expr_key(quad.op, left, right)
                if key in expr_table:
                    node_id = expr_table[key]
                    nodes[node_id]["labels"].append(quad.result)
                    nodes[node_id]["reused"] = True
                else:
                    node_id = f"n{next_id}"
                    next_id += 1
                    nodes[node_id] = {
                        "op": quad.op,
                        "labels": [quad.result],
                        "inputs": [left, right],
                        "reused": False,
                    }
                    expr_table[key] = node_id
                aliases[quad.result] = node_id
            elif quad.op == "=":
                aliases[quad.result] = resolve(quad.arg1)

        return {"nodes": nodes}

    def draw_dag_block(self, block_name: str, graph: dict, x: int, y: int) -> tuple[int, int]:
        nodes: dict[str, dict] = graph["nodes"]
        title = QGraphicsSimpleTextItem(f"{block_name} DAG")
        title.setFont(make_font("Arial", 15, True))
        title.setBrush(QColor("#111827"))
        title.setPos(x, y)
        self.dag_scene.addItem(title)

        if not nodes:
            empty = QGraphicsSimpleTextItem("该基本块没有可构造 DAG 的算术表达式。")
            empty.setFont(QFont("Microsoft YaHei UI", 12))
            empty.setBrush(QColor("#64748b"))
            empty.setPos(x, y + 36)
            self.dag_scene.addItem(empty)
            return 520, 90

        levels = self.compute_dag_levels(nodes)
        refs = set()
        for node in nodes.values():
            refs.update(node["inputs"])
        leaves = sorted(ref for ref in refs if ref not in nodes)

        by_level: dict[int, list[str]] = {}
        for node_id, level in levels.items():
            by_level.setdefault(level, []).append(node_id)
        for leaf in leaves:
            by_level.setdefault(0, []).append(f"leaf:{leaf}")

        max_level = max(by_level)
        positions: dict[str, QRectF] = {}
        row_gap = 145
        col_gap = 76
        max_width = 0

        for level in range(max_level, -1, -1):
            items = by_level.get(level, [])
            current_x = x
            row_y = y + 48 + (max_level - level) * row_gap
            for item_id in items:
                label, reused = self.dag_node_label(item_id, nodes)
                width = max(150, min(300, max(len(part) for part in label.split("\n")) * 11 + 42))
                height = 78 if item_id in nodes else 58
                rect = QRectF(current_x, row_y, width, height)
                positions[item_id] = rect
                self.add_dag_node(rect, label, reused)
                current_x += width + col_gap
            max_width = max(max_width, current_x - x)

        for node_id, node in nodes.items():
            for input_ref in node["inputs"]:
                input_id = input_ref if input_ref in nodes else f"leaf:{input_ref}"
                if input_id in positions:
                    self.add_dag_edge(positions[node_id], positions[input_id])

        block_height = 64 + (max_level + 1) * row_gap
        return max_width, block_height

    def layout_dag_nodes(
        self,
        nodes: dict[str, dict],
        levels: dict[str, int],
        leaves: list[str],
        x: int,
        y: int,
    ) -> dict[str, QRectF]:
        row_gap = 128
        col_gap = 90
        node_width = 150
        expr_height = 76
        leaf_height = 58
        max_level = max(levels.values(), default=1)
        positions: dict[str, QRectF] = {}

        for order, leaf in enumerate(leaves):
            positions[f"leaf:{leaf}"] = QRectF(
                x + order * (node_width + col_gap),
                y + max_level * row_gap,
                node_width,
                leaf_height,
            )

        def place(node_id: str) -> QRectF:
            if node_id in positions:
                return positions[node_id]
            child_rects = []
            for input_ref in nodes[node_id]["inputs"]:
                input_id = input_ref if input_ref in nodes else f"leaf:{input_ref}"
                if input_id in nodes:
                    child_rects.append(place(input_id))
                else:
                    child_rects.append(positions[input_id])

            child_center = sum(rect.center().x() for rect in child_rects) / max(1, len(child_rects))
            level = levels.get(node_id, 1)
            rect = QRectF(
                child_center - node_width / 2,
                y + (max_level - level) * row_gap,
                node_width,
                expr_height,
            )
            positions[node_id] = rect
            return rect

        for node_id in sorted(nodes, key=lambda item: levels.get(item, 0)):
            place(node_id)

        self.separate_dag_rows(positions, nodes, levels, max_level, node_width, col_gap)
        return positions

    def separate_dag_rows(
        self,
        positions: dict[str, QRectF],
        nodes: dict[str, dict],
        levels: dict[str, int],
        max_level: int,
        node_width: int,
        col_gap: int,
    ) -> None:
        by_row: dict[int, list[str]] = {}
        for item_id in positions:
            if item_id.startswith("leaf:"):
                row = max_level
            else:
                row = max_level - levels.get(item_id, 0)
            by_row.setdefault(row, []).append(item_id)

        min_left = min(rect.left() for rect in positions.values())
        for items in by_row.values():
            items.sort(key=lambda item: positions[item].left())
            cursor = min_left
            for item_id in items:
                rect = positions[item_id]
                if rect.left() < cursor:
                    rect.moveLeft(cursor)
                    positions[item_id] = rect
                cursor = positions[item_id].right() + col_gap

    def compute_dag_levels(self, nodes: dict[str, dict]) -> dict[str, int]:
        cache: dict[str, int] = {}

        def level_of(node_id: str) -> int:
            if node_id in cache:
                return cache[node_id]
            node = nodes[node_id]
            child_levels = []
            for input_ref in node["inputs"]:
                if input_ref in nodes:
                    child_levels.append(level_of(input_ref))
                else:
                    child_levels.append(0)
            cache[node_id] = 1 + max(child_levels, default=0)
            return cache[node_id]

        return {node_id: level_of(node_id) for node_id in nodes}

    def dag_node_label(self, item_id: str, nodes: dict[str, dict]) -> tuple[str, bool]:
        if item_id.startswith("leaf:"):
            return item_id[5:], False
        node = nodes[item_id]
        return ",".join(node["labels"]) + "\n" + node["op"], bool(node["reused"])

    def add_dag_node(self, rect: QRectF, label: str, reused: bool) -> None:
        item = QGraphicsRectItem(rect)
        item.setBrush(QColor("#ffffff"))
        item.setPen(QPen(QColor("#e11d48" if reused else "#111111"), 3.0 if reused else 1.6))
        self.dag_scene.addItem(item)

        lines = label.split("\n")
        y = rect.top() + 10
        for line_text in lines:
            text = QGraphicsSimpleTextItem(line_text)
            text.setFont(QFont("Consolas", 13))
            text.setBrush(QColor("#000000"))
            text_rect = text.boundingRect()
            text.setPos(rect.left() + (rect.width() - text_rect.width()) / 2, y)
            self.dag_scene.addItem(text)
            y += 24

    def add_dag_edge(self, start: QRectF, end: QRectF) -> None:
        start_point = QPointF(start.center().x(), start.bottom())
        end_point = QPointF(end.center().x(), end.top())
        path = QPainterPath()
        path.moveTo(start_point)
        middle_y = (start.bottom() + end.top()) / 2
        path.cubicTo(
            QPointF(start.center().x(), middle_y),
            QPointF(end.center().x(), middle_y),
            end_point,
        )
        item = QGraphicsPathItem(path)
        item.setPen(QPen(QColor("#111111"), 1.7))
        self.dag_scene.addItem(item)
        self.add_dag_arrow_head(end_point)

    def add_dag_arrow_head(self, point: QPointF) -> None:
        arrow = QPainterPath()
        arrow.moveTo(point)
        arrow.lineTo(point.x() - 6, point.y() - 10)
        arrow.lineTo(point.x() + 6, point.y() - 10)
        arrow.closeSubpath()
        item = QGraphicsPathItem(arrow)
        item.setBrush(QColor("#111111"))
        item.setPen(QPen(QColor("#111111"), 1.0))
        self.dag_scene.addItem(item)

    def show_error(self, exc: Exception) -> None:
        self.status_label.setText(f"执行失败：{exc}")
        QMessageBox.critical(self, "执行失败", str(exc))


def main() -> None:
    app = QApplication(sys.argv)
    window = CompilerQtUI()
    window.show()
    runner = getattr(app, "exec", app.exec_)
    sys.exit(runner())


if __name__ == "__main__":
    main()
