# -*- coding: utf-8 -*-
"""
Диалоговое окно фонового экспорта проекта в MKV:
- Асинхронное выполнение в отдельном потоке QThread (без зависания GUI и без статуса «Не отвечает»)
- Полная адаптация под режим высокой контрастности Windows (High Contrast)
- Чёткое разделение: «Что уже сделано», «Текущий процесс» и «Что осталось сделать»
- Кнопка мгновенной отмены экспорта с корректным завершением FFmpeg
- Полная доступность для программ экранного доступа NVDA / JAWS
"""

import os
import subprocess
import threading
import time
from typing import Dict, Any, Optional

from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QProgressBar, QFrame, QMessageBox, QApplication
)
from PySide6.QtCore import Qt, QThread, Signal, Slot, QUrl
from PySide6.QtGui import QFont, QDesktopServices, QKeySequence, QShortcut

from core.mkv_exporter import export_project_to_mkv
from core.audio_dsp import render_master_audio_track, format_duration_sec


class MKVExportWorker(QThread):
    """Фоновый рабочий поток для экспорта фильма в MKV."""

    progress_updated = Signal(dict)
    export_finished = Signal(str)
    export_error = Signal(str)
    export_cancelled = Signal()

    def __init__(self, project, output_path: str, config, parent=None):
        super().__init__(parent)
        self.project = project
        self.output_path = output_path
        self.config = config
        self.cancel_event = threading.Event()
        self.process_holder = []
        self._is_cancelled = False

    def cancel(self):
        """Отменяет экспорт и прерывает выполняющийся процесс FFmpeg."""
        self._is_cancelled = True
        self.cancel_event.set()
        if self.process_holder:
            try:
                proc = self.process_holder[0]
                proc.terminate()
                proc.wait(timeout=1.5)
            except Exception:
                try:
                    proc.kill()
                except Exception:
                    pass

    def run(self):
        try:
            def on_progress(data: dict):
                if self.cancel_event.is_set():
                    return
                self.progress_updated.emit(data)

            success = export_project_to_mkv(
                project=self.project,
                output_mkv_path=self.output_path,
                config=self.config,
                progress_callback=on_progress,
                cancel_event=self.cancel_event,
                process_holder=self.process_holder
            )

            if self.cancel_event.is_set() or self._is_cancelled:
                self.export_cancelled.emit()
            elif success:
                self.export_finished.emit(self.output_path)
            else:
                self.export_error.emit("Экспорт был остановлен или завершился с ошибкой.")

        except Exception as e:
            if self.cancel_event.is_set() or self._is_cancelled:
                self.export_cancelled.emit()
            else:
                self.export_error.emit(str(e))



