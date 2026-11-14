# -*- coding: utf-8 -*-
"""
Боковая панель микшера и компрессора (размещается справа):
- Вертикальные регуляторы громкости фильма и комментариев (от -15 dB до +20 dB)
- Вертикальные регуляторы компрессора (порог, упреждение, восстановление)
- Индикатор уровня сигнала в реальном времени в децибелах (Peak Level Meter)
- Кнопка сброса всех настроек по умолчанию
- Полная доступность для скринридеров NVDA / JAWS
"""

from typing import Dict, Any, Optional
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QSizePolicy, QFrame, QRadioButton, QButtonGroup, QProgressBar, QCheckBox
)
from PySide6.QtCore import Qt, Signal, QSize, QTimer
from PySide6.QtGui import QPainter, QColor, QPen, QFont

from ui.accessible_slider import AccessibleSmoothSlider


class AudioLevelMeter(QWidget):
    """
    Высококонтрастный индикатор уровня аудиосигнала (VU Peak Meter) в децибелах.
    Отображает уровень от -60 dBFS до 0 dBFS с цветовой дифференциацией и числовым значением.
    """

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setMinimumWidth(32)
        self.setFixedWidth(44)
        self.setMinimumHeight(140)
        self._current_db: float = -60.0
        self._peak_db: float = -60.0
        self.setAccessibleName("Индикатор уровня выходного сигнала")
        self.setAccessibleDescription("Показывает текущий пиковый уровень мастер-звука в децибелах")

        # Плавный спад пикового индикатора
        self._decay_timer = QTimer(self)
        self._decay_timer.setInterval(40)
        self._decay_timer.timeout.connect(self._on_decay_tick)
        self._decay_timer.start()

    def set_level_db(self, db_val: float):
        """Устанавливает текущий уровень сигнала в dBFS (-60..0)."""
        clamped = max(-60.0, min(0.0, float(db_val)))
        self._current_db = clamped
        if clamped > self._peak_db:
            self._peak_db = clamped
        self.update()
        if abs(clamped - (-60.0)) > 0.5:
            self.setAccessibleName(f"Уровень сигнала: {clamped:.1f} dBFS")

    def reset_meter(self):
        """Сбрасывает показания индикатора в минимум."""
        self._current_db = -60.0
        self._peak_db = -60.0
        self.update()
        self.setAccessibleName("Уровень сигнала: тишина (-60 dBFS)")

    def _on_decay_tick(self):
        if self._current_db > -60.0:
            self._current_db = max(-60.0, self._current_db - 1.5)
        if self._peak_db > -60.0:
            self._peak_db = max(-60.0, self._peak_db - 0.8)
        self.update()

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing, False)

        w = self.width()
        h = self.height()

        # Фоновая подложка
        painter.fillRect(0, 0, w, h, QColor("#111116"))

        # Рамка шкалы
        painter.setPen(QPen(QColor("#FFFFFF"), 2))
        painter.drawRect(1, 1, w - 2, h - 2)

        meter_x = 4
        meter_w = w - 8
        meter_y = 4
        meter_h = h - 24

        fill_ratio = (self._current_db + 60.0) / 60.0
        fill_ratio = max(0.0, min(1.0, fill_ratio))
        bar_h = int(fill_ratio * meter_h)

        if bar_h > 0:
            draw_y = meter_y + meter_h - bar_h
            if fill_ratio > 0.95:
                bar_color = QColor("#FF0033")
            elif fill_ratio > 0.75:
                bar_color = QColor("#FFCC00")
            else:
                bar_color = QColor("#00FF66")

            painter.fillRect(meter_x, draw_y, meter_w, bar_h, bar_color)

        if self._peak_db > -58.0:
            peak_ratio = (self._peak_db + 60.0) / 60.0
            peak_y = int(meter_y + meter_h - (peak_ratio * meter_h))


