# -*- coding: utf-8 -*-
"""
Диалоговое окно фоновой генерации тифлокомментариев с помощью Google Gemini:
- Асинхронное выполнение в отдельном потоке QThread (без зависания GUI и без статуса «Не отвечает»)
- Полная адаптация под режим высокой контрастности Windows (High Contrast)
- Чёткое разделение: «Что уже сделано», «Текущий процесс» и «Что осталось сделать»
- Кнопка мгновенной отмены анализа с сохранением всех уже обработанных частей видео
- Полная доступность для программ экранного доступа NVDA / JAWS
"""

import os
import threading
import time
from typing import Dict, Any, List, Optional

from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QProgressBar, QFrame, QMessageBox, QApplication
)
from PySide6.QtCore import Qt, QThread, Signal, Slot, QTimer
from PySide6.QtGui import QFont, QKeySequence, QShortcut

from core.gemini_client import GeminiClient
from core.character_manager import CharacterManager
from core.video_splitter import split_video_into_chunks


class GeminiGenerationWorker(QThread):
    """Фоновый рабочий поток для пошагового анализа видео и генерации тифлокомментариев."""

    progress_updated = Signal(dict)
    chunk_finished = Signal(int, dict)
    generation_finished = Signal()
    generation_error = Signal(str)
    generation_cancelled = Signal()

    def __init__(self, project, config, parent=None):
        super().__init__(parent)
        self.project = project
        self.config = config
        self.cancel_event = threading.Event()
        self._is_cancelled = False

    def cancel(self):
        """Отменяет генерацию тифлокомментариев."""
        self._is_cancelled = True
        self.cancel_event.set()

    def run(self):
        try:
            client = GeminiClient(self.config.api_key)
            char_mgr = CharacterManager(self.project)

            # 1. Нарезка видео на части, если ещё не нарезано
            if not self.project.chunks:
                self.progress_updated.emit({
                    "phase": "split",
                    "percent": 0,
                    "message": "Нарезка исходного видео на части без перекодировки...",
                    "done_text": "Инициализация проекта...",
                    "curr_text": "Нарезка видеофайла на фрагменты для модели Gemini...",
                    "rem_text": "Анализ видеофрагментов и генерация тифлокомментариев"
                })

                chunk_sec = self.config.chunk_duration_minutes * 60.0

                def split_cb(c_idx, total_c):
                    if self.cancel_event.is_set() or self._is_cancelled:
                        return
                    self.progress_updated.emit({
                        "phase": "split",
                        "percent": int((c_idx / max(1, total_c)) * 20),
                        "message": f"Нарезка части {c_idx} из {total_c}...",
                        "done_text": f"Нарезано частей: {c_idx - 1} из {total_c}",
                        "curr_text": f"Подготовка фрагмента {c_idx} из {total_c}...",
                        "rem_text": f"Осталось нарезать: {total_c - c_idx + 1} частей"
                    })

                chunks = split_video_into_chunks(
                    src_video_path=self.project.data["src_video_path"],
                    output_dir=self.project.parts_dir,
                    chunk_duration_sec=chunk_sec,
                    custom_ffmpeg=self.config.ffmpeg_path,
                    progress_callback=split_cb
                )
                if self.cancel_event.is_set() or self._is_cancelled:
                    self.generation_cancelled.emit()
                    return

                self.project.data["chunks"] = chunks
                self.project.save()

            total_chunks = len(self.project.chunks)

            for chunk_idx, chunk in enumerate(self.project.chunks, start=1):
                if self.cancel_event.is_set() or self._is_cancelled:
                    self.generation_cancelled.emit()
                    return

                if chunk.get("processed"):
                    continue

                # Формируем сводку уже сделанного
                done_chunks_count = sum(1 for c in self.project.chunks if c.get("processed"))
                done_comms_count = len(self.project.commentaries)
                done_chars_count = len(self.project.characters)
                done_summary = (
                    f"Нарезка видео: завершена ({total_chunks} частей)\n"
                    f"Обработано частей: {done_chunks_count} из {total_chunks}\n"
                    f"Создано тифлокомментариев: {done_comms_count} шт.\n"
                    f"Зафиксировано персонажей: {done_chars_count} героев"
                )

                # Настраиваемая пауза перед обращением к Gemini API для соблюдения лимитов
                pause_total = self.config.api_request_pause_sec
                if chunk_idx > 1 and pause_total > 0:
                    for rem in range(pause_total, 0, -1):
                        if self.cancel_event.is_set() or self._is_cancelled:
                            self.generation_cancelled.emit()
                            return

                        self.progress_updated.emit({
                            "phase": "pause",
                            "current_chunk": chunk_idx,
                            "total_chunks": total_chunks,
                            "percent": int(((chunk_idx - 1) / total_chunks) * 100),
                            "pause_rem": rem,
                            "message": f"Пауза соблюдения лимитов API: осталось {rem} сек. перед частью {chunk_idx}/{total_chunks}...",
                            "done_text": done_summary,
                            "curr_text": f"Соблюдение лимитов Gemini API: пауза {rem} сек. перед частью {chunk_idx}/{total_chunks}",
                            "rem_text": f"Осталось обработать: {total_chunks - chunk_idx + 1} частей"
                        })

                        # Спим короткими интервалами по 100 мс для мгновенного отклика кнопки Отмена
                        for _ in range(10):
                            if self.cancel_event.is_set() or self._is_cancelled:
                                self.generation_cancelled.emit()
                                return
                            time.sleep(0.1)

                if self.cancel_event.is_set() or self._is_cancelled:
                    self.generation_cancelled.emit()
                    return

                chunk_file = chunk["filepath"]
                start_abs = chunk["start_time_sec"]
                end_abs = chunk["end_time_sec"]
                chunk_name = chunk.get("filename", os.path.basename(chunk_file))


                def gen_cb(msg):
                    if self.cancel_event.is_set() or self._is_cancelled:
                        return
                    self.progress_updated.emit({
                        "phase": "analyzing",
                        "current_chunk": chunk_idx,
                        "total_chunks": total_chunks,
                        "percent": int(((chunk_idx - 0.5) / total_chunks) * 100),
                        "message": f"Часть {chunk_idx}/{total_chunks}: {msg}",
                        "done_text": done_summary,
                        "curr_text": f"Часть {chunk_idx} из {total_chunks} ({chunk_name}):\n{msg}",
                        "rem_text": f"Осталось обработать: {total_chunks - chunk_idx} частей"
                    })

                gen_cb("Загрузка видеофайла в Google Gemini...")

                res_data = client.generate_commentary_for_chunk(
                    chunk_file_path=chunk_file,
                    chunk_index=chunk_idx,
                    total_chunks=total_chunks,
                    start_abs_sec=start_abs,
                    end_abs_sec=end_abs,
                    existing_characters=self.project.characters,
                    previous_commentaries=self.project.commentaries,
                    user_prompt=self.project.user_prompt,
                    model_name=self.config.gemini_model,
                    progress_callback=gen_cb
                )

                if self.cancel_event.is_set() or self._is_cancelled:
                    self.generation_cancelled.emit()
                    return

                diag = res_data.get("diagnostics", {})
                if diag.get("video_status") == "missing":
                    self.generation_error.emit(f"Ошибка в части {chunk_idx}: Видеоряд недоступен. Комментирование остановлено.")
                    return

                from core.gemini_client import parse_time_to_seconds

                chars = res_data.get("characters", [])
                comms = res_data.get("commentaries", [])
                chunk_duration = max(0.1, end_abs - start_abs)

                for char_item in chars:
                    raw_fts = char_item.get("frame_timestamp", char_item.get("frame_timestamp_sec", char_item.get("best_frame_timestamp", 0.0)))
                    char_item["frame_timestamp_sec"] = parse_time_to_seconds(raw_fts, max_duration=chunk_duration)

                if chars:
                    char_mgr.process_detected_characters(chars, chunk_file, start_abs)

                for c in comms:
                    raw_start = c.get("start_time", c.get("start_time_sec", 0.0))
                    raw_end = c.get("end_time", c.get("end_time_sec", 0.0))

                    rel_start = parse_time_to_seconds(raw_start, max_duration=chunk_duration)
                    rel_end = parse_time_to_seconds(raw_end, max_duration=chunk_duration)
                    if rel_end <= rel_start:
                        rel_end = rel_start + 2.0

                    c["start_time"] = round(start_abs + rel_start, 3)
                    c["end_time"] = round(start_abs + rel_end, 3)
                    c["duration_sec"] = round(c["end_time"] - c["start_time"], 3)
                    c["chunk_index"] = chunk_idx

                self.project.add_commentaries(comms)
                chunk["processed"] = True
                self.project.data["current_chunk_index"] = chunk_idx
                self.project.save()

                self.chunk_finished.emit(chunk_idx, res_data)

            self.project.data["status"] = "ready_for_review"
            self.project.save()
            self.generation_finished.emit()

        except Exception as e:
            if self.cancel_event.is_set() or self._is_cancelled:
                self.generation_cancelled.emit()
            else:
                self.generation_error.emit(str(e))



