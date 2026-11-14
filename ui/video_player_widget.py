# -*- coding: utf-8 -*-
"""
Видеоплеер с поддержкой:
- Воспроизведения видео через QMediaPlayer и QVideoWidget
- Наложения текста тифлокомментариев (субтитров) поверх видеокадра
- Синхронного воспроизведения аудио тифлокомментариев
- Полноэкранного режима (F11 / Esc)
- Полной доступности для NVDA/JAWS
"""

import os
import math
import wave
import struct
from typing import List, Dict, Any, Optional
import numpy as np
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton, QSlider,
    QStyle, QSizePolicy
)
from PySide6.QtMultimedia import QMediaPlayer, QAudioOutput
from PySide6.QtMultimediaWidgets import QVideoWidget
from PySide6.QtCore import Qt, QUrl, Signal, Slot, QPoint, QEvent, QTimer
from ui.accessible_slider import AccessibleSmoothSlider


class FullscreenPlayerWindow(QWidget):
    """Полноэкранное окно видеопросмотра с оверлеем субтитров и доступным управлением."""

    closed = Signal()

    def __init__(self, parent_player):
        super().__init__(None, Qt.Window | Qt.FramelessWindowHint)
        self.parent_player = parent_player
        self.setStyleSheet("background-color: #000000; color: #FFFFFF;")
        self.setAccessibleName("Полноэкранный просмотр видео")
        self.setAccessibleDescription("Нажмите Escape или F11 для выхода из полноэкранного режима")

        self.init_ui()

    def init_ui(self):
        self.main_layout = QVBoxLayout(self)
        self.main_layout.setContentsMargins(0, 0, 0, 0)
        self.main_layout.setSpacing(0)

        # Контейнер под видео
        self.video_area = QWidget(self)
        self.video_area_layout = QVBoxLayout(self.video_area)
        self.video_area_layout.setContentsMargins(0, 0, 0, 0)
        self.video_area_layout.setSpacing(0)
        self.main_layout.addWidget(self.video_area, 1)

        # Полноэкранный блок субтитров
        self.lbl_subtitle = QLabel(self)
        self.lbl_subtitle.setAlignment(Qt.AlignCenter)
        self.lbl_subtitle.setWordWrap(True)
        self.lbl_subtitle.setStyleSheet(
            "background-color: rgba(10, 15, 20, 230); color: #00FFCC; "
            "font-size: 20px; font-weight: bold; padding: 10px 20px; "
            "border-top: 2px solid #00FFCC; min-height: 46px;"
        )
        self.lbl_subtitle.hide()
        self.lbl_subtitle.setAccessibleName("Субтитр текущего тифлокомментария в полноэкранном режиме")
        self.main_layout.addWidget(self.lbl_subtitle)

        # Нижняя панель управления в полноэкранном режиме
        self.ctrl_panel = QWidget(self)
        self.ctrl_panel.setStyleSheet(
            "background-color: rgba(15, 15, 15, 230); border-top: 2px solid #00FFCC; padding: 4px;"
        )
        ctrl_layout = QVBoxLayout(self.ctrl_panel)
        ctrl_layout.setContentsMargins(10, 4, 10, 4)
        ctrl_layout.setSpacing(4)

        # Верхняя строка: Слайдер позиции на всю ширину и метка времени
        row_slider = QHBoxLayout()
        row_slider.setSpacing(10)

        self.slider_pos = AccessibleSmoothSlider(Qt.Horizontal, self)
        self.slider_pos.setRange(0, 1000)
        self.slider_pos.setAccessibleName("Позиция воспроизведения видео в полноэкранном режиме")
        self.slider_pos.sliderMoved.connect(self.parent_player.set_position)
        row_slider.addWidget(self.slider_pos, 1)

        self.lbl_time = QLabel("00:00:00 / 00:00:00", self)
        self.lbl_time.setStyleSheet("font-size: 15px; font-weight: bold; color: #00FFCC;")
        self.lbl_time.setAccessibleName("Текущее время и общая длительность")
        row_slider.addWidget(self.lbl_time)
        ctrl_layout.addLayout(row_slider)

        # Нижняя строка: Кнопки управления и выход из полноэкранного режима
        row_btns = QHBoxLayout()
        row_btns.setSpacing(8)

        self.btn_play = QPushButton("Пауза", self)
        self.btn_play.setIcon(self.style().standardIcon(QStyle.SP_MediaPause))
        self.btn_play.setAccessibleName("Кнопка Воспроизведение и Пауза")
        self.btn_play.setStyleSheet("font-size: 14px; font-weight: bold; padding: 6px 14px;")
        self.btn_play.clicked.connect(self.parent_player.toggle_play)
        row_btns.addWidget(self.btn_play)

        self.btn_back = QPushButton("◀ 5 сек", self)
        self.btn_back.setAccessibleName("Перемотка назад на 5 секунд")
        self.btn_back.setStyleSheet("font-size: 14px; padding: 6px 12px;")
        self.btn_back.clicked.connect(lambda: self.parent_player.seek_relative(-5000))
        row_btns.addWidget(self.btn_back)

        self.btn_fwd = QPushButton("5 сек ▶", self)
        self.btn_fwd.setAccessibleName("Перемотка вперед на 5 секунд")
        self.btn_fwd.setStyleSheet("font-size: 14px; padding: 6px 12px;")
        self.btn_fwd.clicked.connect(lambda: self.parent_player.seek_relative(5000))
        row_btns.addWidget(self.btn_fwd)

        row_btns.addStretch()

        self.btn_exit_fs = QPushButton("Обычный экран (Esc / F11)", self)
        self.btn_exit_fs.setStyleSheet(
            "QPushButton { font-size: 14px; font-weight: bold; padding: 6px 16px; border: 2px solid #00FFCC; }"
            "QPushButton:hover { background-color: #005544; }"
        )
        self.btn_exit_fs.setAccessibleName("Выйти из полноэкранного режима")
        self.btn_exit_fs.clicked.connect(self.close)
        row_btns.addWidget(self.btn_exit_fs)

        ctrl_layout.addLayout(row_btns)
        self.main_layout.addWidget(self.ctrl_panel, 0)

    def set_subtitle_text(self, text: str):
        if text.strip():
            self.lbl_subtitle.setText(text)
            self.lbl_subtitle.show()
        else:
            self.lbl_subtitle.setText("")
            self.lbl_subtitle.hide()

    def sync_state(self, pos_ms: int, dur_ms: int, is_playing: bool):
        if not self.slider_pos.isSliderDown():
            self.slider_pos.setRange(0, dur_ms)
            self.slider_pos.setValue(pos_ms)
        pos_s = pos_ms // 1000
        dur_s = dur_ms // 1000
        pos_str = f"{pos_s//3600:02d}:{(pos_s%3600)//60:02d}:{pos_s%60:02d}"
        dur_str = f"{dur_s//3600:02d}:{(dur_s%3600)//60:02d}:{dur_s%60:02d}"
        self.lbl_time.setText(f"{pos_str} / {dur_str}")

        if is_playing:
            self.btn_play.setText("Пауза")
            self.btn_play.setIcon(self.style().standardIcon(QStyle.SP_MediaPause))
        else:
            self.btn_play.setText("Воспроизведение")
            self.btn_play.setIcon(self.style().standardIcon(QStyle.SP_MediaPlay))

    def keyPressEvent(self, event):
        if event.key() in (Qt.Key_Escape, Qt.Key_F11):
            self.close()
            event.accept()
        elif event.key() == Qt.Key_Space:
            self.parent_player.toggle_play()
            event.accept()
        elif event.key() == Qt.Key_Left:
            self.parent_player.seek_relative(-5000)
            event.accept()
        elif event.key() == Qt.Key_Right:
            self.parent_player.seek_relative(5000)
            event.accept()
        else:
            super().keyPressEvent(event)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self.parent_player.update_subtitle_geometry()

    def closeEvent(self, event):
        self.closed.emit()
        super().closeEvent(event)


