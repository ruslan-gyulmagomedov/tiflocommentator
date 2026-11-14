# -*- coding: utf-8 -*-
"""
Диалоговое окно фонового синтеза речи (TTS) для комментариев:
- Асинхронное выполнение в отдельном потоке QThread (без зависания GUI и без статуса «Не отвечает»)
- Полная адаптация под режим высокой контрастности Windows (High Contrast)
- Чёткое разделение: «Что уже сделано», «Текущий процесс» и «Что осталось сделать»
- Кнопка мгновенной отмены озвучки с сохранением всех уже озвученных комментариев
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


class TTSGenerationWorker(QThread):
    """Фоновый рабочий поток для синтеза речи тифлокомментариев."""

    progress_updated = Signal(dict)
    tts_finished = Signal(int, int)
    tts_error = Signal(str)
    tts_cancelled = Signal(int, int)

    def __init__(
        self,
        project,
        config,
        engine_type: str = "gemini",
        comments_to_process: Optional[List[Dict[str, Any]]] = None,
        tts_service=None,
        parent=None
    ):
        super().__init__(parent)
        self.project = project
        self.config = config
        self.engine_type = engine_type
        self.comments = comments_to_process or []
        self.tts_service = tts_service
        self.cancel_event = threading.Event()
        self._is_cancelled = False

    def cancel(self):
        """Отменяет генерацию речи."""
        self._is_cancelled = True
        self.cancel_event.set()

    def run(self):
        try:
            from core.tts_engine import TTSService
            if self.tts_service is None:
                self.tts_service = TTSService(self.config)

            targets = list(self.comments)
            total = len(targets)
            if total == 0:
                self.tts_finished.emit(0, 0)
                return

            success_count = 0
            pause_sec = self.config.api_request_pause_sec if self.engine_type == "gemini" else 0
            last_voiced_text = ""

            for idx, comm in enumerate(targets, start=1):
                if self.cancel_event.is_set() or self._is_cancelled:
                    self.tts_cancelled.emit(success_count, total)
                    return

                # Пауза между запросами к Gemini API для соблюдения квот и лимитов
                if idx > 1 and pause_sec > 0:
                    for rem in range(pause_sec, 0, -1):
                        if self.cancel_event.is_set() or self._is_cancelled:
                            self.tts_cancelled.emit(success_count, total)
                            return

                        data = {
                            "phase": "pause",
                            "cur": idx - 1,
                            "total": total,
                            "percent": int(((idx - 1) / total) * 100),
                            "pause_rem": rem,
                            "message": f"Пауза соблюдения лимитов Gemini API: осталось {rem} сек. (перед репликой {idx}/{total})",
                            "last_voiced": last_voiced_text,
                            "current_text": comm.get("text", "")
                        }
                        self.progress_updated.emit(data)

                        # Спим короткими интервалами по 100 мс для мгновенного отклика кнопки Отмена
                        for _ in range(10):
                            if self.cancel_event.is_set() or self._is_cancelled:
                                self.tts_cancelled.emit(success_count, total)
                                return
                            time.sleep(0.1)

                if self.cancel_event.is_set() or self._is_cancelled:
                    self.tts_cancelled.emit(success_count, total)
                    return

                comm_text = comm.get("text", "")
                data = {
                    "phase": "synthesizing",
                    "cur": idx,
                    "total": total,
                    "percent": int(((idx - 1) / total) * 100),
                    "message": f"Озвучивание ({idx}/{total}): «{comm_text[:50]}...»",
                    "last_voiced": last_voiced_text,
                    "current_text": comm_text
                }
                self.progress_updated.emit(data)

                ok = self.tts_service.synthesize_single_commentary(comm, self.project, engine_type=self.engine_type)
                if ok:
                    success_count += 1
                    last_voiced_text = comm_text
                    self.project.resolve_overlaps()
                    self.project.save()

                if self.cancel_event.is_set() or self._is_cancelled:
                    self.tts_cancelled.emit(success_count, total)
                    return

            self.project.resolve_overlaps()
            self.project.save()
            self.tts_finished.emit(success_count, total)

        except Exception as e:
            if self.cancel_event.is_set() or self._is_cancelled:
                self.tts_cancelled.emit(success_count, total)
            else:
                self.tts_error.emit(str(e))


class TTSProgressDialog(QDialog):
    """
    Высококонтрастное диалоговое окно прогресса синтеза речи тифлокомментариев.
    """

    def __init__(
        self,
        project,
        config,
        engine_type: str = "gemini",
        comments_to_process: Optional[List[Dict[str, Any]]] = None,
        tts_service=None,
        parent=None
    ):
        super().__init__(parent)
        self.project = project
        self.config = config
        self.engine_type = engine_type
        self.comments = comments_to_process or []
        self.tts_service = tts_service
        self.start_time = time.time()
        self.is_completed = False
        self.is_cancelled = False
        self.success_count = 0
        self.total_count = len(self.comments)

        engine_name = "Google Gemini TTS" if engine_type == "gemini" else "Microsoft SAPI5"
        self.setWindowTitle(f"Озвучивание тифлокомментариев — {engine_name}")
        self.setAccessibleName(f"Окно озвучивания комментариев синтезатором {engine_name}")
        self.setAccessibleDescription("Окно отображает текущую фразу, количество озвученных комментариев и прогресс.")
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

        engine_title = "Google Gemini TTS" if self.engine_type == "gemini" else "Microsoft SAPI5"
        lbl_title = QLabel(f"🎙️ Озвучивание комментариев: «{self.project.name}» ({engine_title})", self)
        lbl_title.setStyleSheet("font-size: 16px; font-weight: bold; color: #00FFFF;")
        lbl_title.setAccessibleName(f"Озвучивание комментариев проекта {self.project.name}")
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

        self.lbl_done_text = QLabel("Инициализация синтезатора речи...", card_frame)
        self.lbl_done_text.setStyleSheet("font-size: 12px; color: #AAFFAA; padding-left: 8px;")
        self.lbl_done_text.setWordWrap(True)
        self.lbl_done_text.setAccessibleName("Список выполненных шагов озвучивания")
        card_layout.addWidget(self.lbl_done_text)

        sep1 = QFrame(card_frame)
        sep1.setFrameShape(QFrame.HLine)
        sep1.setStyleSheet("color: #334455;")
        card_layout.addWidget(sep1)

        # 2. Выполняется сейчас
        self.lbl_head_curr = QLabel("⚙️ Текущий процесс:", card_frame)
        self.lbl_head_curr.setStyleSheet("font-weight: bold; font-size: 13px; color: #FFD700;")
        card_layout.addWidget(self.lbl_head_curr)

        self.lbl_curr_text = QLabel("Подготовка к генерации речи...", card_frame)
        self.lbl_curr_text.setStyleSheet("font-size: 13px; font-weight: bold; color: #00FFFF; padding-left: 8px;")
        self.lbl_curr_text.setWordWrap(True)
        self.lbl_curr_text.setAccessibleName("Текущая озвучиваемая фраза")
        card_layout.addWidget(self.lbl_curr_text)

        sep2 = QFrame(card_frame)
        sep2.setFrameShape(QFrame.HLine)
        sep2.setStyleSheet("color: #334455;")
        card_layout.addWidget(sep2)

        # 3. Осталось сделать
        self.lbl_head_rem = QLabel("⏳ Что осталось сделать:", card_frame)
        self.lbl_head_rem.setStyleSheet("font-weight: bold; font-size: 13px; color: #FFAA55;")
        card_layout.addWidget(self.lbl_head_rem)

        self.lbl_rem_text = QLabel(f"Осталось озвучить: {self.total_count} комментариев", card_frame)
        self.lbl_rem_text.setStyleSheet("font-size: 12px; color: #B0C4DE; padding-left: 8px;")
        self.lbl_rem_text.setWordWrap(True)
        self.lbl_rem_text.setAccessibleName("Оставшиеся комментарии для озвучивания")
        card_layout.addWidget(self.lbl_rem_text)

        layout.addWidget(card_frame)

        # Линейка прогресса
        self.progress_bar = QProgressBar(self)
        self.progress_bar.setRange(0, 100)
        self.progress_bar.setValue(0)
        self.progress_bar.setFixedHeight(30)
        self.progress_bar.setFormat(f"0 / {self.total_count} (0%)")
        self.progress_bar.setAccessibleName("Индикатор прогресса озвучивания в процентах")
        layout.addWidget(self.progress_bar)

        # Нижняя панель со статистикой и кнопками
        bottom_layout = QHBoxLayout()
        bottom_layout.setContentsMargins(0, 4, 0, 0)

        voice_name = self.config.gemini_tts_voice if self.engine_type == "gemini" else self.config.sapi5_voice
        self.lbl_stats = QLabel(f"Прошло времени: 00:00 | Голос: {voice_name}", self)
        self.lbl_stats.setStyleSheet("font-size: 12px; color: #00FFFF;")
        self.lbl_stats.setAccessibleName("Статистика времени синтеза речи")
        bottom_layout.addWidget(self.lbl_stats)

        bottom_layout.addStretch()

        self.btn_cancel = QPushButton("Отмена (Esc)", self)
        self.btn_cancel.setObjectName("btn_cancel")
        self.btn_cancel.setAccessibleName("Кнопка Прервать озвучивание комментариев")
        self.btn_cancel.setAccessibleDescription("Прерывает синтез речи и сохраняет все уже готовые реплики в проекте")
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
        voice_name = self.config.gemini_tts_voice if self.engine_type == "gemini" else self.config.sapi5_voice
        self.lbl_stats.setText(f"Прошло времени: {el_m:02d}:{el_s:02d} | Голос: {voice_name}")

    def start_worker(self):
        self.worker = TTSGenerationWorker(
            project=self.project,
            config=self.config,
            engine_type=self.engine_type,
            comments_to_process=self.comments,
            tts_service=self.tts_service,
            parent=self
        )
        self.worker.progress_updated.connect(self.on_progress_updated)
        self.worker.tts_finished.connect(self.on_tts_finished)
        self.worker.tts_error.connect(self.on_tts_error)
        self.worker.tts_cancelled.connect(self.on_tts_cancelled)
        self.worker.start()

    @Slot(dict)
    def on_progress_updated(self, data: dict):
        cur = data.get("cur", 0)
        total = data.get("total", self.total_count)
        pct = data.get("percent", 0)
        phase = data.get("phase", "synthesizing")
        msg = data.get("message", "")
        last_voiced = data.get("last_voiced", "")
        current_text = data.get("current_text", "")
        rem_count = max(0, total - cur)

        self.progress_bar.setValue(pct)
        self.progress_bar.setFormat(f"{cur} / {total} ({pct}%)")

        if cur > 0:
            done_desc = f"Озвучено комментариев: {cur} из {total} ({pct}%)"
            if last_voiced:
                done_desc += f"\nПоследняя готовая фраза: «{last_voiced[:60]}»"
            self.lbl_done_text.setText(done_desc)
        else:
            self.lbl_done_text.setText("Подготовка параметров синтезатора...")

        if phase == "pause":
            pause_rem = data.get("pause_rem", 0)
            self.lbl_head_curr.setText("⏳ Пауза лимитов API:")
            self.lbl_head_curr.setStyleSheet("font-weight: bold; font-size: 13px; color: #FFAA00;")
            self.lbl_curr_text.setText(f"Соблюдение лимитов Gemini API: осталось {pause_rem} сек. перед следующей репликой")
        else:
            self.lbl_head_curr.setText("⚙️ Текущий процесс:")
            self.lbl_head_curr.setStyleSheet("font-weight: bold; font-size: 13px; color: #FFD700;")
            self.lbl_curr_text.setText(f"Озвучивание ({cur}/{total}): «{current_text[:80]}»")

        self.lbl_rem_text.setText(f"Осталось озвучить: {rem_count} комментариев")

    @Slot(int, int)
    def on_tts_finished(self, success_count: int, total_count: int):
        self.is_completed = True
        self.success_count = success_count
        self.progress_bar.setValue(100)
        self.progress_bar.setFormat(f"100% — Успешно озвучено {success_count} из {total_count}")

        self.lbl_head_curr.setText("✅ Статус:")
        self.lbl_head_curr.setStyleSheet("font-weight: bold; font-size: 13px; color: #00FF66;")
        self.lbl_curr_text.setText(f"Озвучивание успешно завершено! Создано {success_count} аудиодорожек.")
        self.lbl_curr_text.setStyleSheet("font-size: 13px; font-weight: bold; color: #AAFFAA; padding-left: 8px;")

        self.lbl_done_text.setText(f"Все комментарии ({success_count} шт.) успешно озвучены и синхронизированы.")
        self.lbl_rem_text.setText("Все задачи выполнены. Аудиодорожки готовы к предпросмотру.")

        self.btn_cancel.hide()
        self.btn_close.show()
        self.btn_close.setFocus()
        QApplication.beep()

    @Slot(str)
    def on_tts_error(self, err_msg: str):
        self.is_completed = True
        self.progress_bar.setFormat("Ошибка синтеза речи")
        self.lbl_curr_text.setText(f"Ошибка:\n{err_msg}")
        self.lbl_curr_text.setStyleSheet("font-size: 13px; font-weight: bold; color: #FF5555; padding-left: 8px;")
        self.btn_cancel.setText("Закрыть")
        QMessageBox.critical(self, "Ошибка синтеза речи", f"Не удалось завершить озвучивание:\n{err_msg}")

    @Slot(int, int)
    def on_tts_cancelled(self, success_count: int, total_count: int):
        self.is_cancelled = True
        self.success_count = success_count
        self.progress_bar.setFormat(f"Озвучивание прервано ({success_count} сохранено)")
        self.lbl_curr_text.setText(f"Процесс остановлен пользователем. Сохранено {success_count} из {total_count} комментариев.")
        self.lbl_curr_text.setStyleSheet("font-size: 13px; font-weight: bold; color: #FF8888; padding-left: 8px;")
        self.reject()

    def request_cancel(self):
        if self.is_completed or self.is_cancelled:
            self.reject()
            return

        reply = QMessageBox.question(
            self,
            "Подтверждение отмены",
            "Вы действительно хотите прервать озвучивание комментариев?\nВсе уже озвученные реплики будут сохранены в проекте.",
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No
        )
        if reply == QMessageBox.Yes:
            self.btn_cancel.setEnabled(False)
            self.btn_cancel.setText("Остановка...")
            self.lbl_curr_text.setText("Завершение текущей реплики и сохранение проекта...")
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