class MKVExportProgressDialog(QDialog):
    """
    Высококонтрастное доступное диалоговое окно прогресса экспорта фильма в MKV.
    """

    def __init__(self, project, output_path: str, config, parent=None):
        super().__init__(parent)
        self.project = project
        self.output_path = output_path
        self.config = config
        self.start_time = time.time()
        self.is_completed = False
        self.is_cancelled = False

        self.setWindowTitle("Экспорт проекта в MKV — Тифлокомментатор")
        self.setAccessibleName("Окно индикации экспорта фильма в формат MKV")
        self.setAccessibleDescription("Окно отображает текущий этап создания видеофайла, сделанные шаги и оставшиеся задачи.")
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
                background-color: #004d40;
                border-color: #FFFF00;
            }
            QPushButton:focus {
                border: 2px solid #FFFF00;
                outline: none;
            }
            QPushButton#btn_cancel {
                border: 2px solid #FF5555;
                color: #FFFFFF;
                background-color: #331111;
            }
            QPushButton#btn_cancel:hover {
                background-color: #661111;
                border-color: #FFFF00;
            }
            QPushButton#btn_done {
                border: 2px solid #00FF66;
                color: #FFFFFF;
                background-color: #0d381e;
            }
            QPushButton#btn_done:hover {
                background-color: #155c32;
                border-color: #FFFF00;
            }
        """)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(18, 18, 18, 18)
        layout.setSpacing(12)

        lbl_title = QLabel(f"🎬 Экспорт проекта: «{self.project.name}»", self)
        lbl_title.setStyleSheet("font-size: 16px; font-weight: bold; color: #00FFFF;")
        lbl_title.setAccessibleName(f"Экспорт фильма {self.project.name}")
        layout.addWidget(lbl_title)

        lbl_out = QLabel(f"<b>Файл назначения:</b> {self.output_path}", self)
        lbl_out.setStyleSheet("font-size: 12px; color: #DDDDDD;")
        lbl_out.setWordWrap(True)
        layout.addWidget(lbl_out)

        card_frame = QFrame(self)
        card_frame.setObjectName("card_frame")
        card_layout = QVBoxLayout(card_frame)
        card_layout.setContentsMargins(14, 12, 14, 12)
        card_layout.setSpacing(10)

        # 1. Сделано
        self.lbl_head_done = QLabel("✅ Что уже сделано:", card_frame)
        self.lbl_head_done.setStyleSheet("font-weight: bold; font-size: 13px; color: #00FF66;")
        card_layout.addWidget(self.lbl_head_done)

        self.lbl_done_text = QLabel("Инициализация процесса экспорта...", card_frame)
        self.lbl_done_text.setStyleSheet("font-size: 12px; color: #AAFFAA; padding-left: 8px;")
        self.lbl_done_text.setWordWrap(True)
        self.lbl_done_text.setAccessibleName("Список выполненных шагов экспорта")
        card_layout.addWidget(self.lbl_done_text)

        sep1 = QFrame(card_frame)
        sep1.setFrameShape(QFrame.HLine)
        sep1.setStyleSheet("color: #334455;")
        card_layout.addWidget(sep1)

        # 2. Выполняется сейчас
        self.lbl_head_curr = QLabel("⚙️ Текущий процесс:", card_frame)
        self.lbl_head_curr.setStyleSheet("font-weight: bold; font-size: 13px; color: #FFD700;")
        card_layout.addWidget(self.lbl_head_curr)

        self.lbl_curr_text = QLabel("Подготовка к экспорту...", card_frame)
        self.lbl_curr_text.setStyleSheet("font-size: 13px; font-weight: bold; color: #00FFFF; padding-left: 8px;")
        self.lbl_curr_text.setWordWrap(True)
        self.lbl_curr_text.setAccessibleName("Текущая выполняемая операция экспорта")
        card_layout.addWidget(self.lbl_curr_text)

        sep2 = QFrame(card_frame)
        sep2.setFrameShape(QFrame.HLine)
        sep2.setStyleSheet("color: #334455;")
        card_layout.addWidget(sep2)

        # 3. Осталось сделать
        self.lbl_head_rem = QLabel("⏳ Что осталось сделать:", card_frame)
        self.lbl_head_rem.setStyleSheet("font-weight: bold; font-size: 13px; color: #FFAA55;")
        card_layout.addWidget(self.lbl_head_rem)

        self.lbl_rem_text = QLabel("1. Генерация субтитров SRT\n2. Сведение и компрессия звука\n3. Сборка MKV", card_frame)
        self.lbl_rem_text.setStyleSheet("font-size: 12px; color: #B0C4DE; padding-left: 8px;")
        self.lbl_rem_text.setWordWrap(True)
        self.lbl_rem_text.setAccessibleName("Оставшиеся этапы экспорта")
        card_layout.addWidget(self.lbl_rem_text)

        layout.addWidget(card_frame)

        # Линейка прогресса
        self.progress_bar = QProgressBar(self)
        self.progress_bar.setRange(0, 100)
        self.progress_bar.setValue(0)
        self.progress_bar.setFixedHeight(30)
        self.progress_bar.setFormat("%p% — Экспорт в процессе")
        self.progress_bar.setAccessibleName("Индикатор общего прогресса экспорта в процентах")
        layout.addWidget(self.progress_bar)

        # Статистика времени и скорости
        self.lbl_stats = QLabel("Прошло времени: 00:00 | Скорость: —", self)
        self.lbl_stats.setStyleSheet("font-size: 12px; color: #FFCC00; font-weight: bold;")
        self.lbl_stats.setAccessibleName("Статистика времени и скорости экспорта")
        layout.addWidget(self.lbl_stats)

        # Кнопки управления
        btn_layout = QHBoxLayout()
        btn_layout.setSpacing(10)

        self.btn_open_folder = QPushButton("📂 Открыть папку с фильмом", self)
        self.btn_open_folder.setAccessibleName("Открыть папку с экспортированным видеофайлом")
        self.btn_open_folder.clicked.connect(self.open_output_folder)
        self.btn_open_folder.hide()
        btn_layout.addWidget(self.btn_open_folder)

        btn_layout.addStretch(1)

        self.btn_cancel = QPushButton("❌ Прервать экспорт (Отмена)", self)
        self.btn_cancel.setObjectName("btn_cancel")
        self.btn_cancel.setAccessibleName("Прервать экспорт фильма и закрыть окно")
        self.btn_cancel.clicked.connect(self.request_cancel)
        btn_layout.addWidget(self.btn_cancel)

        self.btn_close = QPushButton("Готово (Закрыть)", self)
        self.btn_close.setObjectName("btn_done")
        self.btn_close.setAccessibleName("Закрыть окно после успешного экспорта")
        self.btn_close.clicked.connect(self.accept)
        self.btn_close.hide()
        btn_layout.addWidget(self.btn_close)

        layout.addLayout(btn_layout)

        esc_shortcut = QShortcut(QKeySequence(Qt.Key_Escape), self)
        esc_shortcut.activated.connect(self.on_escape_pressed)

    def start_worker(self):
        """Запускает фоновый поток экспорта."""
        self.worker = MKVExportWorker(self.project, self.output_path, self.config, self)
        self.worker.progress_updated.connect(self.on_progress_updated)
        self.worker.export_finished.connect(self.on_export_finished)
        self.worker.export_error.connect(self.on_export_error)
        self.worker.export_cancelled.connect(self.on_export_cancelled)
        self.worker.start()

    @Slot(dict)
    def on_progress_updated(self, data: dict):
        """Обновляет индикацию при получении данных от фонового потока."""
        if self.is_completed or self.is_cancelled:
            return

        pct = data.get("overall_pct", 0.0)
        self.progress_bar.setValue(int(pct))
        self.progress_bar.setFormat(f"{pct:.1f}% — {data.get('step_name', '')}")

        done_txt = data.get("done_text", "")
        if done_txt:
            self.lbl_done_text.setText(done_txt)

        curr_txt = data.get("current_text", "")
        if curr_txt:
            self.lbl_curr_text.setText(curr_txt)

        rem_txt = data.get("remaining_text", "")
        if rem_txt:
            self.lbl_rem_text.setText(rem_txt)

        elapsed_sec = int(time.time() - self.start_time)
        el_m, el_s = divmod(elapsed_sec, 60)
        speed = data.get("speed_str", "—")
        self.lbl_stats.setText(f"Прошло времени: {el_m:02d}:{el_s:02d} | Скорость обработки: {speed}")



    @Slot(str)
    def on_export_finished(self, out_path: str):
        """Обрабатывает успешное завершение экспорта."""
        self.is_completed = True
        self.progress_bar.setValue(100)
        self.progress_bar.setFormat("100% — Экспорт успешно завершен!")

        self.lbl_head_curr.setText("✅ Статус:")
        self.lbl_head_curr.setStyleSheet("font-weight: bold; font-size: 13px; color: #00FF66;")
        self.lbl_curr_text.setText(f"Видеофайл успешно экспортирован:\n{out_path}")
        self.lbl_curr_text.setStyleSheet("font-size: 13px; font-weight: bold; color: #AAFFAA; padding-left: 8px;")

        self.lbl_rem_text.setText("Все задачи выполнены. Файл готов к просмотру.")

        elapsed_sec = int(time.time() - self.start_time)
        el_m, el_s = divmod(elapsed_sec, 60)
        self.lbl_stats.setText(f"Общее время экспорта: {el_m:02d}:{el_s:02d}")

        self.btn_cancel.hide()
        self.btn_open_folder.show()
        self.btn_close.show()
        self.btn_close.setFocus()

        QApplication.beep()

    @Slot(str)
    def on_export_error(self, err_msg: str):
        """Обрабатывает ошибку экспорта."""
        self.is_completed = True
        self.progress_bar.setFormat("Ошибка экспорта")
        self.lbl_curr_text.setText(f"Ошибка:\n{err_msg}")
        self.lbl_curr_text.setStyleSheet("font-size: 13px; font-weight: bold; color: #FF5555; padding-left: 8px;")
        self.btn_cancel.setText("Закрыть")
        QMessageBox.critical(self, "Ошибка экспорта", f"Не удалось завершить экспорт видео:\n{err_msg}")

    @Slot()
    def on_export_cancelled(self):
        """Обрабатывает факт отмены экспорта."""
        self.is_cancelled = True
        self.progress_bar.setFormat("Экспорт прерван пользователем")
        self.lbl_curr_text.setText("Экспорт был отменен. Временные файлы удалены.")
        self.lbl_curr_text.setStyleSheet("font-size: 13px; font-weight: bold; color: #FF8888; padding-left: 8px;")
        self.btn_cancel.setText("Закрыть")
        self.reject()

    def request_cancel(self):
        """Запрашивает подтверждение и выполняет отмену экспорта."""
        if self.is_completed or self.is_cancelled:
            self.reject()
            return

        reply = QMessageBox.question(
            self,
            "Подтверждение отмены",
            "Вы действительно хотите прервать экспорт видеофайла?",
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No
        )
        if reply == QMessageBox.Yes:
            self.btn_cancel.setEnabled(False)
            self.btn_cancel.setText("Прерывание...")
            self.lbl_curr_text.setText("Остановка процессов FFmpeg и очистка временных данных...")
            self.worker.cancel()

    def on_escape_pressed(self):
        """Обработка клавиши Esc."""
        if self.is_completed:
            self.accept()
        else:
            self.request_cancel()

    def open_output_folder(self):
        """Открывает папку с сохраненным видеофайлом."""
        folder = os.path.dirname(os.path.abspath(self.output_path))
        if os.path.isdir(folder):
            QDesktopServices.openUrl(QUrl.fromLocalFile(folder))

    def closeEvent(self, event):
        """Контролирует закрытие окна через системную кнопку крестика."""
        if self.is_completed or self.is_cancelled:
            event.accept()
        else:
            self.request_cancel()
            event.ignore()



class AudioExportWorker(QThread):
    """Фоновый рабочий поток для экспорта сведенного мастер-аудио в MP3 или WAV."""

    progress_updated = Signal(dict)
    export_finished = Signal(str)
    export_error = Signal(str)
    export_cancelled = Signal()

    def __init__(self, project, output_path: str, config, parent=None):
        super().__init__(parent)
        self.project = project
        self.output_path = output_path
        self.config = config
        self.cancel_event = threading.Event()
        self.process_holder = []
        self._is_cancelled = False

    def cancel(self):
        self._is_cancelled = True
        self.cancel_event.set()
        if self.process_holder:
            try:
                proc = self.process_holder[0]
                proc.terminate()
                proc.wait(timeout=1.5)
            except Exception:
                try:
                    proc.kill()
                except Exception:
                    pass

    def run(self):
        try:
            start_t = time.time()
            total_dur_sec = float(self.project.data.get("total_duration_sec", 0.0))
            num_comms = len(self.project.commentaries)
            ext_name = os.path.splitext(self.output_path)[1].upper().replace(".", "")

            def emit_prog(data: dict):
                if not self.cancel_event.is_set():
                    self.progress_updated.emit(data)

            emit_prog({
                "step": 1,
                "total_steps": 1,
                "overall_pct": 0.0,
                "step_name": f"Сведение аудио ({ext_name})",
                "done_text": "Инициализация сведения мастер-звука...",
                "current_text": f"Сведение дорожки фильма и {num_comms} комментариев под компрессором...",
                "remaining_text": f"Экспорт в файл {ext_name}",
                "speed_str": "—",
                "time_str": "00:00"
            })

            def audio_prog_cb(frac: float, cur_str: str, speed_str: str):
                if self.cancel_event.is_set():
                    return
                elapsed = time.time() - start_t
                time_str = format_duration_sec(elapsed)
                pct = round(frac * 100.0, 1)
                emit_prog({
                    "step": 1,
                    "total_steps": 1,
                    "overall_pct": pct,
                    "step_name": f"Сведение аудио ({ext_name})",
                    "done_text": f"Обработано аудио: {cur_str}",
                    "current_text": f"Кодирование мастер-трека в {ext_name} (скорость {speed_str})...",
                    "remaining_text": "Завершение записи аудиофайла",
                    "speed_str": speed_str,
                    "time_str": time_str
                })

            valid_comms = [
                c for c in self.project.commentaries
                if c.get("audio_file") and os.path.isfile(c.get("audio_file")) and not c.get("audio_needs_rebuild", False)
            ]

            src_video = self.project.video_path if hasattr(self.project, "video_path") and self.project.video_path else self.project.data.get("src_video_path", "")
            ok = render_master_audio_track(
                source_video_or_audio=src_video,
                commentaries_with_audio=valid_comms,
                output_audio_path=self.output_path,
                movie_vol_db=self.config.movie_volume_db,
                comm_vol_db=self.config.commentary_volume_db,
                movie_muted=self.config.movie_muted,
                comm_muted=self.config.commentary_muted,
                auto_ducking=self.config.auto_ducking,
                ducking_db=self.config.ducking_level_db,
                ducking_attack_ms=self.config.ducking_attack_ms,
                ducking_release_ms=self.config.ducking_release_ms,
                comp_threshold_db=self.config.compressor_threshold_db,
                comp_lookahead_ms=self.config.compressor_lookahead_ms,
                comp_release_ms=self.config.compressor_release_ms,
                custom_ffmpeg=self.config.ffmpeg_path,
                total_duration_sec=total_dur_sec,
                progress_callback=audio_prog_cb,
                cancel_event=self.cancel_event,
                process_holder=self.process_holder
            )

            if self.cancel_event.is_set() or self._is_cancelled:
                self.export_cancelled.emit()
            elif ok and os.path.isfile(self.output_path):
                elapsed = time.time() - start_t
                emit_prog({
                    "step": 1,
                    "total_steps": 1,
                    "overall_pct": 100.0,
                    "step_name": "Экспорт завершен",
                    "done_text": f"✓ Мастер-аудиодорожка успешно сведена ({num_comms} комментариев)",
                    "current_text": f"Файл успешно сохранен:\n{self.output_path}",
                    "remaining_text": "Все этапы завершены",
                    "speed_str": "—",
                    "time_str": format_duration_sec(elapsed)
                })
                self.export_finished.emit(self.output_path)
            else:
                self.export_error.emit("Экспорт аудио был остановлен или завершился с ошибкой.")
        except Exception as e:
            if self.cancel_event.is_set() or self._is_cancelled:
                self.export_cancelled.emit()
            else:
                self.export_error.emit(str(e))


class AudioExportProgressDialog(QDialog):
    """Высококонтрастное диалоговое окно прогресса экспорта мастер-аудио (MP3 / WAV)."""

    def __init__(self, project, output_path: str, config, parent=None):
        super().__init__(parent)
        self.project = project
        self.output_path = output_path
        self.config = config
        self.start_time = time.time()
        self.is_completed = False
        self.is_cancelled = False

        ext = os.path.splitext(output_path)[1].upper().replace(".", "")
        self.setWindowTitle(f"Экспорт аудио ({ext}) — Тифлокомментатор")
        self.setAccessibleName(f"Окно индикации экспорта аудиофайла в формат {ext}")
        self.setAccessibleDescription("Окно отображает текущий этап сведения аудиодорожки и прогресс кодирования.")
        self.setWindowModality(Qt.WindowModal)
        self.setMinimumWidth(680)
        self.setMinimumHeight(380)

        self.init_ui()
        self.start_worker()

    def init_ui(self):
        self.setStyleSheet("""
            QDialog { background-color: #0c1017; color: #FFFFFF; border: 2px solid #00FFCC; }
            QLabel { color: #FFFFFF; }
            QFrame#card_frame { background-color: #141a24; border: 2px solid #00FFCC; border-radius: 6px; }
            QProgressBar { border: 2px solid #00FFCC; border-radius: 4px; background-color: #05080c; text-align: center; color: #FFFFFF; font-size: 13px; font-weight: bold; }
            QProgressBar::chunk { background-color: #00FFCC; }
            QPushButton { background-color: #1a2332; color: #FFFFFF; border: 2px solid #00FFCC; border-radius: 4px; padding: 7px 16px; font-size: 13px; font-weight: bold; }
            QPushButton:hover { background-color: #004d40; border-color: #FFFF00; }
            QPushButton:focus { border: 2px solid #FFFF00; outline: none; }
            QPushButton#btn_cancel { border: 2px solid #FF5555; color: #FFFFFF; background-color: #331111; }
            QPushButton#btn_cancel:hover { background-color: #661111; border-color: #FFFF00; }
            QPushButton#btn_done { border: 2px solid #00FF66; color: #FFFFFF; background-color: #0d381e; }
            QPushButton#btn_done:hover { background-color: #155c32; border-color: #FFFF00; }
        """)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(18, 18, 18, 18)
        layout.setSpacing(12)

        lbl_title = QLabel(f"🎵 Экспорт мастер-аудио: «{self.project.name}»", self)
        lbl_title.setStyleSheet("font-size: 15px; font-weight: bold; color: #00FFCC;")
        layout.addWidget(lbl_title)

        lbl_out = QLabel(f"<b>Файл назначения:</b> {self.output_path}", self)
        lbl_out.setStyleSheet("font-size: 12px; color: #DDDDDD;")
        lbl_out.setWordWrap(True)
        layout.addWidget(lbl_out)

        card_frame = QFrame(self)
        card_frame.setObjectName("card_frame")
        card_layout = QVBoxLayout(card_frame)
        card_layout.setContentsMargins(14, 12, 14, 12)
        card_layout.setSpacing(10)

        self.lbl_head_curr = QLabel("⚙️ Текущий процесс:", card_frame)
        self.lbl_head_curr.setStyleSheet("font-weight: bold; font-size: 13px; color: #FFD700;")
        card_layout.addWidget(self.lbl_head_curr)

        self.lbl_curr_text = QLabel("Подготовка аудиофайлов комментария и фильма...", card_frame)
        self.lbl_curr_text.setStyleSheet("font-size: 13px; font-weight: bold; color: #00FFCC; padding-left: 8px;")
        self.lbl_curr_text.setWordWrap(True)
        self.lbl_curr_text.setAccessibleName("Текущая операция экспорта аудио")
        card_layout.addWidget(self.lbl_curr_text)

        sep = QFrame(card_frame)
        sep.setFrameShape(QFrame.HLine)
        sep.setStyleSheet("color: #334455;")
        card_layout.addWidget(sep)

        self.lbl_head_done = QLabel("✅ Статус:", card_frame)
        self.lbl_head_done.setStyleSheet("font-weight: bold; font-size: 13px; color: #00FF66;")
        card_layout.addWidget(self.lbl_head_done)

        self.lbl_done_text = QLabel("Инициализация сведения мастер-звука...", card_frame)
        self.lbl_done_text.setStyleSheet("font-size: 12px; color: #AAFFAA; padding-left: 8px;")
        self.lbl_done_text.setWordWrap(True)
        self.lbl_done_text.setAccessibleName("Статус сведения аудио")
        self.progress_bar = QProgressBar(self)
        self.progress_bar.setRange(0, 100)
        self.progress_bar.setValue(0)
        self.progress_bar.setFixedHeight(30)
        self.progress_bar.setFormat("%p% — Экспорт аудио")
        self.progress_bar.setAccessibleName("Индикатор общего прогресса экспорта аудио в процентах")
        layout.addWidget(self.progress_bar)

        self.lbl_stats = QLabel("Прошло времени: 00:00 | Скорость: —", self)
        self.lbl_stats.setStyleSheet("font-size: 12px; color: #FFCC00; font-weight: bold;")
        self.lbl_stats.setAccessibleName("Статистика времени и скорости экспорта аудио")
        layout.addWidget(self.lbl_stats)

        btn_layout = QHBoxLayout()
        btn_layout.setSpacing(10)

        self.btn_open_folder = QPushButton("📂 Открыть папку с аудио", self)
        self.btn_open_folder.setAccessibleName("Открыть папку с экспортированным аудиофайлом")
        self.btn_open_folder.clicked.connect(self.open_output_folder)
        self.btn_open_folder.hide()
        btn_layout.addWidget(self.btn_open_folder)

        btn_layout.addStretch(1)

        self.btn_cancel = QPushButton("❌ Прервать экспорт (Отмена)", self)
        self.btn_cancel.setObjectName("btn_cancel")
        self.btn_cancel.setAccessibleName("Прервать экспорт аудиофайла и закрыть окно")
        self.btn_cancel.clicked.connect(self.request_cancel)
        btn_layout.addWidget(self.btn_cancel)

        self.btn_close = QPushButton("Готово (Закрыть)", self)
        self.btn_close.setObjectName("btn_done")
        self.btn_close.setAccessibleName("Закрыть окно после успешного экспорта")
        self.btn_close.clicked.connect(self.accept)
        self.btn_close.hide()
        btn_layout.addWidget(self.btn_close)

        layout.addLayout(btn_layout)

        esc_shortcut = QShortcut(QKeySequence(Qt.Key_Escape), self)
        esc_shortcut.activated.connect(self.on_escape_pressed)

    def start_worker(self):
        self.worker = AudioExportWorker(self.project, self.output_path, self.config, self)
        self.worker.progress_updated.connect(self.on_progress_updated)
        self.worker.export_finished.connect(self.on_export_finished)
        self.worker.export_error.connect(self.on_export_error)
        self.worker.export_cancelled.connect(self.on_export_cancelled)
        self.worker.start()

    @Slot(dict)
    def on_progress_updated(self, data: dict):
        if self.is_completed or self.is_cancelled:
            return
        pct = data.get("overall_pct", 0.0)
        self.progress_bar.setValue(int(pct))
        self.progress_bar.setFormat(f"{pct:.1f}% — {data.get('step_name', '')}")

        done_txt = data.get("done_text", "")
        if done_txt:
            self.lbl_done_text.setText(done_txt)

        curr_txt = data.get("current_text", "")
        if curr_txt:
            self.lbl_curr_text.setText(curr_txt)

        elapsed_sec = int(time.time() - self.start_time)
        el_m, el_s = divmod(elapsed_sec, 60)
        speed = data.get("speed_str", "—")
        self.lbl_stats.setText(f"Прошло времени: {el_m:02d}:{el_s:02d} | Скорость обработки: {speed}")

    @Slot(str)
    def on_export_finished(self, out_path: str):
        self.is_completed = True
        self.progress_bar.setValue(100)
        self.progress_bar.setFormat("100% — Экспорт аудио успешно завершен!")

        self.lbl_head_curr.setText("✅ Статус:")
        self.lbl_head_curr.setStyleSheet("font-weight: bold; font-size: 13px; color: #00FF66;")
        self.lbl_curr_text.setText(f"Аудиофайл успешно экспортирован:\n{out_path}")
        self.lbl_curr_text.setStyleSheet("font-size: 13px; font-weight: bold; color: #AAFFAA; padding-left: 8px;")

        elapsed_sec = int(time.time() - self.start_time)
        el_m, el_s = divmod(elapsed_sec, 60)
        self.lbl_stats.setText(f"Общее время экспорта: {el_m:02d}:{el_s:02d}")

        self.btn_cancel.hide()
        self.btn_open_folder.show()
        self.btn_close.show()
        self.btn_close.setFocus()

        QApplication.beep()

    @Slot(str)
    def on_export_error(self, err_msg: str):
        self.is_completed = True
        self.progress_bar.setFormat("Ошибка экспорта")
        self.lbl_curr_text.setText(f"Ошибка:\n{err_msg}")
        self.lbl_curr_text.setStyleSheet("font-size: 13px; font-weight: bold; color: #FF5555; padding-left: 8px;")
        self.btn_cancel.setText("Закрыть")
        QMessageBox.critical(self, "Ошибка экспорта", f"Не удалось экспортировать аудио:\n{err_msg}")

    @Slot()
    def on_export_cancelled(self):
        self.is_cancelled = True
        self.progress_bar.setFormat("Экспорт прерван пользователем")
        self.lbl_curr_text.setText("Экспорт аудио был отменен.")
        self.lbl_curr_text.setStyleSheet("font-size: 13px; font-weight: bold; color: #FF8888; padding-left: 8px;")
        self.btn_cancel.setText("Закрыть")
        self.reject()

    def request_cancel(self):
        if self.is_completed or self.is_cancelled:
            self.reject()
            return

        reply = QMessageBox.question(
            self,
            "Подтверждение отмены",
            "Вы действительно хотите прервать экспорт аудиофайла?",
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No
        )
        if reply == QMessageBox.Yes:
            self.btn_cancel.setEnabled(False)
            self.btn_cancel.setText("Прерывание...")
            self.lbl_curr_text.setText("Остановка процессов FFmpeg...")
            self.worker.cancel()

    def on_escape_pressed(self):
        if self.is_completed:
            self.accept()
        else:
            self.request_cancel()

    def open_output_folder(self):
        folder = os.path.dirname(os.path.abspath(self.output_path))
        if os.path.isdir(folder):
            QDesktopServices.openUrl(QUrl.fromLocalFile(folder))

    def closeEvent(self, event):
        if self.is_completed or self.is_cancelled:
            event.accept()
        else:
            self.request_cancel()
            event.ignore()


