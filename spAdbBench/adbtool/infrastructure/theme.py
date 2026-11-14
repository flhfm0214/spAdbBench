from __future__ import annotations

from dataclasses import dataclass

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor, QPalette
from PySide6.QtWidgets import QApplication


@dataclass(frozen=True)
class ThemeTokens:
    name: str
    bg: str
    surface: str
    surface_alt: str
    text: str
    muted: str
    border: str
    accent: str
    accent_text: str
    selection: str
    danger: str
    danger_hover: str
    success: str
    warning: str
    input_bg: str
    table_alt: str
    video_bg: str


LIGHT = ThemeTokens(
    name="light",
    bg="#f5f6f7",
    surface="#ffffff",
    surface_alt="#eef0f2",
    text="#1f2328",
    muted="#475467",
    border="#d0d7de",
    accent="#2563eb",
    accent_text="#ffffff",
    selection="#dbeafe",
    danger="#b42318",
    danger_hover="#912018",
    success="#1a7f37",
    warning="#b54708",
    input_bg="#ffffff",
    table_alt="#fafbfc",
    video_bg="#111315",
)

DARK = ThemeTokens(
    name="dark",
    bg="#1e1f22",
    surface="#26282b",
    surface_alt="#2e3135",
    text="#e6e8eb",
    muted="#b8bdc4",
    border="#3c4043",
    accent="#4f8ef7",
    accent_text="#0b1220",
    selection="#1f3a5f",
    danger="#f97066",
    danger_hover="#ff8a80",
    success="#5dd39e",
    warning="#f5b759",
    input_bg="#1b1c1f",
    table_alt="#2a2c30",
    video_bg="#0b0c0d",
)


def resolve_theme(mode: str, app: QApplication | None = None) -> ThemeTokens:
    if mode == "dark":
        return DARK
    if mode == "light":
        return LIGHT
    if app is not None and app.styleHints().colorScheme() == Qt.ColorScheme.Dark:
        return DARK
    return LIGHT


