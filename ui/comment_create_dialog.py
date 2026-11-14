# -*- coding: utf-8 -*-
"""
Диалоговое окно ручного создания тифлокомментария на текущей позиции видео.
Полная доступность для скринридеров NVDA / JAWS: автоматический фокус на поле ввода текста,
доступные имена, горячие клавиши и крупные контрастные элементы.
"""

from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QTextEdit, QDoubleSpinBox,
    QPushButton, QFormLayout, QGroupBox
)
from PySide6.QtCore import Qt


def format_seconds_to_time_str(sec: float) -> str:
    """Форматирует секунды в ЧЧ:ММ:СС.ммм."""
    s = max(0.0, sec)
    hours = int(s // 3600)
    minutes = int((s % 3600) // 60)
    seconds = s % 60
    return f"{hours:02d}:{minutes:02d}:{seconds:06.3f}"


class CommentCreateDialog(QDialog):
    """Диалог создания нового тифлокомментария на заданной позиции."""

    def __init__(self, current_pos_sec: float = 0.0, default_duration: float = 3.0, max_duration: float = 600.0, parent=None):
        super().__init__(parent)
        self.start_time = max(0.0, round(current_pos_sec, 3))
        self.default_duration = max(0.5, round(default_duration, 2))
        self.max_duration = max_duration

        self.setWindowTitle("Создание нового тифлокомментария")
        self.resize(580, 360)
        self.setModal(True)

        self.init_ui()

    def init_ui(self):
        main_layout = QVBoxLayout(self)
        main_layout.setSpacing(8)

        grp_time = QGroupBox("Временные границы тифлокомментария", self)
        form_time = QFormLayout(grp_time)

        self.lbl_start = QLabel(f"{format_seconds_to_time_str(self.start_time)} ({self.start_time:.3f} сек.)", self)
        self.lbl_start.setAccessibleName("Время начала звучания комментария")
        self.lbl_start.setStyleSheet("font-weight: bold; color: #00FFCC; font-size: 14px;")
        form_time.addRow("Время начала (старт):", self.lbl_start)

        self.spin_duration = QDoubleSpinBox(self)
        self.spin_duration.setRange(0.5, self.max_duration)
        self.spin_duration.setSingleStep(0.5)
        self.spin_duration.setDecimals(2)
        self.spin_duration.setValue(self.default_duration)
        self.spin_duration.setSuffix(" сек.")
        self.spin_duration.setStyleSheet("font-size: 14px; padding: 4px;")
        self.spin_duration.setAccessibleName("Длительность тифлокомментария в секундах")
        self.spin_duration.setAccessibleDescription("Укажите планируемую продолжительность комментария")
        self.spin_duration.valueChanged.connect(self._on_duration_changed)
        form_time.addRow("Планируемая длительность:", self.spin_duration)

        end_sec = self.start_time + self.default_duration
        self.lbl_end = QLabel(f"{format_seconds_to_time_str(end_sec)} ({end_sec:.3f} сек.)", self)
        self.lbl_end.setAccessibleName("Расчетное время окончания комментария")
        self.lbl_end.setStyleSheet("font-weight: bold; color: #FFCC00; font-size: 14px;")
        form_time.addRow("Время окончания (финиш):", self.lbl_end)

        main_layout.addWidget(grp_time)

        lbl_text = QLabel("Текст тифлокомментария:", self)
        lbl_text.setStyleSheet("font-weight: bold; font-size: 14px;")
        lbl_text.setAccessibleName("Текст нового тифлокомментария")
        main_layout.addWidget(lbl_text)

        self.text_edit = QTextEdit(self)
        self.text_edit.setPlaceholderText("Введите текст описания сцены, действий или персонажей...")
        self.text_edit.setStyleSheet("font-size: 15px; padding: 6px;")
        self.text_edit.setAccessibleName("Поле ввода текста тифлокомментария")
        self.text_edit.setAccessibleDescription("Введите текст тифлоописания")
        main_layout.addWidget(self.text_edit)

        btn_layout = QHBoxLayout()
        self.btn_create = QPushButton("Создать комментарий (Ctrl+Enter)", self)
        self.btn_create.setStyleSheet(
            "QPushButton { font-weight: bold; font-size: 14px; padding: 8px 16px; min-height: 34px; }"
        )
        self.btn_create.setAccessibleName("Кнопка Создать тифлокомментарий")
        self.btn_create.clicked.connect(self._validate_and_accept)

        self.btn_cancel = QPushButton("Отмена (Esc)", self)
        self.btn_cancel.setStyleSheet(
            "QPushButton { font-size: 14px; padding: 8px 16px; min-height: 34px; }"
        )
        self.btn_cancel.setAccessibleName("Кнопка Отмена")
        self.btn_cancel.clicked.connect(self.reject)

        btn_layout.addStretch()
        btn_layout.addWidget(self.btn_create)
        btn_layout.addWidget(self.btn_cancel)
        main_layout.addLayout(btn_layout)

        self.text_edit.setFocus()

    def _on_duration_changed(self, dur_val: float):
        end_sec = self.start_time + dur_val
        self.lbl_end.setText(f"{format_seconds_to_time_str(end_sec)} ({end_sec:.3f} сек.)")

    def _validate_and_accept(self):
        text = self.get_text()
        if not text:
            self.text_edit.setFocus()
            return
        self.accept()

    def keyPressEvent(self, event):
        if event.key() == Qt.Key_Return and (event.modifiers() & Qt.ControlModifier):
            self._validate_and_accept()
            event.accept()
        else:
            super().keyPressEvent(event)

    def get_text(self) -> str:
        return self.text_edit.toPlainText().strip()

    def get_start_time(self) -> float:
        return self.start_time

    def get_duration(self) -> float:
        return round(self.spin_duration.value(), 3)

    def get_end_time(self) -> float:
        return round(self.start_time + self.spin_duration.value(), 3)
