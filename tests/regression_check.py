"""Regression checks for the compiler design course project.

Run with:
    python tests/regression_check.py

The checks intentionally exercise the same integrated path used by the Qt UI:
class-C source -> quadruples -> interpreter -> LLVM -> CFG/DAG.
"""

from __future__ import annotations

import os
from pathlib import Path
import re
import shutil
import subprocess
import sys


BASE_DIR = Path(__file__).resolve().parents[1]
if str(BASE_DIR) not in sys.path:
    sys.path.insert(0, str(BASE_DIR))

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication

from modules.cfg import build_cfg, render_basic_blocks
from modules.dag_optimizer import DAGOptimizer
from modules.ide_diagnostics import CLikeIdeDiagnostics
from modules.interpreter import QuadInterpreter
from modules.llvm_converter import LLVMConverter
from modules.quad import Quad, parse_quad_line
from qt_ui import CompilerQtUI


def assert_true(condition: bool, message: str) -> None:
    if not condition:
        raise AssertionError(message)


def parse_return(compare_text: str) -> int:
    match = re.search(r"Quad return value:\s+(-?\d+)", compare_text)
    if not match:
        raise AssertionError("Cannot find quad return value")
    return int(match.group(1))


def parse_outputs(interpreter_text: str) -> list[int]:
    body = interpreter_text.split("Output Values:", 1)[1].split("Final Variables:", 1)[0]
    values = []
    for line in body.splitlines():
        text = line.strip()
        if re.fullmatch(r"-?\d+", text):
            values.append(int(text))
    return values


def run_source_case(window: CompilerQtUI, name: str, source: str, read_input: str, expected_return: int, expected_outputs: list[int]) -> None:
    window.clear_results()
    window.source_editor.setPlainText(source)
    window.interpreter_input_edit.setText(read_input)
    window.update_ide_diagnostics()
    diagnostics = window.source_diagnostics_box.toPlainText()
    assert_true("No lexical, syntax, or semantic errors." in diagnostics, f"{name}: IDE diagnostics failed\n{diagnostics}")

    window.run_source_full_pipeline()
    compare_text = window.text_tabs["Source Verify"].toPlainText()
    assert_true("Overall check: PASS" in compare_text, f"{name}: Source Verify failed\n{compare_text[:1000]}")
    actual_return = parse_return(compare_text)
    assert_true(actual_return == expected_return, f"{name}: expected return {expected_return}, got {actual_return}")

    exec_key = next(key for key in window.text_tabs if key == "解释执行")
    actual_outputs = parse_outputs(window.text_tabs[exec_key].toPlainText())
    assert_true(actual_outputs == expected_outputs, f"{name}: expected output {expected_outputs}, got {actual_outputs}")

    llvm_ir = window.text_tabs["LLVM IR"].toPlainText()
    assert_true("define i32 @main" in llvm_ir, f"{name}: LLVM main missing")
    assert_true("alloca i32" in llvm_ir, f"{name}: LLVM alloca missing")
    assert_true("br " in llvm_ir or "ret i32" in llvm_ir, f"{name}: LLVM terminator missing")

    cfg_text = window.text_tabs["基本块"].toPlainText()
    dag_text = window.text_tabs["DAG 分析"].toPlainText()
    optimized_text = window.text_tabs["优化四元式"].toPlainText()
    assert_true("B0" in cfg_text, f"{name}: CFG/basic blocks missing")
    assert_true("DAG nodes" in dag_text, f"{name}: DAG report missing")
    assert_true(optimized_text.strip(), f"{name}: optimized quads missing")


def run_quad_case(name: str, lines: list[str], expected_return: int, expected_outputs: list[int], read_inputs: list[int] | None = None) -> None:
    quads = [parse_quad_line(line, index) for index, line in enumerate(lines)]
    result = QuadInterpreter(quads, input_values=read_inputs).run()
    assert_true(result.return_value == expected_return, f"{name}: expected return {expected_return}, got {result.return_value}")
    assert_true(result.output_values == expected_outputs, f"{name}: expected output {expected_outputs}, got {result.output_values}")

    llvm_ir = LLVMConverter(quads).convert()
    assert_true("alloca i32" in llvm_ir, f"{name}: LLVM alloca missing")
    cfg = build_cfg(quads)
    assert_true(cfg.blocks, f"{name}: CFG has no blocks")
    assert_true("B0" in render_basic_blocks(cfg), f"{name}: basic block render missing")
    optimization = DAGOptimizer(cfg).optimize()
    assert_true(optimization.optimized_quads, f"{name}: optimized quads empty")


