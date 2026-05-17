"""Start the best available UI for the compiler design project."""

from __future__ import annotations


def main() -> None:
    try:
        import qt_ui

        qt_ui.main()
    except ImportError as exc:
        print(f"Qt binding is not available in this Python interpreter: {exc}")
        print("Falling back to the Tkinter UI. To use the Qt UI, run: pip install PySide6_Essentials shiboken6")
        import ui

        ui.main()


if __name__ == "__main__":
    main()