class GeminiGenerationProgressDialog(QDialog):
    """
    Высококонтрастное доступное диалоговое окно прогресса создания тифлокомментариев Gemini.
    """

    def __init__(self, project, config, parent=None):
        super().__init__(parent)
        self.project = project
        self.config = config
        self.start_time = time.time()
        self.is_completed = False
        self.is_cancelled = False

        self.setWindowTitle(f"Генерация тифлокомментариев Gemini — «{self.project.name}»")
        self.setAccessibleName("Окно генерации тифлокомментариев с помощью искусственного интеллекта Google Gemini")
        self.setAccessibleDescription("Окно подробно отображает текущий шаг анализа видео, сделанные этапы, количество созданных комментариев и оставшиеся части.")
        self.setWindowModality(Qt.WindowModal)
        self.setMinimumWidth(700)
        self.setMinimumHeight(460)

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

        lbl_title = QLabel(f"🤖 Генерация тифлокомментариев Gemini: «{self.project.name}»", self)
        lbl_title.setStyleSheet("font-size: 16px; font-weight: bold; color: #00FFFF;")
        lbl_title.setAccessibleName(f"Генерация тифлокомментариев для фильма {self.project.name}")
        layout.addWidget(lbl_title)

        card_frame = QFrame(self)
        card_frame.setObjectName("card_frame")
        card_layout = QVBoxLayout(card_frame)
        card_layout.setContentsMargins(14, 12, 14, 12)
        card_layout.setSpacing(10)

        # 1. Сделано
        self.lbl_head_done = QLabel("✅ Что уже сделано:", card_frame)
        self.lbl_head_done.setStyleSheet("font-weight: bold; font-size: 13px; color: #00FF66;")
        card_layout.addWidget(self.lbl_head_done)

        self.lbl_done_text = QLabel("Инициализация анализа видео...", card_frame)
        self.lbl_done_text.setStyleSheet("font-size: 12px; color: #AAFFAA; padding-left: 8px;")
        self.lbl_done_text.setWordWrap(True)
        self.lbl_done_text.setAccessibleName("Список выполненных этапов генерации")
        card_layout.addWidget(self.lbl_done_text)

        sep1 = QFrame(card_frame)
        sep1.setFrameShape(QFrame.HLine)
        sep1.setStyleSheet("color: #334455;")
        card_layout.addWidget(sep1)

        # 2. Выполняется сейчас
        self.lbl_head_curr = QLabel("⚙️ Текущий процесс:", card_frame)
        self.lbl_head_curr.setStyleSheet("font-weight: bold; font-size: 13px; color: #FFD700;")
        card_layout.addWidget(self.lbl_head_curr)

        self.lbl_curr_text = QLabel("Подготовка видео к анализу...", card_frame)
        self.lbl_curr_text.setStyleSheet("font-size: 13px; font-weight: bold; color: #00FFFF; padding-left: 8px;")
        self.lbl_curr_text.setWordWrap(True)
        self.lbl_curr_text.setAccessibleName("Текущее выполняемое действие модели")
        card_layout.addWidget(self.lbl_curr_text)

        sep2 = QFrame(card_frame)
        sep2.setFrameShape(QFrame.HLine)
        sep2.setStyleSheet("color: #334455;")
        card_layout.addWidget(sep2)

        # 3. Осталось сделать
        self.lbl_head_rem = QLabel("⏳ Что осталось сделать:", card_frame)
        self.lbl_head_rem.setStyleSheet("font-weight: bold; font-size: 13px; color: #FFAA55;")
        card_layout.addWidget(self.lbl_head_rem)

        self.lbl_rem_text = QLabel("Анализ всех частей фильма и создание карточек героев", card_frame)
        self.lbl_rem_text.setStyleSheet("font-size: 12px; color: #B0C4DE; padding-left: 8px;")
        self.lbl_rem_text.setWordWrap(True)
        self.lbl_rem_text.setAccessibleName("Оставшиеся этапы анализа")
        card_layout.addWidget(self.lbl_rem_text)

        layout.addWidget(card_frame)

        # Линейка прогресса
        self.progress_bar = QProgressBar(self)
        self.progress_bar.setRange(0, 100)
        self.progress_bar.setValue(0)
        self.progress_bar.setFixedHeight(30)
        self.progress_bar.setFormat("Подготовка...")
        self.progress_bar.setAccessibleName("Индикатор общего прогресса анализа видео в процентах")
        layout.addWidget(self.progress_bar)

        # Нижняя панель со статистикой и кнопками
        bottom_layout = QHBoxLayout()
        bottom_layout.setContentsMargins(0, 4, 0, 0)

        self.lbl_stats = QLabel(f"Прошло времени: 00:00 | Модель: {self.config.gemini_model}", self)
        self.lbl_stats.setStyleSheet("font-size: 12px; color: #00FFFF;")
        self.lbl_stats.setAccessibleName("Статистика времени анализа")
        bottom_layout.addWidget(self.lbl_stats)

        bottom_layout.addStretch()

        self.btn_cancel = QPushButton("Отмена (Esc)", self)
        self.btn_cancel.setObjectName("btn_cancel")
        self.btn_cancel.setAccessibleName("Кнопка Прервать создание тифлокомментариев")
        self.btn_cancel.setAccessibleDescription("Прерывает анализ видео и сохраняет все уже готовые комментарии и персонажи в проекте")
        self.btn_cancel.clicked.connect(self.request_cancel)
        bottom_layout.addWidget(self.btn_cancel)

        self.btn_close = QPushButton("Закрыть (Enter)", self)
        self.btn_close.setObjectName("btn_done")
        self.btn_close.setAccessibleName("Кнопка Закрыть окно")
        self.btn_close.clicked.connect(self.accept)
        self.btn_close.hide()
        bottom_layout.addWidget(self.btn_close)

        layout.addLayout(bottom_layout)

        # Горячая клавиша Esc
        self.shortcut_esc = QShortcut(QKeySequence(Qt.Key_Escape), self)
        self.shortcut_esc.activated.connect(self.on_escape_pressed)

        # Таймер прошедшего времени
        self.timer = QTimer(self)
        self.timer.setInterval(1000)
        self.timer.timeout.connect(self.update_elapsed_time)
        self.timer.start()


    def update_elapsed_time(self):
        if self.is_completed or self.is_cancelled:
            return
        elapsed_sec = int(time.time() - self.start_time)
        el_m, el_s = divmod(elapsed_sec, 60)
        self.lbl_stats.setText(f"Прошло времени: {el_m:02d}:{el_s:02d} | Модель: {self.config.gemini_model}")

    def start_worker(self):
        self.worker = GeminiGenerationWorker(
            project=self.project,
            config=self.config,
            parent=self
        )
        self.worker.progress_updated.connect(self.on_progress_updated)
        self.worker.chunk_finished.connect(self.on_chunk_finished)
        self.worker.generation_finished.connect(self.on_generation_finished)
        self.worker.generation_error.connect(self.on_generation_error)
        self.worker.generation_cancelled.connect(self.on_generation_cancelled)
        self.worker.start()

    @Slot(dict)
    def on_progress_updated(self, data: dict):
        pct = data.get("percent", 0)
        phase = data.get("phase", "analyzing")
        msg = data.get("message", "")
        done_text = data.get("done_text", "")
        curr_text = data.get("curr_text", "")
        rem_text = data.get("rem_text", "")
        cur_c = data.get("current_chunk", 1)
        tot_c = data.get("total_chunks", max(1, len(self.project.chunks)))

        self.progress_bar.setValue(pct)
        if phase == "split":
            self.progress_bar.setFormat(f"Нарезка видео ({pct}%)")
        elif phase == "pause":
            self.progress_bar.setFormat(f"Пауза API ({pct}%)")
        else:
            self.progress_bar.setFormat(f"Часть {cur_c} из {tot_c} ({pct}%)")

        if done_text:
            self.lbl_done_text.setText(done_text)
        if curr_text:
            if phase == "pause":
                self.lbl_head_curr.setText("⏳ Пауза лимитов API:")
                self.lbl_head_curr.setStyleSheet("font-weight: bold; font-size: 13px; color: #FFAA00;")
            else:
                self.lbl_head_curr.setText("⚙️ Текущий процесс:")
                self.lbl_head_curr.setStyleSheet("font-weight: bold; font-size: 13px; color: #FFD700;")
            self.lbl_curr_text.setText(curr_text)
        if rem_text:
            self.lbl_rem_text.setText(rem_text)

    @Slot(int, dict)
    def on_chunk_finished(self, chunk_idx: int, res_data: dict):
        total_chunks = len(self.project.chunks)
        done_chunks = sum(1 for c in self.project.chunks if c.get("processed"))
        comms_count = len(self.project.commentaries)
        chars_count = len(self.project.characters)

        self.lbl_done_text.setText(
            f"Нарезка видео: завершена ({total_chunks} частей)\n"
            f"Обработано частей: {done_chunks} из {total_chunks}\n"
            f"Создано тифлокомментариев: {comms_count} шт.\n"
            f"Зафиксировано персонажей: {chars_count} героев"
        )

    @Slot()
    def on_generation_finished(self):
        self.is_completed = True
        self.progress_bar.setValue(100)
        self.progress_bar.setFormat("100% — Анализ видео успешно завершен!")

        self.lbl_head_curr.setText("✅ Статус:")
        self.lbl_head_curr.setStyleSheet("font-weight: bold; font-size: 13px; color: #00FF66;")
        self.lbl_curr_text.setText(
            f"Тифлокомментирование фильма успешно завершено!\n"
            f"Всего создано комментариев: {len(self.project.commentaries)} шт., "
            f"героев в картотеке: {len(self.project.characters)}."
        )
        self.lbl_curr_text.setStyleSheet("font-size: 13px; font-weight: bold; color: #AAFFAA; padding-left: 8px;")

        self.lbl_rem_text.setText("Все части фильма обработаны. Проект готов к просмотру и озвучиванию.")

        self.btn_cancel.hide()
        self.btn_close.show()
        self.btn_close.setFocus()
        QApplication.beep()

    @Slot(str)
    def on_generation_error(self, err_msg: str):
        self.is_completed = True
        self.progress_bar.setFormat("Ошибка генерации")
        self.lbl_curr_text.setText(f"Ошибка:\n{err_msg}")
        self.lbl_curr_text.setStyleSheet("font-size: 13px; font-weight: bold; color: #FF5555; padding-left: 8px;")
        self.btn_cancel.setText("Закрыть")
        QMessageBox.critical(self, "Ошибка генерации", f"Произошла ошибка при генерации тифлокомментариев:\n{err_msg}")

    @Slot()
    def on_generation_cancelled(self):
        self.is_cancelled = True
        comms_count = len(self.project.commentaries)
        chars_count = len(self.project.characters)
        self.progress_bar.setFormat(f"Генерация прервана ({comms_count} комментариев сохранено)")
        self.lbl_curr_text.setText(
            f"Процесс остановлен пользователем.\n"
            f"Сохранено комментариев: {comms_count}, персонажей: {chars_count}."
        )
        self.lbl_curr_text.setStyleSheet("font-size: 13px; font-weight: bold; color: #FF8888; padding-left: 8px;")
        self.reject()

    def request_cancel(self):
        if self.is_completed or self.is_cancelled:
            self.reject()
            return

        reply = QMessageBox.question(
            self,
            "Подтверждение отмены",
            "Вы действительно хотите прервать генерацию тифлокомментариев?\nВсе уже созданные комментарии и карточки героев будут сохранены в проекте.",
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No
        )
        if reply == QMessageBox.Yes:
            self.btn_cancel.setEnabled(False)
            self.btn_cancel.setText("Остановка...")
            self.lbl_curr_text.setText("Остановка анализа и сохранение обработанных данных проекта...")
            self.worker.cancel()

    def on_escape_pressed(self):
        if self.is_completed:
            self.accept()
        else:
            self.request_cancel()

    def closeEvent(self, event):
        if self.is_completed or self.is_cancelled:
            event.accept()
        else:
            self.request_cancel()
            event.ignore()

