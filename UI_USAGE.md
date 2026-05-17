# UI 界面使用说明

## 推荐启动方式：PySide6 Qt 界面

当前项目使用 PySide6 实现 Qt 交互界面。

演示任务书第 2 条“整合、完善已完成的编译程序各阶段相关功能，并能可视化演示”时运行：

```bash
python stage_ui.py
```

该界面展示：源程序、词法 Tokens、语法 AST、语法树图、语义检查 / 符号表、中间代码四元式，以及编译阶段流程图。

演示 3.2、4.2、4.4 的四元式解释、LLVM IR、CFG 和 DAG 优化时运行：

```bash
python qt_ui.py
```

在该界面中可以直接输入类 C 源码，点击“源码生成并全流程”。系统会自动完成：

```text
类 C 源码 -> 四元式生成 -> 源码执行验证 -> 四元式解释执行 -> LLVM IR -> CFG -> DAG 优化
```

`Source Verify` 标签页会展示源码直接执行结果与四元式解释执行结果的对比，用于验证四元式是否正确。
完成 DAG 优化后，界面还会重新基于优化后的四元式生成“优化后基本块”“优化后 CFG DOT”和“优化后 CFG 图”，便于和原始 CFG 对比截图。

`类C源码` 标签页同时集成了 4.3 编程 IDE 功能：关键字/函数名高亮、回车自动缩进、源码格式化，以及 `IDE诊断` 标签页中的词法、语法、语义实时错误提示和修改建议。

也可以使用统一入口：

```bash
python start_ui.py
```

如果提示缺少 Qt 运行库，请在当前 PyCharm 解释器环境中安装：

```bash
pip install PySide6_Essentials shiboken6
```

或执行：

```bash
pip install -r requirements.txt
```

## 备用启动方式：Tkinter 界面

如果当前环境无法安装 Qt，也可以运行旧版备用界面：

```bash
python ui.py
```

## 主要输出文件

Qt 界面的结果会展示在标签页中，也会保存到输出目录。常见输出包括：

```text
interpreter_result.txt
llvm_ir.ll
basic_blocks.txt
cfg.dot
dag_blocks.txt
optimized_quads.txt
optimized_basic_blocks.txt
optimized_cfg.dot
compare_report.txt
ide_diagnostics.txt
```
