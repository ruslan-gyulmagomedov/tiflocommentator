# -*- coding: utf-8 -*-
"""
Диалоговое окно ввода индивидуальных инструкций пользователя к выделенному фрагменту видео.
Полная доступность для скринридеров NVDA / JAWS.
"""

from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QPlainTextEdit, QPushButton
)
from PySide6.QtCore import Qt
from PySide6.QtGui import QKeySequence, QShortcut


class FragmentPromptDialog(QDialog):
    """Диалог ввода индивидуальных пожеланий к выделенному фрагменту видео."""

    def __init__(self, start_sec: float, end_sec: float, initial_prompt: str = "", parent=None):
        super().__init__(parent)
        self.start_sec = start_sec
        self.end_sec = end_sec
        self.dur_sec = max(0.1, round(end_sec - start_sec, 3))

        start_m, start_s = divmod(int(start_sec), 60)
        start_h, start_m = divmod(start_m, 60)
        start_frac = int(round((start_sec - int(start_sec)) * 1000))
        end_m, end_s = divmod(int(end_sec), 60)
        end_h, end_m = divmod(end_m, 60)
        end_frac = int(round((end_sec - int(end_sec)) * 1000))

        self.time_str = f"{start_h:02d}:{start_m:02d}:{start_s:02d}.{start_frac:03d} — {end_h:02d}:{end_m:02d}:{end_s:02d}.{end_frac:03d}"
        self.setWindowTitle(f"Комментирование фрагмента ({self.time_str})")
        self.setAccessibleName(f"Окно комментирования выделенного фрагмента от {start_sec:.2f} до {end_sec:.2f} секунд")
        self.resize(680, 440)
        self.setModal(True)

        self.init_ui(initial_prompt)

    def init_ui(self, initial_prompt: str):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setSpacing(10)

        lbl_info = QLabel(
            f"🎬 <b>Выделенный фрагмент:</b> {self.time_str} (длительность: {self.dur_sec:.2f} сек.)<br><br>"
            "Введите индивидуальные пожелания к комментированию только этого отрезка "
            "(или оставьте поле пустым для применения стандартных правил).<br><br>"
            "<i>Примечание: Общие пожелания проекта к данному фрагменту НЕ передаются.</i>",
            self
        )
        lbl_info.setTextFormat(Qt.RichText)
        lbl_info.setWordWrap(True)
        lbl_info.setStyleSheet(
            "background-color: #16222f; color: #00FFCC; font-size: 13px; padding: 10px; "
            "border: 1px solid #00AA88; border-radius: 4px;"
        )
        lbl_info.setAccessibleName(f"Информация о выделенном фрагменте {self.time_str}")
        layout.addWidget(lbl_info)

        lbl_edit_title = QLabel("Индивидуальные пожелания к выделенному фрагменту (необязательно):", self)
        lbl_edit_title.setStyleSheet("font-weight: bold; font-size: 13px; color: #FFFFFF;")
        lbl_edit_title.setAccessibleName("Поле ввода пожеланий к фрагменту")
        layout.addWidget(lbl_edit_title)

        self.text_edit = QPlainTextEdit(self)
        self.text_edit.setPlainText(initial_prompt or "")
        self.text_edit.setPlaceholderText(
            "Например:\n"
            "- Подробно описать обстановку и выражение лица персонажа.\n"
            "- Перевести иностранную надпись на русский язык.\n"
            "(Если оставить пустым, фрагмент комментируется по стандартным правилам)."
        )
        self.text_edit.setAccessibleName("Текст индивидуальных пожеланий к фрагменту")
        self.text_edit.setStyleSheet(
            "QPlainTextEdit { background-color: #1a1a1a; color: #FFFFFF; font-size: 14px; "
            "border: 2px solid #333333; border-radius: 4px; padding: 6px; }"
            "QPlainTextEdit:focus { border-color: #00FFCC; }"
        )
        layout.addWidget(self.text_edit, 1)

        btn_layout = QHBoxLayout()
        btn_layout.setSpacing(10)

        self.btn_submit = QPushButton("✨ Отправить на комментирование (Ctrl+Enter)", self)
        self.btn_submit.setAccessibleName("Кнопка Отправить фрагмент на комментирование в Gemini")
        self.btn_submit.setStyleSheet(
            "QPushButton { font-weight: bold; font-size: 13px; padding: 6px 18px; min-height: 32px; "
            "background-color: #007755; color: #FFFFFF; border: 1px solid #00AA77; border-radius: 4px; }"
            "QPushButton:hover { background-color: #009966; }"
            "QPushButton:focus { border: 2px solid #FFFF00; }"
        )
        self.btn_submit.clicked.connect(self.accept)

        self.btn_cancel = QPushButton("Отмена (Esc)", self)
        self.btn_cancel.setAccessibleName("Кнопка Отмена")
        self.btn_cancel.setStyleSheet(
            "QPushButton { font-size: 13px; padding: 6px 16px; min-height: 32px; "
            "background-color: #333333; color: #FFFFFF; border: 1px solid #555555; border-radius: 4px; }"
            "QPushButton:hover { background-color: #444444; }"
            "QPushButton:focus { border: 2px solid #FFFF00; }"
        )
        self.btn_cancel.clicked.connect(self.reject)

        btn_layout.addStretch(1)
        btn_layout.addWidget(self.btn_submit)
        btn_layout.addWidget(self.btn_cancel)
        layout.addLayout(btn_layout)

        shortcut_save = QShortcut(QKeySequence("Ctrl+Return"), self)
        shortcut_save.activated.connect(self.accept)
        shortcut_save_enter = QShortcut(QKeySequence("Ctrl+Enter"), self)
        shortcut_save_enter.activated.connect(self.accept)

        self.text_edit.setFocus()

    def get_fragment_prompt(self) -> str:
        """Возвращает введенный текст пожеланий пользователя к фрагменту."""
        return self.text_edit.toPlainText().strip()
