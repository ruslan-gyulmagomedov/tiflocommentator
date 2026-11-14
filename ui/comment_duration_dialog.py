# -*- coding: utf-8 -*-
"""
Диалоговое окно изменения продолжительности тифлокомментария.
Полная поддержка скринридеров NVDA / JAWS.
"""

from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QDoubleSpinBox, QPushButton, QFormLayout
)
from PySide6.QtCore import Qt


class CommentDurationDialog(QDialog):
    """Диалог изменения продолжительности или времени окончания комментария."""

    def __init__(
        self,
        start_time: float,
        current_end_time: float,
        min_duration: float = 0.2,
        max_duration: float = 600.0,
        parent=None
    ):
        super().__init__(parent)
        self.start_time = start_time
        self.orig_end_time = current_end_time
        self.min_duration = max(0.1, round(min_duration, 2))
        self.cur_duration = max(self.min_duration, round(current_end_time - start_time, 2))

        self.setWindowTitle("Изменение продолжительности комментария")
        self.resize(420, 200)
        self.setModal(True)

        layout = QVBoxLayout(self)
        form = QFormLayout()

        lbl_start = QLabel(f"{self.start_time:.3f} сек.", self)
        lbl_start.setAccessibleName("Время начала звучания комментария")
        form.addRow("Время начала (старт):", lbl_start)

        self.spin_duration = QDoubleSpinBox(self)
        self.spin_duration.setRange(self.min_duration, max_duration)
        self.spin_duration.setSingleStep(0.1)
        self.spin_duration.setDecimals(2)
        self.spin_duration.setValue(self.cur_duration)
        self.spin_duration.setSuffix(" сек.")
        self.spin_duration.setAccessibleName("Продолжительность комментария в секундах")
        self.spin_duration.setAccessibleDescription(
            f"Укажите новую продолжительность звучания тифлокомментария (минимум {self.min_duration:.2f} сек. с учётом лимита скорости)"
        )
        form.addRow("Продолжительность:", self.spin_duration)

        self.lbl_end_preview = QLabel(f"{self.start_time + self.cur_duration:.3f} сек.", self)
        self.lbl_end_preview.setAccessibleName("Рассчитанное время окончания")
        form.addRow("Время окончания (финиш):", self.lbl_end_preview)

        self.spin_duration.valueChanged.connect(self.update_end_preview)

        layout.addLayout(form)

        btn_layout = QHBoxLayout()
        self.btn_ok = QPushButton("Применить", self)
        self.btn_ok.setAccessibleName("Кнопка Применить изменения продолжительности")
        self.btn_ok.clicked.connect(self.accept)

        self.btn_cancel = QPushButton("Отмена", self)
        self.btn_cancel.setAccessibleName("Кнопка Отмена")
        self.btn_cancel.clicked.connect(self.reject)

        btn_layout.addStretch()
        btn_layout.addWidget(self.btn_ok)
        btn_layout.addWidget(self.btn_cancel)
        layout.addLayout(btn_layout)

        self.spin_duration.setFocus()

    def update_end_preview(self, val: float):
        end_t = self.start_time + val
        self.lbl_end_preview.setText(f"{end_t:.3f} сек.")

    def get_new_duration(self) -> float:
        return self.spin_duration.value()

    def get_new_end_time(self) -> float:
        return round(self.start_time + self.spin_duration.value(), 3)
