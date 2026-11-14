# -*- coding: utf-8 -*-
"""
Диалоговое окно фоновой подготовки и нормализации видеофайлов:
- Асинхронное выполнение в отдельном потоке QThread (без зависания GUI и без статуса «Не отвечает»)
- Полная адаптация под режим высокой контрастности Windows (High Contrast)
- Чёткое разделение: «Что уже сделано», «Текущий процесс» и «Что осталось сделать»
- Кнопка мгновенной отмены с корректным завершением FFmpeg
- Полная доступность для программ экранного доступа NVDA / JAWS
"""

import os
import threading
import time
from typing import Dict, Any, Optional, List

from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QProgressBar, QFrame, QMessageBox
)
from PySide6.QtCore import Qt, QThread, Signal, Slot
from PySide6.QtGui import QKeySequence, QShortcut

from core.video_splitter import normalize_video_container, analyze_media
from core.project_manager import Project, ProjectManager
from core.audio_dsp import format_duration_sec


class VideoPreparationWorker(QThread):
    """Фоновый рабочий поток для подготовки и нормализации видео."""

    progress_updated = Signal(dict)
    preparation_finished = Signal(object)  # Project
    preparation_error = Signal(str)
    preparation_cancelled = Signal()

    def __init__(
        self,
        project_mgr: ProjectManager,
        project_name: str,
        src_video_path: str,
        chunk_min: int,
        config,
        is_opening: bool = False,
        project_folder: str = "",
        parent=None
    ):
        super().__init__(parent)
        self.project_mgr = project_mgr
        self.project_name = project_name
        self.src_video_path = src_video_path
        self.chunk_min = chunk_min
        self.config = config
        self.is_opening = is_opening
        self.project_folder = project_folder
        self.cancel_event = threading.Event()
        self.process_holder: List[Any] = []
        self._is_cancelled = False

    def cancel(self):
        """Отменяет подготовку и прерывает выполняющийся процесс FFmpeg."""
        self._is_cancelled = True
        self.cancel_event.set()
        if self.process_holder:
            try:
                proc = self.process_holder[0]
                proc.terminate()
                proc.wait(timeout=1.5)
            except Exception:
                try:
                    proc = self.process_holder[0]
                    proc.kill()
                except Exception:
                    pass

    def run(self):
        try:
            if self.is_opening:
                self._run_open_project()
            else:
                self._run_create_project()
        except Exception as e:
            if self.cancel_event.is_set() or self._is_cancelled:
                self.preparation_cancelled.emit()
            else:
                self.preparation_error.emit(str(e))

    def _run_open_project(self):
        proj = Project.load(self.project_folder)
        if not proj:
            self.preparation_error.emit(f"Не удалось прочитать проект из папки:\n{self.project_folder}")
            return

        cur_video = proj.data.get("src_video_path", "")
        if cur_video and os.path.isfile(cur_video):
            target_mp4 = os.path.join(self.project_folder, "source_video.mp4")
            cur_ext = os.path.splitext(cur_video)[1].lower()

            if cur_ext != ".mp4" and cur_video != target_mp4 and not (os.path.isfile(target_mp4) and os.path.getsize(target_mp4) > 0):
                self.progress_updated.emit({
                    "percent": 20,
                    "step_name": "Автонормализация устаревшего видеофайла проекта",
                    "done_text": "Загрузка данных проекта",
                    "curr_text": f"Оптимизация медиафайла {os.path.basename(cur_video)} в эталонный MP4 (H.264/AAC/FastStart)...",
                    "rem_text": "Открытие проекта в плеере",
                    "speed_str": "—",
                    "time_str": "00:00"
                })

                def on_norm_progress(pct: float, speed: str, rem_time: str):
                    if self.cancel_event.is_set() or self._is_cancelled:
                        return
                    self.progress_updated.emit({
                        "percent": int(20 + pct * 0.75),
                        "step_name": "Нормализация видеопотока проекта",
                        "done_text": "Загрузка данных проекта",
                        "curr_text": f"Конвертация видеоряда в формат H.264/AAC...\nСкорость: {speed}, осталось: {rem_time}",
                        "rem_text": "Открытие проекта в плеере",
                        "speed_str": speed,
                        "time_str": rem_time
                    })

                norm_ok = normalize_video_container(
                    input_path=cur_video,
                    output_path=target_mp4,
                    custom_ffmpeg=self.config.ffmpeg_path,
                    custom_ffprobe=self.config.ffprobe_path,
                    progress_callback=on_norm_progress,
                    cancel_event=self.cancel_event,
                    process_holder=self.process_holder
                )

                if norm_ok and os.path.isfile(target_mp4):
                    proj.data["src_video_path"] = target_mp4
                    proj.data["source_video_rel"] = "source_video.mp4"
                    media_info = analyze_media(target_mp4, custom_ffprobe=self.config.ffprobe_path)
                    if media_info.duration > 0:
                        proj.data["total_duration_sec"] = round(media_info.duration, 3)
                    proj.save()

        self.preparation_finished.emit(proj)

    def _run_create_project(self):
        if self.cancel_event.is_set() or self._is_cancelled:
            self.preparation_cancelled.emit()
            return

        self.progress_updated.emit({
            "percent": 5,
            "step_name": "Анализ исходного медиафайла",
            "done_text": "Инициализация параметров проекта",
            "curr_text": f"Анализ структуры видео и аудио:\n{os.path.basename(self.src_video_path)}...",
            "rem_text": "2. Оптимизация видеопотока (H.264/AAC)\n3. Создание структуры проекта",
            "speed_str": "—",
            "time_str": "00:00"
        })

        media_info = analyze_media(self.src_video_path, custom_ffprobe=self.config.ffprobe_path)
        total_dur = media_info.duration
        codec_name = (media_info.video_codec or "unknown").upper()
        needs_transcode = codec_name.lower() not in ("h264", "avc1")

        safe_name = "".join(c for c in self.project_name if c.isalnum() or c in (' ', '_', '-', '.')).strip()
        if not safe_name:
            safe_name = f"Project_{int(time.time())}"

        folder_path = os.path.join(self.project_mgr.projects_dir, safe_name)
        if os.path.exists(folder_path):
            folder_path = os.path.join(self.project_mgr.projects_dir, f"{safe_name}_{int(time.time())}")
        os.makedirs(folder_path, exist_ok=True)

        dest_video_name = "source_video.mp4"
        dest_video_path = os.path.join(folder_path, dest_video_name)

        if self.cancel_event.is_set() or self._is_cancelled:
            self.preparation_cancelled.emit()
            return

        mode_str = "Оптимизация видеоряда в эталонный H.264 (23.976/25 fps) и звука в AAC 48 кГц..." if needs_transcode else "Мгновенный побитовый перенос видео H.264 и нормализация звука в AAC..."

        def on_norm_progress(pct: float, speed: str, rem_time: str):
            if self.cancel_event.is_set() or self._is_cancelled:
                return
            scaled_pct = int(5 + (pct * 0.85))
            self.progress_updated.emit({
                "percent": min(92, max(5, scaled_pct)),
                "step_name": "Нормализация видео и звука для Gemini",
                "done_text": f"1. Анализ медиафайла ({codec_name}, {format_duration_sec(total_dur)})",
                "curr_text": f"{mode_str}\nСкорость: {speed}, осталось: {rem_time}",
                "rem_text": "3. Сохранение метаданных и открытие проекта",
                "speed_str": speed,
                "time_str": rem_time
            })

        norm_ok = normalize_video_container(
            input_path=self.src_video_path,
            output_path=dest_video_path,
            custom_ffmpeg=self.config.ffmpeg_path,
            custom_ffprobe=self.config.ffprobe_path,
            progress_callback=on_norm_progress,
            cancel_event=self.cancel_event,
            process_holder=self.process_holder
        )

        if self.cancel_event.is_set() or self._is_cancelled:
            self.preparation_cancelled.emit()
            return

        if not norm_ok or not os.path.isfile(dest_video_path):
            import shutil
            ext = os.path.splitext(self.src_video_path)[1] or ".mp4"
            dest_video_name = f"source_video{ext}"
            dest_video_path = os.path.join(folder_path, dest_video_name)
            if os.path.abspath(self.src_video_path) != os.path.abspath(dest_video_path):
                shutil.copy2(self.src_video_path, dest_video_path)

        self.progress_updated.emit({
            "percent": 95,
            "step_name": "Сохранение метаданных проекта",
            "done_text": "1. Анализ файла\n2. Оптимизация видеоконтейнера (H.264/AAC)",
            "curr_text": f"Формирование проекта «{self.project_name}»...",
            "rem_text": "Готово к работе",
            "speed_str": "—",
            "time_str": "00:00"
        })

        proj = Project(self.project_name, folder_path)
        proj.data["chunk_duration_minutes"] = self.chunk_min
        proj.data["src_video_path"] = dest_video_path
        proj.data["source_video_rel"] = os.path.basename(dest_video_path)
        proj.data["original_src_path"] = self.src_video_path

        norm_info = analyze_media(dest_video_path, custom_ffprobe=self.config.ffprobe_path)
        if norm_info.duration > 0:
            proj.data["total_duration_sec"] = round(norm_info.duration, 3)
        elif total_dur > 0:
            proj.data["total_duration_sec"] = round(total_dur, 3)

        proj.save()
        self.preparation_finished.emit(proj)



