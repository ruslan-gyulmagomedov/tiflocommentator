# -*- coding: utf-8 -*-
"""
Диалоги подтверждения, рассчитанные на скринридеры NVDA / JAWS.

Стандартный QMessageBox.question показывает кнопки Yes/No, которые
озвучиваются по-английски и не сообщают, чем опасен выбор. Здесь кнопки
подписаны по-русски, фокус по умолчанию стоит на «Отмена», а Escape
тоже отменяет действие: случайный Enter не удаляет данные.
"""

from PySide6.QtWidgets import QMessageBox
from PySide6.QtCore import Qt


def confirm_destructive(parent, title: str, text: str,
                        accept_text: str = "Удалить",
                        cancel_text: str = "Отмена") -> bool:
    """
    Спрашивает подтверждение удаления. Возвращает True, только если
    пользователь явно выбрал действие кнопкой accept_text.
    """
    box = QMessageBox(parent)
    box.setWindowTitle(title)
    box.setIcon(QMessageBox.Warning)
    box.setTextFormat(Qt.PlainText)
    box.setText(text)
    box.setAccessibleName(title)
    box.setAccessibleDescription(
        "Опасное действие. Нажмите «Отмена», чтобы ничего не удалять."
    )

    accept_btn = box.addButton(accept_text, QMessageBox.DestructiveRole)
    cancel_btn = box.addButton(cancel_text, QMessageBox.RejectRole)
    accept_btn.setAccessibleName(accept_text)
    cancel_btn.setAccessibleName(cancel_text)

    # Фокус и Enter по умолчанию — на безопасном варианте.
    box.setDefaultButton(cancel_btn)
    box.setEscapeButton(cancel_btn)
    cancel_btn.setFocus(Qt.OtherFocusReason)

    box.exec()
    return box.clickedButton() is accept_btn
