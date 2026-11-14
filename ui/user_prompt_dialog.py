# -*- coding: utf-8 -*-
"""
Диалоговое окно для ввода и редактирования индивидуальных пожеланий пользователя к проекту.
Пожелания сохраняются в проекте (project.json) и передаются в контекст Gemini API
с наивысшим приоритетом над всеми стандартными инструкциями.
Полная доступность для скринридеров NVDA / JAWS.
"""

from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QPlainTextEdit, QPushButton, QSizePolicy
)
from PySide6.QtCore import Qt
from PySide6.QtGui import QKeySequence, QShortcut


class UserPromptDialog(QDialog):
    """Диалог ввода и редактирования пожеланий пользователя к проекту тифлокомментирования."""

    def __init__(self, current_prompt: str = "", project_name: str = "", parent=None):
        super().__init__(parent)
        self.setWindowTitle(f"Пожелания пользователя к проекту — {project_name}" if project_name else "Пожелания пользователя к проекту")
        self.resize(700, 480)
        self.setModal(True)

        self.init_ui(current_prompt)

    def init_ui(self, current_prompt: str):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setSpacing(10)

        # Информационная панель с описанием приоритета и назначения
        lbl_info = QLabel(
            "Укажите ваши индивидуальные пожелания к тифлокомментированию, синопсис, сценарий "
            "или особые требования (например, сделать перевод иностранной речи, сосредоточиться на "
            "определенных персонажах, изменить стиль описания).\n\n"
            "⚠️ ВНИМАНИЕ: Данные указания сохраняются в проекте, передаются модели Gemini при анализе "
            "каждого фрагмента фильма и имеют НАИВЫСШИЙ ПРИОРИТЕТ над стандартными правилами.",
            self
        )
        lbl_info.setWordWrap(True)
        lbl_info.setStyleSheet(
            "background-color: #121b24; color: #00FFCC; font-size: 13px; padding: 10px; "
            "border: 1px solid #00AA88; border-radius: 4px;"
        )
        lbl_info.setAccessibleName("Информация о назначении и наивысшем приоритете пожеланий пользователя")
        layout.addWidget(lbl_info)

        lbl_edit_title = QLabel("Текст пожеланий, сюжет или сценарий к фильму:", self)
        lbl_edit_title.setStyleSheet("font-weight: bold; font-size: 13px; color: #FFFFFF;")
        lbl_edit_title.setAccessibleName("Текст пожеланий, сюжет или сценарий к фильму")
        layout.addWidget(lbl_edit_title)

        self.text_edit = QPlainTextEdit(self)
        self.text_edit.setPlainText(current_prompt or "")
        self.text_edit.setPlaceholderText(
            "Например:\n"
            "- Сделайте не тифлокомментарии, а полный перевод всех диалогов на русский язык.\n"
            "- Краткий сюжет фильма: Главный герой отправляется на поиски пропавшей экспедиции...\n"
            "- Обратите особое внимание на жесты и мимику персонажа в синем костюме (это майор Смирнов)."
        )
        self.text_edit.setAccessibleName("Поле ввода пожеланий и инструкций пользователя")
        self.text_edit.setAccessibleDescription(
            "Введите пожелания к тифлокомментированию, сюжет или сценарий. "
            "Нажмите Ctrl+Enter для сохранения или Escape для отмены."
        )
        self.text_edit.setStyleSheet(
            "QPlainTextEdit { background-color: #1a1a1a; color: #FFFFFF; font-size: 14px; "
            "border: 2px solid #333333; border-radius: 4px; padding: 6px; }"
            "QPlainTextEdit:focus { border-color: #00FFCC; }"
        )
        layout.addWidget(self.text_edit, 1)

        # Нижняя панель с кнопками
        btn_layout = QHBoxLayout()
        btn_layout.setSpacing(10)

        self.btn_save = QPushButton("Сохранить (Ctrl+Enter)", self)
        self.btn_save.setAccessibleName("Кнопка Сохранить пожелания к проекту")
        self.btn_save.setAccessibleDescription("Сохраняет введенные пожелания в проекте")
        self.btn_save.setStyleSheet(
            "QPushButton { font-weight: bold; font-size: 13px; padding: 6px 18px; min-height: 32px; "
            "background-color: #007755; color: #FFFFFF; border: 1px solid #00AA77; border-radius: 4px; }"
            "QPushButton:hover { background-color: #009966; }"
            "QPushButton:focus { border: 2px solid #FFFF00; }"
        )
        self.btn_save.clicked.connect(self.accept)

        self.btn_cancel = QPushButton("Отмена (Esc)", self)
        self.btn_cancel.setAccessibleName("Кнопка Отмена")
        self.btn_cancel.setAccessibleDescription("Закрывает окно без сохранения изменений")
        self.btn_cancel.setStyleSheet(
            "QPushButton { font-size: 13px; padding: 6px 16px; min-height: 32px; "
            "background-color: #333333; color: #FFFFFF; border: 1px solid #555555; border-radius: 4px; }"
            "QPushButton:hover { background-color: #444444; }"
            "QPushButton:focus { border: 2px solid #FFFF00; }"
        )
        self.btn_cancel.clicked.connect(self.reject)

        btn_layout.addStretch(1)
        btn_layout.addWidget(self.btn_save)
        btn_layout.addWidget(self.btn_cancel)
        layout.addLayout(btn_layout)

        # Горячая клавиша Ctrl+Enter для быстрого сохранения
        shortcut_save = QShortcut(QKeySequence("Ctrl+Return"), self)
        shortcut_save.activated.connect(self.accept)
        shortcut_save_enter = QShortcut(QKeySequence("Ctrl+Enter"), self)
        shortcut_save_enter.activated.connect(self.accept)

        self.text_edit.setFocus()

    def get_user_prompt(self) -> str:
        """Возвращает введенный текст пожеланий пользователя."""
        return self.text_edit.toPlainText().strip()
