# -*- coding: utf-8 -*-
"""
Диалоговое окно подтверждения повторной генерации тифлокомментариев для всего видео.
Оптимизировано для режимов высокой контрастности Windows, крупных системных шрифтов и экранных луп.
Полная доступность для скринридеров NVDA / JAWS.
"""

from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QPushButton, QFrame, QSizePolicy
)
from PySide6.QtCore import Qt


class RegenerationConfirmDialog(QDialog):
    """
    Широкое доступное диалоговое окно предупреждения перед повторной генерацией комментариев.
    Кнопки гарантированно остаются видимыми при любых системных масштабах и размерах шрифта.
    """

    def __init__(self, commentaries_count: int = 0, parent=None):
        super().__init__(parent)
        self.commentaries_count = commentaries_count

        self.setWindowTitle("Повторная генерация тифлокомментариев")
        self.setAccessibleName("Окно подтверждения повторной генерации тифлокомментариев")
        self.setAccessibleDescription(
            "Предупреждение об удалении всех существующих комментариев перед повторным запуском анализа видео."
        )
        self.setWindowModality(Qt.WindowModal)

        self.setMinimumWidth(700)
        self.setMaximumWidth(960)
        self.resize(760, 280)

        self.init_ui()

    def init_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(14, 14, 14, 14)
        layout.setSpacing(12)

        # Контейнер-карточка в стиле высокой контрастности
        card = QFrame(self)
        card.setObjectName("confirm_card")
        card.setStyleSheet("""
            QFrame#confirm_card {
                background-color: #0c1017;
                border: 2px solid #00FFFF;
                border-radius: 6px;
                padding: 12px;
            }
        """)
        card_layout = QVBoxLayout(card)
        card_layout.setContentsMargins(10, 10, 10, 10)
        card_layout.setSpacing(10)

        # Заголовок предупреждения
        count_text = f" (всего в проекте: {self.commentaries_count} шт.)" if self.commentaries_count > 0 else ""
        lbl_title = QLabel(f"⚠️ В проекте уже есть тифлокомментарии{count_text}", card)
        lbl_title.setStyleSheet("font-size: 15px; font-weight: bold; color: #FFFF00;")
        lbl_title.setWordWrap(True)
        lbl_title.setAccessibleName("Заголовок предупреждения о существующих комментариях")
        card_layout.addWidget(lbl_title)

        # Пояснительный текст
        info_text = (
            "• Все существующие комментарии (как озвученные, так и неозвученные) будут полностью удалены.\n"
            "• Генерация начнется заново с 1-й части видео.\n"
            "• Пожелания пользователя и карточки всех персонажей проекта сохраняются."
        )
        lbl_info = QLabel(info_text, card)
        lbl_info.setStyleSheet("font-size: 13px; color: #FFFFFF; line-height: 140%;")
        lbl_info.setWordWrap(True)
        lbl_info.setAccessibleName("Информация о последствиях повторной генерации")
        card_layout.addWidget(lbl_info)

        # Вопрос с подтверждением
        lbl_question = QLabel("Удалить существующие комментарии и начать генерацию заново?", card)
        lbl_question.setStyleSheet("font-size: 14px; font-weight: bold; color: #00FFFF; padding-top: 4px;")
        lbl_question.setWordWrap(True)
        lbl_question.setAccessibleName("Вопрос подтверждения")
        card_layout.addWidget(lbl_question)

        layout.addWidget(card)

        # Нижняя панель с крупными доступными кнопками
        btn_layout = QHBoxLayout()
        btn_layout.setSpacing(12)
        btn_layout.addStretch(1)

        self.btn_confirm = QPushButton("&Да, удалить и сгенерировать заново", self)
        self.btn_confirm.setAccessibleName("Удалить текущие комментарии и начать повторную генерацию")
        self.btn_confirm.setAccessibleDescription("Удаляет все комментарии проекта и запускает анализ Gemini с первой части")
        self.btn_confirm.setStyleSheet("""
            QPushButton {
                background-color: #880000;
                color: #FFFFFF;
                border: 2px solid #FF5555;
                border-radius: 4px;
                padding: 8px 18px;
                font-size: 13px;
                font-weight: bold;
                min-height: 34px;
            }
            QPushButton:hover {
                background-color: #AA0000;
                border-color: #FFFF00;
            }
            QPushButton:focus {
                border: 2px solid #FFFF00;
                outline: none;
            }
        """)
        self.btn_confirm.clicked.connect(self.accept)
        btn_layout.addWidget(self.btn_confirm)

        self.btn_cancel = QPushButton("&Отмена (не удалять)", self)
        self.btn_cancel.setAccessibleName("Отмена повторной генерации")
        self.btn_cancel.setAccessibleDescription("Закрывает окно без удаления комментариев")
        self.btn_cancel.setDefault(True)
        self.btn_cancel.setStyleSheet("""
            QPushButton {
                background-color: #1a2332;
                color: #FFFFFF;
                border: 2px solid #00FFFF;
                border-radius: 4px;
                padding: 8px 20px;
                font-size: 13px;
                font-weight: bold;
                min-height: 34px;
            }
            QPushButton:hover {
                background-color: #004d40;
                border-color: #FFFF00;
            }
            QPushButton:focus {
                border: 2px solid #FFFF00;
                outline: none;
            }
        """)
        self.btn_cancel.clicked.connect(self.reject)
        btn_layout.addWidget(self.btn_cancel)

        layout.addLayout(btn_layout)

        # Устанавливаем первоначальный фокус на кнопку Отмена для безопасности
        self.btn_cancel.setFocus()