class VideoPlayerWidget(QWidget):
    """Виджет видеоплеера с оверлеем тифлокомментариев и полноэкранным режимом."""

    position_changed = Signal(int)       # Текущая позиция в мс
    duration_changed = Signal(int)       # Общая длительность в мс
    commentary_active = Signal(dict)     # Активный комментарий
    level_changed = Signal(float)        # Текущий уровень звука (dBFS)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.commentaries: List[Dict[str, Any]] = []
        self.last_played_comm_id = ""
        self.current_comm_audio_file = ""
        self.pending_comm_offset_ms = 0
        self.fs_window: Optional[FullscreenPlayerWindow] = None

        # DSP параметры звука (автодакинг, громкости, компрессор/лимитер)
        self.movie_vol_db: float = 0.0
        self.comm_vol_db: float = 0.0
        self.movie_muted: bool = False
        self.comm_muted: bool = False
        self.movie_vol_pct: int = 100
        self.comm_vol_pct: int = 100
        self.auto_ducking: bool = True
        self.ducking_db: float = -12.0
        self.ducking_attack_ms: float = 50.0
        self.ducking_release_ms: float = 200.0
        self.comp_threshold_db: float = -2.0
        self.comp_lookahead_ms: float = 5.0
        self.comp_release_ms: float = 120.0

        # Вычисленные нормализованные уровни громкости [0.0 ... 1.0]
        self.base_movie_vol: float = 1.0
        self.base_comm_vol: float = 1.0
        self.duck_gain_multiplier: float = 0.25119
        self.current_applied_movie_vol: float = 1.0
        self.current_applied_comm_vol: float = 1.0

        self.init_ui()
        self.init_player()
        self.calculate_dsp_levels()

    def init_ui(self):
        self.main_layout = QVBoxLayout(self)
        self.main_layout.setContentsMargins(0, 0, 0, 0)
        self.main_layout.setSpacing(2)

        # Контейнер для видео
        self.video_container = QWidget(self)
        self.video_container.setMinimumSize(480, 220)
        self.video_container.setStyleSheet("background-color: #000000;")
        self.video_container_layout = QVBoxLayout(self.video_container)
        self.video_container_layout.setContentsMargins(0, 0, 0, 0)
        self.video_container_layout.setSpacing(0)

        self.video_widget = QVideoWidget(self.video_container)
        self.video_widget.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        self.video_widget.setAccessibleName("Область видеопредпросмотра")
        self.video_widget.installEventFilter(self)
        self.video_container_layout.addWidget(self.video_widget)

        self.main_layout.addWidget(self.video_container, 1)

        # Блок субтитров тифлокомментария (отображается прямо под видеокадром)
        self.lbl_subtitle = QLabel(self)
        self.lbl_subtitle.setAlignment(Qt.AlignCenter)
        self.lbl_subtitle.setWordWrap(True)
        self.lbl_subtitle.setStyleSheet(
            "background-color: #0b0f14; color: #00FFCC; "
            "font-size: 16px; font-weight: bold; padding: 6px 12px; "
            "border: 2px solid #00FFCC; border-radius: 4px; min-height: 40px;"
        )
        self.lbl_subtitle.hide()
        self.lbl_subtitle.setAccessibleName("Субтитр текущего тифлокомментария")
        self.main_layout.addWidget(self.lbl_subtitle)

        # Панель управления воспроизведением
        self.ctrl_panel = QWidget(self)
        ctrl_layout = QVBoxLayout(self.ctrl_panel)
        ctrl_layout.setContentsMargins(8, 4, 8, 4)
        ctrl_layout.setSpacing(4)

        # Верхний уровень: Слайдер воспроизведения на всю ширину и таймкоды
        row_slider = QHBoxLayout()
        row_slider.setSpacing(10)

        self.slider_pos = AccessibleSmoothSlider(Qt.Horizontal, self)
        self.slider_pos.setRange(0, 1000)
        self.slider_pos.setAccessibleName("Позиция воспроизведения фильма")
        self.slider_pos.sliderMoved.connect(self.set_position)
        row_slider.addWidget(self.slider_pos, 1)

        self.lbl_time = QLabel("00:00:00 / 00:00:00", self)
        self.lbl_time.setAccessibleName("Время воспроизведения и общая длительность фильма")
        self.lbl_time.setStyleSheet("font-weight: bold; color: #FFCC00; font-size: 15px;")
        row_slider.addWidget(self.lbl_time)
        ctrl_layout.addLayout(row_slider)

        # Нижний уровень: Кнопки управления воспроизведением и полный экран
        row_btns = QHBoxLayout()
        row_btns.setSpacing(8)

        self.btn_play = QPushButton("Воспроизведение", self)
        self.btn_play.setIcon(self.style().standardIcon(QStyle.SP_MediaPlay))
        self.btn_play.setAccessibleName("Кнопка Воспроизведение и Пауза")
        self.btn_play.setAccessibleDescription("Клавиша Пробел переключает воспроизведение и паузу")
        self.btn_play.setStyleSheet("font-weight: bold; font-size: 13px; padding: 5px 12px;")
        self.btn_play.clicked.connect(self.toggle_play)
        row_btns.addWidget(self.btn_play)

        self.btn_back = QPushButton("◀ 5 сек", self)
        self.btn_back.setAccessibleName("Перемотка назад на 5 секунд")
        self.btn_back.setStyleSheet("font-size: 13px; font-weight: bold; padding: 5px 10px;")
        self.btn_back.clicked.connect(lambda: self.seek_relative(-5000))
        row_btns.addWidget(self.btn_back)

        self.btn_fwd = QPushButton("5 сек ▶", self)
        self.btn_fwd.setAccessibleName("Перемотка вперед на 5 секунд")
        self.btn_fwd.setStyleSheet("font-size: 13px; font-weight: bold; padding: 5px 10px;")
        self.btn_fwd.clicked.connect(lambda: self.seek_relative(5000))
        row_btns.addWidget(self.btn_fwd)

        row_btns.addStretch(1)

        self.btn_fullscreen = QPushButton("Полный экран (F11)", self)
        self.btn_fullscreen.setIcon(self.style().standardIcon(QStyle.SP_TitleBarMaxButton))
        self.btn_fullscreen.setAccessibleName("Переключить полноэкранный режим")
        self.btn_fullscreen.setStyleSheet("font-size: 13px; font-weight: bold; padding: 5px 12px;")
        self.btn_fullscreen.clicked.connect(self.toggle_fullscreen)
        row_btns.addWidget(self.btn_fullscreen)

        ctrl_layout.addLayout(row_btns)
        self.main_layout.addWidget(self.ctrl_panel, 0)

    def init_player(self):
        self.player = QMediaPlayer(self)
        self.audio_output = QAudioOutput(self)
        self.player.setAudioOutput(self.audio_output)
        self.player.setVideoOutput(self.video_widget)

        self.player.positionChanged.connect(self.on_player_position_changed)
        self.player.durationChanged.connect(self.on_player_duration_changed)
        self.player.mediaStatusChanged.connect(self._on_player_media_status_changed)

        self.master_audio_player = QMediaPlayer(self)
        self.master_audio_out = QAudioOutput(self)
        self.master_audio_player.setAudioOutput(self.master_audio_out)
        self.master_audio_player.mediaStatusChanged.connect(self._on_master_media_status_changed)
        self.master_audio_path: str = ""
        self.is_using_master_audio: bool = False
        self._master_peak_envelope: Optional[np.ndarray] = None

        self.comm_player = QMediaPlayer(self)
        self.comm_audio_out = QAudioOutput(self)
        self.comm_player.setAudioOutput(self.comm_audio_out)
        self.comm_player.mediaStatusChanged.connect(self._on_comm_media_status_changed)

        # Высокоточный таймер для гладкого управления DSP огибающей дакинга (50 Гц)
        self.dsp_timer = QTimer(self)
        self.dsp_timer.setInterval(20)
        self.dsp_timer.timeout.connect(self._on_dsp_timer_tick)

    def calculate_dsp_levels(self):
        """
        Рассчитывает базовые параметры DSP и обновляет множитель дакинга.
        Громкость фильма и комментариев регулируются независимо (от -15 dB до +20 dB).
        """
        movie_gain = 10.0 ** (max(-15.0, min(20.0, self.movie_vol_db)) / 20.0)
        comm_gain = 10.0 ** (max(-15.0, min(20.0, self.comm_vol_db)) / 20.0)

        self.base_movie_vol = max(0.0, min(1.0, movie_gain))
        self.base_comm_vol = max(0.0, min(1.0, comm_gain))

        if self.auto_ducking:
            self.duck_gain_multiplier = 10.0 ** (self.ducking_db / 20.0)
        else:
            self.duck_gain_multiplier = 1.0

    def compute_ducking_multiplier(self, pos_sec: float) -> float:
        """
        Вычисляет коэффициент огибающей дакинга для текущей позиции времени в секундах.
        Поддерживает плавную атаку (attack) и спад (release) огибающей.
        """
        if not self.auto_ducking or not self.commentaries:
            return 1.0

        attack_sec = max(0.005, self.ducking_attack_ms / 1000.0)
        release_sec = max(0.005, self.ducking_release_ms / 1000.0)
        duck_mult = self.duck_gain_multiplier

        min_multiplier = 1.0

        for c in self.commentaries:
            st = float(c.get("start_time", 0.0))
            et = float(c.get("end_time", st + 2.0))

            # Проверяем попадание в зону действия дакинга комментария
            if (st - attack_sec) <= pos_sec <= (et + release_sec):
                if pos_sec < st:
                    # Фаза атаки: плавное снижение от 1.0 до duck_mult
                    frac = max(0.0, min(1.0, (pos_sec - (st - attack_sec)) / attack_sec))
                    mult = 1.0 - frac * (1.0 - duck_mult)
                elif pos_sec <= et:
                    # Фаза удержания: приглушенный уровень
                    mult = duck_mult
                else:
                    # Фаза восстановления (release): плавный подъем от duck_mult до 1.0
                    frac = max(0.0, min(1.0, (pos_sec - et) / release_sec))
                    mult = duck_mult + frac * (1.0 - duck_mult)

                if mult < min_multiplier:
                    min_multiplier = mult

        return min_multiplier

    def compute_commentary_activity(self, pos_sec: float) -> float:
        """
        Определяет коэффициент активности аудиокомментария для текущей позиции в секундах.
        Возвращает 1.0, если в текущей позиции звучит комментарий с готовым аудиофайлом, иначе 0.0.
        """
        if not self.commentaries:
            return 0.0

        for c in self.commentaries:
            st = float(c.get("start_time", 0.0))
            et = float(c.get("end_time", st + 2.0))
            if st <= pos_sec <= et:
                audio_file = c.get("audio_file")
                if audio_file and os.path.isfile(audio_file) and not c.get("audio_needs_rebuild", False):
                    return 1.0
        return 0.0

    def apply_audio_dsp(self, pos_ms: int):
        """
        Применяет DSP параметры к воспроизведению:
        - Громкость фильма воспроизводится на установленном уровне и приглушается дакингом (если он включен).
        - Если автодакинг отключен, фильм играет на полной установленной громкости.
        - Громкость комментариев играет на своем установленном уровне и никогда не снижает громкость фильма вне комментария.
        """
        pos_sec = pos_ms / 1000.0

        if self.movie_muted:
            target_movie_vol = 0.0
        elif not self.auto_ducking:
            # Автодакинг отключен: фильм никогда не приглушается
            target_movie_vol = self.base_movie_vol
        else:
            # Автодакинг включен: фильм плавно приглушается во время комментариев
            duck_mult = self.compute_ducking_multiplier(pos_sec)
            target_movie_vol = max(0.0, min(1.0, self.base_movie_vol * duck_mult))

        target_comm_vol = 0.0 if self.comm_muted else self.base_comm_vol

        if abs(self.current_applied_movie_vol - target_movie_vol) > 0.001:
            self.current_applied_movie_vol = target_movie_vol
            self.audio_output.setVolume(target_movie_vol)

        if abs(self.current_applied_comm_vol - target_comm_vol) > 0.001:
            self.current_applied_comm_vol = target_comm_vol
            self.comm_audio_out.setVolume(target_comm_vol)

    def set_audio_dsp_config(
        self,
        movie_vol_db: float = 0.0,
        comm_vol_db: float = 0.0,
        movie_muted: bool = False,
        comm_muted: bool = False,
        auto_ducking: bool = True,
        ducking_db: float = -12.0,
        ducking_attack_ms: float = 50.0,
        ducking_release_ms: float = 200.0,
        comp_threshold_db: float = -2.0,
        comp_lookahead_ms: float = 5.0,
        comp_release_ms: float = 120.0,
        **kwargs
    ):
        """Устанавливает новые DSP параметры и мгновенно применяет их к воспроизведению."""
        if "movie_muted" in kwargs:
            self.movie_muted = bool(kwargs["movie_muted"])
        else:
            self.movie_muted = bool(movie_muted)

        if "comm_muted" in kwargs:
            self.comm_muted = bool(kwargs["comm_muted"])
        else:
            self.comm_muted = bool(comm_muted)

        if "movie_vol_pct" in kwargs:
            pct = float(kwargs["movie_vol_pct"])
            self.movie_vol_db = 20.0 * math.log10(max(0.01, pct / 100.0))
            self.movie_vol_pct = int(round(pct))
        elif movie_vol_db > 20.0:
            self.movie_vol_pct = int(round(movie_vol_db))
            self.movie_vol_db = 20.0 * math.log10(max(0.01, movie_vol_db / 100.0))
        else:
            self.movie_vol_db = float(movie_vol_db)
            self.movie_vol_pct = int(round(100.0 * (10.0 ** (self.movie_vol_db / 20.0))))

        if "comm_vol_pct" in kwargs:
            pct = float(kwargs["comm_vol_pct"])
            self.comm_vol_db = 20.0 * math.log10(max(0.01, pct / 100.0))
            self.comm_vol_pct = int(round(pct))
        elif comm_vol_db > 20.0:
            self.comm_vol_pct = int(round(comm_vol_db))
            self.comm_vol_db = 20.0 * math.log10(max(0.01, comm_vol_db / 100.0))
        else:
            self.comm_vol_db = float(comm_vol_db)
            self.comm_vol_pct = int(round(100.0 * (10.0 ** (self.comm_vol_db / 20.0))))

        self.auto_ducking = auto_ducking
        self.ducking_db = ducking_db
        self.ducking_attack_ms = ducking_attack_ms
        self.ducking_release_ms = ducking_release_ms
        self.comp_threshold_db = comp_threshold_db
        self.comp_lookahead_ms = comp_lookahead_ms
        self.comp_release_ms = comp_release_ms
        self.calculate_dsp_levels()
        self.apply_audio_dsp(self.player.position())

    def update_from_config(self, config):
        """Обновляет все DSP параметры из переданного объекта ConfigManager."""
        self.set_audio_dsp_config(
            movie_vol_db=config.movie_volume_db,
            comm_vol_db=config.commentary_volume_db,
            movie_muted=config.movie_muted,
            comm_muted=config.commentary_muted,
            auto_ducking=config.auto_ducking,
            ducking_db=config.ducking_level_db,
            ducking_attack_ms=config.ducking_attack_ms,
            ducking_release_ms=config.ducking_release_ms,
            comp_threshold_db=config.compressor_threshold_db,
            comp_lookahead_ms=config.compressor_lookahead_ms,
            comp_release_ms=config.compressor_release_ms
        )

    def _on_dsp_timer_tick(self):
        """Тик таймера для гладкой огибающей звука при воспроизведении и пик-метра."""
        if self.player.playbackState() == QMediaPlayer.PlayingState:
            pos_ms = self.player.position()
            if not self.is_using_master_audio:
                self.apply_audio_dsp(pos_ms)

            # Чтение уровня звука из предрассчитанного envelope в RAM (0% дискового I/O)
            level_db = -60.0
            if self.is_using_master_audio and self._master_peak_envelope is not None:
                # 20 значений в секунду (каждые 50 мс)
                env_idx = int((pos_ms / 1000.0) * 20)
                if 0 <= env_idx < len(self._master_peak_envelope):
                    level_db = float(self._master_peak_envelope[env_idx])
            elif not self.is_using_master_audio:
                # В режиме быстрого редактирования
                pos_sec = pos_ms / 1000.0
                comm_act = self.compute_commentary_activity(pos_sec)
                if comm_act > 0 and not self.comm_muted:
                    level_db = max(-30.0, min(0.0, -3.0 + self.comm_vol_db))
                elif not self.movie_muted:
                    level_db = max(-40.0, min(0.0, -10.0 + self.movie_vol_db))

            self.level_changed.emit(level_db)

    def eventFilter(self, watched, event):
        if watched == self.video_widget and event.type() == QEvent.MouseButtonDblClick:
            self.toggle_fullscreen()
            return True
        return super().eventFilter(watched, event)

    def update_subtitle_geometry(self):
        target_parent = self.lbl_subtitle.parentWidget()
        if not target_parent:
            return
        w = target_parent.width()
        h = target_parent.height()
        sub_h = 75
        self.lbl_subtitle.setGeometry(25, max(10, h - sub_h - 25), max(100, w - 50), sub_h)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self.update_subtitle_geometry()

    def _on_player_media_status_changed(self, status):
        """Обработчик изменения медиа-статуса основного видеоплеера."""
        if status in (QMediaPlayer.LoadedMedia, QMediaPlayer.BufferedMedia):
            # Переводим в состояние паузы при загрузке, чтобы отрендерить первый кадр
            if self.player.playbackState() == QMediaPlayer.StoppedState:
                self.player.pause()
        elif status == QMediaPlayer.EndOfMedia:
            # Видео дошло до конца - останавливаем воспроизведение без зацикливания
            self.pause()
            if self.is_using_master_audio:
                self.master_audio_player.stop()
            self.stop_comm_audio()
            # Фиксируем позицию в конце без повторного запуска
            dur_ms = self.player.duration()
            if dur_ms > 0:
                self.player.setPosition(dur_ms)
                if not self.slider_pos.isSliderDown():
                    self.slider_pos.setValue(dur_ms)

    def _on_master_media_status_changed(self, status):
        """Обработчик изменения медиа-статуса плеера мастер-аудио."""
        if status == QMediaPlayer.EndOfMedia:
            # Мастер-аудио дошло до конца
            if self.player.playbackState() == QMediaPlayer.PlayingState:
                self.pause()
            self.master_audio_player.stop()
            self.stop_comm_audio()

    def _on_comm_media_status_changed(self, status):
        """Обработчик готовности аудиофайла комментария для точного позиционирования."""
        if status in (QMediaPlayer.LoadedMedia, QMediaPlayer.BufferedMedia):
            if self.pending_comm_offset_ms > 0:
                self.comm_player.setPosition(self.pending_comm_offset_ms)
                self.pending_comm_offset_ms = 0

    def stop_comm_audio(self):
        """Останавливает воспроизведение аудио тифлокомментария и освобождает файл."""
        self.comm_player.stop()
        self.comm_player.setSource(QUrl())
        self.last_played_comm_id = ""
        self.current_comm_audio_file = ""
        self.pending_comm_offset_ms = 0

    def load_master_audio(self, audio_path: str):
        """Загружает сведенный мастер-аудиопоток с компрессором и переключает плеер на него."""
        if audio_path and os.path.isfile(audio_path):
            self.master_audio_path = audio_path
            self.is_using_master_audio = True

            # Рассчитываем компактный массив пиков (всего ~90 КБ в RAM на 1.5 часа)
            try:
                m = np.memmap(audio_path, dtype=np.int16, mode='r', offset=44)
                step = 48000 * 2 // 20  # 50 мс стерео = 4800 int16
                num_chunks = len(m) // step
                if num_chunks > 0:
                    truncated = m[: num_chunks * step].reshape(num_chunks, step)
                    peaks = np.max(np.abs(truncated), axis=1)
                    peaks_float = np.maximum(peaks.astype(np.float32), 1.0) / 32768.0
                    self._master_peak_envelope = 20.0 * np.log10(peaks_float)
                else:
                    self._master_peak_envelope = None
                del m
            except Exception:
                self._master_peak_envelope = None

            cur_pos = self.player.position()
            is_playing = (self.player.playbackState() == QMediaPlayer.PlayingState)
            self.stop_comm_audio()
            self.audio_output.setVolume(0.0)  # Заглушаем прямой звук видео
            self.master_audio_out.setVolume(1.0)
            self.master_audio_player.stop()
            self.master_audio_player.setSource(QUrl.fromLocalFile(audio_path))
            self.master_audio_player.setPosition(cur_pos)
            if is_playing:
                self.master_audio_player.play()

    def clear_master_audio(self):
        """Отключает мастер-аудиопоток и возвращает плеер в режим прямой озвучки."""
        self.is_using_master_audio = False
        self.master_audio_path = ""
        self._master_peak_envelope = None
        self.master_audio_player.stop()
        self.master_audio_player.setSource(QUrl())
        self.audio_output.setVolume(0.0 if self.movie_muted else self.current_applied_movie_vol)

    def clear_media(self):
        """Полностью выгружает видео и аудио, освобождая файловые дескрипторы."""
        self.player.stop()
        self.player.setSource(QUrl())
        self.clear_master_audio()
        self.stop_comm_audio()
        self.commentaries = []
        self.lbl_subtitle.setText("")
        self.lbl_subtitle.hide()
        if self.fs_window:
            self.fs_window.set_subtitle_text("")
        self.slider_pos.setValue(0)
        self.slider_pos.setRange(0, 0)
        self.lbl_time.setText("00:00:00 / 00:00:00")
        self.btn_play.setText("Воспроизведение (Пробел)")
        self.btn_play.setIcon(self.style().standardIcon(QStyle.SP_MediaPlay))

    def load_media(self, media_path: str, commentaries: List[Dict[str, Any]] = None, master_audio_path: str = ""):
        """Загружает видеофайл, список комментариев и опциональный мастер-аудиопоток."""
        if not os.path.isfile(media_path):
            return
        self.stop_comm_audio()
        self.commentaries = commentaries or []
        self.player.setSource(QUrl.fromLocalFile(media_path))
        self.player.pause()
        if master_audio_path and os.path.isfile(master_audio_path):
            self.load_master_audio(master_audio_path)
        else:
            self.clear_master_audio()
            self.calculate_dsp_levels()
            self.apply_audio_dsp(0)

    def set_commentaries(self, commentaries: List[Dict[str, Any]]):
        self.commentaries = commentaries or []
        self.on_player_position_changed(self.player.position())
    def find_commentary_at(self, pos_sec: float) -> Optional[Dict[str, Any]]:
        for c in self.commentaries:
            st = float(c.get("start_time", 0.0))
            et = float(c.get("end_time", 0.0))
            if st <= pos_sec <= et:
                return c
        return None


    def is_playing(self) -> bool:
        """Возвращает True, если плеер находится в состоянии активного воспроизведения."""
        return self.player.playbackState() == QMediaPlayer.PlayingState

    def toggle_play(self):
        if self.player.playbackState() == QMediaPlayer.PlayingState:
            self.pause()
        else:
            self.play()

    def play(self):
        dur = self.player.duration()
        cur_pos = self.player.position()
        if dur > 0 and cur_pos >= dur - 50:
            # Находимся в самом конце — не начинаем зацикленное воспроизведение, ждем перемотки
            return

        self.player.play()
        self.dsp_timer.start()
        self.btn_play.setText("Пауза")
        self.btn_play.setIcon(self.style().standardIcon(QStyle.SP_MediaPause))
        if self.fs_window:
            self.fs_window.btn_play.setText("Пауза")
            self.fs_window.btn_play.setIcon(self.style().standardIcon(QStyle.SP_MediaPause))

        if self.is_using_master_audio and os.path.isfile(self.master_audio_path):
            self.audio_output.setVolume(0.0)
            self.master_audio_player.setPosition(cur_pos)
            self.master_audio_player.play()
            return

        # Fallback режим, если мастер-аудио еще не сведено
        pos_ms = self.player.position()
        pos_sec = pos_ms / 1000.0
        active_comm = None
        for c in self.commentaries:
            st = float(c.get("start_time", 0.0))
            et = float(c.get("end_time", 0.0))
            if st <= pos_sec <= et:
                active_comm = c
                break

        if active_comm:
            comm_id = active_comm.get("id")
            audio_file = active_comm.get("audio_file")
            if (
                self.last_played_comm_id == comm_id
                and self.current_comm_audio_file == audio_file
                and self.comm_player.playbackState() == QMediaPlayer.PausedState
            ):
                self.comm_player.play()
            else:
                self.last_played_comm_id = ""
                self.on_player_position_changed(pos_ms)
        else:
            # Находимся вне комментариев — гарантированно выключаем аудио комментариев
            self.stop_comm_audio()

    def pause(self):
        self.player.pause()
        self.dsp_timer.stop()
        if self.is_using_master_audio:
            self.master_audio_player.pause()
        if self.comm_player.playbackState() == QMediaPlayer.PlayingState:
            self.comm_player.pause()
        self.btn_play.setText("Воспроизведение")
        self.btn_play.setIcon(self.style().standardIcon(QStyle.SP_MediaPlay))
        if self.fs_window:
            self.fs_window.btn_play.setText("Воспроизведение")
            self.fs_window.btn_play.setIcon(self.style().standardIcon(QStyle.SP_MediaPlay))

    def set_position(self, position_ms: int):
        if self.player.playbackState() == QMediaPlayer.StoppedState:
            self.player.pause()
        self.player.setPosition(position_ms)
        if self.is_using_master_audio and os.path.isfile(self.master_audio_path):
            self.master_audio_player.setPosition(position_ms)
        else:
            self.stop_comm_audio()
        self.on_player_position_changed(position_ms)

    def seek_relative(self, delta_ms: int):
        cur = self.player.position()
        dur = self.player.duration()
        new_pos = max(0, min(dur, cur + delta_ms))
        self.set_position(new_pos)

    def on_player_position_changed(self, pos_ms: int):
        dur_ms = self.player.duration()
        # Если позиция достигла конца медиа, принудительно останавливаем
        if dur_ms > 0 and pos_ms >= dur_ms and self.player.playbackState() == QMediaPlayer.PlayingState:
            self._on_player_media_status_changed(QMediaPlayer.EndOfMedia)
            return

        if not self.slider_pos.isSliderDown():
            self.slider_pos.setValue(pos_ms)
        self.position_changed.emit(pos_ms)
        self.update_time_label(pos_ms, dur_ms)

        if self.is_using_master_audio and os.path.isfile(self.master_audio_path):
            # В режиме мастер-аудио не сбрасываем аудиодекодер на естественных микроколебаниях (100-150 мс),
            # выравниваем только при существенном рассинхроне (> 1000 мс) или паузе
            if self.player.playbackState() == QMediaPlayer.PlayingState:
                master_pos = self.master_audio_player.position()
                if abs(master_pos - pos_ms) > 1000:
                    self.master_audio_player.setPosition(pos_ms)
                if self.master_audio_player.playbackState() != QMediaPlayer.PlayingState:
                    self.master_audio_player.play()
        else:
            # Применяем DSP громкости фильма в fallback-режиме
            self.apply_audio_dsp(pos_ms)

        if self.fs_window and self.fs_window.isVisible():
            self.fs_window.sync_state(
                pos_ms, self.player.duration(), self.player.playbackState() == QMediaPlayer.PlayingState
            )

        pos_sec = pos_ms / 1000.0
        active_comm = None

        for c in self.commentaries:
            st = float(c.get("start_time", 0.0))
            et = float(c.get("end_time", 0.0))
            if st <= pos_sec <= et:
                active_comm = c
                break

        if active_comm:
            sub_text = active_comm.get("text", "")
            self.lbl_subtitle.setText(sub_text)
            self.lbl_subtitle.show()
            if self.fs_window and self.fs_window.isVisible():
                self.fs_window.set_subtitle_text(sub_text)
            self.commentary_active.emit(active_comm)

            # Если используется мастер-аудио, звук комментариев уже смикширован и скомпрессирован
            if not self.is_using_master_audio:
                comm_id = active_comm.get("id")
                is_playing = (self.player.playbackState() == QMediaPlayer.PlayingState)
                if is_playing:
                    audio_file = active_comm.get("audio_file")
                    if audio_file and os.path.isfile(audio_file) and not active_comm.get("audio_needs_rebuild", False):
                        st = float(active_comm.get("start_time", 0.0))
                        offset_ms = max(0, int((pos_sec - st) * 1000))

                        if comm_id != self.last_played_comm_id or self.current_comm_audio_file != audio_file:
                            # Новый комментарий или сменился аудиофайл
                            self.last_played_comm_id = comm_id
                            self.current_comm_audio_file = audio_file
                            self.comm_audio_out.setVolume(self.current_applied_comm_vol)
                            self.pending_comm_offset_ms = offset_ms
                            self.comm_player.stop()
                            self.comm_player.setSource(QUrl.fromLocalFile(audio_file))
                            if offset_ms > 0 and self.comm_player.mediaStatus() in (QMediaPlayer.LoadedMedia, QMediaPlayer.BufferedMedia):
                                self.comm_player.setPosition(offset_ms)
                                self.pending_comm_offset_ms = 0
                            self.comm_player.play()
                        else:
                            # Тот же самый комментарий
                            if self.comm_player.playbackState() != QMediaPlayer.PlayingState:
                                if offset_ms > 0:
                                    self.comm_player.setPosition(offset_ms)
                                self.comm_player.play()
                            else:
                                # Проверяем рассинхрон позиции более 300 мс
                                cur_audio_pos = self.comm_player.position()
                                if abs(cur_audio_pos - offset_ms) > 300:
                                    self.comm_player.setPosition(offset_ms)
        else:
            self.lbl_subtitle.setText("")
            self.lbl_subtitle.hide()
            if self.fs_window and self.fs_window.isVisible():
                self.fs_window.set_subtitle_text("")

            if not self.is_using_master_audio and (self.last_played_comm_id or self.comm_player.playbackState() != QMediaPlayer.StoppedState):
                self.stop_comm_audio()

    def on_player_duration_changed(self, dur_ms: int):
        self.slider_pos.setRange(0, dur_ms)
        self.duration_changed.emit(dur_ms)
        self.update_time_label(self.player.position(), dur_ms)
        if self.fs_window and self.fs_window.isVisible():
            self.fs_window.sync_state(
                self.player.position(), dur_ms, self.player.playbackState() == QMediaPlayer.PlayingState
            )

    def update_time_label(self, pos_ms: int, dur_ms: int):
        pos_s = pos_ms // 1000
        dur_s = dur_ms // 1000
        pos_str = f"{pos_s//3600:02d}:{(pos_s%3600)//60:02d}:{pos_s%60:02d}"
        dur_str = f"{dur_s//3600:02d}:{(dur_s%3600)//60:02d}:{dur_s%60:02d}"
        self.lbl_time.setText(f"{pos_str} / {dur_str}")

    def toggle_fullscreen(self):
        if self.fs_window and self.fs_window.isVisible():
            self.exit_fullscreen()
        else:
            self.enter_fullscreen()

    def enter_fullscreen(self):
        if not self.fs_window:
            self.fs_window = FullscreenPlayerWindow(self)
            self.fs_window.closed.connect(self.on_fullscreen_closed)

        self.video_container_layout.removeWidget(self.video_widget)
        self.fs_window.video_area_layout.addWidget(self.video_widget)

        self.btn_fullscreen.setText("Обычный экран (Esc / F11)")
        self.fs_window.sync_state(
            self.player.position(), self.player.duration(), self.player.playbackState() == QMediaPlayer.PlayingState
        )
        if self.lbl_subtitle.isVisible():
            self.fs_window.set_subtitle_text(self.lbl_subtitle.text())
        else:
            self.fs_window.set_subtitle_text("")

        self.fs_window.showFullScreen()

    def exit_fullscreen(self):
        if self.fs_window and self.fs_window.isVisible():
            self.fs_window.close()

    def on_fullscreen_closed(self):
        if self.fs_window:
            self.fs_window.video_area_layout.removeWidget(self.video_widget)
        self.video_container_layout.addWidget(self.video_widget)

        self.btn_fullscreen.setText("Полный экран (F11)")

    def keyPressEvent(self, event):
        if event.key() == Qt.Key_F11:
            self.toggle_fullscreen()
            event.accept()
        elif event.key() == Qt.Key_Space:
            self.toggle_play()
            event.accept()
        elif event.key() == Qt.Key_Left:
            self.seek_relative(-5000)
            event.accept()
        elif event.key() == Qt.Key_Right:
            self.seek_relative(5000)
            event.accept()
        else:
            super().keyPressEvent(event)

