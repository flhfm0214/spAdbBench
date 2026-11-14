from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication

from adbtool.ui.widgets.terminal_view import TerminalView


def make_view(qtbot) -> TerminalView:
    view = TerminalView()
    qtbot.addWidget(view)
    view.show()
    view.set_prompt("adb> ")
    view.setFocus()
    return view


def test_prompt_and_input_share_the_terminal_document(qtbot):
    view = make_view(qtbot)

    view.set_input_text("devices")

    assert view.toPlainText() == "adb> devices"
    assert view.input_text() == "devices"


def test_enter_emits_command_and_redraws_prompt(qtbot):
    view = make_view(qtbot)
    submitted = []
    view.submitted.connect(submitted.append)
    view.set_input_text("devices")

    qtbot.keyClick(view, Qt.Key_Return)

    assert submitted == ["devices"]
    assert view.toPlainText() == "adb> devices\nadb> "
    assert view.input_text() == ""


def test_output_is_inserted_before_the_active_prompt(qtbot):
    view = make_view(qtbot)
    view.set_input_text("abc")

    view.append_output("line one\nline two\n")

    assert view.toPlainText() == "line one\nline two\nadb> abc"
    assert view.input_text() == "abc"


def test_prompt_switch_preserves_existing_transcript(qtbot):
    view = make_view(qtbot)
    view.append_output("hello output\n")
    view.flush_output()

    view.set_prompt("fastboot> ", reset=False)
    assert view.toPlainText() == "hello output\nfastboot> "

    view.set_prompt("adb> ", reset=False)
    assert view.toPlainText() == "hello output\nadb> "


def test_ctrl_a_and_ctrl_e_move_inside_input(qtbot):
    view = make_view(qtbot)
    view.set_input_text("echo hello")
    view.set_cursor_end()

    qtbot.keyClick(view, Qt.Key_A, Qt.KeyboardModifier.ControlModifier)
    assert view.textCursor().position() == view.input_start

    qtbot.keyClick(view, Qt.Key_E, Qt.KeyboardModifier.ControlModifier)
    assert view.textCursor().position() == view.input_end


def test_shift_insert_pastes_into_input(qtbot):
    view = make_view(qtbot)
    view.set_input_text("")
    QApplication.clipboard().setText("getprop ro.product.model")
    view.setFocus()

    qtbot.keyClick(
        view,
        Qt.Key_Insert,
        Qt.KeyboardModifier.ShiftModifier,
    )

    assert view.input_text() == "getprop ro.product.model"


def test_backspace_cannot_delete_the_prompt(qtbot):
    view = make_view(qtbot)
    view.set_input_text("")
    view.setFocus()

    qtbot.keyClick(view, Qt.Key_Backspace)

    assert view.toPlainText() == "adb> "


def test_context_menu_exposes_terminal_actions(qtbot):
    view = make_view(qtbot)
    menu = view.build_context_menu()

    labels = [action.text() for action in menu.actions()]
    for expected in ("粘贴", "复制", "全部复制", "全选", "清屏"):
        assert expected in labels


def test_context_menu_paste_action_inserts_clipboard(qtbot):
    view = make_view(qtbot)
    view.set_input_text("echo ")
    QApplication.clipboard().setText("你好")
    menu = view.build_context_menu()
    paste = next(action for action in menu.actions() if action.text() == "粘贴")

    paste.trigger()

    assert view.input_text() == "echo 你好"


def test_copy_all_uses_whole_terminal_text(qtbot):
    view = make_view(qtbot)
    view.set_input_text("devices")

    view.copy_all()

    assert QApplication.clipboard().text() == "adb> devices"


def test_tab_and_interrupt_are_exposed_as_signals(qtbot):
    view = make_view(qtbot)
    events = []
    view.tab_pressed.connect(lambda: events.append("tab"))
    view.interrupt_requested.connect(lambda: events.append("interrupt"))

    qtbot.keyClick(view, Qt.Key_Tab)
    qtbot.keyClick(view, Qt.Key_C, Qt.KeyboardModifier.ControlModifier)

    assert events == ["tab", "interrupt"]