def build_stylesheet(t: ThemeTokens) -> str:
    return f"""
    QWidget {{
        color: {t.text};
        background-color: {t.bg};
        font-size: 13px;
    }}
    QMainWindow, QDialog {{ background-color: {t.bg}; }}
    QMenuBar {{ background-color: {t.surface}; border-bottom: 1px solid {t.border}; }}
    QMenuBar::item {{ padding: 5px 10px; background: transparent; }}
    QMenuBar::item:selected {{ background-color: {t.surface_alt}; }}
    QMenu {{ background-color: {t.surface}; border: 1px solid {t.border}; padding: 4px; }}
    QMenu::item {{ padding: 5px 24px 5px 20px; }}
    QMenu::item:selected {{ background-color: {t.selection}; }}
    QToolBar {{ background-color: {t.surface}; border: none; spacing: 4px; padding: 4px; }}

    QListWidget#Nav {{
        background-color: {t.surface_alt};
        border: none;
        padding: 8px 6px;
        outline: none;
    }}
    QListWidget#Nav::item {{
        padding: 8px 10px;
        margin: 1px 0;
        border-radius: 2px;
        color: {t.muted};
    }}
    QListWidget#Nav::item:hover {{ background-color: {t.surface}; color: {t.text}; }}
    QListWidget#Nav::item:selected {{ background-color: {t.selection}; color: {t.text}; }}

    QWidget#Sidebar {{ background-color: {t.surface_alt}; }}
    QPushButton#NavSettings {{
        background-color: transparent;
        border: none;
        border-top: 1px solid {t.border};
        border-bottom: 1px solid {t.border};
        border-radius: 0;
        color: {t.muted};
        text-align: left;
        padding: 10px 16px;
        font-weight: 600;
    }}
    QPushButton#NavSettings:hover {{ background-color: {t.surface}; color: {t.text}; }}

    QFrame#Toast {{
        background-color: {t.surface};
        border: 1px solid {t.accent};
        border-left: 4px solid {t.accent};
        border-radius: 4px;
    }}
    QLabel#ToastTitle {{ font-weight: 600; color: {t.text}; }}
    QLabel#ToastText {{ color: {t.muted}; }}
    QPushButton#ToastClose {{
        background: transparent;
        border: none;
        color: {t.muted};
        font-size: 16px;
        padding: 0;
        min-height: 24px;
    }}
    QPushButton#ToastClose:hover {{ color: {t.text}; background-color: {t.surface_alt}; }}
    QLabel#WarningText {{
        color: {t.warning};
        font-weight: 600;
        padding: 6px 8px;
        background-color: {t.surface_alt};
        border-left: 3px solid {t.warning};
    }}
    QListWidget#GuideList {{
        background-color: {t.surface};
        border: 1px solid {t.border};
        outline: none;
    }}

    QWidget#TopBar {{ background-color: {t.surface}; border-bottom: 1px solid {t.border}; }}
    QWidget#PageHeader {{ background-color: {t.bg}; }}

    QPushButton {{
        background-color: {t.surface};
        color: {t.text};
        border: 1px solid {t.border};
        border-radius: 3px;
        padding: 6px 14px;
        min-height: 24px;
    }}
    QPushButton:hover {{ background-color: {t.surface_alt}; }}
    QPushButton:pressed {{ background-color: {t.selection}; }}
    QPushButton:disabled {{ color: {t.muted}; background-color: {t.surface_alt}; }}
    QPushButton#Primary {{
        background-color: {t.accent};
        color: {t.accent_text};
        border-color: {t.accent};
    }}
    QPushButton#Primary:hover {{ background-color: {t.accent}; }}
    QPushButton#Danger {{
        background-color: {t.danger};
        color: #ffffff;
        border-color: {t.danger};
    }}
    QPushButton#Danger:hover {{ background-color: {t.danger_hover}; }}
    QPushButton#Danger:disabled {{
        background-color: {t.surface_alt};
        color: {t.muted};
        border-color: {t.border};
    }}
    QPushButton#Primary:disabled {{
        background-color: {t.surface_alt};
        color: {t.muted};
        border-color: {t.border};
    }}
    QPushButton#LinkButton {{
        background: transparent;
        border: none;
        color: {t.accent};
        padding: 2px 4px;
    }}

    QLineEdit, QComboBox, QSpinBox, QDoubleSpinBox, QPlainTextEdit, QTextEdit {{
        background-color: {t.input_bg};
        color: {t.text};
        border: 1px solid {t.border};
        border-radius: 3px;
        padding: 5px 7px;
        selection-background-color: {t.selection};
    }}
    QLineEdit, QComboBox, QSpinBox, QDoubleSpinBox {{ min-height: 24px; }}
    QSpinBox::up-button, QDoubleSpinBox::up-button,
    QSpinBox::down-button, QDoubleSpinBox::down-button {{
        width: 0px;
        height: 0px;
        border: none;
        background: transparent;
    }}
    QLineEdit:focus, QComboBox:focus, QSpinBox:focus, QDoubleSpinBox:focus,
    QPlainTextEdit:focus, QTextEdit:focus {{ border-color: {t.accent}; }}
    QWidget#TerminalFrame {{
        background-color: {t.input_bg};
        border: 1px solid {t.border};
        border-radius: 2px;
    }}
    QPlainTextEdit#TerminalOutput {{
        background-color: {t.input_bg};
        border: none;
        border-radius: 0;
        padding: 4px 6px;
    }}
    QComboBox QAbstractItemView {{
        background-color: {t.surface};
        border: 1px solid {t.border};
        selection-background-color: {t.selection};
    }}
    QComboBox QAbstractItemView::item {{ padding: 6px 8px; }}

    QTableWidget, QTableView {{
        background-color: {t.surface};
        alternate-background-color: {t.table_alt};
        gridline-color: {t.border};
        border: 1px solid {t.border};
        selection-background-color: {t.selection};
        selection-color: {t.text};
        outline: none;
    }}
    QHeaderView::section {{
        background-color: {t.surface_alt};
        color: {t.muted};
        border: none;
        border-bottom: 1px solid {t.border};
        padding: 5px;
        font-weight: 600;
    }}
    QTableCornerButton::section {{ background-color: {t.surface_alt}; border: none; }}

    QGroupBox {{
        border: none;
        margin-top: 16px;
        padding-top: 8px;
    }}
    QGroupBox::title {{
        subcontrol-origin: margin;
        left: 0;
        padding: 0 0 6px 0;
        color: {t.text};
        font-size: 15px;
        font-weight: 700;
    }}
    QFrame#Separator {{ color: {t.border}; background-color: {t.border}; max-height: 1px; }}

    QLabel#SectionTitle {{ font-size: 20px; font-weight: 700; color: {t.text}; }}
    QLabel#Value {{ font-weight: 600; color: {t.text}; }}
    QLabel#MetricValue {{ font-size: 22px; font-weight: 600; color: {t.text}; }}
    QLabel#MetricDetail {{ color: {t.muted}; font-size: 12px; }}
    QLabel#MetricError {{ color: {t.danger}; }}
    QLabel#Muted {{ color: {t.muted}; font-size: 12px; }}
    QWidget#ProjectLinkBox {{ background-color: {t.surface_alt}; }}
    QLabel#ProjectLink {{ color: {t.accent}; background: transparent; }}
    QPushButton#ProjectLinkIcon {{
        background: transparent;
        border: none;
        padding: 0;
        min-height: 0;
    }}
    QLabel#FormLabel {{ color: {t.text}; font-size: 13px; font-weight: 600; }}
    QLabel#DangerRisk {{ color: {t.danger}; font-weight: 600; }}
    QLabel#StatusSuccess {{ color: {t.success}; }}
    QLabel#StatusError {{ color: {t.danger}; }}
    QLabel#ScreenshotPreview {{
        background-color: {t.video_bg};
        color: {t.muted};
        border: 1px solid {t.border};
    }}
    QWidget#ScreenPreview {{
        background-color: {t.surface};
    }}
    QWidget#ControlSidebar {{
        background-color: {t.surface_alt};
        border-right: 1px solid {t.border};
    }}
    QWidget#ControlSidebar[landscape="true"] {{
        border-right: none;
        border-bottom: 1px solid {t.border};
    }}
    QScrollArea#SidebarScroll, QWidget#SidebarContent {{
        background-color: transparent;
        border: none;
    }}
    QWidget#NativeVideoHost {{
        background-color: {t.video_bg};
    }}
    QLabel#SidebarTitle {{
        color: {t.muted};
        font-weight: 600;
        font-size: 12px;
    }}
    QLabel#SidebarHint {{
        color: {t.muted};
        font-size: 11px;
    }}
    QPushButton#SidebarKey {{
        text-align: center;
        padding: 6px 4px;
        min-height: 26px;
    }}
    QPushButton#SidebarRetry {{
        color: {t.accent};
        border: 1px solid {t.accent};
        background-color: transparent;
        padding: 6px 4px;
    }}
    QLabel#SidebarValue {{ font-weight: 600; color: {t.text}; }}
    QLabel#SidebarSensor {{ color: {t.muted}; font-size: 11px; }}
    QLabel#VideoCanvas {{
        background-color: {t.video_bg};
        color: {t.muted};
        border: 1px solid {t.border};
    }}
    QLabel#VideoDevice {{ font-weight: 600; color: {t.text}; }}
    QLabel#VideoStatus {{ color: {t.muted}; }}
    QLabel#VideoPlaceholder {{
        background-color: {t.video_bg};
        color: {t.muted};
        border: 1px solid {t.border};
    }}

    QTabWidget::pane {{ border: 1px solid {t.border}; background: {t.surface}; }}
    QTabBar::tab {{
        background: {t.surface_alt};
        padding: 9px 16px;
        border: none;
        color: {t.text};
        font-size: 15px;
        font-weight: 600;
    }}
    QTabBar::tab:selected {{ background: {t.surface}; color: {t.accent}; font-weight: 700; }}

    QStatusBar {{ background-color: {t.surface}; border-top: 1px solid {t.border}; color: {t.muted}; }}
    QStatusBar::item {{ border: none; }}

    QDockWidget {{ color: {t.text}; }}
    QDockWidget::title {{ background-color: {t.surface_alt}; padding: 6px 8px; text-align: left; }}
    QSplitter::handle {{ background-color: {t.border}; width: 1px; height: 1px; }}

    QCheckBox, QRadioButton {{ spacing: 8px; color: {t.text}; }}
    QCheckBox::indicator, QRadioButton::indicator {{ width: 14px; height: 14px; }}
    QProgressBar {{
        border: 1px solid {t.border};
        border-radius: 2px;
        background-color: {t.surface_alt};
        text-align: center;
        min-height: 16px;
    }}
    QProgressBar::chunk {{ background-color: {t.accent}; }}
    QScrollBar:vertical {{ background: {t.surface_alt}; width: 12px; margin: 0; }}
    QScrollBar::handle:vertical {{ background: {t.border}; min-height: 24px; border-radius: 2px; }}
    QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{ height: 0; }}
    QScrollBar:horizontal {{ background: {t.surface_alt}; height: 12px; margin: 0; }}
    QScrollBar::handle:horizontal {{ background: {t.border}; min-width: 24px; border-radius: 2px; }}
    QScrollBar::add-line:horizontal, QScrollBar::sub-line:horizontal {{ width: 0; }}
    QToolTip {{ background-color: {t.surface}; color: {t.text}; border: 1px solid {t.border}; padding: 4px; }}
    """


