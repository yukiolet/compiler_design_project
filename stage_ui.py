"""Integrated compiler-stage demonstration UI.

This UI is for requirement 2 in the course task: integrate the completed
compiler stages and demonstrate them visually.
"""

from __future__ import annotations

import importlib.util
from pathlib import Path
import sys

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import QColor, QFont, QPainter, QPainterPath, QPen
from PySide6.QtWidgets import (
    QApplication,
    QFileDialog,
    QFrame,
    QGraphicsPathItem,
    QGraphicsRectItem,
    QGraphicsScene,
    QGraphicsSimpleTextItem,
    QGraphicsView,
    QHBoxLayout,
    QLabel,
    QMainWindow,
    QMessageBox,
    QPushButton,
    QPlainTextEdit,
    QSplitter,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from modules.interpreter import QuadInterpreter, render_interpreter_result
from modules.quad import EMPTY, Quad
from modules.source_interpreter import (
    SourceInterpreter,
    render_execution_compare,
    render_source_execution,
)


BASE_DIR = Path(__file__).resolve().parent
OLD_CODE_DIR = BASE_DIR / "old_code"
OUTPUT_DIR = BASE_DIR / "output" / "stage_ui"


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


def load_module(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Cannot load module: {path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class CompilerStages:
    def __init__(self) -> None:
        self.ir_module = load_module("old_intermediate_code", OLD_CODE_DIR / "intermediate_code.py")
        self.parser_module = load_module("old_parser", OLD_CODE_DIR / "parser.py")
        self.semantic_module = load_module("old_semantic_analyzer", OLD_CODE_DIR / "semantic_analyzer.py")

    def run(self, source: str) -> dict:
        OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

        tokens = self.ir_module.LexicalAnalyzer(source).analyze()
        token_text = self.render_tokens(tokens)

        ast_for_display = self.parser_module.Parser(tokens).parse()
        ast_lines = self.parser_module.ast_lines(ast_for_display)
        ast_text = "\n".join(line.rstrip() for line in ast_lines) + "\n"

        ast_path = OUTPUT_DIR / "ast.txt"
        ast_path.write_text(ast_text, encoding="utf-8")
        semantic_root = self.semantic_module.parse_ast_file(ast_path)
        analyzer = self.semantic_module.SemanticAnalyzer(semantic_root)
        analyzer.write_outputs = lambda: None
        analyzer.analyze()
        semantic_text = self.render_semantic(analyzer)

        ast_for_ir = self.ir_module.Parser(tokens).parse()
        quads = self.ir_module.IntermediateCodeGenerator().generate(ast_for_ir)
        quad_text = self.render_quads(quads)
        quad_objects = self.to_quad_objects(quads)

        source_result = SourceInterpreter(ast_for_ir).run()
        quad_result = QuadInterpreter(quad_objects).run()
        source_execution_text = render_source_execution(source_result)
        quad_execution_text = render_interpreter_result(quad_result)
        compare_text = render_execution_compare(source_result, quad_result)
        validation_text = (
            compare_text
            + "\n"
            + "=" * 72
            + "\n\n"
            + source_execution_text
            + "\n"
            + "=" * 72
            + "\n\n"
            + quad_execution_text
        )

        (OUTPUT_DIR / "tokens.txt").write_text(token_text, encoding="utf-8")
        (OUTPUT_DIR / "semantic.txt").write_text(semantic_text, encoding="utf-8")
        (OUTPUT_DIR / "quads.txt").write_text(quad_text, encoding="utf-8")
        (OUTPUT_DIR / "source_execution.txt").write_text(source_execution_text, encoding="utf-8")
        (OUTPUT_DIR / "quad_execution_from_source.txt").write_text(quad_execution_text, encoding="utf-8")
        (OUTPUT_DIR / "execution_compare.txt").write_text(compare_text, encoding="utf-8")
        (OUTPUT_DIR / "source.c").write_text(source, encoding="utf-8")

        return {
            "tokens": token_text,
            "ast": ast_text,
            "ast_root": ast_for_display,
            "semantic": semantic_text,
            "quads": quad_text,
            "validation": validation_text,
        }

    def render_tokens(self, tokens) -> str:
        lines = ["lexeme\tcode\tline"]
        for token in tokens:
            lines.append(f"{token.lexeme}\t{token.code}\t{token.line}")
        return "\n".join(lines) + "\n"

    def render_semantic(self, analyzer) -> str:
        lines = ["Semantic Errors:"]
        if analyzer.errors:
            for line, code in analyzer.errors:
                lines.append(f"line {line}: error code {code}")
        else:
            lines.append("No semantic errors.")

        lines.extend(["", "Variables:", "name\ttype\tinit\tscope\tline"])
        for entry in analyzer.var_entries:
            lines.append(f"{entry['name']}\t{entry['type']}\t{entry['init']}\t{entry['scope']}\t{entry['line']}")

        lines.extend(["", "Constants:", "name\ttype\tvalue\tscope\tline"])
        for entry in analyzer.const_entries:
            lines.append(f"{entry['name']}\t{entry['type']}\t{entry['value']}\t{entry['scope']}\t{entry['line']}")

        lines.extend(["", "Functions:", "name\treturn_type\tparam_count\tparam_types\tline"])
        for entry in analyzer.function_entries:
            param_types = ",".join(param["type"] for param in entry["params"])
            lines.append(
                f"{entry['name']}\t{entry['return_type']}\t{len(entry['params'])}\t{param_types}\t{entry['line']}"
            )
        return "\n".join(lines) + "\n"

    def render_quads(self, quads) -> str:
        lines = []
        for index, quad in enumerate(quads):
            op, arg1, arg2, result = quad
            lines.append(f"{index}: ({op}, {arg1}, {arg2}, {result})")
        return "\n".join(lines) + "\n"

    def to_quad_objects(self, quads) -> list[Quad]:
        result: list[Quad] = []
        for index, quad in enumerate(quads):
            op, arg1, arg2, target = quad
            result.append(
                Quad(
                    index,
                    self.clean_quad_field(op),
                    self.clean_quad_field(arg1),
                    self.clean_quad_field(arg2),
                    self.clean_quad_field(target),
                )
            )
        return result

    def clean_quad_field(self, value) -> str:
        if value is None:
            return EMPTY
        text = str(value).strip()
        return text if text else EMPTY


class StageDemoUI(QMainWindow):
    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle("编译程序各阶段整合演示")
        self.resize(1260, 820)
        self.setMinimumSize(1060, 680)
        self.compiler = CompilerStages()
        self.text_tabs: dict[str, QPlainTextEdit] = {}
        self.flow_scene = QGraphicsScene()
        self.flow_view = QGraphicsView(self.flow_scene)
        self.ast_scene = QGraphicsScene()
        self.ast_view = QGraphicsView(self.ast_scene)
        self.ast_zoom = 1.0
        self.status = QLabel("输入类 C 源程序后，点击“运行全部阶段”。")
        self.build_ui()
        self.apply_style()
        self.source_editor.setPlainText(DEFAULT_SOURCE)
        self.draw_flow()

    def build_ui(self) -> None:
        central = QWidget()
        root = QHBoxLayout(central)
        root.setContentsMargins(0, 0, 0, 0)
        self.setCentralWidget(central)

        side = QFrame()
        side.setObjectName("side")
        side.setFixedWidth(300)
        side_layout = QVBoxLayout(side)
        side_layout.setContentsMargins(22, 24, 22, 20)
        side_layout.setSpacing(12)

        title = QLabel("阶段整合演示")
        title.setObjectName("title")
        subtitle = QLabel("词法 · 语法 · 语义 · 中间代码")
        subtitle.setObjectName("subtitle")
        side_layout.addWidget(title)
        side_layout.addWidget(subtitle)
        side_layout.addSpacing(16)

        actions = [
            ("运行全部阶段", self.run_all, "primaryButton"),
            ("打开源程序", self.open_source, "sideButton"),
            ("保存源程序", self.save_source, "sideButton"),
            ("清除结果", self.clear_results, "sideButton"),
        ]
        for text, slot, object_name in actions:
            button = QPushButton(text)
            button.setObjectName(object_name)
            button.setMinimumHeight(40)
            button.clicked.connect(slot)
            side_layout.addWidget(button)

        side_layout.addStretch(1)
        tips = QLabel("本界面用于任务书第 2 条：整合并可视化演示已完成的编译程序各阶段功能。")
        tips.setObjectName("tips")
        tips.setWordWrap(True)
        side_layout.addWidget(tips)

        content = QWidget()
        content_layout = QVBoxLayout(content)
        content_layout.setContentsMargins(18, 18, 18, 14)
        content_layout.setSpacing(12)

        header = QFrame()
        header.setObjectName("header")
        header_layout = QHBoxLayout(header)
        header_layout.setContentsMargins(18, 12, 18, 12)
        header_title = QLabel("编译程序阶段流水线")
        header_title.setObjectName("headerTitle")
        header_layout.addWidget(header_title)
        header_layout.addStretch(1)
        self.status.setObjectName("status")
        header_layout.addWidget(self.status)
        content_layout.addWidget(header)

        splitter = QSplitter()
        self.source_editor = QPlainTextEdit()
        self.source_editor.setObjectName("sourceEditor")
        self.source_editor.setFont(QFont("Consolas", 11))
        splitter.addWidget(self.source_editor)

        self.tabs = QTabWidget()
        self.build_tabs()
        splitter.addWidget(self.tabs)
        splitter.setSizes([430, 760])
        content_layout.addWidget(splitter, 1)

        root.addWidget(side)
        root.addWidget(content, 1)

    def build_tabs(self) -> None:
        self.flow_view.setRenderHint(QPainter.Antialiasing, True)
        self.flow_view.setBackgroundBrush(QColor("#ffffff"))
        self.ast_view.setRenderHint(QPainter.Antialiasing, True)
        self.ast_view.setDragMode(QGraphicsView.ScrollHandDrag)
        self.ast_view.setBackgroundBrush(QColor("#ffffff"))
        self.tabs.addTab(self.flow_view, "阶段流程图")
        self.tabs.addTab(self.build_ast_tab(), "语法树图")
        for name in ["词法 Tokens", "语法 AST", "语义 / 符号表", "中间代码四元式", "Source Verify", "说明"]:
            edit = QPlainTextEdit()
            edit.setReadOnly(True)
            edit.setLineWrapMode(QPlainTextEdit.NoWrap)
            edit.setFont(QFont("Consolas", 10))
            self.text_tabs[name] = edit
            self.tabs.addTab(edit, name)
        self.text_tabs["说明"].setPlainText(
            "使用说明：\n"
            "1. 左侧输入或打开类 C 源程序。\n"
            "2. 点击“运行全部阶段”。\n"
            "3. 右侧查看词法分析、语法树、语义检查、符号表和四元式结果。\n"
            "4. 输出文件会保存到 output/stage_ui，便于写报告和截图。\n"
        )

    def build_ast_tab(self) -> QWidget:
        tab = QWidget()
        layout = QVBoxLayout(tab)
        layout.setContentsMargins(8, 8, 8, 8)
        layout.setSpacing(8)

        toolbar = QHBoxLayout()
        toolbar.addWidget(QLabel("语法树图可拖动查看，也可用鼠标滚轮缩放"))
        toolbar.addStretch(1)
        for text, slot in [
            ("放大", self.zoom_ast_in),
            ("缩小", self.zoom_ast_out),
            ("适应窗口", self.fit_ast_view),
            ("重置", self.reset_ast_zoom),
        ]:
            button = QPushButton(text)
            button.setObjectName("toolbarButton")
            button.clicked.connect(slot)
            toolbar.addWidget(button)
        layout.addLayout(toolbar)
        layout.addWidget(self.ast_view, 1)
        self.ast_view.wheelEvent = self.ast_wheel_event
        return tab

    def apply_style(self) -> None:
        self.setStyleSheet(
            """
            QMainWindow { background: #eef2f7; }
            #side { background: #172033; }
            #title { color: #ffffff; font-size: 22px; font-weight: 700; }
            #subtitle, #tips { color: #b8c4d8; }
            QPushButton {
                border: none;
                border-radius: 7px;
                padding: 8px 12px;
                color: #e5e7eb;
                background: #26354d;
                font-weight: 600;
            }
            QPushButton:hover { background: #334760; }
            #primaryButton { background: #2563eb; color: white; font-size: 14px; }
            #primaryButton:hover { background: #1d4ed8; }
            #sideButton { text-align: left; }
            #toolbarButton {
                background: #eef2ff;
                color: #1e3a8a;
                border: 1px solid #bfdbfe;
                padding: 6px 12px;
                text-align: center;
            }
            #toolbarButton:hover { background: #dbeafe; }
            #header {
                background: #ffffff;
                border: 1px solid #d8dee9;
                border-radius: 8px;
            }
            #headerTitle { color: #111827; font-size: 18px; font-weight: 700; }
            #status { color: #475569; }
            QSplitter::handle { background: #d8dee9; width: 4px; }
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
                border: 1px solid #d8dee9;
                border-radius: 8px;
                padding: 10px;
                selection-background-color: #bfdbfe;
            }
            """
        )

    def draw_flow(self) -> None:
        self.flow_scene.clear()
        stages = [
            ("源程序", "类 C 代码输入"),
            ("词法分析", "Token 序列"),
            ("语法分析", "AST 语法树"),
            ("语义分析", "错误检查 / 符号表"),
            ("中间代码生成", "四元式"),
        ]
        x = 70
        y = 110
        width = 170
        height = 86
        gap = 58
        positions = []
        title = QGraphicsSimpleTextItem("Compiler Front-end Pipeline")
        title.setFont(QFont("Arial", 18, QFont.Bold))
        title.setBrush(QColor("#111827"))
        title.setPos(70, 38)
        self.flow_scene.addItem(title)
        for i, (name, desc) in enumerate(stages):
            left = x + i * (width + gap)
            rect = QRectF(left, y, width, height)
            positions.append(rect)
            box = QGraphicsRectItem(rect)
            box.setBrush(QColor("#ffffff"))
            box.setPen(QPen(QColor("#2563eb"), 2))
            self.flow_scene.addItem(box)
            name_item = QGraphicsSimpleTextItem(name)
            name_item.setFont(QFont("Microsoft YaHei UI", 13, QFont.Bold))
            name_item.setBrush(QColor("#111827"))
            name_item.setPos(left + 18, y + 15)
            self.flow_scene.addItem(name_item)
            desc_item = QGraphicsSimpleTextItem(desc)
            desc_item.setFont(QFont("Microsoft YaHei UI", 10))
            desc_item.setBrush(QColor("#475569"))
            desc_item.setPos(left + 18, y + 48)
            self.flow_scene.addItem(desc_item)
        for i in range(len(positions) - 1):
            self.add_flow_arrow(positions[i], positions[i + 1])
        self.flow_scene.setSceneRect(0, 0, 1160, 330)

    def add_flow_arrow(self, start: QRectF, end: QRectF) -> None:
        y = start.center().y()
        x1 = start.right()
        x2 = end.left()
        path = QPainterPath()
        path.moveTo(QPointF(x1, y))
        path.lineTo(QPointF(x2, y))
        line = QGraphicsPathItem(path)
        line.setPen(QPen(QColor("#111827"), 1.8))
        self.flow_scene.addItem(line)
        arrow = QPainterPath()
        arrow.moveTo(QPointF(x2, y))
        arrow.lineTo(QPointF(x2 - 10, y - 6))
        arrow.lineTo(QPointF(x2 - 10, y + 6))
        arrow.closeSubpath()
        arrow_item = QGraphicsPathItem(arrow)
        arrow_item.setBrush(QColor("#111827"))
        arrow_item.setPen(QPen(QColor("#111827"), 1))
        self.flow_scene.addItem(arrow_item)

    def draw_ast_tree(self, root) -> None:
        self.ast_scene.clear()
        if root is None:
            return

        title = QGraphicsSimpleTextItem("AST Syntax Tree")
        title.setFont(QFont("Arial", 18, QFont.Bold))
        title.setBrush(QColor("#111827"))
        title.setPos(70, 30)
        self.ast_scene.addItem(title)

        positions: dict[int, QRectF] = {}
        next_leaf_x = [70]
        self.layout_ast_node(root, 0, next_leaf_x, positions)

        for node in self.walk_ast(root):
            rect = positions[id(node)]
            for child in getattr(node, "children", []):
                child_rect = positions[id(child)]
                self.add_ast_edge(rect, child_rect)

        for node in self.walk_ast(root):
            self.add_ast_node(positions[id(node)], self.ast_label(node))

        bounds = self.ast_scene.itemsBoundingRect().adjusted(-60, -50, 90, 90)
        self.ast_scene.setSceneRect(bounds)
        self.ast_zoom = 1.0
        self.apply_ast_zoom()
        self.ast_view.centerOn(positions[id(root)].center())

    def zoom_ast_in(self) -> None:
        self.ast_zoom = min(self.ast_zoom * 1.2, 3.5)
        self.apply_ast_zoom()

    def zoom_ast_out(self) -> None:
        self.ast_zoom = max(self.ast_zoom / 1.2, 0.25)
        self.apply_ast_zoom()

    def reset_ast_zoom(self) -> None:
        self.ast_zoom = 1.0
        self.apply_ast_zoom()

    def fit_ast_view(self) -> None:
        if self.ast_scene.itemsBoundingRect().isEmpty():
            return
        bounds = self.ast_scene.itemsBoundingRect().adjusted(-40, -40, 40, 40)
        self.ast_view.fitInView(bounds, Qt.KeepAspectRatio)
        self.ast_zoom = self.ast_view.transform().m11()

    def apply_ast_zoom(self) -> None:
        self.ast_view.resetTransform()
        self.ast_view.scale(self.ast_zoom, self.ast_zoom)

    def ast_wheel_event(self, event) -> None:
        if event.angleDelta().y() > 0:
            self.zoom_ast_in()
        else:
            self.zoom_ast_out()
        event.accept()

    def layout_ast_node(self, node, depth: int, next_leaf_x: list[int], positions: dict[int, QRectF]) -> float:
        children = getattr(node, "children", [])
        y = 90 + depth * 115
        width = max(120, min(260, len(self.ast_label(node)) * 8 + 34))
        height = 46

        if not children:
            x = next_leaf_x[0]
            next_leaf_x[0] += width + 38
        else:
            child_centers = [self.layout_ast_node(child, depth + 1, next_leaf_x, positions) for child in children]
            x = (min(child_centers) + max(child_centers)) / 2 - width / 2

        positions[id(node)] = QRectF(x, y, width, height)
        return x + width / 2

    def walk_ast(self, root):
        yield root
        for child in getattr(root, "children", []):
            yield from self.walk_ast(child)

    def ast_label(self, node) -> str:
        kind = getattr(node, "kind", "")
        value = getattr(node, "value", None)
        line = getattr(node, "line", None)
        if value is not None:
            label = f"{kind}: {value}"
        else:
            label = str(kind)
        if line is not None:
            label += f" [{line}]"
        return label

    def add_ast_node(self, rect: QRectF, label: str) -> None:
        box = QGraphicsRectItem(rect)
        box.setBrush(QColor("#ffffff"))
        box.setPen(QPen(QColor("#2563eb"), 1.8))
        self.ast_scene.addItem(box)

        text = QGraphicsSimpleTextItem(label)
        text.setFont(QFont("Consolas", 10))
        text.setBrush(QColor("#111827"))
        text_rect = text.boundingRect()
        text.setPos(rect.left() + (rect.width() - text_rect.width()) / 2, rect.top() + 13)
        self.ast_scene.addItem(text)

    def add_ast_edge(self, start: QRectF, end: QRectF) -> None:
        start_point = QPointF(start.center().x(), start.bottom())
        end_point = QPointF(end.center().x(), end.top())
        path = QPainterPath()
        path.moveTo(start_point)
        path.lineTo(end_point)
        edge = QGraphicsPathItem(path)
        edge.setPen(QPen(QColor("#111827"), 1.2))
        self.ast_scene.addItem(edge)

    def run_all(self) -> None:
        try:
            result = self.compiler.run(self.source_editor.toPlainText())
            self.draw_ast_tree(result["ast_root"])
            self.text_tabs["词法 Tokens"].setPlainText(result["tokens"])
            self.text_tabs["语法 AST"].setPlainText(result["ast"])
            self.text_tabs["语义 / 符号表"].setPlainText(result["semantic"])
            self.text_tabs["中间代码四元式"].setPlainText(result["quads"])
            self.text_tabs["Source Verify"].setPlainText(result["validation"])
            self.status.setText(f"运行完成，结果已保存到 {OUTPUT_DIR}")
        except Exception as exc:
            self.show_error(exc)

    def open_source(self) -> None:
        path, _ = QFileDialog.getOpenFileName(self, "打开源程序", str(BASE_DIR), "C files (*.c *.txt);;All files (*)")
        if path:
            self.source_editor.setPlainText(Path(path).read_text(encoding="utf-8"))
            self.status.setText(f"已打开：{path}")

    def save_source(self) -> None:
        OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
        path, _ = QFileDialog.getSaveFileName(self, "保存源程序", str(OUTPUT_DIR / "source.c"), "C files (*.c);;Text files (*.txt)")
        if path:
            Path(path).write_text(self.source_editor.toPlainText(), encoding="utf-8")
            self.status.setText(f"源程序已保存：{path}")

    def clear_results(self) -> None:
        for key, tab in self.text_tabs.items():
            if key != "说明":
                tab.clear()
        self.ast_scene.clear()
        self.status.setText("结果已清除，可以输入下一组源程序。")

    def show_error(self, exc: Exception) -> None:
        self.status.setText(f"运行失败：{exc}")
        QMessageBox.critical(self, "运行失败", str(exc))


def main() -> None:
    app = QApplication(sys.argv)
    window = StageDemoUI()
    window.show()
    runner = getattr(app, "exec", app.exec_)
    sys.exit(runner())


if __name__ == "__main__":
    main()