class VideoPreparationProgressDialog(QDialog):
    """
    Высококонтрастное доступное диалоговое окно подготовки и нормализации видео.
    """

    def __init__(
        self,
        project_mgr: ProjectManager,
        project_name: str,
        src_video_path: str,
        chunk_min: int,
        config,
        is_opening: bool = False,
        project_folder: str = "",
        parent=None
    ):
        super().__init__(parent)
        self.project_mgr = project_mgr
        self.project_name = project_name
        self.src_video_path = src_video_path
        self.chunk_min = chunk_min
        self.config = config
        self.is_opening = is_opening
        self.project_folder = project_folder

        self.result_project: Optional[Project] = None
        self.is_completed = False
        self.is_cancelled = False

        self.setWindowTitle("Подготовка и оптимизация видео — Тифлокомментатор")
        self.setAccessibleName("Окно оптимизации и подготовки видеофайла для анализа в Google Gemini")
        self.setAccessibleDescription("Окно отображает текущий процесс приведения видео и аудио к эталонному стандарту H.264 и AAC, что гарантирует точную синхронизацию тифлокомментариев.")
        self.setWindowModality(Qt.WindowModal)
        self.setMinimumWidth(680)
        self.setMinimumHeight(440)

        self.init_ui()
        self.start_worker()
    def init_ui(self):
        self.setStyleSheet("""
            QDialog {
                background-color: #0c1017;
                color: #FFFFFF;
                border: 2px solid #00FFFF;
            }
            QLabel {
                color: #FFFFFF;
            }
            QFrame#card_frame {
                background-color: #141a24;
                border: 2px solid #00FFFF;
                border-radius: 6px;
            }
            QProgressBar {
                border: 2px solid #00FFFF;
                border-radius: 4px;
                background-color: #05080c;
                text-align: center;
                color: #FFFFFF;
                font-size: 13px;
                font-weight: bold;
            }
            QProgressBar::chunk {
                background-color: #00E5FF;
            }
            QPushButton {
                background-color: #1a2332;
                color: #FFFFFF;
                border: 2px solid #00FFFF;
                border-radius: 4px;
                padding: 7px 16px;
                font-size: 13px;
                font-weight: bold;
            }
            QPushButton:hover {
                background-color: #00E5FF;
                color: #000000;
            }
            QPushButton:focus {
                border: 2px solid #FFFF00;
                background-color: #00E5FF;
                color: #000000;
            }
        """)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 16, 20, 16)
        layout.setSpacing(12)

        title_text = "⚙️ Оптимизация медиафайла для Gemini" if not self.is_opening else "⚙️ Проверка и нормализация видео проекта"
        self.lbl_title = QLabel(title_text, self)
        self.lbl_title.setStyleSheet("font-size: 17px; font-weight: bold; color: #00FFFF;")
        self.lbl_title.setAccessibleName(title_text)
        layout.addWidget(self.lbl_title)

        self.card_frame = QFrame(self)
        self.card_frame.setObjectName("card_frame")
        card_layout = QVBoxLayout(self.card_frame)
        card_layout.setContentsMargins(14, 12, 14, 12)
        card_layout.setSpacing(10)

        # 1. Что уже сделано
        self.lbl_head_done = QLabel("✅ Что уже сделано:", self.card_frame)
        self.lbl_head_done.setStyleSheet("font-weight: bold; font-size: 13px; color: #00FF66;")
        self.lbl_done_text = QLabel("Инициализация процесса подготовки...", self.card_frame)
        self.lbl_done_text.setStyleSheet("font-size: 12px; color: #DDDDDD;")
        self.lbl_done_text.setWordWrap(True)
        card_layout.addWidget(self.lbl_head_done)
        card_layout.addWidget(self.lbl_done_text)

        # 2. Текущий процесс
        self.lbl_head_curr = QLabel("⚙️ Текущий процесс:", self.card_frame)
        self.lbl_head_curr.setStyleSheet("font-weight: bold; font-size: 13px; color: #00E5FF;")
        self.lbl_curr_text = QLabel("Анализ технической структуры медиапотоков...", self.card_frame)
        self.lbl_curr_text.setStyleSheet("font-size: 13px; font-weight: bold; color: #FFFFFF;")
        self.lbl_curr_text.setWordWrap(True)
        card_layout.addWidget(self.lbl_head_curr)
        card_layout.addWidget(self.lbl_curr_text)

        # 3. Что осталось сделать
        self.lbl_head_rem = QLabel("⏳ Что осталось сделать:", self.card_frame)
        self.lbl_head_rem.setStyleSheet("font-weight: bold; font-size: 13px; color: #FFCC00;")
        self.lbl_rem_text = QLabel("Оптимизация видеоряда, сведение звука и запуск проекта", self.card_frame)
        self.lbl_rem_text.setStyleSheet("font-size: 12px; color: #DDDDDD;")
        self.lbl_rem_text.setWordWrap(True)
        card_layout.addWidget(self.lbl_head_rem)
        card_layout.addWidget(self.lbl_rem_text)

        layout.addWidget(self.card_frame)

        self.progress_bar = QProgressBar(self)
        self.progress_bar.setRange(0, 100)
        self.progress_bar.setValue(0)
        self.progress_bar.setAccessibleName("Индикатор общего прогресса нормализации видео")
        layout.addWidget(self.progress_bar)

        bottom_layout = QHBoxLayout()
        bottom_layout.setSpacing(10)

        self.lbl_stats = QLabel("Скорость: — | Осталось времени: —", self)
        self.lbl_stats.setStyleSheet("font-size: 12px; color: #AAAAAA; font-weight: bold;")
        self.lbl_stats.setAccessibleName("Скорость обработки и расчетное оставшееся время")
        bottom_layout.addWidget(self.lbl_stats)

        bottom_layout.addStretch(1)

        self.btn_cancel = QPushButton("Отмена", self)
        self.btn_cancel.setAccessibleName("Отменить подготовку видео")
        self.btn_cancel.setAccessibleDescription("Прерывает процесс нормализации видеофайла и закрывает окно")
        self.btn_cancel.clicked.connect(self.on_cancel_clicked)
        bottom_layout.addWidget(self.btn_cancel)

        layout.addLayout(bottom_layout)
        QShortcut(QKeySequence(Qt.Key_Escape), self, self.on_cancel_clicked)
    def start_worker(self):
        self.worker = VideoPreparationWorker(
            project_mgr=self.project_mgr,
            project_name=self.project_name,
            src_video_path=self.src_video_path,
            chunk_min=self.chunk_min,
            config=self.config,
            is_opening=self.is_opening,
            project_folder=self.project_folder,
            parent=self
        )
        self.worker.progress_updated.connect(self.on_progress_updated)
        self.worker.preparation_finished.connect(self.on_preparation_finished)
        self.worker.preparation_error.connect(self.on_preparation_error)
        self.worker.preparation_cancelled.connect(self.on_preparation_cancelled)
        self.worker.start()

    @Slot(dict)
    def on_progress_updated(self, data: dict):
        pct = data.get("percent", 0)
        self.progress_bar.setValue(pct)

        done_text = data.get("done_text", "")
        if done_text:
            self.lbl_done_text.setText(done_text)

        curr_text = data.get("curr_text", "")
        if curr_text:
            self.lbl_curr_text.setText(curr_text)

        rem_text = data.get("rem_text", "")
        if rem_text:
            self.lbl_rem_text.setText(rem_text)

        speed_str = data.get("speed_str", "—")
        time_str = data.get("time_str", "—")
        self.lbl_stats.setText(f"Скорость: {speed_str} | Осталось времени: {time_str}")

    @Slot(object)
    def on_preparation_finished(self, project: Project):
        self.is_completed = True
        self.result_project = project
        self.accept()

    @Slot(str)
    def on_preparation_error(self, err_msg: str):
        self.is_completed = True
        QMessageBox.critical(self, "Ошибка подготовки видео", f"Произошла ошибка при нормализации видеофайла:\n{err_msg}")
        self.reject()

    @Slot()
    def on_preparation_cancelled(self):
        self.is_cancelled = True
        self.reject()

    def on_cancel_clicked(self):
        if self.is_completed or self.is_cancelled:
            self.reject()
            return
        reply = QMessageBox.question(
            self, "Отмена подготовки видео",
            "Вы действительно хотите прервать процесс подготовки видеофайла?",
            QMessageBox.Yes | QMessageBox.No
        )
        if reply == QMessageBox.Yes:
            self.btn_cancel.setEnabled(False)
            self.btn_cancel.setText("Остановка...")
            self.lbl_curr_text.setText("Прерывание операции FFmpeg...")
            self.worker.cancel()

    def closeEvent(self, event):
        if not self.is_completed and not self.is_cancelled:
            self.on_cancel_clicked()
            event.ignore()
        else:
            event.accept()



