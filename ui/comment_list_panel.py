# -*- coding: utf-8 -*-
"""
Боковая панель со списком тифлокомментариев:
- Размещение во всю высоту окна слева
- Изменение размера перетягиванием разделителя
- Одиночный клик / выбор стрелками -> переход курсора таймлайна и видео на начало комментария
- Двойной клик -> редактирование текста комментария
- Контекстное меню со всеми операциями (редактирование, хронометраж, озвучка SAPI5/Gemini, удаление аудио, удаление)
- Кнопка закрытия [✕]
- Доступность для скринридеров NVDA / JAWS
"""

import os
from typing import List, Dict, Any, Optional
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QTableWidget, QTableWidgetItem, QHeaderView, QAbstractItemView,
    QMenu, QMessageBox, QSizePolicy
)
from PySide6.QtCore import Qt, Signal, QPoint, QSize
from PySide6.QtGui import QAction

from ui.comment_edit_dialog import CommentEditDialog
from ui.comment_duration_dialog import CommentDurationDialog
from ui.accessible_dialogs import confirm_destructive


class AccessibleCommentTable(QTableWidget):
    """Таблица тифлокомментариев с поддержкой множественного выбора и клавиатурных шорткатов."""

    edit_requested = Signal(str)
    delete_requested = Signal()
    delete_audio_requested = Signal()
    add_requested = Signal()
    toggle_panel_requested = Signal()
    close_panel_requested = Signal()

    def keyPressEvent(self, event):
        # Резервная обработка Ctrl+L и Escape: срабатывает, только если
        # оконный QAction не перехватил клавишу раньше (шорткаты обрабатываются
        # до keyPressEvent, поэтому двойного срабатывания не будет).
        if event.key() == Qt.Key_L and (event.modifiers() & Qt.ControlModifier):
            self.toggle_panel_requested.emit()
            event.accept()
            return
        if event.key() == Qt.Key_Escape:
            self.close_panel_requested.emit()
            event.accept()
            return
        if event.key() in (Qt.Key_Return, Qt.Key_Enter):
            row = self.currentRow()
            if row >= 0:
                item_0 = self.item(row, 0)
                if item_0:
                    comm_id = item_0.data(Qt.UserRole)
                    if comm_id:
                        self.edit_requested.emit(comm_id)
                        event.accept()
                        return
        elif event.key() == Qt.Key_Delete and (event.modifiers() & (Qt.ShiftModifier | Qt.ControlModifier)):
            self.delete_audio_requested.emit()
            event.accept()
            return
        elif event.key() == Qt.Key_Delete:
            self.delete_requested.emit()
            event.accept()
            return
        elif event.key() == Qt.Key_Insert or (event.key() == Qt.Key_T and (event.modifiers() & Qt.ControlModifier)):
            self.add_requested.emit()
            event.accept()
            return
        super().keyPressEvent(event)


