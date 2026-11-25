# -*- coding: utf-8 -*-
"""
Главное окно приложения для тифлокомментирования видео на Python (PySide6).
Полная поддержка скринридеров NVDA / JAWS, клавиатурная навигация, интерактивный таймлайн.
"""

import os
import time
import threading
from typing import Optional, List, Dict, Any
from PySide6.QtWidgets import (
    QMainWindow, QWidget, QVBoxLayout, QHBoxLayout, QGridLayout, QPushButton, QLabel,
    QMenuBar, QMenu, QStatusBar, QFileDialog, QMessageBox, QProgressDialog,
    QSplitter, QCheckBox, QSlider, QToolBar, QInputDialog, QSizePolicy, QApplication
)
from PySide6.QtCore import Qt, QThread, Signal, Slot, QVariantAnimation, QEasingCurve, QTimer, QUrl
from PySide6.QtGui import QAction, QKeySequence, QIcon, QDesktopServices
from core.version import APP_VERSION
from core.app_paths import get_icon_path, get_help_index_path

from core.config_manager import ConfigManager
from core.project_manager import ProjectManager, Project
from core.gemini_client import GeminiClient
from core.character_manager import CharacterManager
from core.tts_engine import TTSService, SAPI5Engine
from core.video_splitter import analyze_media, split_video_into_chunks
from core.audio_dsp import render_master_audio_track
from core.mkv_exporter import export_project_to_mkv
from core.srt_manager import parse_srt_file, export_commentaries_to_srt

from ui.video_player_widget import VideoPlayerWidget
from ui.accessible_timeline import AccessibleTimelineWidget
from ui.comment_list_panel import CommentListPanel
from ui.audio_dsp_panel import AudioDspPanel
from ui.settings_dialog import SettingsDialog
from ui.project_list_dialog import ProjectListDialog
from ui.character_cards_dialog import CharacterCardsDialog
from ui.comment_edit_dialog import CommentEditDialog
from ui.comment_create_dialog import CommentCreateDialog
from ui.export_progress_dialog import MKVExportProgressDialog, AudioExportProgressDialog
from ui.user_prompt_dialog import UserPromptDialog
from ui.fragment_prompt_dialog import FragmentPromptDialog
from ui.fragment_generation_dialog import FragmentGenerationProgressDialog
from ui.generation_progress_dialog import GeminiGenerationProgressDialog, GeminiGenerationWorker
from ui.chunk_selection_dialog import ChunkSelectionDialog
from ui.tts_progress_dialog import TTSProgressDialog, TTSGenerationWorker
from ui.video_preparation_dialog import VideoPreparationProgressDialog
from ui.regeneration_confirm_dialog import RegenerationConfirmDialog
from ui.about_dialog import AboutDialog


class MasterAudioRenderWorker(QThread):
    """Фоновый рабочий поток для высокоскоростного сведения мастер-аудиопотока с компрессией."""
    finished_render = Signal(str)
    error_render = Signal(str)
    progress_updated = Signal(float, str, str)

    def __init__(
        self,
        src_video_or_audio: str,
        commentaries: List[Dict[str, Any]],
        output_path: str,
        config: ConfigManager,
        total_duration_sec: float = 0.0,
        parent=None
    ):
        super().__init__(parent)
        self.src_video_or_audio = src_video_or_audio
        self.commentaries = [dict(c) for c in commentaries]
        self.output_path = output_path
        self.config = config
        self.total_duration_sec = float(total_duration_sec)
        self.cancel_event = threading.Event()

    def run(self):
        tmp_output = self.output_path + f".tmp_{int(time.time() * 1000)}.wav"
        try:
            def prog_cb(frac: float, cur_str: str, speed_str: str):
                if not self.cancel_event.is_set():
                    self.progress_updated.emit(frac, cur_str, speed_str)

            ok = render_master_audio_track(
                source_video_or_audio=self.src_video_or_audio,
                commentaries_with_audio=self.commentaries,
                output_audio_path=tmp_output,
                movie_vol_db=self.config.movie_volume_db,
                comm_vol_db=self.config.commentary_volume_db,
                movie_muted=self.config.movie_muted,
                comm_muted=self.config.commentary_muted,
                comp_threshold_db=self.config.compressor_threshold_db,
                comp_lookahead_ms=self.config.compressor_lookahead_ms,
                comp_release_ms=self.config.compressor_release_ms,
                custom_ffmpeg=self.config.ffmpeg_path,
                total_duration_sec=self.total_duration_sec,
                progress_callback=prog_cb,
                cancel_event=self.cancel_event
            )
            if ok and os.path.isfile(tmp_output) and not self.cancel_event.is_set():
                # Безопасная атомарная замена файла
                try:
                    if os.path.isfile(self.output_path):
                        try:
                            os.replace(tmp_output, self.output_path)
                        except Exception:
                            time.sleep(0.05)
                            os.replace(tmp_output, self.output_path)
                    else:
                        os.rename(tmp_output, self.output_path)
                except Exception:
                    self.output_path = tmp_output

                self.finished_render.emit(self.output_path)
            else:
                if os.path.isfile(tmp_output):
                    try:
                        os.remove(tmp_output)
                    except Exception:
                        pass
                self.error_render.emit("Рендер мастер-аудио отменен или завершен с ошибкой")
        except Exception as e:
            if os.path.isfile(tmp_output):
                try:
                    os.remove(tmp_output)
                except Exception:
                    pass
            self.error_render.emit(str(e))

    def cancel(self):
        self.cancel_event.set()


