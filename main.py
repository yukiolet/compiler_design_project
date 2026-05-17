"""Unified entry point for the compiler design course project."""

from __future__ import annotations

import argparse
from pathlib import Path
import re

from modules.cfg import build_cfg, render_basic_blocks, render_cfg_dot
from modules.dag_optimizer import DAGOptimizer
from modules.interpreter import QuadInterpreter, render_interpreter_result
from modules.llvm_converter import LLVMConverter
from modules.quad import read_quads, write_quads


BASE_DIR = Path(__file__).resolve().parent
DEFAULT_INPUT_PATH = BASE_DIR / "input" / "quads.txt"
DEFAULT_OUTPUT_DIR = BASE_DIR / "output"


def parse_read_inputs(text: str) -> list[int]:
    if not text.strip():
        return []
    return [int(token, 0) for token in re.split(r"[\s,;]+", text.strip()) if token]


def run_pipeline(input_path: Path, output_dir: Path, read_inputs: list[int] | None = None) -> None:
    output_dir.mkdir(exist_ok=True)

    quads = read_quads(input_path)
    if not quads:
        raise RuntimeError(f"No quadruples found in {input_path}")

    interpreter_result = QuadInterpreter(quads, input_values=read_inputs).run()
    (output_dir / "interpreter_result.txt").write_text(
        render_interpreter_result(interpreter_result),
        encoding="utf-8",
    )

    llvm_ir = LLVMConverter(quads).convert()
    (output_dir / "llvm_ir.ll").write_text(llvm_ir, encoding="utf-8")

    cfg = build_cfg(quads)
    (output_dir / "basic_blocks.txt").write_text(render_basic_blocks(cfg), encoding="utf-8")
    (output_dir / "cfg.dot").write_text(render_cfg_dot(cfg), encoding="utf-8")

    optimization = DAGOptimizer(cfg).optimize()
    write_quads(output_dir / "optimized_quads.txt", optimization.optimized_quads)
    (output_dir / "dag_blocks.txt").write_text(optimization.dag_report, encoding="utf-8")
    (output_dir / "compare_report.txt").write_text(optimization.compare_report, encoding="utf-8")

    optimized_cfg = build_cfg(optimization.optimized_quads)
    (output_dir / "optimized_basic_blocks.txt").write_text(
        render_basic_blocks(optimized_cfg),
        encoding="utf-8",
    )
    (output_dir / "optimized_cfg.dot").write_text(render_cfg_dot(optimized_cfg), encoding="utf-8")

    print("Compiler design pipeline finished.")
    print(f"Input file: {input_path}")
    print(f"Input quads: {len(quads)}")
    print(f"Read inputs: {read_inputs or []}")
    print(f"Output directory: {output_dir}")
    print("Generated: interpreter_result.txt, llvm_ir.ll, basic_blocks.txt, cfg.dot, dag_blocks.txt, optimized_quads.txt, compare_report.txt, optimized_basic_blocks.txt, optimized_cfg.dot")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run quadruple interpreter, LLVM conversion, CFG, and DAG optimization.")
    parser.add_argument("--input", type=Path, default=DEFAULT_INPUT_PATH, help="quadruple input file")
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT_DIR, help="output directory")
    parser.add_argument("--read-input", default="", help="values consumed by read(), separated by spaces or commas")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    run_pipeline(args.input.resolve(), args.output.resolve(), parse_read_inputs(args.read_input))


if __name__ == "__main__":
    main()