class CommentListPanel(QWidget):
    """Боковая панель списка тифлокомментариев."""

    seek_requested = Signal(int)
    commentary_timing_changed = Signal(str)           # comm_id при изменении длительности/границ
    commentary_moved = Signal(str, float, float)      # comm_id, new_start, new_end
    commentary_text_edited = Signal(str)              # comm_id при изменении текста
    commentary_updated = Signal(str)                  # comm_id (обратная совместимость)
    commentary_deleted = Signal(str)                  # comm_id
    commentaries_deleted = Signal(list)               # List[str]
    commentary_audio_deleted = Signal(list)           # List[str]
    commentaries_resynthesize_requested = Signal(list, str)   # (List[str], engine_type)
    add_commentary_requested = Signal()
    import_srt_requested = Signal()
    export_srt_requested = Signal()
    close_requested = Signal()
    toggle_panel_requested = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.commentaries: List[Dict[str, Any]] = []
        self.max_speedup: float = 3.0
        self.setMinimumWidth(0)
        self.setMinimumSize(0, 0)
        self.setAccessibleName("Панель списка тифлокомментариев")
        self.setAccessibleDescription(
            "Боковая панель со списком комментариев. Ctrl+L или Escape закрывают панель."
        )
        self.init_ui()

    def minimumSizeHint(self) -> QSize:
        """Позволяет сплиттеру плавно изменять размер до нуля без рывков и скачков."""
        return QSize(0, 0)

    def sizeHint(self) -> QSize:
        return QSize(300, 600)

    def set_max_speedup(self, val: float):
        """Устанавливает максимальный лимит разгона речи для контроля границ."""
        self.max_speedup = max(1.0, float(val or 3.0))

    def init_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(4, 4, 4, 4)
        layout.setSpacing(4)

        # Верхняя плашка панели: заголовок и кнопка закрытия
        header_layout = QHBoxLayout()
        header_layout.setContentsMargins(4, 2, 4, 2)

        self.lbl_title = QLabel("📋 Комментарии", self)
        self.lbl_title.setStyleSheet("font-weight: bold; font-size: 13px; color: #00FFCC;")
        self.lbl_title.setAccessibleName("Панель списка тифлокомментариев")
        self.lbl_title.setMinimumWidth(0)
        header_layout.addWidget(self.lbl_title)

        self.lbl_count = QLabel("(0)", self)
        self.lbl_count.setStyleSheet("font-size: 12px; color: #AAAAAA;")
        header_layout.addWidget(self.lbl_count)

        header_layout.addStretch(1)

        self.btn_close = QPushButton("✕", self)
        self.btn_close.setFixedSize(26, 24)
        self.btn_close.setToolTip("Закрыть панель комментариев (Ctrl+L)")
        self.btn_close.setAccessibleName("Закрыть список комментариев")
        self.btn_close.setStyleSheet(
            "QPushButton { font-weight: bold; font-size: 14px; background: transparent; color: #CCCCCC; border: 1px solid #555555; border-radius: 3px; }"
            "QPushButton:hover { background-color: #AA0000; color: #FFFFFF; border-color: #FF0000; }"
        )
        self.btn_close.clicked.connect(self.close_requested.emit)
        header_layout.addWidget(self.btn_close)

        layout.addLayout(header_layout)

        # Таблица комментариев
        self.table = AccessibleCommentTable(self)
        self.table.setMinimumWidth(0)
        self.table.setMinimumSize(0, 0)
        self.table.setColumnCount(3)
        self.table.setHorizontalHeaderLabels(["Время", "Озвучка", "Текст комментария"])

        header = self.table.horizontalHeader()
        header.setSectionResizeMode(0, QHeaderView.ResizeToContents)
        header.setSectionResizeMode(1, QHeaderView.ResizeToContents)
        header.setSectionResizeMode(2, QHeaderView.Stretch)

        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.ExtendedSelection)
        # Tab должен уходить из таблицы к следующему элементу, а не ходить
        # по ячейкам: иначе скринридер «запирается» внутри списка.
        self.table.setTabKeyNavigation(False)
        self.table.setFocusPolicy(Qt.StrongFocus)
        self.table.setAccessibleName("Таблица списка тифлокомментариев")
        self.table.setAccessibleDescription(
            "Используйте стрелки для перехода, Shift+стрелки для выделения группы, "
            "Enter для редактирования текста, Delete для удаления, Shift+Delete для удаления озвучки, "
            "Ctrl+T для добавления нового комментария. Tab выходит из таблицы, Escape и Ctrl+L закрывают панель."
        )

        self.table.itemDoubleClicked.connect(self.on_table_double_clicked)
        self.table.itemSelectionChanged.connect(self.on_table_selection_changed)
        self.table.edit_requested.connect(self.edit_commentary_by_id)
        self.table.delete_requested.connect(self.delete_selected_commentaries)
        self.table.delete_audio_requested.connect(self.delete_selected_audio)
        self.table.add_requested.connect(self.add_commentary_requested.emit)
        self.table.toggle_panel_requested.connect(self.toggle_panel_requested.emit)
        self.table.close_panel_requested.connect(self.close_requested.emit)

        self.table.setContextMenuPolicy(Qt.CustomContextMenu)
        self.table.customContextMenuRequested.connect(self.on_table_context_menu)

        layout.addWidget(self.table, 1)

        # Нижняя панель быстрых кнопок импорта и экспорта SRT во всю ширину
        panel_btn_layout = QVBoxLayout()
        panel_btn_layout.setContentsMargins(2, 2, 2, 2)
        panel_btn_layout.setSpacing(3)

        panel_btn_style = (
            "QPushButton { font-size: 11px; font-weight: bold; padding: 4px 8px; min-height: 26px; }"
            "QPushButton:hover { background-color: #005544; }"
        )

        self.btn_panel_import = QPushButton("📥 Импорт из SRT (Ctrl+I)", self)
        self.btn_panel_import.setStyleSheet(panel_btn_style)
        self.btn_panel_import.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        self.btn_panel_import.setMinimumWidth(0)
        self.btn_panel_import.setToolTip("Импортировать комментарии из файла субтитров SRT (Ctrl+I)")
        self.btn_panel_import.setAccessibleName("Импортировать комментарии из файла SRT")
        self.btn_panel_import.clicked.connect(self.import_srt_requested.emit)
        panel_btn_layout.addWidget(self.btn_panel_import)

        self.btn_panel_export = QPushButton("📄 Экспорт в SRT (Ctrl+Shift+E)", self)
        self.btn_panel_export.setStyleSheet(panel_btn_style)
        self.btn_panel_export.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        self.btn_panel_export.setMinimumWidth(0)
        self.btn_panel_export.setToolTip("Экспортировать комментарии проекта в файл субтитров SRT (Ctrl+Shift+E)")
        self.btn_panel_export.setAccessibleName("Экспортировать комментарии в файл SRT")
        self.btn_panel_export.clicked.connect(self.export_srt_requested.emit)
        panel_btn_layout.addWidget(self.btn_panel_export)

        layout.addLayout(panel_btn_layout)

    def keyPressEvent(self, event):
        """Резервная обработка горячих клавиш панели, когда фокус на её дочерних виджетах."""
        if event.key() == Qt.Key_L and (event.modifiers() & Qt.ControlModifier):
            self.toggle_panel_requested.emit()
            event.accept()
            return
        if event.key() == Qt.Key_Escape:
            self.close_requested.emit()
            event.accept()
            return
        super().keyPressEvent(event)

    def focus_table(self):
        """Передаёт фокус в таблицу комментариев (используется при открытии панели)."""
        if not self.table.hasFocus():
            self.table.setFocus(Qt.OtherFocusReason)
        if self.table.rowCount() > 0 and self.table.currentRow() < 0:
            self.table.setCurrentCell(0, 0)

    def set_commentaries(self, commentaries: List[Dict[str, Any]]):
        self.commentaries = commentaries or []
        self.refresh_table()

    def get_selected_comm_ids(self) -> List[str]:
        selected_rows = sorted(list(set(idx.row() for idx in self.table.selectedIndexes())))
        ids = []
        for r in selected_rows:
            item_0 = self.table.item(r, 0)
            if item_0:
                cid = item_0.data(Qt.UserRole)
                if cid:
                    ids.append(cid)
        return ids

    def refresh_table(self):
        self.table.blockSignals(True)
        self.table.setRowCount(len(self.commentaries))
        self.lbl_count.setText(f"({len(self.commentaries)})")

        for row, c in enumerate(self.commentaries):
            st = float(c.get("start_time", 0.0))
            et = float(c.get("end_time", 0.0))
            dur = max(0.0, round(et - st, 3))

            st_str = f"{int(st//3600):02d}:{int((st%3600)//60):02d}:{st%60:05.2f}"
            et_str = f"{int(et//3600):02d}:{int((et%3600)//60):02d}:{et%60:05.2f}"

            audio_f = c.get("audio_file")
            has_audio = bool(audio_f and os.path.isfile(audio_f) and not c.get("audio_needs_rebuild", False))
            engine = (c.get("tts_engine") or "SAPI5").upper()
            speed_f = float(c.get("speed_factor") or 1.0)

            if has_audio:
                if speed_f and speed_f > 1.001:
                    type_str = f"{engine} ({speed_f:.2f}x)"
                else:
                    type_str = engine
            elif c.get("audio_needs_rebuild", False) and audio_f and os.path.isfile(audio_f):
                type_str = "Требуется"
            else:
                type_str = "Нет"

            item_st = QTableWidgetItem(st_str)
            item_st.setData(Qt.UserRole, c.get("id"))
            item_type = QTableWidgetItem(type_str)
            item_text = QTableWidgetItem(c.get("text", ""))

            for item in [item_st, item_type, item_text]:
                item.setFlags(item.flags() & ~Qt.ItemIsEditable)

            item_st.setToolTip(f"Интервал звучания: {st_str} — {et_str} (длительность {dur:.2f} сек.)")
            item_type.setToolTip(f"Статус озвучки: {type_str}")

            self.table.setItem(row, 0, item_st)
            self.table.setItem(row, 1, item_type)
            self.table.setItem(row, 2, item_text)

        self.table.blockSignals(False)

    def select_commentary_by_id(self, comm_id: str):
        for row in range(self.table.rowCount()):
            item_0 = self.table.item(row, 0)
            if item_0 and item_0.data(Qt.UserRole) == comm_id:
                self.table.blockSignals(True)
                self.table.clearSelection()
                self.table.selectRow(row)
                self.table.scrollToItem(item_0)
                self.table.blockSignals(False)
                break

    def on_table_selection_changed(self):
        row = self.table.currentRow()
        if 0 <= row < len(self.commentaries):
            st = float(self.commentaries[row].get("start_time", 0.0))
            self.seek_requested.emit(int(st * 1000))

    def on_table_double_clicked(self, item):
        row = item.row()
        item_0 = self.table.item(row, 0)
        if item_0:
            comm_id = item_0.data(Qt.UserRole)
            if comm_id:
                self.edit_commentary_by_id(comm_id)

    def edit_commentary_by_id(self, comm_id: str):
        target = next((c for c in self.commentaries if c.get("id") == comm_id), None)
        if not target:
            return

        dlg = CommentEditDialog(target.get("text", ""), self)
        if dlg.exec():
            new_text = dlg.get_text()
            if new_text and new_text != target.get("text"):
                target["text"] = new_text
                target["audio_needs_rebuild"] = True
                self.commentary_text_edited.emit(comm_id)
                self.refresh_table()

    def change_duration_by_id(self, comm_id: str):
        target = next((c for c in self.commentaries if c.get("id") == comm_id), None)
        if not target:
            return

        st = float(target.get("start_time") or 0.0)
        et = float(target.get("end_time") or (st + 2.0))
        raw_dur = float(target.get("raw_duration_sec") or 0.0)
        if raw_dur > 0.0 and self.max_speedup > 0.0:
            min_dur = max(0.2, round(raw_dur / self.max_speedup, 3))
        else:
            min_dur = 0.2

        dlg = CommentDurationDialog(start_time=st, current_end_time=et, min_duration=min_dur, parent=self)
        if dlg.exec():
            new_end = dlg.get_new_end_time()
            target["end_time"] = new_end
            target["duration_sec"] = round(new_end - st, 3)
            self.commentary_timing_changed.emit(comm_id)
            self.refresh_table()

    def delete_selected_audio(self, selected_ids: Optional[List[str]] = None):
        target_ids = selected_ids if selected_ids is not None else self.get_selected_comm_ids()
        if not target_ids:
            return

        count = len(target_ids)
        if count == 1:
            comm = next((c for c in self.commentaries if c.get("id") == target_ids[0]), None)
            text_preview = comm.get("text", "")[:40] if comm else ""
            msg = f"Удалить аудиозапись озвучки для комментария?\n«{text_preview}...»\n\nТекст комментария и временные метки сохранятся."
        else:
            msg = f"Удалить аудиозаписи озвучки для {count} выбранных комментариев?\n\nТексты комментариев и временные метки сохранятся."

        if confirm_destructive(self, "Удаление озвучки", msg):
            self.commentary_audio_deleted.emit(target_ids)

    def delete_selected_commentaries(self, selected_ids: Optional[List[str]] = None):
        target_ids = selected_ids if selected_ids is not None else self.get_selected_comm_ids()
        if not target_ids:
            return

        count = len(target_ids)
        if count == 1:
            comm = next((c for c in self.commentaries if c.get("id") == target_ids[0]), None)
            text_preview = comm.get("text", "")[:50] if comm else ""
            msg = f"Удалить выбранный тифлокомментарий и его аудиозапись?\n«{text_preview}...»"
        else:
            msg = f"Удалить {count} выбранных тифлокомментариев и все относящиеся к ним аудиофайлы?"

        if confirm_destructive(self, "Удаление комментариев", msg):
            self.commentaries_deleted.emit(target_ids)

    def on_table_context_menu(self, pos: QPoint):
        sel_ids = self.get_selected_comm_ids()
        item = self.table.itemAt(pos)
        if item:
            clicked_row = item.row()
            item_0 = self.table.item(clicked_row, 0)
            if item_0:
                clicked_id = item_0.data(Qt.UserRole)
                if clicked_id and clicked_id not in sel_ids:
                    self.table.clearSelection()
                    self.table.selectRow(clicked_row)
                    sel_ids = [clicked_id]
        if not sel_ids:
            menu = QMenu(self)
            act_add = QAction("➕ Добавить комментарий на текущей позиции (Ctrl+T / Ins)", self)
            act_add.triggered.connect(self.add_commentary_requested.emit)
            menu.addAction(act_add)

            menu.addSeparator()
            act_import_srt = QAction("📥 Импортировать комментарии из SRT... (Ctrl+I)", self)
            act_import_srt.triggered.connect(self.import_srt_requested.emit)
            menu.addAction(act_import_srt)

            act_export_srt = QAction("📄 Экспортировать комментарии в SRT... (Ctrl+Shift+E)", self)
            act_export_srt.triggered.connect(self.export_srt_requested.emit)
            menu.addAction(act_export_srt)

            menu.exec(self.table.viewport().mapToGlobal(pos))
            return

        self.show_context_menu_for_ids(sel_ids, self.table.viewport().mapToGlobal(pos))

    def show_context_menu_for_ids(self, comm_ids: List[str], global_pos: QPoint):
        if not comm_ids:
            return

        menu = QMenu(self)
        count = len(comm_ids)

        act_add = QAction("➕ Добавить комментарий на текущей позиции (Ctrl+T / Ins)", self)
        act_add.triggered.connect(self.add_commentary_requested.emit)
        menu.addAction(act_add)
        menu.addSeparator()

        if count == 1:
            cid = comm_ids[0]
            act_edit = QAction("✏️ Редактировать текст комментария (Enter)", self)
            act_edit.triggered.connect(lambda: self.edit_commentary_by_id(cid))
            menu.addAction(act_edit)

            act_dur = QAction("⏱️ Изменить продолжительность комментария...", self)
            act_dur.triggered.connect(lambda: self.change_duration_by_id(cid))
            menu.addAction(act_dur)

            menu.addSeparator()
            act_voice_sapi = QAction("🗣️ Озвучить комментарий (SAPI5)", self)
            act_voice_sapi.triggered.connect(lambda: self.commentaries_resynthesize_requested.emit([cid], "sapi5"))
            menu.addAction(act_voice_sapi)

            act_voice_gemini = QAction("🎙️ Озвучить комментарий (Gemini)", self)
            act_voice_gemini.triggered.connect(lambda: self.commentaries_resynthesize_requested.emit([cid], "gemini"))
            menu.addAction(act_voice_gemini)

            menu.addSeparator()
            act_del_audio = QAction("🗑️ Удалить озвучку (аудиофайл)... (Shift+Del)", self)
            act_del_audio.triggered.connect(lambda: self.delete_selected_audio([cid]))
            menu.addAction(act_del_audio)

            act_del = QAction("❌ Удалить комментарий и аудиозапись (Delete)", self)
            act_del.triggered.connect(lambda: self.delete_selected_commentaries([cid]))
            menu.addAction(act_del)
        else:
            act_voice_sapi = QAction(f"🗣️ Озвучить выбранные ({count} шт.) с помощью SAPI5", self)
            act_voice_sapi.triggered.connect(lambda: self.commentaries_resynthesize_requested.emit(comm_ids, "sapi5"))
            menu.addAction(act_voice_sapi)

            act_voice_gemini = QAction(f"🎙️ Озвучить выбранные ({count} шт.) с помощью Gemini", self)
            act_voice_gemini.triggered.connect(lambda: self.commentaries_resynthesize_requested.emit(comm_ids, "gemini"))
            menu.addAction(act_voice_gemini)

            menu.addSeparator()
            act_del_audio = QAction(f"🗑️ Удалить озвучку для выбранных ({count} шт.)... (Shift+Del)", self)
            act_del_audio.triggered.connect(lambda: self.delete_selected_audio(comm_ids))
            menu.addAction(act_del_audio)

            act_del = QAction(f"❌ Удалить выбранные ({count} шт.) комментарии и аудио... (Delete)", self)
            act_del.triggered.connect(lambda: self.delete_selected_commentaries(comm_ids))
            menu.addAction(act_del)

        menu.addSeparator()
        act_import_srt = QAction("📥 Импортировать комментарии из SRT... (Ctrl+I)", self)
        act_import_srt.triggered.connect(self.import_srt_requested.emit)
        menu.addAction(act_import_srt)

        act_export_srt = QAction("📄 Экспортировать комментарии в SRT... (Ctrl+Shift+E)", self)
        act_export_srt.triggered.connect(self.export_srt_requested.emit)
        menu.addAction(act_export_srt)

        menu.exec(global_pos)