class VerticalSliderStrip(QWidget):
    """Один вертикальный регулятор с заголовком, числовой меткой, кнопками шага, слайдером и опциональным флажком Mute."""

    value_changed = Signal(float)
    mute_changed = Signal(bool)

    def __init__(
        self,
        title: str,
        min_val: float,
        max_val: float,
        default_val: float,
        step_val: float,
        unit: str = "dB",
        accessible_desc: str = "",
        show_mute: bool = False,
        parent=None
    ):
        super().__init__(parent)
        self.title = title
        self.min_val = float(min_val)
        self.max_val = float(max_val)
        self.default_val = float(default_val)
        self.step_val = float(step_val)
        self.unit = unit
        self.accessible_desc = accessible_desc
        self.show_mute = show_mute

        self.scale_factor = 10.0 if self.unit in ("dB", " x") else 1.0

        self.init_ui()

    def init_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(2, 2, 2, 2)
        layout.setSpacing(4)
        layout.setAlignment(Qt.AlignHCenter)

        self.lbl_title = QLabel(self.title, self)
        self.lbl_title.setAlignment(Qt.AlignCenter)
        self.lbl_title.setStyleSheet("font-size: 11px; font-weight: bold; color: #00FFCC;")
        layout.addWidget(self.lbl_title)

        self.btn_up = QPushButton("+", self)
        self.btn_up.setFixedSize(36, 28)
        self.btn_up.setStyleSheet("font-weight: bold; font-size: 14px; background-color: #1a1a24; border: 2px solid #FFFFFF;")
        self.btn_up.setAccessibleName(f"Увеличить {self.title}")
        self.btn_up.clicked.connect(self._step_up)
        layout.addWidget(self.btn_up, 0, Qt.AlignHCenter)

        min_int = int(round(self.min_val * self.scale_factor))
        max_int = int(round(self.max_val * self.scale_factor))
        def_int = int(round(self.default_val * self.scale_factor))

        self.slider = AccessibleSmoothSlider(Qt.Vertical, self)
        self.slider.setRange(min_int, max_int)
        self.slider.setValue(def_int)
        self.slider.setMinimumHeight(130)
        self.slider.setFixedWidth(34)
        self.slider.setAccessibleName(f"{self.title}: {self._format_value_str(self.default_val)}")
        if self.accessible_desc:
            self.slider.setAccessibleDescription(self.accessible_desc)
        self.slider.valueChanged.connect(self._on_slider_moved)
        layout.addWidget(self.slider, 1, Qt.AlignHCenter)

        self.btn_down = QPushButton("-", self)
        self.btn_down.setFixedSize(36, 28)
        self.btn_down.setStyleSheet("font-weight: bold; font-size: 14px; background-color: #1a1a24; border: 2px solid #FFFFFF;")
        self.btn_down.setAccessibleName(f"Уменьшить {self.title}")
        self.btn_down.clicked.connect(self._step_down)
        layout.addWidget(self.btn_down, 0, Qt.AlignHCenter)

        self.lbl_val = QLabel(self._format_value_str(self.default_val), self)
        self.lbl_val.setAlignment(Qt.AlignCenter)
        self.lbl_val.setStyleSheet("font-size: 11px; font-weight: bold; color: #FFFF00; background: #000000; padding: 2px 4px; border: 1px solid #444455; border-radius: 3px;")
        layout.addWidget(self.lbl_val)

        if self.show_mute:
            self.cb_mute = QCheckBox("Выкл", self)
            self.cb_mute.setStyleSheet("QCheckBox { color: #FF6666; font-size: 10px; font-weight: bold; } QCheckBox::indicator { width: 14px; height: 14px; }")
            self.cb_mute.setToolTip(f"Отключить звук источника: {self.title}")
            self.cb_mute.setAccessibleName(f"Отключить звук {self.title}")
            self.cb_mute.setAccessibleDescription(f"Флажок полного отключения звука источника {self.title}")
            self.cb_mute.toggled.connect(self._on_mute_toggled)
            layout.addWidget(self.cb_mute, 0, Qt.AlignHCenter)
        else:
            self.cb_mute = None

    def _format_value_str(self, val: float) -> str:
        if self.unit == "dB":
            if abs(val) < 0.05:
                return "0.0 dB"
            return f"{val:+.1f} dB" if self.scale_factor > 1.0 else f"{val:+.0f} dB"
        elif self.unit == "ms":
            return f"{val:.0f} ms" if abs(val - int(val)) < 0.05 else f"{val:.1f} ms"
        return f"{val} {self.unit}"

    def _on_slider_moved(self, int_val: int):
        float_val = round(int_val / self.scale_factor, 1)
        txt = self._format_value_str(float_val)
        if not self.is_muted():
            self.lbl_val.setText(txt)
        self.slider.setAccessibleName(f"{self.title}: {txt}")
        self.value_changed.emit(float_val)

    def _on_mute_toggled(self, checked: bool):
        if self.cb_mute:
            self.slider.setEnabled(not checked)
            self.btn_up.setEnabled(not checked)
            self.btn_down.setEnabled(not checked)
            if checked:
                self.lbl_val.setText("ВЫКЛ")
                self.lbl_val.setStyleSheet("font-size: 10px; font-weight: bold; color: #FF4444; background: #220000; padding: 2px 4px; border: 1px solid #FF0000; border-radius: 3px;")
            else:
                self.lbl_val.setText(self._format_value_str(self.get_value()))
                self.lbl_val.setStyleSheet("font-size: 11px; font-weight: bold; color: #FFFF00; background: #000000; padding: 2px 4px; border: 1px solid #444455; border-radius: 3px;")
        self.mute_changed.emit(checked)

    def is_muted(self) -> bool:
        return bool(self.cb_mute and self.cb_mute.isChecked())

    def set_muted(self, muted: bool):
        if self.cb_mute and self.cb_mute.isChecked() != bool(muted):
            self.cb_mute.setChecked(bool(muted))

    def _step_up(self):
        cur_int = self.slider.value()
        step_int = int(round(self.step_val * self.scale_factor))
        self.slider.setValue(min(self.slider.maximum(), cur_int + step_int))

    def _step_down(self):
        cur_int = self.slider.value()
        step_int = int(round(self.step_val * self.scale_factor))
        self.slider.setValue(max(self.slider.minimum(), cur_int - step_int))

    def get_value(self) -> float:
        return round(self.slider.value() / self.scale_factor, 1)

    def set_value(self, val: float):
        clamped = max(self.min_val, min(self.max_val, float(val)))
        int_val = int(round(clamped * self.scale_factor))
        self.slider.setValue(int_val)
        if not self.is_muted():
            self.lbl_val.setText(self._format_value_str(clamped))

    def reset_default(self):
        self.set_value(self.default_val)
        self.set_muted(False)


