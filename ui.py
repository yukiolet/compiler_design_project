"""Interactive Tkinter UI for the compiler design course project."""

from __future__ import annotations

from pathlib import Path
import tkinter as tk
from tkinter import filedialog, messagebox, ttk

from modules.cfg import CFGResult, build_cfg, render_basic_blocks, render_cfg_dot
from modules.dag_optimizer import DAGOptimizer
from modules.interpreter import QuadInterpreter, render_interpreter_result
from modules.llvm_converter import LLVMConverter
from modules.quad import Quad, format_quad, read_quads, write_quads


BASE_DIR = Path(__file__).resolve().parent
INPUT_DIR = BASE_DIR / "input"
OUTPUT_DIR = BASE_DIR / "output"


class CompilerCourseUI(tk.Tk):
    def __init__(self) -> None:
        super().__init__()
        self.title("编译原理课程设计 - 四元式分析系统")
        self.geometry("1180x760")
        self.minsize(980, 640)

        self.input_path = tk.StringVar(value=str(INPUT_DIR / "quads.txt"))
        self.output_path = tk.StringVar(value=str(OUTPUT_DIR / "ui"))
        self.status = tk.StringVar(value="请选择输入文件并执行操作。")

        self.quads: list[Quad] = []
        self.cfg: CFGResult | None = None
        self.text_views: dict[str, tk.Text] = {}
        self.cfg_canvas: tk.Canvas | None = None

        self.configure_style()
        self.build_layout()
        self.load_input_preview()

    def configure_style(self) -> None:
        style = ttk.Style(self)
        style.theme_use("clam")
        style.configure("TFrame", background="#f5f7fb")
        style.configure("Panel.TFrame", background="#ffffff", relief="solid", borderwidth=1)
        style.configure("TLabel", background="#f5f7fb", foreground="#1f2937")
        style.configure("Panel.TLabel", background="#ffffff", foreground="#111827")
        style.configure("Title.TLabel", font=("Microsoft YaHei UI", 14, "bold"))
        style.configure("TButton", padding=(10, 6))
        style.configure("Primary.TButton", padding=(10, 7))
        style.configure("TNotebook", background="#f5f7fb")
        style.configure("TNotebook.Tab", padding=(12, 6))

    def build_layout(self) -> None:
        root = ttk.Frame(self, padding=12)
        root.pack(fill=tk.BOTH, expand=True)

        left = ttk.Frame(root, width=300, style="Panel.TFrame", padding=14)
        left.pack(side=tk.LEFT, fill=tk.Y)
        left.pack_propagate(False)

        right = ttk.Frame(root)
        right.pack(side=tk.RIGHT, fill=tk.BOTH, expand=True, padx=(12, 0))

        ttk.Label(left, text="四元式分析系统", style="Title.TLabel").pack(anchor=tk.W, pady=(0, 14))

        ttk.Label(left, text="输入文件", style="Panel.TLabel").pack(anchor=tk.W)
        input_row = ttk.Frame(left, style="Panel.TFrame")
        input_row.pack(fill=tk.X, pady=(6, 10))
        input_box = ttk.Combobox(input_row, textvariable=self.input_path, values=self.input_file_values())
        input_box.pack(side=tk.LEFT, fill=tk.X, expand=True)
        input_box.bind("<<ComboboxSelected>>", lambda _event: self.load_input_preview())
        ttk.Button(input_row, text="浏览", command=self.browse_input).pack(side=tk.RIGHT, padx=(6, 0))

        ttk.Label(left, text="输出目录", style="Panel.TLabel").pack(anchor=tk.W)
        output_row = ttk.Frame(left, style="Panel.TFrame")
        output_row.pack(fill=tk.X, pady=(6, 16))
        ttk.Entry(output_row, textvariable=self.output_path).pack(side=tk.LEFT, fill=tk.X, expand=True)
        ttk.Button(output_row, text="选择", command=self.browse_output).pack(side=tk.RIGHT, padx=(6, 0))

        ttk.Label(left, text="执行操作", style="Panel.TLabel").pack(anchor=tk.W, pady=(0, 8))
        buttons = [
            ("全部执行", self.run_all),
            ("四元式解释执行", self.run_interpreter),
            ("生成 LLVM IR", self.run_llvm),
            ("基本块 / CFG 分析", self.run_cfg),
            ("DAG 局部优化", self.run_dag),
            ("清除结果", self.clear_results),
            ("重新载入输入", self.load_input_preview),
        ]
        for text, command in buttons:
            ttk.Button(left, text=text, command=command, style="Primary.TButton").pack(fill=tk.X, pady=4)

        ttk.Separator(left).pack(fill=tk.X, pady=14)
        ttk.Label(left, text="建议报告截图", style="Panel.TLabel").pack(anchor=tk.W)
        tips = (
            "1. 解释执行结果\n"
            "2. LLVM IR 输出\n"
            "3. 基本块划分表\n"
            "4. CFG 图或 DOT 文本\n"
            "5. DAG 优化前后对比"
        )
        ttk.Label(left, text=tips, style="Panel.TLabel", justify=tk.LEFT).pack(anchor=tk.W, pady=(6, 0))

        self.notebook = ttk.Notebook(right)
        self.notebook.pack(fill=tk.BOTH, expand=True)
        for name in [
            "输入四元式",
            "解释执行",
            "LLVM IR",
            "基本块",
            "CFG DOT",
            "CFG 图",
            "DAG 分析",
            "优化四元式",
            "优化对比",
        ]:
            self.add_tab(name)

        status_bar = ttk.Label(right, textvariable=self.status, anchor=tk.W)
        status_bar.pack(fill=tk.X, pady=(8, 0))

    def input_file_values(self) -> list[str]:
        if not INPUT_DIR.exists():
            return []
        return [str(path) for path in sorted(INPUT_DIR.glob("*.txt"))]

    def add_tab(self, name: str) -> None:
        frame = ttk.Frame(self.notebook)
        self.notebook.add(frame, text=name)
        if name == "CFG 图":
            canvas_frame = ttk.Frame(frame, padding=8)
            canvas_frame.pack(fill=tk.BOTH, expand=True)
            self.cfg_canvas = tk.Canvas(
                canvas_frame,
                background="#ffffff",
                highlightthickness=1,
                highlightbackground="#9ca3af",
            )
            x_scroll = ttk.Scrollbar(canvas_frame, orient=tk.HORIZONTAL, command=self.cfg_canvas.xview)
            y_scroll = ttk.Scrollbar(canvas_frame, orient=tk.VERTICAL, command=self.cfg_canvas.yview)
            self.cfg_canvas.configure(xscrollcommand=x_scroll.set, yscrollcommand=y_scroll.set)
            self.cfg_canvas.grid(row=0, column=0, sticky="nsew")
            y_scroll.grid(row=0, column=1, sticky="ns")
            x_scroll.grid(row=1, column=0, sticky="ew")
            canvas_frame.rowconfigure(0, weight=1)
            canvas_frame.columnconfigure(0, weight=1)
        else:
            text = tk.Text(
                frame,
                wrap=tk.NONE,
                undo=False,
                font=("Consolas", 11),
                background="#ffffff",
                foreground="#111827",
                insertbackground="#111827",
            )
            x_scroll = ttk.Scrollbar(frame, orient=tk.HORIZONTAL, command=text.xview)
            y_scroll = ttk.Scrollbar(frame, orient=tk.VERTICAL, command=text.yview)
            text.configure(xscrollcommand=x_scroll.set, yscrollcommand=y_scroll.set)
            text.grid(row=0, column=0, sticky="nsew")
            y_scroll.grid(row=0, column=1, sticky="ns")
            x_scroll.grid(row=1, column=0, sticky="ew")
            frame.rowconfigure(0, weight=1)
            frame.columnconfigure(0, weight=1)
            self.text_views[name] = text

    def browse_input(self) -> None:
        file_path = filedialog.askopenfilename(
            initialdir=INPUT_DIR,
            title="选择四元式输入文件",
            filetypes=[("Text files", "*.txt"), ("All files", "*.*")],
        )
        if file_path:
            self.input_path.set(file_path)
            self.load_input_preview()

    def browse_output(self) -> None:
        directory = filedialog.askdirectory(initialdir=OUTPUT_DIR, title="选择输出目录")
        if directory:
            self.output_path.set(directory)

    def set_text(self, tab_name: str, content: str) -> None:
        text = self.text_views[tab_name]
        text.configure(state=tk.NORMAL)
        text.delete("1.0", tk.END)
        text.insert(tk.END, content)
        text.configure(state=tk.DISABLED)

    def load_quads(self) -> list[Quad]:
        path = Path(self.input_path.get())
        quads = read_quads(path)
        if not quads:
            raise RuntimeError(f"输入文件没有可解析的四元式：{path}")
        self.quads = quads
        return quads

    def load_input_preview(self) -> None:
        try:
            path = Path(self.input_path.get())
            if path.exists():
                self.set_text("输入四元式", path.read_text(encoding="utf-8"))
                self.status.set(f"已载入输入文件：{path}")
            else:
                self.set_text("输入四元式", "")
                self.status.set("输入文件不存在。")
        except Exception as exc:
            self.show_error(exc)

    def clear_results(self) -> None:
        result_tabs = [
            "解释执行",
            "LLVM IR",
            "基本块",
            "CFG DOT",
            "DAG 分析",
            "优化四元式",
            "优化对比",
        ]
        for tab in result_tabs:
            self.set_text(tab, "")
        if self.cfg_canvas is not None:
            self.cfg_canvas.delete("all")
            self.cfg_canvas.configure(scrollregion=(0, 0, 0, 0))
        self.cfg = None
        self.status.set("结果已清除，可以选择或修改下一组四元式继续测试。")

    def output_dir(self) -> Path:
        path = Path(self.output_path.get())
        path.mkdir(parents=True, exist_ok=True)
        return path

    def run_all(self) -> None:
        try:
            self.run_interpreter(show_done=False)
            self.run_llvm(show_done=False)
            self.run_cfg(show_done=False)
            self.run_dag(show_done=False)
            self.status.set(f"全部执行完成，结果已保存到：{self.output_dir()}")
        except Exception as exc:
            self.show_error(exc)

    def run_interpreter(self, show_done: bool = True) -> None:
        try:
            quads = self.load_quads()
            result = QuadInterpreter(quads).run()
            content = render_interpreter_result(result)
            self.set_text("解释执行", content)
            (self.output_dir() / "interpreter_result.txt").write_text(content, encoding="utf-8")
            if show_done:
                self.status.set("四元式解释执行完成。")
        except Exception as exc:
            self.show_error(exc)

    def run_llvm(self, show_done: bool = True) -> None:
        try:
            quads = self.load_quads()
            content = LLVMConverter(quads).convert()
            self.set_text("LLVM IR", content)
            (self.output_dir() / "llvm_ir.ll").write_text(content, encoding="utf-8")
            if show_done:
                self.status.set("LLVM IR 生成完成。")
        except Exception as exc:
            self.show_error(exc)

    def run_cfg(self, show_done: bool = True) -> None:
        try:
            quads = self.load_quads()
            self.cfg = build_cfg(quads)
            blocks = render_basic_blocks(self.cfg)
            dot = render_cfg_dot(self.cfg)
            self.set_text("基本块", blocks)
            self.set_text("CFG DOT", dot)
            self.draw_cfg(self.cfg)
            out = self.output_dir()
            (out / "basic_blocks.txt").write_text(blocks, encoding="utf-8")
            (out / "cfg.dot").write_text(dot, encoding="utf-8")
            if show_done:
                self.status.set("基本块划分和 CFG 构建完成。")
        except Exception as exc:
            self.show_error(exc)

    def run_dag(self, show_done: bool = True) -> None:
        try:
            quads = self.load_quads()
            cfg = build_cfg(quads)
            self.cfg = cfg
            optimization = DAGOptimizer(cfg).optimize()
            self.set_text("DAG 分析", optimization.dag_report)
            optimized_text = "\n".join(format_quad(quad, i) for i, quad in enumerate(optimization.optimized_quads)) + "\n"
            self.set_text("优化四元式", optimized_text)
            self.set_text("优化对比", optimization.compare_report)
            out = self.output_dir()
            write_quads(out / "optimized_quads.txt", optimization.optimized_quads)
            (out / "dag_blocks.txt").write_text(optimization.dag_report, encoding="utf-8")
            (out / "compare_report.txt").write_text(optimization.compare_report, encoding="utf-8")
            if show_done:
                self.status.set("DAG 局部优化完成。")
        except Exception as exc:
            self.show_error(exc)

    def draw_cfg(self, cfg: CFGResult) -> None:
        canvas = self.cfg_canvas
        if canvas is None:
            return
        canvas.delete("all")
        if not cfg.blocks:
            return

        levels = self.compute_cfg_levels(cfg)
        level_items: dict[int, list] = {}
        for block in cfg.blocks:
            level_items.setdefault(levels.get(block.name, 0), []).append(block)

        margin_x = 70
        margin_y = 70
        gap_x = 90
        gap_y = 95
        positions: dict[str, tuple[int, int, int, int]] = {}

        canvas.create_text(
            margin_x,
            25,
            text="CFG Control Flow Graph",
            anchor=tk.W,
            fill="#111827",
            font=("Times New Roman", 16, "bold"),
        )

        max_canvas_width = 0
        max_canvas_height = 0
        for level in sorted(level_items):
            blocks = level_items[level]
            widths = [self.block_visual_size(block)[0] for block in blocks]
            row_width = sum(widths) + gap_x * max(0, len(blocks) - 1)
            left = margin_x
            top = margin_y + level * (self.max_level_height(blocks) + gap_y)
            for block, width in zip(blocks, widths):
                height = self.block_visual_size(block)[1]
                right = left + width
                bottom = top + height
                positions[block.name] = (left, top, right, bottom)
                self.draw_cfg_block(canvas, block, left, top, right, bottom)
                left = right + gap_x
                max_canvas_height = max(max_canvas_height, bottom)
            max_canvas_width = max(max_canvas_width, margin_x + row_width)

        for block in cfg.blocks:
            for succ in sorted(block.successors):
                if succ not in positions:
                    continue
                self.draw_cfg_edge(canvas, positions[block.name], positions[succ], levels[block.name] >= levels[succ])

        canvas.configure(scrollregion=(0, 0, max(1100, max_canvas_width + margin_x), max(700, max_canvas_height + margin_y)))

    def compute_cfg_levels(self, cfg: CFGResult) -> dict[str, int]:
        if not cfg.blocks:
            return {}
        levels = {cfg.blocks[0].name: 0}
        queue = [cfg.blocks[0]]
        block_by_name = {block.name: block for block in cfg.blocks}
        while queue:
            block = queue.pop(0)
            base = levels[block.name]
            for succ in sorted(block.successors):
                next_level = base + 1
                if succ not in levels or next_level < levels[succ]:
                    levels[succ] = next_level
                    queue.append(block_by_name[succ])
        for block in cfg.blocks:
            levels.setdefault(block.name, len(levels))
        return levels

    def block_visual_size(self, block) -> tuple[int, int]:
        lines = [format_quad(quad) for quad in block.quads]
        max_chars = max([len(block.name)] + [len(line) for line in lines])
        width = max(190, min(420, max_chars * 7 + 34))
        height = max(70, 32 + len(lines) * 18)
        return width, height

    def max_level_height(self, blocks: list) -> int:
        return max(self.block_visual_size(block)[1] for block in blocks)

    def draw_cfg_block(self, canvas: tk.Canvas, block, left: int, top: int, right: int, bottom: int) -> None:
        canvas.create_rectangle(left, top, right, bottom, fill="#ffffff", outline="#111111", width=1.5)
        canvas.create_text(
            (left + right) // 2,
            top + 14,
            text=block.name,
            anchor=tk.CENTER,
            fill="#000000",
            font=("Times New Roman", 13, "bold"),
        )
        y = top + 32
        for quad in block.quads:
            canvas.create_text(
                (left + right) // 2,
                y,
                text=format_quad(quad),
                anchor=tk.N,
                fill="#000000",
                font=("Times New Roman", 11),
            )
            y += 18

    def draw_cfg_edge(
        self,
        canvas: tk.Canvas,
        start: tuple[int, int, int, int],
        end: tuple[int, int, int, int],
        is_back_edge: bool,
    ) -> None:
        x1 = (start[0] + start[2]) // 2
        y1 = start[3]
        x2 = (end[0] + end[2]) // 2
        y2 = end[1]

        if is_back_edge:
            side_x = min(start[0], end[0]) - 35
            canvas.create_line(
                x1,
                y1,
                side_x,
                y1 + 25,
                side_x,
                y2 - 25,
                x2,
                y2,
                arrow=tk.LAST,
                fill="#000000",
                width=1.5,
                smooth=True,
            )
            return

        canvas.create_line(x1, y1, x2, y2, arrow=tk.LAST, fill="#000000", width=1.5, smooth=True)

    def show_error(self, exc: Exception) -> None:
        self.status.set(f"执行失败：{exc}")
        messagebox.showerror("执行失败", str(exc))


def main() -> None:
    app = CompilerCourseUI()
    app.mainloop()


if __name__ == "__main__":
    main()
