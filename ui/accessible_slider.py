# -*- coding: utf-8 -*-
"""
Доступный крупный слайдер с высокой контрастностью и плавной регулировкой.
Полная поддержка скринридеров NVDA / JAWS и пользователей с нарушениями зрения.
"""

from PySide6.QtWidgets import QSlider, QStyleOptionSlider, QStyle
from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QMouseEvent, QKeyEvent


# Контрастный QSS стиль для слайдеров (High Contrast)
ACCESSIBLE_SLIDER_STYLE = """
QSlider {
    min-height: 36px;
    background: transparent;
}

/* Горизонтальный слайдер */
QSlider::groove:horizontal {
    height: 14px;
    background: #111111;
    border: 2px solid #FFFFFF;
    border-radius: 7px;
}

QSlider::sub-page:horizontal {
    background: #00E5FF;
    border: 2px solid #FFFFFF;
    border-radius: 7px;
}

QSlider::add-page:horizontal {
    background: #222222;
    border: 2px solid #FFFFFF;
    border-radius: 7px;
}

QSlider::handle:horizontal {
    background: #FFFF00;
    border: 3px solid #FFFFFF;
    width: 30px;
    height: 30px;
    margin: -8px 0;
    border-radius: 15px;
}

QSlider::handle:horizontal:hover {
    background: #00FF66;
    border: 3px solid #FFFF00;
}

QSlider::handle:horizontal:pressed {
    background: #FFFFFF;
    border: 3px solid #00E5FF;
}

/* Вертикальный слайдер */
QSlider::groove:vertical {
    width: 14px;
    background: #111111;
    border: 2px solid #FFFFFF;
    border-radius: 7px;
}

QSlider::sub-page:vertical {
    background: #222222;
    border: 2px solid #FFFFFF;
    border-radius: 7px;
}

QSlider::add-page:vertical {
    background: #00E5FF;
    border: 2px solid #FFFFFF;
    border-radius: 7px;
}

QSlider::handle:vertical {
    background: #FFFF00;
    border: 3px solid #FFFFFF;
    width: 30px;
    height: 30px;
    margin: 0 -8px;
    border-radius: 15px;
}

QSlider::handle:vertical:hover {
    background: #00FF66;
    border: 3px solid #FFFF00;
}

QSlider::handle:vertical:pressed {
    background: #FFFFFF;
    border: 3px solid #00E5FF;
}

QSlider:focus {
    outline: none;
}

QSlider::handle:focus {
    border: 3px solid #00FFFF;
    background: #FFFF00;
}
"""

STEP_BUTTON_STYLE = """
QPushButton {
    min-height: 38px;
    min-width: 44px;
    font-size: 13px;
    font-weight: bold;
    color: #FFFFFF;
    background-color: #1A1A1A;
    border: 2px solid #FFFFFF;
    border-radius: 6px;
    padding: 4px 10px;
}

QPushButton:hover {
    background-color: #00E5FF;
    color: #000000;
    border: 2px solid #FFFF00;
}

QPushButton:pressed {
    background-color: #FFFFFF;
    color: #000000;
    border: 2px solid #00E5FF;
}

QPushButton:focus {
    border: 2px solid #00FFFF;
    outline: none;
}
"""

STEP_LABEL_STYLE = """
QLabel {
    font-size: 14px;
    font-weight: bold;
    color: #FFFF00;
    background: transparent;
    padding: 2px 6px;
}
"""


class AccessibleSmoothSlider(QSlider):
    """
    Крупный слайдер высокой контрастности с мгновенным переходом
    в точку клика мыши и непрерывной плавной регулировкой без рывков.
    """

    def __init__(self, orientation=Qt.Horizontal, parent=None):
        super().__init__(orientation, parent)
        self.setFocusPolicy(Qt.StrongFocus)
        self.setMouseTracking(False)
        self.setStyleSheet(ACCESSIBLE_SLIDER_STYLE)
        self.setMinimumHeight(48)
        self.setCursor(Qt.PointingHandCursor)
        self._is_dragging = False

    def _value_from_pos(self, pos) -> int:
        """Точно вычисляет значение слайдера исходя из координаты курсора."""
        opt = QStyleOptionSlider()
        self.initStyleOption(opt)
        style = self.style()
        groove_rect = style.subControlRect(
            QStyle.CC_Slider, opt, QStyle.SC_SliderGroove, self
        )
        handle_rect = style.subControlRect(
            QStyle.CC_Slider, opt, QStyle.SC_SliderHandle, self
        )

        if self.orientation() == Qt.Horizontal:
            x = pos.x() if hasattr(pos, 'x') else int(pos)
            handle_w = handle_rect.width()
            min_x = groove_rect.x() + handle_w // 2
            max_x = groove_rect.right() - handle_w // 2

            if max_x <= min_x:
                return self.minimum()

            ratio = (x - min_x) / float(max_x - min_x)
            ratio = max(0.0, min(1.0, ratio))
            if self.invertedAppearance():
                ratio = 1.0 - ratio
            val_range = self.maximum() - self.minimum()
            return int(round(self.minimum() + ratio * val_range))
        else:
            y = pos.y() if hasattr(pos, 'y') else int(pos)
            handle_h = handle_rect.height()
            min_y = groove_rect.y() + handle_h // 2
            max_y = groove_rect.bottom() - handle_h // 2

            if max_y <= min_y:
                return self.minimum()

            ratio = (y - min_y) / float(max_y - min_y)
            ratio = max(0.0, min(1.0, ratio))
            if not self.invertedAppearance():
                ratio = 1.0 - ratio
            val_range = self.maximum() - self.minimum()
            return int(round(self.minimum() + ratio * val_range))

    def mousePressEvent(self, event: QMouseEvent):
        if event.button() == Qt.LeftButton:
            self._is_dragging = True
            self.setSliderDown(True)
            new_val = self._value_from_pos(event.position())
            self.setValue(new_val)
            self.sliderMoved.emit(new_val)
            event.accept()
            return
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event: QMouseEvent):
        if self._is_dragging and (event.buttons() & Qt.LeftButton):
            new_val = self._value_from_pos(event.position())
            if new_val != self.value():
                self.setValue(new_val)
                self.sliderMoved.emit(new_val)
            event.accept()
            return
        elif self._is_dragging and not (event.buttons() & Qt.LeftButton):
            self._is_dragging = False
            self.setSliderDown(False)
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event: QMouseEvent):
        if event.button() == Qt.LeftButton:
            if self._is_dragging:
                self._is_dragging = False
                self.setSliderDown(False)
                new_val = self._value_from_pos(event.position())
                self.setValue(new_val)
                self.sliderMoved.emit(new_val)
            event.accept()
            return
        super().mouseReleaseEvent(event)

    def hideEvent(self, event):
        self._is_dragging = False
        self.setSliderDown(False)
        super().hideEvent(event)