class AudioDspPanel(QWidget):
    """
    Правая панель микшера и упреждающего компрессора:
    - Вертикальные регуляторы фильма, комментариев и параметров компрессора
    - Индикатор уровня сигнала в dBFS
    - Кнопка сброса параметров по умолчанию
    - Сигналы для живого фонового обновления мастер-звука
    """

    dsp_settings_changed = Signal(dict)
    mode_changed = Signal(bool)  # True = Итоговый звук, False = Быстрое редактирование
    close_requested = Signal()

    def __init__(self, config=None, parent=None):
        super().__init__(parent)
        self.config = config
        self._is_loading = False
        self.setMinimumWidth(0)
        self.setMinimumSize(0, 0)
        self.init_ui()
        if self.config:
            self.load_from_config(self.config)

    def minimumSizeHint(self) -> QSize:
        return QSize(0, 0)

    def sizeHint(self) -> QSize:
        return QSize(360, 600)

    def init_ui(self):
        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(4, 4, 4, 4)
        main_layout.setSpacing(4)

        header_layout = QHBoxLayout()
        header_layout.setContentsMargins(4, 2, 4, 2)

        self.lbl_title = QLabel("🎛️ Микшер и компрессор", self)
        self.lbl_title.setStyleSheet("font-weight: bold; font-size: 13px; color: #00FFCC;")
        self.lbl_title.setAccessibleName("Панель микшера и компрессора")
        header_layout.addWidget(self.lbl_title)

        header_layout.addStretch(1)

        self.btn_close = QPushButton("✕", self)
        self.btn_close.setFixedSize(26, 24)
        self.btn_close.setToolTip("Скрыть панель микшера (Ctrl+M)")
        self.btn_close.setAccessibleName("Кнопка Закрыть панель микшера")
        self.btn_close.clicked.connect(self.close_requested.emit)
        header_layout.addWidget(self.btn_close)

        main_layout.addLayout(header_layout)

        # Блок выбора режима работы предпросмотра звука
        grp_mode = QFrame(self)
        grp_mode.setStyleSheet("background-color: #14141d; border: 1px solid #333344; border-radius: 4px; padding: 2px;")
        mode_layout = QVBoxLayout(grp_mode)
        mode_layout.setContentsMargins(6, 4, 6, 4)
        mode_layout.setSpacing(4)

        lbl_mode_caption = QLabel("Режим предпросмотра звука:", self)
        lbl_mode_caption.setStyleSheet("font-size: 11px; font-weight: bold; color: #FFFFFF;")
        mode_layout.addWidget(lbl_mode_caption)

        mode_radios_layout = QHBoxLayout()
        mode_radios_layout.setContentsMargins(0, 0, 0, 0)
        mode_radios_layout.setSpacing(8)

        self.mode_group = QButtonGroup(self)

        self.rb_fast_mode = QRadioButton("⚡ Быстрое ред.", self)
        self.rb_fast_mode.setStyleSheet("QRadioButton { color: #00FFCC; font-weight: bold; font-size: 11px; } QRadioButton::indicator { width: 14px; height: 14px; }")
        self.rb_fast_mode.setToolTip("Режим «Быстрое редактирование»: мгновенный отклик без генерации мастер-трека (до 0 dB).")
        self.rb_fast_mode.setAccessibleName("Режим Быстрое редактирование")
        self.rb_fast_mode.setAccessibleDescription("Быстрое редактирование без фоновой генерации мастер-трека. Регулировка громкости до 0 dB.")
        self.rb_fast_mode.setChecked(True)
        self.mode_group.addButton(self.rb_fast_mode, 0)
        mode_radios_layout.addWidget(self.rb_fast_mode)

        self.rb_final_mode = QRadioButton("🎧 Итоговый звук", self)
        self.rb_final_mode.setStyleSheet("QRadioButton { color: #FFAA00; font-weight: bold; font-size: 11px; } QRadioButton::indicator { width: 14px; height: 14px; }")
        self.rb_final_mode.setToolTip("Режим «Итоговый звук»: фоновое сведение мастер-трека с компрессором и усилением выше 0 dB.")
        self.rb_final_mode.setAccessibleName("Режим Итоговый звук")
        self.rb_final_mode.setAccessibleDescription("Фоновое сведение мастер-трека с компрессором и усилением до +20 dB.")
        self.mode_group.addButton(self.rb_final_mode, 1)
        mode_radios_layout.addWidget(self.rb_final_mode)

        self.rb_fast_mode.toggled.connect(self._on_mode_toggled)

        mode_layout.addLayout(mode_radios_layout)

        # Контейнер индикации процесса генерации мастер-трека
        self.render_progress_frame = QFrame(self)
        self.render_progress_frame.setStyleSheet("background-color: #1a1a26; border: 1px solid #444466; border-radius: 4px; padding: 2px;")
        prog_layout = QVBoxLayout(self.render_progress_frame)
        prog_layout.setContentsMargins(4, 3, 4, 3)
        prog_layout.setSpacing(2)

        self.lbl_render_status = QLabel("⏳ Сведение мастер-трека...", self)
        self.lbl_render_status.setStyleSheet("font-size: 10px; font-weight: bold; color: #FFAA00;")
        self.lbl_render_status.setAccessibleName("Статус сведения мастер-трека")
        prog_layout.addWidget(self.lbl_render_status)

        self.render_progress_bar = QProgressBar(self)
        self.render_progress_bar.setRange(0, 100)
        self.render_progress_bar.setValue(0)
        self.render_progress_bar.setFixedHeight(12)
        self.render_progress_bar.setTextVisible(False)
        self.render_progress_bar.setStyleSheet(
            "QProgressBar { background-color: #0d0d14; border: 1px solid #555577; border-radius: 2px; } "
            "QProgressBar::chunk { background-color: qlineargradient(x1:0, y1:0, x2:1, y2:0, stop:0 #FFAA00, stop:1 #00FFCC); border-radius: 2px; }"
        )
        self.render_progress_bar.setAccessibleName("Прогресс сведения мастер-трека")
        prog_layout.addWidget(self.render_progress_bar)

        self.render_progress_frame.hide()
        mode_layout.addWidget(self.render_progress_frame)

        main_layout.addWidget(grp_mode)

        grp_strips = QFrame(self)
        grp_strips.setStyleSheet("background-color: #14141d; border: 1px solid #333344; border-radius: 4px;")
        strips_layout = QHBoxLayout(grp_strips)
        strips_layout.setContentsMargins(4, 4, 4, 4)
        strips_layout.setSpacing(4)

        self.strip_movie = VerticalSliderStrip(
            title="Фильм",
            min_val=-15.0,
            max_val=20.0,
            default_val=0.0,
            step_val=1.0,
            unit="dB",
            accessible_desc="Усиление звуковой дорожки фильма перед компрессором",
            show_mute=True,
            parent=self
        )
        self.strip_movie.value_changed.connect(self._on_values_changed)
        self.strip_movie.mute_changed.connect(self._on_values_changed)
        strips_layout.addWidget(self.strip_movie)

        self.strip_comm = VerticalSliderStrip(
            title="Голос ТК",
            min_val=-15.0,
            max_val=20.0,
            default_val=0.0,
            step_val=1.0,
            unit="dB",
            accessible_desc="Усиление тифлокомментариев перед компрессором",
            show_mute=True,
            parent=self
        )
        self.strip_comm.value_changed.connect(self._on_values_changed)
        self.strip_comm.mute_changed.connect(self._on_values_changed)
        strips_layout.addWidget(self.strip_comm)

        sep1 = QFrame(self)
        sep1.setFrameShape(QFrame.VLine)
        sep1.setStyleSheet("background-color: #444455;")
        strips_layout.addWidget(sep1)

        self.strip_thresh = VerticalSliderStrip(
            title="Порог",
            min_val=-20.0,
            max_val=0.0,
            default_val=-2.0,
            step_val=0.5,
            unit="dB",
            accessible_desc="Порог срабатывания пик-лимитера компрессора",
            parent=self
        )
        self.strip_thresh.value_changed.connect(self._on_values_changed)
        strips_layout.addWidget(self.strip_thresh)

        self.strip_lookahead = VerticalSliderStrip(
            title="Упрежд.",
            min_val=1.0,
            max_val=30.0,
            default_val=5.0,
            step_val=1.0,
            unit="ms",
            accessible_desc="Упреждение компрессора (lookahead)",
            parent=self
        )
        self.strip_lookahead.value_changed.connect(self._on_values_changed)
        strips_layout.addWidget(self.strip_lookahead)

        self.strip_release = VerticalSliderStrip(
            title="Спад",
            min_val=10.0,
            max_val=500.0,
            default_val=120.0,
            step_val=10.0,
            unit="ms",
            accessible_desc="Время восстановления компрессора (release)",
            parent=self
        )
        self.strip_release.value_changed.connect(self._on_values_changed)
        strips_layout.addWidget(self.strip_release)

        sep2 = QFrame(self)
        sep2.setFrameShape(QFrame.VLine)
        sep2.setStyleSheet("background-color: #444455;")
        strips_layout.addWidget(sep2)

        level_box = QVBoxLayout()
        level_box.setContentsMargins(2, 2, 2, 2)
        level_box.setAlignment(Qt.AlignHCenter)

        lbl_meter = QLabel("Уровень", self)
        lbl_meter.setAlignment(Qt.AlignCenter)
        lbl_meter.setStyleSheet("font-size: 11px; font-weight: bold; color: #00FFCC;")
        level_box.addWidget(lbl_meter)

        self.meter = AudioLevelMeter(self)
        level_box.addWidget(self.meter, 1, Qt.AlignHCenter)

        strips_layout.addLayout(level_box)
        main_layout.addWidget(grp_strips, 1)

        self.btn_reset_defaults = QPushButton("🔄 Сброс по умолчанию", self)
        self.btn_reset_defaults.setStyleSheet(
            "QPushButton { font-weight: bold; font-size: 12px; padding: 6px 10px; background-color: #1e1e28; border: 2px solid #00FFCC; border-radius: 4px; }"
            "QPushButton:hover { background-color: #005544; }"
        )
        self.btn_reset_defaults.setAccessibleName("Сбросить все настройки громкости и компрессора на значения по умолчанию")
        self.btn_reset_defaults.clicked.connect(self.reset_all_to_defaults)
        main_layout.addWidget(self.btn_reset_defaults)



    def _on_values_changed(self):
        """Отправляет сигнал об изменении параметров микшера."""
        if self._is_loading:
            return
        data = self.get_dsp_settings()
        if self.config:
            self.config.movie_volume_db = data["movie_volume_db"]
            self.config.commentary_volume_db = data["commentary_volume_db"]
            self.config.movie_muted = data["movie_muted"]
            self.config.commentary_muted = data["commentary_muted"]
            self.config.compressor_threshold_db = data["compressor_threshold_db"]
            self.config.compressor_lookahead_ms = data["compressor_lookahead_ms"]
            self.config.compressor_release_ms = data["compressor_release_ms"]
            self.config.save()
        self.dsp_settings_changed.emit(data)

    def get_dsp_settings(self) -> Dict[str, Any]:
        return {
            "movie_volume_db": self.strip_movie.get_value(),
            "commentary_volume_db": self.strip_comm.get_value(),
            "movie_muted": self.strip_movie.is_muted(),
            "commentary_muted": self.strip_comm.is_muted(),
            "compressor_threshold_db": self.strip_thresh.get_value(),
            "compressor_lookahead_ms": self.strip_lookahead.get_value(),
            "compressor_release_ms": self.strip_release.get_value(),
        }

    def load_from_config(self, config):
        """Загружает параметры из переданного объекта ConfigManager."""
        self._is_loading = True
        self.strip_movie.set_value(config.movie_volume_db)
        self.strip_comm.set_value(config.commentary_volume_db)
        self.strip_movie.set_muted(config.movie_muted)
        self.strip_comm.set_muted(config.commentary_muted)
        self.strip_thresh.set_value(config.compressor_threshold_db)
        self.strip_lookahead.set_value(config.compressor_lookahead_ms)
        self.strip_release.set_value(config.compressor_release_ms)
        self._is_loading = False

    def reset_all_to_defaults(self):
        """Сбрасывает все регуляторы и флажки к эталонным значениям по умолчанию."""
        self._is_loading = True
        self.strip_movie.reset_default()
        self.strip_comm.reset_default()
        self.strip_thresh.reset_default()
        self.strip_lookahead.reset_default()
        self.strip_release.reset_default()
        self._is_loading = False
        self._on_values_changed()

    def _on_mode_toggled(self):
        """Срабатывает при переключении режима работы (Быстрое ред. / Итоговый звук)."""
        is_final = self.is_final_sound_mode()
        if not is_final:
            self.set_render_idle()
        self.mode_changed.emit(is_final)

    def is_final_sound_mode(self) -> bool:
        """Возвращает True, если выбран режим полного сведения «Итоговый звук»."""
        return self.rb_final_mode.isChecked()

    def set_mode(self, is_final: bool):
        """Программно переключает режим (без сохранения в settings.ini)."""
        if is_final:
            self.rb_final_mode.setChecked(True)
        else:
            self.rb_fast_mode.setChecked(True)

    def set_render_progress(self, percent: int, cur_str: str = "", speed_str: str = ""):
        """Отображает процесс фонового рендера мастер-трека."""
        if not self.is_final_sound_mode():
            self.set_render_idle()
            return
        self.render_progress_frame.show()
        clamped = max(0, min(100, int(percent)))
        self.render_progress_bar.setValue(clamped)
        info_parts = [f"⏳ Сведение: {clamped}%"]
        if cur_str:
            info_parts.append(cur_str)
        if speed_str and speed_str != "—":
            info_parts.append(f"скорость {speed_str}")
        txt = " (".join([info_parts[0], ", ".join(info_parts[1:]) + ")"]) if len(info_parts) > 1 else info_parts[0]
        self.lbl_render_status.setText(txt)
        self.lbl_render_status.setStyleSheet("font-size: 10px; font-weight: bold; color: #FFAA00;")

    def set_render_finished(self, success: bool = True):
        """Отображает завершение сведения мастер-трека."""
        if not self.is_final_sound_mode():
            self.set_render_idle()
            return
        if success:
            self.render_progress_frame.show()
            self.render_progress_bar.setValue(100)
            self.lbl_render_status.setText("✓ Мастер-трек готов")
            self.lbl_render_status.setStyleSheet("font-size: 10px; font-weight: bold; color: #00FFCC;")
        else:
            self.set_render_idle()

    def set_render_idle(self):
        """Скрывает индикатор прогресса и переводит в режим ожидания."""
        self.render_progress_frame.hide()
        self.render_progress_bar.setValue(0)