def apply_theme(app: QApplication, mode: str) -> ThemeTokens:
    tokens = resolve_theme(mode, app)
    palette = QPalette()
    palette.setColor(QPalette.ColorRole.Window, QColor(tokens.bg))
    palette.setColor(QPalette.ColorRole.WindowText, QColor(tokens.text))
    palette.setColor(QPalette.ColorRole.Base, QColor(tokens.input_bg))
    palette.setColor(QPalette.ColorRole.AlternateBase, QColor(tokens.table_alt))
    palette.setColor(QPalette.ColorRole.Text, QColor(tokens.text))
    palette.setColor(QPalette.ColorRole.Button, QColor(tokens.surface))
    palette.setColor(QPalette.ColorRole.ButtonText, QColor(tokens.text))
    palette.setColor(QPalette.ColorRole.Highlight, QColor(tokens.selection))
    palette.setColor(QPalette.ColorRole.HighlightedText, QColor(tokens.text))
    palette.setColor(QPalette.ColorRole.Link, QColor(tokens.accent))
    palette.setColor(QPalette.ColorRole.LinkVisited, QColor(tokens.accent))
    palette.setColor(QPalette.ColorRole.ToolTipBase, QColor(tokens.surface))
    palette.setColor(QPalette.ColorRole.ToolTipText, QColor(tokens.text))
    app.setPalette(palette)
    app.setStyleSheet(build_stylesheet(tokens))
    return tokens
