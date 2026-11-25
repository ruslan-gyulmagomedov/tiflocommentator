# -*- coding: utf-8 -*-
"""
Диалоговое окно и рабочий поток анализа выделенного фрагмента видео в Google Gemini.
"""

import os
import threading
import time
from typing import Dict, Any, List, Optional

from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QProgressBar, QMessageBox
)
from PySide6.QtCore import Qt, QThread, Signal, Slot

from core.gemini_client import GeminiClient, parse_time_to_seconds
from core.character_manager import CharacterManager
from core.video_splitter import extract_video_fragment


class FragmentGenerationWorker(QThread):
    """Фоновый рабочий поток для комментирования выделенного фрагмента видео."""

    progress_updated = Signal(dict)
    generation_finished = Signal(dict)
    generation_error = Signal(str)
    generation_cancelled = Signal()

    def __init__(self, project, config, start_sec: float, end_sec: float, fragment_prompt: str = "", parent=None):
        super().__init__(parent)
        self.project = project
        self.config = config
        self.start_sec = max(0.0, float(start_sec))
        self.end_sec = max(self.start_sec + 0.1, float(end_sec))
        self.fragment_prompt = fragment_prompt
        self.cancel_event = threading.Event()
        self._is_cancelled = False

    def cancel(self):
        self._is_cancelled = True
        self.cancel_event.set()

    def run(self):
        temp_frag_path = ""
        try:
            client = GeminiClient(self.config.api_key)
            char_mgr = CharacterManager(self.project)

            src_video = self.project.data.get("src_video_path", "")
            if not src_video or not os.path.isfile(src_video):
                src_video = os.path.join(self.project.folder_path, self.project.data.get("source_video_rel", "source_video.mp4"))

            if not os.path.isfile(src_video):
                self.generation_error.emit("Исходный видеофайл проекта не найден на диске!")
                return

            self.progress_updated.emit({
                "percent": 15,
                "message": "Вырезание выделенного видеофрагмента..."
            })

            frag_filename = f"frag_{int(self.start_sec*1000)}_{int(self.end_sec*1000)}.mp4"
            temp_frag_path = os.path.join(self.project.parts_dir, frag_filename)

            frag_info = {}
            ok_cut = extract_video_fragment(
                src_video_path=src_video,
                start_sec=self.start_sec,
                end_sec=self.end_sec,
                output_path=temp_frag_path,
                custom_ffmpeg=self.config.ffmpeg_path,
                custom_ffprobe=self.config.ffprobe_path,
                align_to_keyframes=True,
                info=frag_info
            )

            if not ok_cut or not os.path.isfile(temp_frag_path):
                self.generation_error.emit("Не удалось вырезать фрагмент видео для анализа.")
                return

            # -c copy может начать фрагмент только с ключевого кадра, поэтому
            # реальные границы могут отличаться от выделения на таймлайне.
            # Дальше везде используем фактические границы, иначе комментарии
            # поедут на величину сдвига.
            actual_start = float(frag_info.get("start_sec", self.start_sec))
            actual_end = float(frag_info.get("end_sec", self.end_sec))
            if actual_end <= actual_start:
                actual_end = actual_start + 0.1
            print(
                f"Фрагмент: выделено {self.start_sec:.3f}-{self.end_sec:.3f}, "
                f"вырезано {actual_start:.3f}-{actual_end:.3f}, "
                f"сдвиг начала {actual_start - self.start_sec:+.3f} с"
            )

            if self.cancel_event.is_set() or self._is_cancelled:
                self.generation_cancelled.emit()
                return

            def gen_cb(msg):
                if self.cancel_event.is_set() or self._is_cancelled:
                    return
                self.progress_updated.emit({"percent": 50, "message": msg})

            gen_cb("Загрузка видеофрагмента в Google Gemini...")

            res_data = client.generate_commentary_for_fragment(
                fragment_file_path=temp_frag_path,
                start_abs_sec=actual_start,
                end_abs_sec=actual_end,
                existing_characters=self.project.characters,
                fragment_prompt=self.fragment_prompt,
                model_name=self.config.gemini_model,
                progress_callback=gen_cb
            )

            if self.cancel_event.is_set() or self._is_cancelled:
                self.generation_cancelled.emit()
                return

            diag = res_data.get("diagnostics", {})
            if diag.get("video_status") == "missing":
                self.generation_error.emit("Ошибка: Видеоряд во фрагменте недоступен.")
                return

            chars = res_data.get("characters", [])
            comms = res_data.get("commentaries", [])
            frag_dur = max(0.1, actual_end - actual_start)

            for char_item in chars:
                raw_fts = char_item.get("frame_timestamp", char_item.get("frame_timestamp_sec", 0.0))
                char_item["frame_timestamp_sec"] = parse_time_to_seconds(raw_fts, max_duration=frag_dur)

            if chars:
                char_mgr.process_detected_characters(chars, temp_frag_path, actual_start)

            for c in comms:
                raw_start = c.get("start_time", c.get("start_time_sec", 0.0))
                raw_end = c.get("end_time", c.get("end_time_sec", 0.0))

                rel_start = parse_time_to_seconds(raw_start, max_duration=frag_dur)
                rel_end = parse_time_to_seconds(raw_end, max_duration=frag_dur)
                if rel_end <= rel_start:
                    rel_end = rel_start + 2.0

                c["start_time"] = round(actual_start + rel_start, 3)
                c["end_time"] = round(actual_start + rel_end, 3)
                c["duration_sec"] = round(c["end_time"] - c["start_time"], 3)
                c["audio_needs_rebuild"] = True

            self.project.add_commentaries(comms)
            self.project.save()

            self.generation_finished.emit({
                "comments_count": len(comms),
                "characters_count": len(chars),
                "requested_start_sec": round(self.start_sec, 3),
                "requested_end_sec": round(self.end_sec, 3),
                "actual_start_sec": round(actual_start, 3),
                "actual_end_sec": round(actual_end, 3)
            })

        except Exception as e:
            if self.cancel_event.is_set() or self._is_cancelled:
                self.generation_cancelled.emit()
            else:
                self.generation_error.emit(str(e))
        finally:
            if temp_frag_path and os.path.isfile(temp_frag_path):
                try:
                    os.remove(temp_frag_path)
                except Exception:
                    pass


