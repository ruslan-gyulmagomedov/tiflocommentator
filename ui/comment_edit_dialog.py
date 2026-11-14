# -*- coding: utf-8 -*-
"""
Диалоговое окно редактирования текста тифлокомментария.
Полная доступность для NVDA/JAWS: фокус на поле ввода, горячие клавиши, доступные имена.
"""

from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QTextEdit, QPushButton
)
from PySide6.QtCore import Qt


class CommentEditDialog(QDialog):
    """Диалог редактирования текста комментария."""

    def __init__(self, comment_text: str, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Редактирование текста тифлокомментария")
        self.resize(550, 300)
        self.setModal(True)

        self.comment_text = comment_text

        layout = QVBoxLayout(self)

        lbl = QLabel("Текст тифлокомментария:", self)
        lbl.setAccessibleName("Текст тифлокомментария")
        layout.addWidget(lbl)

        self.text_edit = QTextEdit(self)
        self.text_edit.setPlainText(comment_text)
        self.text_edit.setAccessibleName("Поле ввода текста тифлокомментария")
        self.text_edit.setAccessibleDescription("Введите или отредактируйте текст тифлоописания")
        layout.addWidget(self.text_edit)

        btn_layout = QHBoxLayout()

        self.btn_save = QPushButton("Сохранить", self)
        self.btn_save.setAccessibleName("Кнопка Сохранить изменения")
        self.btn_save.setAccessibleDescription("Сохраняет отредактированный текст комментария")
        self.btn_save.setStyleSheet("font-weight: bold; font-size: 14px; padding: 6px 16px; min-height: 32px;")
        self.btn_save.clicked.connect(self.accept)

        self.btn_cancel = QPushButton("Отмена", self)
        self.btn_cancel.setAccessibleName("Кнопка Отмена")
        self.btn_cancel.setStyleSheet("font-size: 14px; padding: 6px 16px; min-height: 32px;")
        self.btn_cancel.clicked.connect(self.reject)

        btn_layout.addStretch()
        btn_layout.addWidget(self.btn_save)
        btn_layout.addWidget(self.btn_cancel)
        layout.addLayout(btn_layout)

        self.text_edit.setFocus()

    def get_text(self) -> str:
        return self.text_edit.toPlainText().strip()
