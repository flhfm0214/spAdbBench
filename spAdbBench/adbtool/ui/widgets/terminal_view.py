from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QContextMenuEvent, QFontDatabase, QTextCursor
from PySide6.QtWidgets import (
    QApplication,
    QMenu,
    QPlainTextEdit,
)


class TerminalView(QPlainTextEdit):
    """Terminal output with one editable prompt line at the bottom."""

    submitted = Signal(str)
    tab_pressed = Signal()
    interrupt_requested = Signal()
    clear_requested = Signal()
    history_previous = Signal()
    history_next = Signal()

    def __init__(self) -> None:
        super().__init__()
        self._prompt = "adb> "
        self._editable = True
        self._buffer = ""
        self.setReadOnly(False)
        self.setUndoRedoEnabled(False)
        self.setMaximumBlockCount(20000)
        self.setCursorWidth(2)
        self.setLineWrapMode(QPlainTextEdit.LineWrapMode.NoWrap)
        self.setFont(
            QFontDatabase.systemFont(QFontDatabase.SystemFont.FixedFont)
        )
        self.set_prompt(self._prompt)

    @property
    def prompt(self) -> str:
        return self._prompt

    @property
    def prompt_start(self) -> int:
        return self.document().lastBlock().position()

    @property
    def input_start(self) -> int:
        return self.prompt_start + len(self._prompt)

    @property
    def input_end(self) -> int:
        return len(self.toPlainText())

    @property
    def editable(self) -> bool:
        return self._editable

    def set_prompt(self, prompt: str, reset: bool = True) -> None:
        self._buffer = ""
        if reset:
            self._prompt = prompt
            self.setPlainText(prompt)
        else:
            # Replace only the active prompt line.  Assign the new prompt after
            # the replacement: input_start depends on the prompt length, and
            # using the longer new prompt against the old document truncates
            # the whole transcript.
            start = self.document().lastBlock().position()
            cursor = QTextCursor(self.document())
            cursor.setPosition(start)
            cursor.movePosition(
                QTextCursor.MoveOperation.End, QTextCursor.MoveMode.KeepAnchor
            )
            cursor.insertText(prompt)
            self._prompt = prompt
        self.set_cursor_end()

    def set_editable(self, editable: bool) -> None:
        self._editable = bool(editable)
        self.setReadOnly(not self._editable)
        if self._editable:
            self.setFocus()

    def input_text(self) -> str:
        return self.toPlainText()[self.input_start :]

    def text(self) -> str:
        return self.input_text()

    def set_input_text(self, text: str) -> None:
        clean = " ".join(str(text).splitlines())
        cursor = QTextCursor(self.document())
        cursor.setPosition(self.input_start)
        cursor.movePosition(
            QTextCursor.MoveOperation.End, QTextCursor.MoveMode.KeepAnchor
        )
        cursor.insertText(clean)
        self.set_cursor_end()

    def setText(self, text: str) -> None:
        self.set_input_text(text)

    def clear(self) -> None:
        self.set_input_text("")

    def set_cursor_end(self) -> None:
        cursor = self.textCursor()
        cursor.movePosition(QTextCursor.MoveOperation.End)
        self.setTextCursor(cursor)
        self.ensureCursorVisible()

    def set_cursor_start(self) -> None:
        cursor = self.textCursor()
        cursor.setPosition(self.input_start)
        self.setTextCursor(cursor)

    def append_output(self, text: str) -> None:
        if not text:
            return
        self._buffer += text.replace("\r\n", "\n").replace("\r", "\n")
        while "\n" in self._buffer:
            line, self._buffer = self._buffer.split("\n", 1)
            self._insert_before_prompt(f"{line}\n")

    def flush_output(self) -> None:
        if not self._buffer:
            return
        text = self._buffer
        self._buffer = ""
        self._insert_before_prompt(f"{text}\n")

    def clear_terminal(self) -> None:
        self.set_prompt(self._prompt)

    def _insert_before_prompt(self, text: str) -> None:
        if not text:
            return
        prompt_start = self.document().lastBlock().position()
        old = self.textCursor()
        old_position = old.position()
        old_anchor = old.anchor()
        cursor = QTextCursor(self.document())
        cursor.setPosition(prompt_start)
        cursor.insertText(text)
        new_position = (
            old_position + len(text)
            if old_position >= prompt_start
            else old_position
        )
        new_anchor = (
            old_anchor + len(text) if old_anchor >= prompt_start else old_anchor
        )
        new_position = min(new_position, self.input_end)
        new_anchor = min(new_anchor, self.input_end)
        cursor = QTextCursor(self.document())
        cursor.setPosition(new_anchor)
        if new_position != new_anchor:
            cursor.setPosition(new_position, QTextCursor.MoveMode.KeepAnchor)
        self.setTextCursor(cursor)
        self.ensureCursorVisible()

    def _ensure_input_cursor(self) -> QTextCursor:
        cursor = self.textCursor()
        if cursor.hasSelection():
            start = min(cursor.position(), cursor.anchor())
            if start < self.input_start:
                cursor.clearSelection()
                cursor.movePosition(QTextCursor.MoveOperation.End)
                self.setTextCursor(cursor)
        if cursor.position() < self.input_start:
            cursor.setPosition(self.input_start)
            self.setTextCursor(cursor)
        return cursor

    def _delete_range(self, start: int, end: int) -> None:
        start = max(start, self.input_start)
        end = min(end, self.input_end)
        if end <= start:
            return
        cursor = QTextCursor(self.document())
        cursor.setPosition(start)
        cursor.setPosition(end, QTextCursor.MoveMode.KeepAnchor)
        cursor.removeSelectedText()
        self.set_cursor_end()

    def _submit(self) -> None:
        command = self.input_text().strip()
        cursor = self.textCursor()
        cursor.movePosition(QTextCursor.MoveOperation.End)
        cursor.insertText(f"\n{self._prompt}")
        self.setTextCursor(cursor)
        self.set_cursor_end()
        if command:
            self.submitted.emit(command)

    def _paste(self) -> None:
        text = QApplication.clipboard().text()
        if not text:
            return
        clean = " ".join(text.replace("\r\n", "\n").splitlines())
        cursor = self._ensure_input_cursor()
        if cursor.hasSelection():
            start = min(cursor.position(), cursor.anchor())
            if start < self.input_start:
                cursor.clearSelection()
                cursor.movePosition(QTextCursor.MoveOperation.End)
            else:
                cursor.removeSelectedText()
        cursor.insertText(clean)
        self.setTextCursor(cursor)
        self.ensureCursorVisible()

    def copy_all(self) -> None:
        QApplication.clipboard().setText(self.toPlainText())

    def build_context_menu(self) -> QMenu:
        menu = QMenu(self)
        paste = menu.addAction("粘贴")
        paste.setEnabled(self._editable)
        paste.triggered.connect(self._paste)
        copy = menu.addAction("复制")
        copy.setEnabled(self.textCursor().hasSelection())
        copy.triggered.connect(self.copy)
        copy_all = menu.addAction("全部复制")
        copy_all.triggered.connect(self.copy_all)
        select_all = menu.addAction("全选")
        select_all.triggered.connect(self.selectAll)
        menu.addSeparator()
        interrupt = menu.addAction("中断当前命令")
        interrupt.setEnabled(self._editable)
        interrupt.triggered.connect(self.interrupt_requested.emit)
        clear = menu.addAction("清屏")
        clear.triggered.connect(self.clear_requested.emit)
        return menu

    def contextMenuEvent(self, event: QContextMenuEvent) -> None:
        self.build_context_menu().exec(event.globalPos())

    def keyPressEvent(self, event) -> None:
        if not self._editable:
            super().keyPressEvent(event)
            return

        key = event.key()
        modifiers = event.modifiers()
        control = bool(modifiers & Qt.KeyboardModifier.ControlModifier)
        shift = bool(modifiers & Qt.KeyboardModifier.ShiftModifier)

        if control and key == Qt.Key.Key_A:
            self.set_cursor_start()
            event.accept()
            return
        if control and key == Qt.Key.Key_E:
            self.set_cursor_end()
            event.accept()
            return
        if control and key == Qt.Key.Key_U:
            cursor = self._ensure_input_cursor()
            self._delete_range(self.input_start, cursor.position())
            event.accept()
            return
        if control and key == Qt.Key.Key_K:
            cursor = self._ensure_input_cursor()
            self._delete_range(cursor.position(), self.input_end)
            event.accept()
            return
        if control and key == Qt.Key.Key_W:
            cursor = self._ensure_input_cursor()
            text = self.toPlainText()
            pos = cursor.position()
            start = pos
            while start > self.input_start and text[start - 1].isspace():
                start -= 1
            while start > self.input_start and not text[start - 1].isspace():
                start -= 1
            self._delete_range(start, pos)
            event.accept()
            return
        if control and key == Qt.Key.Key_L:
            self.clear_requested.emit()
            event.accept()
            return
        if control and key == Qt.Key.Key_C:
            if shift:
                self.copy()
            else:
                self.interrupt_requested.emit()
            event.accept()
            return
        if control and key == Qt.Key.Key_V:
            self._paste()
            event.accept()
            return
        if shift and key == Qt.Key.Key_Insert:
            self._paste()
            event.accept()
            return
        if key in (Qt.Key.Key_Return, Qt.Key.Key_Enter):
            self._submit()
            event.accept()
            return
        if key == Qt.Key.Key_Tab:
            self.tab_pressed.emit()
            event.accept()
            return
        if key == Qt.Key.Key_Up:
            self.history_previous.emit()
            event.accept()
            return
        if key == Qt.Key.Key_Down:
            self.history_next.emit()
            event.accept()
            return
        if key == Qt.Key.Key_Home:
            self.set_cursor_start()
            event.accept()
            return
        if key == Qt.Key.Key_End:
            self.set_cursor_end()
            event.accept()
            return

        cursor = self.textCursor()
        if key in (Qt.Key.Key_Backspace, Qt.Key.Key_Delete):
            if (
                key == Qt.Key.Key_Backspace
                and not cursor.hasSelection()
                and cursor.position() <= self.input_start
            ):
                event.accept()
                return
            if (
                key == Qt.Key.Key_Delete
                and not cursor.hasSelection()
                and cursor.position() >= self.input_end
            ):
                event.accept()
                return
            if cursor.position() < self.input_start:
                self.set_cursor_end()
                event.accept()
                return
            if cursor.hasSelection():
                start = min(cursor.position(), cursor.anchor())
                if start < self.input_start:
                    cursor.clearSelection()
                    self.setTextCursor(cursor)
                    self.set_cursor_end()
                    event.accept()
                    return
            super().keyPressEvent(event)
            return

        if key == Qt.Key.Key_Left:
            if not cursor.hasSelection() and cursor.position() <= self.input_start:
                event.accept()
                return
        if key == Qt.Key.Key_Right:
            if cursor.position() < self.input_start:
                cursor.setPosition(self.input_start)
                self.setTextCursor(cursor)
                event.accept()
                return

        if event.text() and not event.text().isprintable():
            super().keyPressEvent(event)
            return
        if event.text():
            cursor = self._ensure_input_cursor()
        super().keyPressEvent(event)
