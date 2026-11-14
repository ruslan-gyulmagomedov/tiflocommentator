# -*- coding: utf-8 -*-
"""
Диалоговое окно «О программе».
Классический диалог с полной доступностью для программ экранного доступа (NVDA / JAWS).
"""

from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QPushButton, QLineEdit
)
from PySide6.QtCore import Qt
from PySide6.QtGui import QGuiApplication

from core.version import APP_VERSION


class AboutDialog(QDialog):
    """Диалоговое окно «О программе»."""

    CARD_NUMBER_DIGITS = "2202200702385756"
    CARD_NUMBER_DISPLAY = "2202-2007-0238-5756"

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("О программе")
        self.setModal(True)
        self.resize(480, 320)

        # Полное описание окна для автоматического чтения скринридером при открытии
        self.setAccessibleName("О программе")
        self.setAccessibleDescription(
            f"Тифлокомментатор версии {APP_VERSION}. Автор Алексей Викторов. "
            "Если вам понравилась программа, вы можете поддержать работу автора, "
            "отправив ему любую, даже небольшую сумму на карту Сбербанка. "
            "Номер карты: 2202-2007-0238-5756. "
            "В комментарии к переводу очень желательно написать «В дар»."
        )

        self.init_ui()

    def init_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(10)

        # Заголовок и автор
        lbl_info = QLabel(f"Тифлокомментатор версии {APP_VERSION}\nАвтор Алексей Викторов.", self)
        lbl_info.setWordWrap(True)
        layout.addWidget(lbl_info)

        # Поясняющий текст поддержки
        lbl_support = QLabel(
            "Если вам понравилась программа, вы можете поддержать работу автора, "
            "отправив ему любую, даже небольшую сумму на карту Сбербанка номер:",
            self
        )
        lbl_support.setWordWrap(True)
        layout.addWidget(lbl_support)

        # Отдельный фокусируемый элемент с номером карты
        self.edit_card = QLineEdit(self.CARD_NUMBER_DISPLAY, self)
        self.edit_card.setReadOnly(True)
        self.edit_card.setAccessibleName("Номер карты Сбербанка")
        self.edit_card.setAccessibleDescription("Номер карты 2202-2007-0238-5756 для поддержки автора")
        layout.addWidget(self.edit_card)

        # Примечание к переводу
        lbl_comment = QLabel('В комментарии к переводу очень желательно написать "В дар".', self)
        lbl_comment.setWordWrap(True)
        layout.addWidget(lbl_comment)

        # Метка статуса копирования
        self.lbl_status = QLabel("", self)
        self.lbl_status.setWordWrap(True)
        layout.addWidget(self.lbl_status)

        layout.addStretch(1)

        # Кнопка «Скопировать номер карты»
        self.btn_copy_card = QPushButton("Скопировать номер карты", self)
        self.btn_copy_card.setAccessibleName("Скопировать номер карты")
        self.btn_copy_card.setAccessibleDescription("Копирует номер карты 2202200702385756 в буфер обмена")
        self.btn_copy_card.clicked.connect(self.on_copy_card_clicked)
        layout.addWidget(self.btn_copy_card)

        # Кнопка «Закрыть»
        self.btn_close = QPushButton("Закрыть", self)
        self.btn_close.setAccessibleName("Закрыть")
        self.btn_close.setAccessibleDescription("Закрывает окно О программе")
        self.btn_close.clicked.connect(self.accept)
        layout.addWidget(self.btn_close)

        # Фокус при открытии на поле с номером карты
        self.edit_card.setFocus()

    def on_copy_card_clicked(self):
        """Копирует номер карты в буфер обмена без дефисов."""
        clipboard = QGuiApplication.clipboard()
        if clipboard is not None:
            clipboard.setText(self.CARD_NUMBER_DIGITS)
            self.lbl_status.setText("Номер карты скопирован в буфер обмена.")

