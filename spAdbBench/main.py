import sys
from pathlib import Path

from adbtool.application import build_app, build_context, run


def _self_check() -> int:
    app = build_app([])
    context = build_context()
    from adbtool.ui.main_window import MainWindow

    window = MainWindow(context, auto_refresh=False)
    target = Path(context.config_store.root) / "data" / "selfcheck.txt"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text("ok\n", encoding="utf-8")
    window.close()
    app.processEvents()
    return 0


if __name__ == "__main__":
    if "--self-check" in sys.argv:
        raise SystemExit(_self_check())
    raise SystemExit(run())