class MainWindow(QMainWindow):
    """Главное окно приложения Тифлокомментатор."""

    def __init__(self):
        super().__init__()
        self.config = ConfigManager()
        self.project_mgr = ProjectManager()
        self.current_project: Optional[Project] = None
        self.tts_service = TTSService(self.config)
        self.last_comment_list_width: int = 300
        self.last_mixer_width: int = 340
        self._splitter_anim: Optional[QVariantAnimation] = None
        self._mixer_anim: Optional[QVariantAnimation] = None
        self._master_audio_worker: Optional[MasterAudioRenderWorker] = None
        self._resume_playback_after_audio_rebuild: bool = False
        self._master_rebuild_timer = QTimer(self)
        self._master_rebuild_timer.setSingleShot(True)
        self._master_rebuild_timer.setInterval(250)
        self._master_rebuild_timer.timeout.connect(self._do_rebuild_master_audio)

        self.setWindowTitle(f"Тифлокомментатор {APP_VERSION} — видео с Google Gemini")
        self.resize(1180, 800)

        icon_path = get_icon_path()
        if icon_path and os.path.isfile(icon_path):
            self.setWindowIcon(QIcon(icon_path))


        self.init_actions()
        self.init_ui()
        self.init_menus()

        self.player_widget.update_from_config(self.config)

        if self.config.last_project:
            proj = self.project_mgr.open_project(self.config.last_project)
            if proj:
                self.load_project(proj)

    def init_actions(self):
        """Создает и настраивает все действия приложения с горячими клавишами."""
        # Список комментариев
        self.act_view_list = QAction("📋 Список (Ctrl+L)", self)
        self.act_view_list.setCheckable(True)
        self.act_view_list.setChecked(True)
        self.act_view_list.setShortcut(QKeySequence("Ctrl+L"))
        self.act_view_list.setToolTip("Показать или скрыть боковую панель комментариев (Ctrl+L)")
        self.act_view_list.triggered.connect(self.toggle_comment_list_panel)

        # Панель микшера и компрессора
        self.act_view_mixer = QAction("🎛️ Микшер (Ctrl+M)", self)
        self.act_view_mixer.setCheckable(True)
        self.act_view_mixer.setChecked(True)
        self.act_view_mixer.setShortcut(QKeySequence("Ctrl+M"))
        self.act_view_mixer.setToolTip("Показать или скрыть панель микшера и компрессора (Ctrl+M)")
        self.act_view_mixer.triggered.connect(self.toggle_audio_dsp_panel)

        # Создать проект
        self.act_create = QAction("🎬 Создать", self)
        self.act_create.setShortcut(QKeySequence("Ctrl+N"))
        self.act_create.setToolTip("Создать новый проект из видеофайла (Ctrl+N)")
        self.act_create.triggered.connect(self.create_new_project_direct)

        # Открыть проект
        self.act_open = QAction("📂 Проекты", self)
        self.act_open.setShortcut(QKeySequence("Ctrl+O"))
        self.act_open.setToolTip("Список сохраненных проектов тифлокомментирования (Ctrl+O)")
        self.act_open.triggered.connect(self.open_projects_dialog)

        # Сохранить проект
        self.act_save = QAction("💾 Сохранить", self)
        self.act_save.setShortcut(QKeySequence("Ctrl+S"))
        self.act_save.setToolTip("Сохранить текущий проект (Ctrl+S)")
        self.act_save.triggered.connect(self.save_current_project)

        # Пожелания к проекту
        self.act_user_prompt = QAction("📝 Пожелания", self)
        self.act_user_prompt.setShortcut(QKeySequence("Ctrl+U"))
        self.act_user_prompt.setToolTip("Индивидуальные пожелания, сюжет или сценарий к фильму для модели Gemini (Ctrl+U)")
        self.act_user_prompt.triggered.connect(self.open_user_prompt_dialog)

        # Добавить комментарий
        self.act_add_comm = QAction("➕ Добавить (Ctrl+T)", self)
        self.act_add_comm.setShortcut(QKeySequence("Ctrl+T"))
        self.act_add_comm.setToolTip("Создать тифлокомментарий вручную на текущей позиции видео (Ctrl+T / Ins)")
        self.act_add_comm.triggered.connect(self.add_manual_commentary)

        # Gemini
        self.act_gemini = QAction("🤖 Gemini авто", self)
        self.act_gemini.setShortcut(QKeySequence("Ctrl+G"))
        self.act_gemini.setToolTip("Запустить автоматический анализ и создание тифлокомментариев Gemini (Ctrl+G)")
        self.act_gemini.triggered.connect(self.start_gemini_generation)

        # Части видео (генерация по выбранной части)
        self.act_chunks = QAction("🧩 Части видео...", self)
        self.act_chunks.setShortcut(QKeySequence("Ctrl+Shift+C"))
        self.act_chunks.setToolTip("Список всех частей видео: где уже есть тифлокомментарии, а где нет. Позволяет создать или пересоздать комментарии для любой части (Ctrl+Shift+C)")
        self.act_chunks.triggered.connect(self.open_chunks_dialog)

        # SAPI5
        self.act_sapi = QAction("🗣️ SAPI5", self)
        self.act_sapi.setShortcut(QKeySequence("Ctrl+Shift+S"))
        self.act_sapi.setToolTip("Озвучить ещё не озвученные комментарии с помощью синтезатора речи SAPI5 (Ctrl+Shift+S)")
        self.act_sapi.triggered.connect(lambda: self.start_tts_voiceover("sapi5"))

        # Gemini TTS
        self.act_gemini_tts = QAction("🎙️ Gemini TTS", self)
        self.act_gemini_tts.setShortcut(QKeySequence("Ctrl+Shift+T"))
        self.act_gemini_tts.setToolTip("Озвучить ещё не озвученные комментарии с помощью нейросетевого Gemini TTS (Ctrl+Shift+T)")
        self.act_gemini_tts.triggered.connect(lambda: self.start_tts_voiceover("gemini"))

        # Комментировать выделенный фрагмент
        self.act_comment_fragment = QAction("🎬 Прокомментировать фрагмент", self)
        self.act_comment_fragment.setShortcut(QKeySequence("Ctrl+Shift+G"))
        self.act_comment_fragment.setToolTip("Прокомментировать или повторно прокомментировать выделенный на таймлайне фрагмент (Ctrl+Shift+G)")
        self.act_comment_fragment.triggered.connect(self.trigger_comment_selected_fragment)

        # Герои
        self.act_chars = QAction("👥 Герои", self)
        self.act_chars.setShortcut(QKeySequence("Ctrl+K"))
        self.act_chars.setToolTip("Карточки персонажей фильма и их скриншоты (Ctrl+K)")
        self.act_chars.triggered.connect(self.open_character_cards)

        # Настройки
        self.act_settings = QAction("⚙️ Настройки", self)
        self.act_settings.setShortcut(QKeySequence("Ctrl+P"))
        self.act_settings.setToolTip("Настройки программы, моделей Gemini и синтезаторов (Ctrl+P)")
        self.act_settings.triggered.connect(self.open_settings)

        # Статистика расхода токенов
        self.act_token_usage = QAction("📊 Расход токенов", self)
        self.act_token_usage.setShortcut(QKeySequence("Ctrl+Shift+U"))
        self.act_token_usage.setToolTip("Статистика расхода входящих и исходящих токенов по каждой модели и расчет стоимости (Ctrl+Shift+U)")
        self.act_token_usage.triggered.connect(self.open_token_usage_dialog)

        # Импорт комментариев из SRT
        self.act_import_srt = QAction("📥 Импорт из SRT", self)
        self.act_import_srt.setShortcut(QKeySequence("Ctrl+I"))
        self.act_import_srt.setToolTip("Импортировать тифлокомментарии из файла субтитров SRT в текущий проект (Ctrl+I)")
        self.act_import_srt.triggered.connect(self.import_srt)

        # Экспорт комментариев в SRT
        self.act_export_srt = QAction("📄 Экспорт в SRT", self)
        self.act_export_srt.setShortcut(QKeySequence("Ctrl+Shift+E"))
        self.act_export_srt.setToolTip("Экспортировать комментарии текущего проекта в файл субтитров SRT (Ctrl+Shift+E)")
        self.act_export_srt.triggered.connect(self.export_srt)

        # Экспорт мастер-аудио
        self.act_export_audio = QAction("🎵 Экспорт аудио", self)
        self.act_export_audio.setShortcut(QKeySequence("Ctrl+Shift+A"))
        self.act_export_audio.setToolTip("Экспортировать сведенную мастер-аудиодорожку в MP3 или WAV (Ctrl+Shift+A)")
        self.act_export_audio.triggered.connect(self.export_audio)

        # Экспорт в MKV
        self.act_export = QAction("📤 Экспорт", self)
        self.act_export.setShortcut(QKeySequence("Ctrl+E"))
        self.act_export.setToolTip("Экспортировать фильм с тифлокомментариями в MKV видеофайл (Ctrl+E)")
        self.act_export.triggered.connect(self.export_mkv)

        # Справка - Руководство пользователя
        self.act_user_guide = QAction("📖 Руководство пользователя", self)
        self.act_user_guide.setShortcut(QKeySequence("F1"))
        self.act_user_guide.setToolTip("Открыть руководство пользователя в браузере (F1)")
        self.act_user_guide.triggered.connect(self.open_user_guide)

        # Справка - О программе
        self.act_about = QAction("ℹ️ О программе", self)
        self.act_about.setToolTip("Информация о версии программы, авторе и реквизитах поддержки")
        self.act_about.triggered.connect(self.open_about_dialog)

        # Регистрируем все действия на уровне главного окна для глобальных горячих клавиш
        all_actions = [
            self.act_view_list, self.act_view_mixer,
            self.act_create, self.act_open, self.act_save, self.act_user_prompt,
            self.act_import_srt, self.act_export_srt, self.act_export_audio,
            self.act_add_comm, self.act_comment_fragment, self.act_gemini, self.act_chunks,
            self.act_sapi, self.act_gemini_tts,
            self.act_chars, self.act_token_usage, self.act_settings, self.act_export,
            self.act_user_guide, self.act_about
        ]
        for act in all_actions:
            self.addAction(act)

    def init_ui(self):
        central_widget = QWidget(self)
        self.setCentralWidget(central_widget)
        main_layout = QVBoxLayout(central_widget)
        main_layout.setContentsMargins(4, 4, 4, 4)
        main_layout.setSpacing(4)

        # Главный горизонтальный сплиттер (слева панель комментариев во всю высоту, справа плеер + таймлайн)
        self.main_h_splitter = QSplitter(Qt.Horizontal, self)
        self.main_h_splitter.setHandleWidth(7)
        self.main_h_splitter.setStyleSheet("""
            QSplitter::handle:horizontal {
                background-color: #2b2b36;
                border-left: 2px solid #444455;
                border-right: 2px solid #00FFCC;
                width: 7px;
            }
            QSplitter::handle:horizontal:hover {
                background-color: #008877;
            }
            QSplitter::handle:vertical {
                background-color: #2b2b36;
                border-top: 2px solid #444455;
                border-bottom: 2px solid #00FFCC;
                height: 7px;
            }
            QSplitter::handle:vertical:hover {
                background-color: #008877;
            }
        """)

        # Левая панель: Список тифлокомментариев
        self.comment_list_panel = CommentListPanel(self)
        self.comment_list_panel.set_max_speedup(self.config.max_speedup)
        self.comment_list_panel.seek_requested.connect(self.player_widget_seek)
        self.comment_list_panel.commentary_timing_changed.connect(self.on_commentary_timing_changed)
        self.comment_list_panel.commentary_moved.connect(self.on_commentary_moved)
        self.comment_list_panel.commentary_text_edited.connect(self.on_commentary_text_edited)
        self.comment_list_panel.commentary_updated.connect(self.on_commentary_timing_changed)
        self.comment_list_panel.commentary_deleted.connect(self.on_commentary_deleted)
        self.comment_list_panel.commentaries_deleted.connect(self.on_commentaries_deleted)
        self.comment_list_panel.commentary_audio_deleted.connect(self.on_commentary_audio_deleted)
        self.comment_list_panel.commentaries_resynthesize_requested.connect(self.on_commentaries_resynthesize_requested)
        self.comment_list_panel.add_commentary_requested.connect(self.add_manual_commentary)
        self.comment_list_panel.import_srt_requested.connect(self.import_srt)
        self.comment_list_panel.export_srt_requested.connect(self.export_srt)
        self.comment_list_panel.close_requested.connect(lambda: self.set_comment_list_visible(False))
        # Резервный путь для Ctrl+L, если оконный QAction не сработал.
        self.comment_list_panel.toggle_panel_requested.connect(self.toggle_comment_list_panel)
        self.main_h_splitter.addWidget(self.comment_list_panel)

        # Правая область: Видеоплеер, таймлайн и кнопки управления
        right_container = QWidget(self)
        right_layout = QVBoxLayout(right_container)
        right_layout.setContentsMargins(0, 0, 0, 0)
        right_layout.setSpacing(4)

        # Верхний компактный контейнер для маленькой кнопки слева вверху (видна, когда список свернут)
        self.top_reopen_container = QWidget(self)
        top_reopen_layout = QHBoxLayout(self.top_reopen_container)
        top_reopen_layout.setContentsMargins(2, 2, 2, 2)
        top_reopen_layout.setSpacing(0)

        self.btn_reopen_list = QPushButton("📋 ▶ Развернуть список", self)
        self.btn_reopen_list.setStyleSheet("""
            QPushButton {
                font-weight: bold;
                font-size: 11px;
                padding: 4px 10px;
                background-color: #1e1e28;
                color: #00FFCC;
                border: 1px solid #00FFCC;
                border-radius: 4px;
            }
            QPushButton:hover {
                background-color: #005544;
                color: #FFFFFF;
                border-color: #00FFFF;
            }
            QPushButton:focus {
                border: 2px solid #FFFF00;
            }
        """)
        self.btn_reopen_list.setToolTip("Развернуть панель комментариев (Ctrl+L)")
        self.btn_reopen_list.setAccessibleName("Развернуть список комментариев")
        self.btn_reopen_list.setAccessibleDescription("Развернуть скрытую боковую панель списка тифлокомментариев. Горячая клавиша Ctrl+L")
        self.btn_reopen_list.clicked.connect(lambda: self.set_comment_list_visible(True))
        top_reopen_layout.addWidget(self.btn_reopen_list)
        top_reopen_layout.addStretch(1)

        self.btn_reopen_mixer = QPushButton("◀ 🎛️ Развернуть микшер", self)
        self.btn_reopen_mixer.setStyleSheet("""
            QPushButton {
                font-weight: bold;
                font-size: 11px;
                padding: 4px 10px;
                background-color: #1e1e28;
                color: #00FFCC;
                border: 1px solid #00FFCC;
                border-radius: 4px;
            }
            QPushButton:hover {
                background-color: #005544;
                color: #FFFFFF;
                border-color: #00FFFF;
            }
            QPushButton:focus {
                border: 2px solid #FFFF00;
            }
        """)
        self.btn_reopen_mixer.setToolTip("Развернуть панель микшера и компрессора (Ctrl+M)")
        self.btn_reopen_mixer.setAccessibleName("Развернуть панель микшера и компрессора")
        self.btn_reopen_mixer.setAccessibleDescription("Развернуть скрытую боковую панель микшера звука и компрессора. Горячая клавиша Ctrl+M")
        self.btn_reopen_mixer.clicked.connect(lambda: self.set_audio_dsp_panel_visible(True))
        self.btn_reopen_mixer.hide()
        top_reopen_layout.addWidget(self.btn_reopen_mixer)

        self.top_reopen_container.hide()
        self.btn_reopen_list.hide()
        right_layout.addWidget(self.top_reopen_container, 0)

        self.splitter = QSplitter(Qt.Vertical, self)
        self.splitter.setHandleWidth(7)

        # Верхняя панель правой области: Видеоплеер
        self.player_widget = VideoPlayerWidget(self)
        self.player_widget.position_changed.connect(self.on_player_pos_changed)
        self.player_widget.duration_changed.connect(self.on_player_dur_changed)
        self.splitter.addWidget(self.player_widget)

        # Нижняя панель правой области: Интерактивный таймлайн
        self.timeline_widget = AccessibleTimelineWidget(self)
        self.timeline_widget.set_max_speedup(self.config.max_speedup)
        self.timeline_widget.seek_requested.connect(self.player_widget_seek)
        self.timeline_widget.play_pause_requested.connect(self.player_widget.toggle_play)
        self.timeline_widget.commentary_timing_changed.connect(self.on_commentary_timing_changed)
        self.timeline_widget.commentary_moved.connect(self.on_commentary_moved)
        self.timeline_widget.commentary_resized.connect(self.on_commentary_resized)
        self.timeline_widget.fragment_commentary_requested.connect(self.on_comment_selected_fragment)
        self.timeline_widget.commentary_text_edited.connect(self.on_commentary_text_edited)
        self.timeline_widget.commentary_updated.connect(self.on_commentary_timing_changed)
        self.timeline_widget.commentary_deleted.connect(self.on_commentary_deleted)
        self.timeline_widget.commentaries_deleted.connect(self.on_commentaries_deleted)
        self.timeline_widget.commentary_audio_deleted.connect(self.on_commentary_audio_deleted)
        self.timeline_widget.commentaries_resynthesize_requested.connect(self.on_commentaries_resynthesize_requested)
        self.timeline_widget.add_commentary_requested.connect(self.add_manual_commentary)
        self.splitter.addWidget(self.timeline_widget)

        self.splitter.setCollapsible(0, False)
        self.splitter.setCollapsible(1, False)
        self.splitter.setSizes([520, 160])
        right_layout.addWidget(self.splitter, 1)

        # Компактная двухстрочная нижняя панель быстрых действий (2 строки x 6 колонок)
        bottom_bar = QWidget(self)
        bottom_bar_layout = QGridLayout(bottom_bar)
        bottom_bar_layout.setContentsMargins(4, 2, 4, 2)
        bottom_bar_layout.setHorizontalSpacing(4)
        bottom_bar_layout.setVerticalSpacing(3)
        for col_idx in range(6):
            bottom_bar_layout.setColumnStretch(col_idx, 1)

        btn_style = (
            "QPushButton { font-weight: bold; font-size: 11px; padding: 4px 4px; min-height: 28px; min-width: 0px; }"
            "QPushButton:hover { background-color: #005544; }"
        )

        # Строка 1: Управление проектом и комментирование
        self.btn_bottom_list = QPushButton("📋 Список (Ctrl+L)", self)
        self.btn_bottom_list.setStyleSheet(btn_style)
        self.btn_bottom_list.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)
        self.btn_bottom_list.setAccessibleName("Показать или скрыть список комментариев")
        self.btn_bottom_list.clicked.connect(self.toggle_comment_list_panel)
        bottom_bar_layout.addWidget(self.btn_bottom_list, 0, 0)

        self.btn_add_comm = QPushButton("➕ Добавить (Ctrl+T)", self)
        self.btn_add_comm.setStyleSheet(btn_style)
        self.btn_add_comm.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)
        self.btn_add_comm.setAccessibleName("Кнопка Добавить комментарий вручную на текущей позиции")
        self.btn_add_comm.clicked.connect(self.add_manual_commentary)
        bottom_bar_layout.addWidget(self.btn_add_comm, 0, 1)

        self.btn_save_proj = QPushButton("💾 Сохранить (Ctrl+S)", self)
        self.btn_save_proj.setStyleSheet(btn_style)
        self.btn_save_proj.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)
        self.btn_save_proj.setAccessibleName("Кнопка Сохранить проект")
        self.btn_save_proj.clicked.connect(self.save_current_project)
        bottom_bar_layout.addWidget(self.btn_save_proj, 0, 2)

        self.btn_user_prompt = QPushButton("📝 Пожелания (Ctrl+U)", self)
        self.btn_user_prompt.setStyleSheet(btn_style)
        self.btn_user_prompt.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)
        self.btn_user_prompt.setAccessibleName("Кнопка Пожелания пользователя к проекту")
        self.btn_user_prompt.clicked.connect(self.open_user_prompt_dialog)
        bottom_bar_layout.addWidget(self.btn_user_prompt, 0, 3)

        self.btn_chars = QPushButton("👥 Герои (Ctrl+K)", self)
        self.btn_chars.setStyleSheet(btn_style)
        self.btn_chars.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)
        self.btn_chars.setAccessibleName("Кнопка Открыть карточки героев фильма")
        self.btn_chars.clicked.connect(self.open_character_cards)
        bottom_bar_layout.addWidget(self.btn_chars, 0, 4, 1, 2)

        # Строка 2: Импорт/экспорт и синтез речи
        self.btn_import_srt = QPushButton("📥 Импорт SRT (Ctrl+I)", self)
        self.btn_import_srt.setStyleSheet(btn_style)
        self.btn_import_srt.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)
        self.btn_import_srt.setAccessibleName("Кнопка Импортировать комментарии из файла SRT")
        self.btn_import_srt.clicked.connect(self.import_srt)
        bottom_bar_layout.addWidget(self.btn_import_srt, 1, 0)

        self.btn_export_srt = QPushButton("📄 Экспорт SRT (Ctrl+Shift+E)", self)
        self.btn_export_srt.setStyleSheet(btn_style)
        self.btn_export_srt.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)
        self.btn_export_srt.setAccessibleName("Кнопка Экспортировать комментарии в файл SRT")
        self.btn_export_srt.clicked.connect(self.export_srt)
        bottom_bar_layout.addWidget(self.btn_export_srt, 1, 1)

        self.btn_voice_sapi = QPushButton("🗣️ SAPI5 (Ctrl+Shift+S)", self)
        self.btn_voice_sapi.setStyleSheet(btn_style)
        self.btn_voice_sapi.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)
        self.btn_voice_sapi.setAccessibleName("Кнопка Озвучить оставшиеся комментарии с помощью синтезатора SAPI5")
        self.btn_voice_sapi.clicked.connect(lambda: self.start_tts_voiceover("sapi5"))
        bottom_bar_layout.addWidget(self.btn_voice_sapi, 1, 2)

        self.btn_voice_gemini = QPushButton("🎙️ Gemini TTS (Ctrl+Shift+T)", self)
        self.btn_voice_gemini.setStyleSheet(btn_style)
        self.btn_voice_gemini.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)
        self.btn_voice_gemini.setAccessibleName("Кнопка Озвучить оставшиеся комментарии с помощью Gemini TTS")
        self.btn_voice_gemini.clicked.connect(lambda: self.start_tts_voiceover("gemini"))
        bottom_bar_layout.addWidget(self.btn_voice_gemini, 1, 3)

        self.btn_export_audio = QPushButton("🎵 Экспорт аудио (Ctrl+Shift+A)", self)
        self.btn_export_audio.setStyleSheet(btn_style)
        self.btn_export_audio.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)
        self.btn_export_audio.setAccessibleName("Кнопка Экспортировать сведенную аудиодорожку в MP3 или WAV")
        self.btn_export_audio.clicked.connect(self.export_audio)
        bottom_bar_layout.addWidget(self.btn_export_audio, 1, 4)

        self.btn_export = QPushButton("📤 Экспорт в MKV (Ctrl+E)", self)
        self.btn_export.setStyleSheet(btn_style)
        self.btn_export.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)
        self.btn_export.setAccessibleName("Кнопка Экспортировать готовый фильм в MKV")
        self.btn_export.clicked.connect(self.export_mkv)
        bottom_bar_layout.addWidget(self.btn_export, 1, 5)

        right_layout.addWidget(bottom_bar, 0)
        self.main_h_splitter.addWidget(right_container)

        # Правая панель: Микшер и компрессор
        self.audio_dsp_panel = AudioDspPanel(self.config, self)
        self.audio_dsp_panel.dsp_settings_changed.connect(self.on_dsp_panel_changed)
        self.audio_dsp_panel.mode_changed.connect(self.on_dsp_mode_changed)
        self.audio_dsp_panel.close_requested.connect(lambda: self.set_audio_dsp_panel_visible(False))
        self.player_widget.level_changed.connect(self.audio_dsp_panel.meter.set_level_db)
        self.main_h_splitter.addWidget(self.audio_dsp_panel)

        self.main_h_splitter.setCollapsible(0, False)
        self.main_h_splitter.setCollapsible(1, False)
        self.main_h_splitter.setCollapsible(2, False)
        self.main_h_splitter.setSizes([280, 560, 340])
        self.main_h_splitter.splitterMoved.connect(self.on_main_splitter_moved)
        main_layout.addWidget(self.main_h_splitter, 1)

        # Строка состояния
        self.status_bar = self.statusBar()
        self.status_bar.setAccessibleName("Строка состояния приложения")
        self.status_bar.showMessage("Готов к работе")

    def init_menus(self):
        menubar = self.menuBar()

        # Меню Проект
        menu_file = menubar.addMenu("Проект")
        menu_file.addAction(self.act_create)
        menu_file.addAction(self.act_open)
        menu_file.addAction(self.act_save)
        menu_file.addAction(self.act_user_prompt)
        menu_file.addSeparator()
        menu_file.addAction(self.act_import_srt)
        menu_file.addAction(self.act_export_srt)
        menu_file.addAction(self.act_export_audio)
        menu_file.addAction(self.act_export)
        menu_file.addSeparator()

        act_exit = QAction("Выход", self)
        act_exit.setShortcut(QKeySequence("Ctrl+Q"))
        act_exit.triggered.connect(self.close)
        menu_file.addAction(act_exit)

        # Меню Правка
        menu_edit = menubar.addMenu("Правка")
        menu_edit.addAction(self.act_add_comm)
        menu_edit.addAction(self.act_comment_fragment)
        menu_edit.addSeparator()
        menu_edit.addAction(self.act_import_srt)
        menu_edit.addAction(self.act_export_srt)

        # Регистрируем действия на уровне окна для глобальных горячих клавиш
        self.addAction(self.act_import_srt)
        self.addAction(self.act_export_srt)

        # Меню Вид
        menu_view = menubar.addMenu("Вид")
        menu_view.addAction(self.act_view_list)
        menu_view.addAction(self.act_view_mixer)
        self.addAction(self.act_view_list)
        self.addAction(self.act_view_mixer)

        menu_view.addSeparator()

        act_fs = QAction("Полноэкранный режим видео", self)
        act_fs.setShortcut(QKeySequence("F11"))
        act_fs.triggered.connect(self.player_widget.toggle_fullscreen)
        menu_view.addAction(act_fs)
        self.addAction(act_fs)

        menu_view.addSeparator()
        act_size_50 = QAction("Размер окна видео: Компактный (50%)", self)
        act_size_50.setShortcut(QKeySequence("Ctrl+1"))
        act_size_50.triggered.connect(lambda: self.set_splitter_ratio(0.5))
        menu_view.addAction(act_size_50)
        self.addAction(act_size_50)

        act_size_65 = QAction("Размер окна видео: Стандартный (65%)", self)
        act_size_65.setShortcut(QKeySequence("Ctrl+2"))
        act_size_65.triggered.connect(lambda: self.set_splitter_ratio(0.65))
        menu_view.addAction(act_size_65)
        self.addAction(act_size_65)

        act_size_80 = QAction("Размер окна видео: Крупный (80%)", self)
        act_size_80.setShortcut(QKeySequence("Ctrl+3"))
        act_size_80.triggered.connect(lambda: self.set_splitter_ratio(0.80))
        menu_view.addAction(act_size_80)
        self.addAction(act_size_80)

        # Глобальный шорткат Insert для создания комментария
        act_ins = QAction(self)
        act_ins.setShortcut(QKeySequence("Insert"))
        act_ins.triggered.connect(self.add_manual_commentary)
        self.addAction(act_ins)

        # Меню Генерация
        menu_gen = menubar.addMenu("Генерация")
        menu_gen.addAction(self.act_gemini)
        menu_gen.addAction(self.act_chunks)
        menu_gen.addAction(self.act_comment_fragment)

        # Меню Озвучка
        menu_voice = menubar.addMenu("Озвучка")
        menu_voice.addAction(self.act_sapi)
        menu_voice.addAction(self.act_gemini_tts)

        # Меню Герои
        menu_chars = menubar.addMenu("Персонажи")
        menu_chars.addAction(self.act_chars)

        # Меню Настройки
        menu_settings = menubar.addMenu("Настройки")
        menu_settings.addAction(self.act_settings)
        menu_settings.addAction(self.act_token_usage)
        self.addAction(self.act_token_usage)

        # Меню Справка
        menu_help = menubar.addMenu("Справка")
        menu_help.addAction(self.act_user_guide)
        menu_help.addAction(self.act_about)

    def on_main_splitter_moved(self, pos: int, index: int):
        """Отслеживает изменение положения разделителей панелей при перетаскивании мышью."""
        sizes = self.main_h_splitter.sizes()
        if len(sizes) < 3:
            return
        left_w = sizes[0]
        right_w = sizes[2]

        if left_w > 30:
            self.last_comment_list_width = left_w
            if hasattr(self, "btn_reopen_list"):
                self.btn_reopen_list.hide()
            self.act_view_list.setChecked(True)
        else:
            if hasattr(self, "top_reopen_container"):
                self.top_reopen_container.show()
            if hasattr(self, "btn_reopen_list"):
                self.btn_reopen_list.show()
            self.act_view_list.setChecked(False)

        if right_w > 30:
            self.last_mixer_width = right_w
            if hasattr(self, "btn_reopen_mixer"):
                self.btn_reopen_mixer.hide()
            self.act_view_mixer.setChecked(True)
        else:
            if hasattr(self, "top_reopen_container"):
                self.top_reopen_container.show()
            if hasattr(self, "btn_reopen_mixer"):
                self.btn_reopen_mixer.show()
            self.act_view_mixer.setChecked(False)

        if hasattr(self, "btn_reopen_list") and hasattr(self, "btn_reopen_mixer"):
            if not self.btn_reopen_list.isVisible() and not self.btn_reopen_mixer.isVisible():
                if hasattr(self, "top_reopen_container"):
                    self.top_reopen_container.hide()

    def _panel_has_focus(self, panel: QWidget) -> bool:
        """True, если клавиатурный фокус находится внутри панели (или на ней самой)."""
        fw = QApplication.focusWidget()
        return fw is not None and (fw is panel or panel.isAncestorOf(fw))

    def _focus_main_area(self) -> bool:
        """Уводит фокус из скрываемой панели в плеер: скринридер не должен
        остаться на невидимом элементе с нулевой шириной."""
        pw = getattr(self, "player_widget", None)
        if pw is None or not pw.isVisible():
            return False
        for attr in ("slider_pos", "btn_play"):
            w = getattr(pw, attr, None)
            if w is not None and w.isVisible() and w.focusPolicy() != Qt.NoFocus:
                w.setFocus(Qt.OtherFocusReason)
                return True
        if pw.focusPolicy() != Qt.NoFocus:
            pw.setFocus(Qt.OtherFocusReason)
            return True
        return False

    def toggle_comment_list_panel(self):
        sizes = self.main_h_splitter.sizes()
        is_open = bool(len(sizes) >= 1 and sizes[0] > 30) and self.comment_list_panel.isVisible()
        self.set_comment_list_visible(not is_open)

    def set_comment_list_visible(self, visible: bool, animate: bool = True):
        sizes = self.main_h_splitter.sizes()
        if len(sizes) < 3:
            sizes = [280, 560, 340]
        total_w = max(400, sum(sizes))
        right_w = sizes[2]

        if visible:
            target_left = getattr(self, "last_comment_list_width", 280)
            if target_left < 150:
                target_left = 280
            target_left = min(target_left, max(50, total_w - right_w - 50))
        else:
            if sizes[0] > 30:
                self.last_comment_list_width = sizes[0]
            target_left = 0

        self.comment_list_panel.setVisible(True)
        # Уводим фокус ДО схлопывания панели, иначе он останется на
        # невидимом элементе с нулевой шириной и скринридер замолчит.
        if target_left == 0 and self._panel_has_focus(self.comment_list_panel):
            if not self._focus_main_area():
                if hasattr(self, "btn_reopen_list"):
                    self.btn_reopen_list.show()
                    self.btn_reopen_list.setFocus(Qt.OtherFocusReason)
        new_center = max(200, total_w - target_left - right_w)
        self.main_h_splitter.setSizes([target_left, new_center, right_w])

        if target_left == 0:
            if hasattr(self, "top_reopen_container"):
                self.top_reopen_container.show()
            if hasattr(self, "btn_reopen_list"):
                self.btn_reopen_list.show()
            self.act_view_list.setChecked(False)
            if hasattr(self, "status_bar"):
                self.status_bar.showMessage("Панель комментариев свернута", 2000)
            return
        if hasattr(self, "btn_reopen_list"):
            self.btn_reopen_list.hide()
        if hasattr(self, "btn_reopen_mixer") and not self.btn_reopen_mixer.isVisible():
            if hasattr(self, "top_reopen_container"):
                self.top_reopen_container.hide()
        self.act_view_list.setChecked(True)
        if hasattr(self, "status_bar"):
            self.status_bar.showMessage("Панель комментариев развернута", 2000)
        # Фокус — в список: сразу после Ctrl+L пользователь ожидает его там.
        QTimer.singleShot(0, self.comment_list_panel.focus_table)

    def toggle_audio_dsp_panel(self):
        sizes = self.main_h_splitter.sizes()
        is_open = bool(len(sizes) >= 3 and sizes[2] > 30) and self.audio_dsp_panel.isVisible()
        self.set_audio_dsp_panel_visible(not is_open)

    def set_audio_dsp_panel_visible(self, visible: bool, animate: bool = True):
        sizes = self.main_h_splitter.sizes()
        if len(sizes) < 3:
            sizes = [280, 560, 340]
        total_w = max(400, sum(sizes))
        left_w = sizes[0]

        if visible:
            target_right = getattr(self, "last_mixer_width", 340)
            if target_right < 180:
                target_right = 340
            target_right = min(target_right, max(180, total_w - left_w - 200))
        else:
            if sizes[2] > 30:
                self.last_mixer_width = sizes[2]
            target_right = 0

        self.audio_dsp_panel.setVisible(True)
        # Уводим фокус ДО схлопывания панели, иначе он останется на
        # невидимом элементе с нулевой шириной и скринридер замолчит.
        if target_right == 0 and self._panel_has_focus(self.audio_dsp_panel):
            if not self._focus_main_area():
                if hasattr(self, "btn_reopen_mixer"):
                    self.btn_reopen_mixer.show()
                    self.btn_reopen_mixer.setFocus(Qt.OtherFocusReason)
        new_center = max(200, total_w - left_w - target_right)
        self.main_h_splitter.setSizes([left_w, new_center, target_right])

        if target_right == 0:
            if hasattr(self, "top_reopen_container"):
                self.top_reopen_container.show()
            if hasattr(self, "btn_reopen_mixer"):
                self.btn_reopen_mixer.show()
            self.act_view_mixer.setChecked(False)
            if hasattr(self, "status_bar"):
                self.status_bar.showMessage("Панель микшера свернута", 2000)
            return
        if hasattr(self, "btn_reopen_mixer"):
            self.btn_reopen_mixer.hide()
        if hasattr(self, "btn_reopen_list") and not self.btn_reopen_list.isVisible():
            if hasattr(self, "top_reopen_container"):
                self.top_reopen_container.hide()
        self.act_view_mixer.setChecked(True)
        if hasattr(self, "status_bar"):
            self.status_bar.showMessage("Панель микшера развернута", 2000)

    def on_dsp_panel_changed(self, dsp_dict: dict):
        """Срабатывает мгновенно при перемещении любого регулятора на панели микшера."""
        self.player_widget.update_from_config(self.config)
        if hasattr(self, "audio_dsp_panel") and self.audio_dsp_panel.is_final_sound_mode():
            if hasattr(self, "player_widget") and self.player_widget.is_playing():
                self._resume_playback_after_audio_rebuild = True
                self.player_widget.pause()
            self.request_rebuild_master_audio()

    def on_dsp_mode_changed(self, is_final: bool):
        """Срабатывает при переключении режима предпросмотра звука (Быстрое ред. / Итоговый звук)."""
        if not self.current_project:
            return
        if is_final:
            self.status_bar.showMessage("Включен режим «Итоговый звук». Запуск сведения мастер-трека...", 3000)
            self.request_rebuild_master_audio(immediate=True)
        else:
            self._master_rebuild_timer.stop()
            if self._master_audio_worker and self._master_audio_worker.isRunning():
                self._master_audio_worker.cancel()
            self.player_widget.clear_master_audio()
            self.player_widget.update_from_config(self.config)
            if hasattr(self, "audio_dsp_panel"):
                self.audio_dsp_panel.set_render_idle()
            self.status_bar.showMessage("Включен режим «Быстрое редактирование».", 3000)

    def player_widget_seek(self, pos_ms: int):
        self.player_widget.set_position(pos_ms, deferred=True)

    def set_splitter_ratio(self, ratio: float):
        total_h = self.splitter.height()
        if total_h > 100:
            top_h = int(total_h * ratio)
            bot_h = total_h - top_h
            self.splitter.setSizes([top_h, bot_h])

    def create_new_project_direct(self):
        video_filters = "Видеофайлы (*.mp4 *.mkv *.avi *.mov *.vob *.mpg *.mpeg *.wmv *.ts *.webm);;Все файлы (*.*)"
        video_path, _ = QFileDialog.getOpenFileName(
            self, "Выберите видеофайл для создания проекта тифлокомментирования", "", video_filters
        )
        if not video_path:
            return

        default_name = os.path.splitext(os.path.basename(video_path))[0]
        proj_name, ok = QInputDialog.getText(
            self, "Название проекта", "Введите название нового проекта:", text=default_name
        )
        if not ok or not proj_name.strip():
            return

        proj_name = proj_name.strip()
        chunk_min = self.config.chunk_duration_minutes

        prep_dlg = VideoPreparationProgressDialog(
            project_mgr=self.project_mgr,
            project_name=proj_name,
            src_video_path=video_path,
            chunk_min=chunk_min,
            config=self.config,
            parent=self
        )
        if prep_dlg.exec() and prep_dlg.result_project:
            proj = prep_dlg.result_project
            self.load_project(proj)
            self.config.last_project = proj.folder_path
            self.config.save()

            reply = QMessageBox.question(
                self, "Проект создан",
                f"Проект «{proj.name}» успешно создан!\nВидеофайл: {os.path.basename(video_path)}\n\nЗапустить автоматический анализ и создание тифлокомментариев с помощью Google Gemini прямо сейчас?",
                QMessageBox.Yes | QMessageBox.No
            )
            if reply == QMessageBox.Yes:
                self.start_gemini_generation()

    def open_projects_dialog(self):
        dlg = ProjectListDialog(self.project_mgr, self.config, self)
        if dlg.exec():
            if dlg.selected_project:
                self.load_project(dlg.selected_project)
                if dlg.resume_requested:
                    self.start_gemini_generation()
                    return
                if getattr(dlg, "start_generation_requested", False):
                    reply = QMessageBox.question(
                        self, "Проект создан",
                        f"Проект «{dlg.selected_project.name}» успешно создан!\n"
                        f"Видеофайл подготовлен и сконвертирован в эталонный формат.\n\n"
                        f"Запустить автоматический анализ и создание тифлокомментариев с помощью Google Gemini прямо сейчас?",
                        QMessageBox.Yes | QMessageBox.No
                    )
                    if reply == QMessageBox.Yes:
                        self.start_gemini_generation()

    def close_current_project(self):
        """Полностью выгружает текущий проект, останавливает воспроизведение и фоновые процессы."""
        self._master_rebuild_timer.stop()
        if self._master_audio_worker and self._master_audio_worker.isRunning():
            self._master_audio_worker.cancel()
            self._master_audio_worker.wait(300)
            self._master_audio_worker = None

        self.player_widget.clear_media()
        self.comment_list_panel.set_commentaries([])
        self.timeline_widget.set_commentaries([])
        self.timeline_widget.set_duration(0.0)

        if self.current_project:
            if self.config.last_project == self.current_project.folder_path:
                self.config.last_project = ""
                self.config.save()
            self.current_project = None

        self.setWindowTitle("Тифлокомментатор")
        self.status_bar.showMessage("Проект закрыт.")

    def load_project(self, project: Project):
        self.current_project = project
        project.resolve_overlaps()
        self.setWindowTitle(f"Тифлокомментатор {APP_VERSION} — Проект: {project.name}")
        self.timeline_widget.set_max_speedup(self.config.max_speedup)
        self.comment_list_panel.set_max_speedup(self.config.max_speedup)

        src_vid = project.data.get("src_video_path")
        dur = float(project.data.get("total_duration_sec", 0.0))
        is_final = self.audio_dsp_panel.is_final_sound_mode() if hasattr(self, "audio_dsp_panel") else False
        master_path = os.path.join(project.output_dir, "preview_master_audio.wav")
        has_master = is_final and os.path.isfile(master_path) and os.path.getsize(master_path) > 1000

        if src_vid and os.path.isfile(src_vid):
            if dur <= 0.0:
                media_info = analyze_media(src_vid, self.config.ffprobe_path)
                dur = media_info.duration
                if dur > 0:
                    project.data["total_duration_sec"] = dur
            if dur > 0:
                self.timeline_widget.set_duration(dur)
            self.player_widget.load_media(src_vid, project.commentaries, master_path if has_master else "")
        elif project.chunks and os.path.isfile(project.chunks[0].get("filepath", "")):
            first_chunk = project.chunks[0]["filepath"]
            if dur > 0:
                self.timeline_widget.set_duration(dur)
            self.player_widget.load_media(first_chunk, project.commentaries, master_path if has_master else "")
        elif dur > 0:
            self.timeline_widget.set_duration(dur)

        self.comment_list_panel.set_commentaries(project.commentaries)
        self.timeline_widget.set_commentaries(project.commentaries)
        self.audio_dsp_panel.load_from_config(self.config)
        self.player_widget.update_from_config(self.config)
        if is_final:
            self.request_rebuild_master_audio(immediate=True)
        self.status_bar.showMessage(f"Проект «{project.name}» загружен. Комментариев: {len(project.commentaries)}")

    def request_rebuild_master_audio(self, immediate: bool = False):
        """Запрашивает пересчет сведенного мастер-аудиопотока с компрессией."""
        if not self.current_project:
            return
        if hasattr(self, "audio_dsp_panel") and not self.audio_dsp_panel.is_final_sound_mode():
            return
        if hasattr(self, "player_widget") and self.player_widget.is_playing():
            self._resume_playback_after_audio_rebuild = True
            self.player_widget.pause()
        if immediate:
            self._master_rebuild_timer.stop()
            self._do_rebuild_master_audio()
        else:
            self._master_rebuild_timer.start(250)

    def _do_rebuild_master_audio(self):
        """Выполняет быстрый фоновый рендер мастер-звука проекта с компрессором."""
        if not self.current_project:
            return
        if hasattr(self, "audio_dsp_panel") and not self.audio_dsp_panel.is_final_sound_mode():
            return

        src_vid = self.current_project.data.get("src_video_path")
        if not src_vid or not os.path.isfile(src_vid):
            if self.current_project.chunks and os.path.isfile(self.current_project.chunks[0].get("filepath", "")):
                src_vid = self.current_project.chunks[0]["filepath"]
            else:
                return

        master_path = os.path.join(self.current_project.output_dir, "preview_master_audio.wav")
        dur = float(self.current_project.data.get("total_duration_sec", 0.0))

        if self._master_audio_worker and self._master_audio_worker.isRunning():
            self._master_audio_worker.cancel()
            self._master_audio_worker.wait(300)

        if hasattr(self, "audio_dsp_panel"):
            self.audio_dsp_panel.set_render_progress(0, "00:00", "")

        self._master_audio_worker = MasterAudioRenderWorker(
            src_video_or_audio=src_vid,
            commentaries=self.current_project.commentaries,
            output_path=master_path,
            config=self.config,
            total_duration_sec=dur,
            parent=self
        )
        self._master_audio_worker.progress_updated.connect(self._on_master_audio_progress)
        self._master_audio_worker.finished_render.connect(self._on_master_audio_rendered)
        self._master_audio_worker.error_render.connect(self._on_master_audio_error)
        self._master_audio_worker.start()

    def _on_master_audio_progress(self, frac: float, cur_str: str, speed_str: str):
        """Отображает текущий прогресс фонового сведения мастер-аудио."""
        pct = int(round(frac * 100.0))
        if hasattr(self, "audio_dsp_panel"):
            self.audio_dsp_panel.set_render_progress(pct, cur_str, speed_str)
        if hasattr(self, "status_bar"):
            self.status_bar.showMessage(f"⏳ Сведение мастер-трека: {pct}% ({cur_str})")

    def _on_master_audio_rendered(self, master_path: str):
        """Применяет обновленный мастер-аудиопоток в плеер и автоматически возобновляет воспроизведение."""
        if hasattr(self, "audio_dsp_panel"):
            self.audio_dsp_panel.set_render_finished(True)
        if hasattr(self, "status_bar"):
            self.status_bar.showMessage("✓ Мастер-трек готов", 3000)
        if self.current_project and os.path.isfile(master_path):
            self.player_widget.load_master_audio(master_path)
        if getattr(self, "_resume_playback_after_audio_rebuild", False):
            self._resume_playback_after_audio_rebuild = False
            self.player_widget.play()

    def _on_master_audio_error(self, err_msg: str):
        """Обрабатывает ошибку фонового рендера мастер-аудио."""
        if hasattr(self, "audio_dsp_panel"):
            self.audio_dsp_panel.set_render_idle()
        if hasattr(self, "status_bar"):
            self.status_bar.showMessage(f"Ошибка сведения мастер-трека: {err_msg}", 4000)

    def save_current_project(self):
        if not self.current_project:
            QMessageBox.information(self, "Информация", "Нет открытого проекта для сохранения.")
            return

        self.current_project.save()
        self.status_bar.showMessage("Проект успешно сохранен!", 4000)

    def start_gemini_generation(self, chunk_indices=None):
        """
        Запускает создание тифлокомментариев.
        chunk_indices=None — обработать только ещё не обработанные части (продолжение).
        chunk_indices=[...] — пересоздать только явно выбранные части.
        """
        # QAction triggered передаёт bool в первый аргумент — это не список частей
        if isinstance(chunk_indices, bool):
            chunk_indices = None

        if not self.current_project:
            self.open_projects_dialog()
            if not self.current_project:
                return

        if not self.config.api_key:
            QMessageBox.warning(self, "Внимание", "Пожалуйста, укажите ваш Google Gemini API-ключ в Настройках.")
            self.open_settings()
            return

        chunks = self.current_project.chunks
        unprocessed = [c for c in chunks if not c.get("processed")]

        # Подтверждение полного пересоздания — только для запуска «все необработанные»
        if chunk_indices is None:
            all_done = bool(chunks) and not unprocessed
            no_chunks_but_comments = not chunks and bool(self.current_project.commentaries)

            if all_done or no_chunks_but_comments:
                count = len(self.current_project.commentaries)
                confirm_dlg = RegenerationConfirmDialog(commentaries_count=count, parent=self)
                if not confirm_dlg.exec():
                    return

                self.current_project.reset_for_full_regeneration()
                self.player_widget.clear_master_audio()
                self.load_project(self.current_project)

        dlg = GeminiGenerationProgressDialog(self.current_project, self.config, chunk_indices=chunk_indices, parent=self)
        dlg.exec()

        self.load_project(self.current_project)

    def open_chunks_dialog(self):
        """Открывает список всех частей видео с их статусом и запуском по любой части."""
        if not self.current_project:
            QMessageBox.information(
                self, "Информация",
                "Сначала откройте или создайте проект тифлокомментирования."
            )
            return

        if not self.config.api_key:
            QMessageBox.warning(self, "Внимание", "Пожалуйста, укажите ваш Google Gemini API-ключ в Настройках.")
            self.open_settings()
            return

        dlg = ChunkSelectionDialog(self.current_project, parent=self)
        if dlg.exec():
            if dlg.generate_all_requested:
                self.start_gemini_generation()
                return
            if dlg.generate_indices:
                self.start_gemini_generation(chunk_indices=dlg.generate_indices)
                return

    def add_manual_commentary(self):
        """Создает тифлокомментарий вручную на текущей позиции видео."""
        if not self.current_project:
            QMessageBox.information(self, "Информация", "Сначала откройте или создайте проект.")
            return

        self.player_widget.pause()
        cur_pos_sec = self.player_widget.player.position() / 1000.0

        dlg = CommentCreateDialog(current_pos_sec=cur_pos_sec, default_duration=3.0, parent=self)
        if dlg.exec():
            new_id = f"comm_{int(time.time() * 1000)}"
            new_comm = {
                "id": new_id,
                "start_time": dlg.get_start_time(),
                "end_time": dlg.get_end_time(),
                "duration_sec": dlg.get_duration(),
                "text": dlg.get_text(),
                "type": "manual",
                "audio_file": None,
                "raw_audio_file": None,
                "raw_duration_sec": None,
                "speed_factor": 1.0,
                "tts_engine": None,
                "audio_needs_rebuild": True
            }
            self.current_project.add_commentaries([new_comm])
            self.current_project.save()

            self.comment_list_panel.set_commentaries(self.current_project.commentaries)
            self.comment_list_panel.select_commentary_by_id(new_id)
            self.timeline_widget.set_commentaries(self.current_project.commentaries)
            self.player_widget.set_commentaries(self.current_project.commentaries)
            self.request_rebuild_master_audio()

            self.status_bar.showMessage(
                f"Создан комментарий на {dlg.get_start_time():.2f} сек. Нажмите кнопку озвучки для синтеза.", 4000
            )

    def start_tts_voiceover(self, engine_type: str = "sapi5", selected_ids: Optional[List[str]] = None):
        if not self.current_project:
            QMessageBox.information(self, "Информация", "Сначала откройте или создайте проект.")
            return

        comms = self.current_project.commentaries
        if not comms:
            QMessageBox.warning(self, "Внимание", "В проекте нет тифлокомментариев для озвучки.")
            return

        target_comms = [c for c in comms if c.get("id") in selected_ids] if selected_ids else comms
        pending = [
            c for c in target_comms
            if c.get("audio_needs_rebuild", False)
            or not c.get("audio_file")
            or not os.path.isfile(c.get("audio_file", ""))
        ]

        if not pending:
            QMessageBox.information(
                self, "Озвучивание комментариев",
                "Все выбранные тифлокомментарии уже озвучены!\n"
                "Если вы хотите переозвучить их другим способом, сначала удалите озвучку через контекстное меню (Shift+Delete)."
            )
            return

        # Проверка конфликта синтезаторов
        already_voiced = [
            c for c in self.current_project.commentaries
            if c.get("audio_file") and os.path.isfile(c.get("audio_file", "")) and not c.get("audio_needs_rebuild", False)
        ]
        if already_voiced:
            used_engines = set((c.get("tts_engine") or "sapi5").lower() for c in already_voiced)
            if any(e != engine_type.lower() for e in used_engines):
                prev_name = "SAPI5" if "sapi5" in used_engines else "Gemini"
                cur_name = "Gemini" if engine_type == "gemini" else "SAPI5"
                msg = (
                    f"Внимание!\n\n"
                    f"В проекте уже озвучено {len(already_voiced)} комментариев с помощью {prev_name}.\n"
                    f"Вы собираетесь озвучить ещё не озвученные комментарии ({len(pending)} шт.) с помощью {cur_name}.\n\n"
                    f"Голоса тифлокомментариев в фильме будут отличаться.\n\n"
                    f"Вы действительно хотите продолжить озвучивание оставшихся комментариев другим синтезатором?"
                )
                reply = QMessageBox.warning(
                    self, "Предупреждение о смене синтезатора", msg,
                    QMessageBox.Yes | QMessageBox.No
                )
                if reply != QMessageBox.Yes:
                    return

        if engine_type == "gemini" and not self.config.api_key:
            QMessageBox.warning(self, "Внимание", "Пожалуйста, укажите ваш Google Gemini API-ключ в Настройках.")
            self.open_settings()
            return

        if hasattr(self, "player_widget") and self.player_widget.is_playing():
            self._resume_playback_after_audio_rebuild = True
            self.player_widget.pause()

        dlg = TTSProgressDialog(
            self.current_project,
            self.config,
            engine_type=engine_type,
            comments_to_process=pending,
            tts_service=self.tts_service,
            parent=self
        )
        dlg.exec()

        self.current_project.save()
        self.comment_list_panel.set_commentaries(self.current_project.commentaries)
        self.timeline_widget.set_commentaries(self.current_project.commentaries)
        self.player_widget.set_commentaries(self.current_project.commentaries)
        self.request_rebuild_master_audio(immediate=True)

    def on_commentary_timing_changed(self, comm_id: str):
        """
        Обрабатывает изменение продолжительности звучания или границ комментария.
        Если аудио уже существует, мгновенно адаптирует скорость из исходного мастер-файла.
        """
        if not self.current_project:
            return
        if hasattr(self, "audio_dsp_panel") and self.audio_dsp_panel.is_final_sound_mode():
            if hasattr(self, "player_widget") and self.player_widget.is_playing():
                self._resume_playback_after_audio_rebuild = True
                self.player_widget.pause()
        self.player_widget.stop_comm_audio()
        target = next((c for c in self.current_project.commentaries if c.get("id") == comm_id), None)
        if target:
            # Проверяем наличие уже созданной озвучки (мастер-исходника или рабочего аудио)
            has_audio = (
                (target.get("raw_audio_file") and os.path.isfile(target.get("raw_audio_file")))
                or (target.get("audio_file") and os.path.isfile(target.get("audio_file")))
                or os.path.isfile(os.path.join(self.current_project.audio_dir, f"{comm_id}_raw.wav"))
                or os.path.isfile(os.path.join(self.current_project.audio_dir, f"{comm_id}.wav"))
            )
            if has_audio:
                ok = self.tts_service.adjust_audio_for_duration(target, self.current_project)
                speed_f = float(target.get("speed_factor") or 1.0)
                if ok:
                    self.status_bar.showMessage(
                        f"Длительность комментария обновлена. Скорость озвучки адаптирована ({speed_f:.2f}x).", 4000
                    )
                else:
                    self.status_bar.showMessage("Длительность комментария обновлена.", 3000)
            else:
                self.status_bar.showMessage("Длительность комментария обновлена.", 3000)

            self.current_project.resolve_overlaps()
            self.current_project.save()
            self.player_widget.set_commentaries(self.current_project.commentaries)
            self.comment_list_panel.set_commentaries(self.current_project.commentaries)
            self.timeline_widget.set_commentaries(self.current_project.commentaries)
            self.request_rebuild_master_audio()

    def on_commentary_resized(self, comm_id: str, new_start: float, new_end: float):
        """
        Обрабатывает изменение границ комментария мышью на таймлайне (растягивание/сжатие).
        """
        if not self.current_project:
            return
        target = next((c for c in self.current_project.commentaries if c.get("id") == comm_id), None)
        if target:
            target["start_time"] = round(new_start, 3)
            target["end_time"] = round(new_end, 3)
            target["duration_sec"] = round(new_end - new_start, 3)
            self.on_commentary_timing_changed(comm_id)

    def on_commentary_moved(self, comm_id: str, new_start: float, new_end: float):
        """
        Обрабатывает перемещение комментария по шкале времени (длительность сохраняется).
        Перемещенный комментарий занимает новую позицию, а перекрывающиеся комментарии справа сдвигаются.
        """
        if not self.current_project:
            return
        if hasattr(self, "audio_dsp_panel") and self.audio_dsp_panel.is_final_sound_mode():
            if hasattr(self, "player_widget") and self.player_widget.is_playing():
                self._resume_playback_after_audio_rebuild = True
                self.player_widget.pause()
        target = next((c for c in self.current_project.commentaries if c.get("id") == comm_id), None)
        if target:
            target["start_time"] = round(new_start, 3)
            target["end_time"] = round(new_end, 3)
            target["duration_sec"] = round(new_end - new_start, 3)
            self.current_project.resolve_overlaps(moved_comm_id=comm_id)
            self.current_project.save()
            self.player_widget.set_commentaries(self.current_project.commentaries)
            self.comment_list_panel.set_commentaries(self.current_project.commentaries)
            self.timeline_widget.set_commentaries(self.current_project.commentaries)
            self.request_rebuild_master_audio()
            self.status_bar.showMessage("Позиция комментария обновлена.", 2500)

    def trigger_comment_selected_fragment(self):
        """Активирует комментирование выделенного на таймлайне фрагмента."""
        if not self.current_project:
            QMessageBox.information(self, "Информация", "Сначала откройте или создайте проект.")
            return
        sel = self.timeline_widget.canvas.get_selection()
        if not sel:
            QMessageBox.information(
                self, "Выделение фрагмента",
                "Сначала выделите фрагмент видео на таймлайне:\n"
                "• Зажмите Shift и проведите мышью по таймлайну,\n"
                "• Или нажмите клавиши 'I' (точка входа) и 'O' (точка выхода)."
            )
            return
        self.on_comment_selected_fragment(sel[0], sel[1])

    def on_comment_selected_fragment(self, start_sec: float, end_sec: float):
        """Запускает комментирование выделенного диапазона видео в Gemini."""
        if not self.current_project:
            QMessageBox.information(self, "Информация", "Сначала откройте или создайте проект.")
            return
        if not self.config.api_key:
            QMessageBox.warning(
                self, "API-ключ не задан",
                "Укажите API-ключ Google Gemini в меню Настройки -> Google Gemini."
            )
            return

        self.player_widget.pause()

        dlg_prompt = FragmentPromptDialog(start_sec, end_sec, parent=self)
        if not dlg_prompt.exec():
            return

        frag_wishes = dlg_prompt.get_fragment_prompt()

        prog_dlg = FragmentGenerationProgressDialog(
            project=self.current_project,
            config=self.config,
            start_sec=start_sec,
            end_sec=end_sec,
            fragment_prompt=frag_wishes,
            parent=self
        )
        if prog_dlg.exec():
            self.current_project.resolve_overlaps()
            self.current_project.save()
            self.player_widget.set_commentaries(self.current_project.commentaries)
            self.comment_list_panel.set_commentaries(self.current_project.commentaries)
            self.timeline_widget.set_commentaries(self.current_project.commentaries)
            self.timeline_widget.canvas.clear_selection()
            self.request_rebuild_master_audio(immediate=True)
            self.status_bar.showMessage(
                f"Выделенный фрагмент ({start_sec:.2f}с — {end_sec:.2f}с) успешно прокомментирован!", 4000
            )

    def on_commentary_text_edited(self, comm_id: str):
        """
        Обрабатывает редактирование текста комментария.
        """
        if not self.current_project:
            return
        if hasattr(self, "player_widget") and self.player_widget.is_playing():
            self._resume_playback_after_audio_rebuild = True
            self.player_widget.pause()
        self.player_widget.stop_comm_audio()
        target = next((c for c in self.current_project.commentaries if c.get("id") == comm_id), None)
        if target:
            TTSService.delete_commentary_audio(target, self.current_project)
            target["audio_needs_rebuild"] = True
            self.current_project.save()
            self.player_widget.set_commentaries(self.current_project.commentaries)
            self.comment_list_panel.set_commentaries(self.current_project.commentaries)
            self.timeline_widget.set_commentaries(self.current_project.commentaries)
            self.request_rebuild_master_audio(immediate=True)
            self.status_bar.showMessage("Текст комментария изменен. Старая озвучка сброшена, требуется повторная озвучка.", 3500)

    def on_commentary_updated(self, comm_id: str):
        self.on_commentary_timing_changed(comm_id)

    def on_commentary_deleted(self, comm_id: str):
        self.on_commentaries_deleted([comm_id])

    def on_commentaries_deleted(self, comm_ids: List[str]):
        if not self.current_project:
            return
        if hasattr(self, "player_widget") and self.player_widget.is_playing():
            self._resume_playback_after_audio_rebuild = True
            self.player_widget.pause()
        self.player_widget.stop_comm_audio()
        for cid in comm_ids:
            target = next((c for c in self.current_project.commentaries if c.get("id") == cid), None)
            if target:
                TTSService.delete_commentary_audio(target, self.current_project)
                if target in self.current_project.commentaries:
                    self.current_project.commentaries.remove(target)
        self.current_project.save()
        self.player_widget.set_commentaries(self.current_project.commentaries)
        self.comment_list_panel.set_commentaries(self.current_project.commentaries)
        self.timeline_widget.set_commentaries(self.current_project.commentaries)
        self.request_rebuild_master_audio(immediate=True)
        self.status_bar.showMessage(f"Удалено {len(comm_ids)} комментариев.", 3000)

    def on_commentary_audio_deleted(self, comm_ids: List[str]):
        if not self.current_project:
            return
        if hasattr(self, "player_widget") and self.player_widget.is_playing():
            self._resume_playback_after_audio_rebuild = True
            self.player_widget.pause()
        self.player_widget.stop_comm_audio()
        for cid in comm_ids:
            target = next((c for c in self.current_project.commentaries if c.get("id") == cid), None)
            if target:
                TTSService.delete_commentary_audio(target, self.current_project)
        self.current_project.save()
        self.player_widget.set_commentaries(self.current_project.commentaries)
        self.comment_list_panel.set_commentaries(self.current_project.commentaries)
        self.timeline_widget.set_commentaries(self.current_project.commentaries)
        self.request_rebuild_master_audio(immediate=True)
        self.status_bar.showMessage(f"Удалена аудиозапись для {len(comm_ids)} комментариев.", 3000)

    def on_commentaries_resynthesize_requested(self, comm_ids: List[str], engine_type: str):
        if not self.current_project:
            return
        if hasattr(self, "player_widget") and self.player_widget.is_playing():
            self._resume_playback_after_audio_rebuild = True
            self.player_widget.pause()
        for cid in comm_ids:
            target = next((c for c in self.current_project.commentaries if c.get("id") == cid), None)
            if target:
                target["audio_needs_rebuild"] = True
        self.start_tts_voiceover(engine_type=engine_type, selected_ids=comm_ids)

    def on_player_pos_changed(self, pos_ms: int):
        self.timeline_widget.set_position(pos_ms / 1000.0)

    def on_player_dur_changed(self, dur_ms: int):
        if dur_ms > 0:
            dur_sec = dur_ms / 1000.0
            if self.current_project:
                self.current_project.data["total_duration_sec"] = dur_sec
            self.timeline_widget.set_duration(dur_sec)

    def open_character_cards(self):
        if not self.current_project:
            QMessageBox.information(self, "Информация", "Сначала откройте или создайте проект.")
            return
        if hasattr(self, "player_widget") and self.player_widget:
            self.player_widget.pause()
        dlg = CharacterCardsDialog(self.current_project, self)
        dlg.exec()

    def open_user_prompt_dialog(self):
        """Открывает редактор индивидуальных пожеланий пользователя к текущему проекту."""
        if not self.current_project:
            QMessageBox.information(self, "Информация", "Сначала откройте или создайте проект.")
            return

        dlg = UserPromptDialog(
            current_prompt=self.current_project.user_prompt,
            project_name=self.current_project.name,
            parent=self
        )
        if dlg.exec():
            new_prompt = dlg.get_user_prompt()
            self.current_project.user_prompt = new_prompt
            self.current_project.save()
            self.status_bar.showMessage("Пожелания к проекту успешно сохранены!", 4000)

    def open_token_usage_dialog(self):
        """Открывает диалог статистики расхода токенов и расчета затрат."""
        from ui.token_usage_dialog import TokenUsageDialog
        dlg = TokenUsageDialog(self.config, self)
        dlg.exec()

    def open_settings(self):
        dlg = SettingsDialog(self.config, self)
        dlg.showMaximized()
        if dlg.exec():
            # Мгновенно обновляем настройки звука, DSP и лимита скорости речи
            if hasattr(self, "player_widget") and self.player_widget.is_playing():
                self._resume_playback_after_audio_rebuild = True
                self.player_widget.pause()
            self.player_widget.update_from_config(self.config)
            self.timeline_widget.set_max_speedup(self.config.max_speedup)
            self.comment_list_panel.set_max_speedup(self.config.max_speedup)
            self.request_rebuild_master_audio(immediate=True)
        else:
            self.player_widget.update_from_config(self.config)
            self.timeline_widget.set_max_speedup(self.config.max_speedup)
            self.comment_list_panel.set_max_speedup(self.config.max_speedup)

    def open_user_guide(self):
        """Открывает руководство пользователя (Help/index.html) в браузере по умолчанию."""
        help_path = get_help_index_path()
        if help_path and os.path.isfile(help_path):
            url = QUrl.fromLocalFile(help_path)
            opened = QDesktopServices.openUrl(url)
            if not opened:
                import webbrowser
                webbrowser.open(f"file:///{os.path.abspath(help_path).replace(os.sep, '/')}")
        else:
            QMessageBox.warning(
                self,
                "Руководство пользователя",
                f"Файл руководства пользователя не найден:\n{help_path or 'Help/index.html'}"
            )

    def open_about_dialog(self):
        """Открывает диалоговое окно «О программе»."""
        dlg = AboutDialog(self)
        dlg.exec()

    def closeEvent(self, event):
        if hasattr(self, "_master_rebuild_timer"):
            self._master_rebuild_timer.stop()
        if hasattr(self, "_master_audio_worker") and self._master_audio_worker and self._master_audio_worker.isRunning():
            self._master_audio_worker.cancel()
            self._master_audio_worker.wait(500)
        if hasattr(self, "player_widget") and self.player_widget:
            self.player_widget.pause()
            self.player_widget.clear_master_audio()
        super().closeEvent(event)

    def export_audio(self):
        """
        Экспортирует сведенную мастер-аудиодорожку с текущими настройками звука в MP3 или WAV.
        """
        if not self.current_project:
            QMessageBox.information(self, "Информация", "Сначала откройте или создайте проект.")
            return

        def_name = f"{self.current_project.name}_master.mp3"
        out_path, selected_filter = QFileDialog.getSaveFileName(
            self,
            "Экспорт мастер-аудио с тифлокомментариями",
            def_name,
            "Аудио MP3 (*.mp3);;Аудио WAV (*.wav)",
            "Аудио MP3 (*.mp3)"
        )
        if not out_path:
            return

        if "wav" in selected_filter.lower():
            if not out_path.lower().endswith(".wav"):
                out_path += ".wav"
        else:
            if not (out_path.lower().endswith(".mp3") or out_path.lower().endswith(".wav")):
                out_path += ".mp3"

        dlg = AudioExportProgressDialog(self.current_project, out_path, self.config, self)
        dlg.exec()


    def export_mkv(self):
        if not self.current_project:
            QMessageBox.information(self, "Информация", "Сначала откройте или создайте проект.")
            return

        def_name = f"{self.current_project.name}_tiflo.mkv"
        out_path, _ = QFileDialog.getSaveFileName(
            self, "Экспорт фильма с тифлокомментариями в MKV", def_name, "MKV Видео (*.mkv)"
        )
        if not out_path:
            return

        dlg = MKVExportProgressDialog(self.current_project, out_path, self.config, self)
        dlg.exec()

    def import_srt(self):
        """
        Импортирует комментарии из файла субтитров SRT в открытый проект.
        Поддерживает объединение с существующими комментариями или полную замену.
        """
        if not self.current_project:
            QMessageBox.information(self, "Информация", "Сначала откройте или создайте проект.")
            return

        file_path, _ = QFileDialog.getOpenFileName(
            self,
            "Импорт комментариев из файла SRT",
            "",
            "Файлы субтитров SRT (*.srt);;Все файлы (*.*)"
        )
        if not file_path:
            return

        imported = parse_srt_file(file_path)
        if not imported:
            QMessageBox.warning(
                self,
                "Ошибка импорта",
                f"В выбранном файле «{os.path.basename(file_path)}» не найдено корректных субтитров/комментариев в формате SRT."
            )
            return

        existing_count = len(self.current_project.commentaries)
        if existing_count > 0:
            msg_box = QMessageBox(self)
            msg_box.setWindowTitle("Импорт комментариев из SRT")
            msg_box.setText(
                f"В текущем проекте уже есть {existing_count} комментариев.\n"
                f"В файле «{os.path.basename(file_path)}» найдено {len(imported)} комментариев.\n\n"
                f"Выберите способ импорта:"
            )
            msg_box.setIcon(QMessageBox.Question)
            btn_merge = msg_box.addButton("Добавить к существующим", QMessageBox.AcceptRole)
            btn_replace = msg_box.addButton("Заменить все комментарии", QMessageBox.DestructiveRole)
            btn_cancel = msg_box.addButton("Отмена", QMessageBox.RejectRole)
            msg_box.setDefaultButton(btn_merge)
            msg_box.exec()

            clicked = msg_box.clickedButton()
            if clicked == btn_cancel or clicked is None:
                return
            elif clicked == btn_replace:
                # Удаляем аудиофайлы старых комментариев при замене
                for c in list(self.current_project.commentaries):
                    TTSService.delete_commentary_audio(c, self.current_project)
                self.current_project.replace_commentaries(imported)
            else:
                # Объединяем с существующими
                self.current_project.add_commentaries(imported)
        else:
            self.current_project.replace_commentaries(imported)

        self.current_project.save()
        self.player_widget.stop_comm_audio()
        self.player_widget.set_commentaries(self.current_project.commentaries)
        self.comment_list_panel.set_commentaries(self.current_project.commentaries)
        self.timeline_widget.set_commentaries(self.current_project.commentaries)

        info_msg = (
            f"Успешно импортировано {len(imported)} комментариев из файла «{os.path.basename(file_path)}»!\n"
            f"Всего комментариев в проекте: {len(self.current_project.commentaries)} шт.\n\n"
            f"Чтобы озвучить импортированные комментарии голосом, используйте:\n"
            f"• Синтезатор SAPI5 (Ctrl+Shift+S)\n"
            f"• Нейросетевой Gemini TTS (Ctrl+Shift+T)"
        )
        self.status_bar.showMessage(
            f"Успешно импортировано {len(imported)} комментариев из SRT.", 5000
        )
        QMessageBox.information(self, "Импорт завершен", info_msg)

    def export_srt(self):
        """
        Экспортирует тифлокомментарии текущего проекта в файл формата SRT.
        """
        if not self.current_project:
            QMessageBox.information(self, "Информация", "Сначала откройте или создайте проект.")
            return

        comms = self.current_project.commentaries
        if not comms:
            QMessageBox.information(self, "Информация", "В текущем проекте нет комментариев для экспорта.")
            return

        def_name = f"{self.current_project.name}.srt"
        out_path, _ = QFileDialog.getSaveFileName(
            self,
            "Экспорт комментариев в файл SRT",
            def_name,
            "Файлы субтитров SRT (*.srt);;Все файлы (*.*)"
        )
        if not out_path:
            return

        if not out_path.lower().endswith(".srt"):
            out_path += ".srt"

        success = export_commentaries_to_srt(comms, out_path)
        if success:
            self.status_bar.showMessage(
                f"Экспортировано {len(comms)} комментариев в {os.path.basename(out_path)}", 5000
            )
            QMessageBox.information(
                self,
                "Экспорт завершен",
                f"Тифлокомментарии ({len(comms)} шт.) успешно экспортированы в файл:\n{out_path}"
            )
        else:
            QMessageBox.critical(
                self,
                "Ошибка экспорта",
                f"Не удалось записать файл субтитров SRT по пути:\n{out_path}"
            )