class FragmentGenerationProgressDialog(QDialog):
    """Диалог прогресса комментирования выделенного фрагмента."""

    def __init__(self, project, config, start_sec: float, end_sec: float, fragment_prompt: str = "", parent=None):
        super().__init__(parent)
        self.project = project
        self.config = config
        self.start_sec = start_sec
        self.end_sec = end_sec
        self.fragment_prompt = fragment_prompt
        self.is_completed = False
        self.result_info = {}

        self.setWindowTitle("Комментирование выделенного фрагмента — Google Gemini")
        self.setAccessibleName("Окно прогресса анализа выделенного фрагмента видео")
        self.setWindowModality(Qt.WindowModal)
        self.resize(600, 260)

        self.init_ui()
        self.start_worker()

    def init_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(12)

        self.lbl_title = QLabel("🤖 Анализ выделенного фрагмента в Gemini", self)
        self.lbl_title.setStyleSheet("font-size: 15px; font-weight: bold; color: #00FFCC;")
        layout.addWidget(self.lbl_title)

        self.progress_bar = QProgressBar(self)
        self.progress_bar.setRange(0, 100)
        self.progress_bar.setValue(10)
        self.progress_bar.setTextVisible(True)
        self.progress_bar.setStyleSheet(
            "QProgressBar { height: 24px; border: 1px solid #555; border-radius: 4px; text-align: center; color: #FFFFFF; background-color: #222; } "
            "QProgressBar::chunk { background-color: #00AA77; }"
        )
        layout.addWidget(self.progress_bar)

        self.lbl_status = QLabel("Подготовка фрагмента к отправке...", self)
        self.lbl_status.setWordWrap(True)
        self.lbl_status.setStyleSheet("font-size: 13px; color: #FFFFFF; padding: 6px; background-color: #1a1a1a; border-radius: 4px;")
        layout.addWidget(self.lbl_status)

        btn_layout = QHBoxLayout()
        btn_layout.addStretch(1)
        self.btn_cancel = QPushButton("Отмена (Esc)", self)
        self.btn_cancel.setStyleSheet(
            "QPushButton { font-size: 13px; padding: 6px 18px; min-height: 32px; background-color: #442222; color: #FFFFFF; border: 1px solid #883333; border-radius: 4px; } "
            "QPushButton:hover { background-color: #662222; }"
        )
        self.btn_cancel.clicked.connect(self.on_cancel_clicked)
        btn_layout.addWidget(self.btn_cancel)
        layout.addLayout(btn_layout)

    def start_worker(self):
        self.worker = FragmentGenerationWorker(
            project=self.project,
            config=self.config,
            start_sec=self.start_sec,
            end_sec=self.end_sec,
            fragment_prompt=self.fragment_prompt,
            parent=self
        )
        self.worker.progress_updated.connect(self.on_progress)
        self.worker.generation_finished.connect(self.on_finished)
        self.worker.generation_error.connect(self.on_error)
        self.worker.generation_cancelled.connect(self.on_cancelled)
        self.worker.start()

    @Slot(dict)
    def on_progress(self, data: dict):
        pct = data.get("percent", 50)
        self.progress_bar.setValue(pct)
        msg = data.get("message", "")
        self.lbl_status.setText(msg)

    @Slot(dict)
    def on_finished(self, res: dict):
        self.is_completed = True
        self.result_info = res
        self.progress_bar.setValue(100)
        comms_cnt = res.get("comments_count", 0)
        chars_cnt = res.get("characters_count", 0)

        def _hms(sec: float) -> str:
            total = max(0, int(round(sec)))
            h, rem = divmod(total, 3600)
            m, s = divmod(rem, 60)
            return f"{h:02d}:{m:02d}:{s:02d}"

        bounds_note = ""
        try:
            req_s = float(res.get("requested_start_sec", self.start_sec))
            req_e = float(res.get("requested_end_sec", self.end_sec))
            act_s = float(res.get("actual_start_sec", req_s))
            act_e = float(res.get("actual_end_sec", req_e))
            if abs(act_s - req_s) > 0.05 or abs(act_e - req_e) > 0.05:
                bounds_note = (
                    f"\nГраницы фрагмента выровнены по ключевым кадрам:\n"
                    f"выделено {_hms(req_s)}–{_hms(req_e)}, "
                    f"обработано {_hms(act_s)}–{_hms(act_e)}.\n"
                )
        except Exception:
            bounds_note = ""

        QMessageBox.information(
            self, "Анализ фрагмента завершен",
            f"Фрагмент успешно проанализирован!\n\n"
            f"Создано комментариев: {comms_cnt}\n"
            f"Новых персонажей: {chars_cnt}{bounds_note}"
        )
        self.accept()

    @Slot(str)
    def on_error(self, err_msg: str):
        QMessageBox.critical(self, "Ошибка анализа фрагмента", f"Произошла ошибка:\n{err_msg}")
        self.reject()

    @Slot()
    def on_cancelled(self):
        QMessageBox.information(self, "Отмена", "Анализ фрагмента был отменен.")
        self.reject()

    def on_cancel_clicked(self):
        if self.worker.isRunning():
            self.btn_cancel.setEnabled(False)
            self.lbl_status.setText("Отмена анализа...")
            self.worker.cancel()
        else:
            self.reject()

    def closeEvent(self, event):
        if self.worker.isRunning() and not self.is_completed:
            self.worker.cancel()
            self.worker.wait(2000)
        event.accept()