def find_clang() -> str | None:
    clang = shutil.which("clang")
    if clang:
        return clang
    candidates = [
        Path("E:/app/vs2022/VC/Tools/Llvm/bin/clang.exe"),
        Path("E:/app/vs2022/VC/Tools/Llvm/x64/bin/clang.exe"),
        Path("C:/Program Files/Microsoft Visual Studio/2026/BuildTools/VC/Tools/Llvm/bin/clang.exe"),
        Path("C:/Program Files/Microsoft Visual Studio/2026/BuildTools/VC/Tools/Llvm/x64/bin/clang.exe"),
    ]
    for candidate in candidates:
        if candidate.exists():
            return str(candidate)
    return None


def run_optional_llvm_external_check(window: CompilerQtUI) -> None:
    clang = find_clang()
    if not clang:
        print("SKIP optional LLVM external check: clang not found")
        return
    out_dir = BASE_DIR / "output" / "regression"
    out_dir.mkdir(parents=True, exist_ok=True)
    llvm_path = out_dir / "case.ll"
    obj_path = out_dir / "case.obj"
    exe_path = out_dir / "case.exe"
    llvm_path.write_text(window.text_tabs["LLVM IR"].toPlainText(), encoding="utf-8")

    compile_result = subprocess.run(
        [clang, "-c", str(llvm_path), "-o", str(obj_path)],
        cwd=str(BASE_DIR),
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert_true(compile_result.returncode == 0 and obj_path.exists(), f"clang -c failed\n{compile_result.stderr}")

    link_result = subprocess.run(
        [clang, str(llvm_path), "-o", str(exe_path)],
        cwd=str(BASE_DIR),
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert_true(link_result.returncode == 0 and exe_path.exists(), f"clang link failed\n{link_result.stderr}")
    print("PASS optional LLVM external check")


def run_negative_cases() -> None:
    div_zero = [parse_quad_line("0: (/, 10, 0, t1)", 0)]
    try:
        QuadInterpreter(div_zero).run()
    except RuntimeError as exc:
        assert_true("quad 0" in str(exc), "division by zero should include quad index")
    else:
        raise AssertionError("division by zero did not fail")

    bad_jump = [
        parse_quad_line("0: (J, _, _, 99)", 0),
    ]
    try:
        QuadInterpreter(bad_jump).run()
    except RuntimeError as exc:
        assert_true("quad 0" in str(exc), "bad jump should include quad index")
    else:
        raise AssertionError("bad jump did not fail")


def run_ide_negative_case(window: CompilerQtUI) -> None:
    source = """void main()
{
    int x
    x = 10
}
"""
    window.source_editor.setPlainText(source)
    window.update_ide_diagnostics()
    diagnostics = window.source_diagnostics_box.toPlainText()
    assert_true("缺少分号" in diagnostics, f"IDE should detect missing semicolon\n{diagnostics}")

def run_ide_mapping_cases(window: CompilerQtUI) -> None:
    semantic_source = """int read();
void write(int x);
int known(int a);

int known(int a)
{
    int t;
    t = a + 1;
    return t;
}

int no_return(int n)
{
    int r;
    r = n + 1;
}

int main()
{
    const int LIMIT = 10;
    int a, b;
    int a;

    a = read();
    LIMIT = 20;
    b = unknown_func(a, 1);
    c = b + 1;
    write();

    return b;
}
"""
    window.source_editor.setPlainText(semantic_source)
    window.update_ide_diagnostics()
    diagnostics = window.source_diagnostics_box.toPlainText()
    for expected in [
        "[Semantic] Line 12:",
        "(code 307)",
        "[Semantic] Line 22:",
        "(code 301)",
        "[Semantic] Line 25:",
        "(code 309)",
        "[Semantic] Line 26:",
        "(code 304)",
        "[Semantic] Line 27:",
        "(code 302)",
        "[Semantic] Line 28:",
        "(code 305)",
    ]:
        assert_true(expected in diagnostics, f"IDE semantic mapping missing {expected}\n{diagnostics}")

    syntax_source = """int main()
{
    int a;
    if (a > 0 {
        a = 1;
    return a;
"""
    window.source_editor.setPlainText(syntax_source)
    window.update_ide_diagnostics()
    diagnostics = window.source_diagnostics_box.toPlainText()
    assert_true(
        "[Syntax] Line 4:" in diagnostics and "(code 208)" in diagnostics,
        f"IDE should report missing paren at line 4\n{diagnostics}",
    )
    assert_true(
        "[Syntax] Line 6:" in diagnostics and "(code 205)" in diagnostics,
        f"IDE should report missing brace at line 6\n{diagnostics}",
    )
    assert_true(
        diagnostics.count("(code 208)") == 1,
        f"IDE should not duplicate missing paren diagnostics\n{diagnostics}",
    )


def main() -> None:
    app = QApplication.instance() or QApplication(sys.argv)
    window = CompilerQtUI()

    source_cases = [
        (
            "power_param_order",
            """int power(int base, int exp)
{
    int res;
    int i;
    res = 1;
    i = 0;
    while (i < exp) {
        res = res * base;
        i = i + 1;
    }
    return res;
}
int main()
{
    int result;
    result = power(2, 3);
    return result;
}
""",
            "",
            8,
            [],
        ),
        (
            "read_write_branch",
            """void main()
{
    int a;
    int b;
    int c;
    int max;
    a = read();
    b = read();
    c = a + b;
    if (a > b) {
        max = a;
    } else {
        max = b;
    }
    write(c);
    write(max);
}
""",
            "7 12",
            0,
            [19, 12],
        ),
        (
            "recursive_fib",
            """int seq(int m)
{
    int s;
    if (m <= 2) {
        s = 1;
    } else {
        s = seq(m - 1) + seq(m - 2);
    }
    return s;
}
void main()
{
    int n;
    int ans;
    n = read();
    ans = seq(n);
    write(ans);
}
""",
            "6",
            0,
            [8],
        ),
        (
            "four_params",
            """int pack(int a, int b, int c, int d)
{
    int r;
    r = a * 1000 + b * 100 + c * 10 + d;
    return r;
}
int main()
{
    int result;
    result = pack(1, 2, 3, 4);
    return result;
}
""",
            "",
            1234,
            [],
        ),
        (
            "dag_simplify",
            """int main()
{
    int a;
    int b;
    int c;
    int x;
    int y;
    int z;
    a = 2;
    b = 3;
    c = 5;
    x = a + b;
    y = a + b;
    z = c * 0;
    a = a + 0;
    b = b * 1;
    return x + y + z;
}
""",
            "",
            10,
            [],
        ),
    ]

    for case in source_cases:
        run_source_case(window, *case)
        print(f"PASS source: {case[0]}")

    run_optional_llvm_external_check(window)

    run_quad_case(
        "quad_loop_read",
        [
            "0: (main, _, _, _)",
            "1: (call, read, _, t1)",
            "2: (=, t1, _, n)",
            "3: (=, 1, _, i)",
            "4: (=, 0, _, sum)",
            "5: (J<=, i, n, 7)",
            "6: (J, _, _, 12)",
            "7: (+, sum, i, t2)",
            "8: (=, t2, _, sum)",
            "9: (+, i, 1, t3)",
            "10: (=, t3, _, i)",
            "11: (J, _, _, 5)",
            "12: (para, sum, _, _)",
            "13: (call, write, _, t4)",
            "14: (ret, _, _, sum)",
        ],
        expected_return=15,
        expected_outputs=[15],
        read_inputs=[5],
    )
    print("PASS quad: quad_loop_read")

    run_negative_cases()
    print("PASS negative interpreter cases")

    run_ide_negative_case(window)
    print("PASS IDE negative case")

    run_ide_mapping_cases(window)
    print("PASS IDE diagnostic mapping cases")

    window.close()
    app.quit()
    print("ALL REGRESSION CHECKS PASSED")


if __name__ == "__main__":
    main()
