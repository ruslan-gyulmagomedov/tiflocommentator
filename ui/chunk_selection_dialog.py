# -*- coding: utf-8 -*-
"""
Диалог списка всех частей видео проекта:
- Показывает, для каких частей уже созданы тифлокомментарии, а для каких нет
- Позволяет запустить создание/пересоздание комментариев для любой выбранной части
- При пересоздании части старые комментарии только этой части удаляются
Полная доступность для NVDA / JAWS.
"""

import os
from typing import List, Optional, Tuple

from PySide6.QtWidgets import (
    QDialog,
    QVBoxLayout,
    QHBoxLayout,
    QLabel,
    QTableWidget,
    QTableWidgetItem,
    QPushButton,
    QMessageBox,
    QHeaderView,
    QAbstractItemView,
)
from PySide6.QtCore import Qt

from core.audio_dsp import format_duration_sec
from core.video_splitter import (
    plan_chunk_boundaries,
    analyze_media,
    repair_legacy_chunk_timing,
)


class ChunkSelectionDialog(QDialog):
    """
    Список частей видео с их статусом тифлокомментирования.

    По закрытии диалога вызывающий код читает generate_indices — номера
    частей, выбранных для создания или пересоздания комментариев.
    """

    def __init__(self, project, parent=None):
        super().__init__(parent)
        self.project = project
        self.generate_indices: List[int] = []
        self.generate_all_requested = False
        self._rows: List[Tuple[int, float, float, str, int, bool, bool]] = []

        self.setWindowTitle(f"Части видео — «{project.name}»")
        self.setAccessibleName("Список частей видео проекта и статус их тифлокомментирования")
        self.setAccessibleDescription(
            "Таблица показывает все части видео. Для каждой части указано, "
            "созданы ли для неё тифлокомментарии. Можно выбрать часть и создать "
            "или пересоздать комментарии только для неё."
        )
        self.resize(860, 480)
        self.setModal(True)

        repair_legacy_chunk_timing(project)
        self._build_rows()
        self._init_ui()

    def _count_comments_for(self, start_sec: float, end_sec: float, chunk_idx: int) -> int:
        """Считает комментарии, относящиеся к указанной части."""
        count = 0
        for c in self.project.data.get('commentaries', []):
            c_idx = c.get('chunk_index')
            if c_idx is not None:
                if int(c_idx) == chunk_idx:
                    count += 1
                continue
            st = float(c.get('start_time', 0.0) or 0.0)
            if start_sec <= st < max(start_sec + 0.1, end_sec):
                count += 1
        return count

    def _build_rows(self):
        """Строит строки из реальных частей или из плана нарезки."""
        self._rows = []
        chunks = self.project.chunks

        if chunks:
            for idx, ch in enumerate(chunks, start=1):
                st = float(ch.get('start_time_sec', 0.0) or 0.0)
                et = float(ch.get('end_time_sec', 0.0) or 0.0)
                if et <= st:
                    et = st + float(ch.get('duration_sec', 0.0) or 0.0)
                count = self._count_comments_for(st, et, idx)
                exists = os.path.isfile(ch.get('filepath', '') or '')
                name = ch.get('filename') or f"part_{idx:03d}"
                processed = bool(ch.get('processed'))
                self._rows.append((idx, st, et, name, count, exists, processed))
            return

        total = float(self.project.data.get('total_duration_sec', 0.0) or 0.0)
        src = self.project.data.get('src_video_path', '')
        if total <= 0 and src and os.path.isfile(src):
            total = analyze_media(src).duration
        chunk_min = float(self.project.data.get('chunk_duration_minutes', 50) or 50)
        chunk_sec = max(1.0, chunk_min * 60.0)

        boundaries = []
        try:
            boundaries = plan_chunk_boundaries(src, chunk_sec, total_duration=total)
        except Exception:
            boundaries = []

        if not boundaries:
            boundaries = [0.0, total if total > 0 else 1.0]

        for i in range(len(boundaries) - 1):
            idx = i + 1
            st = float(boundaries[i])
            et = float(boundaries[i + 1])
            count = self._count_comments_for(st, et, idx)
            self._rows.append((idx, st, et, f"part_{idx:03d} (план)", count, False, False))

    def _init_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(14, 12, 14, 12)
        layout.setSpacing(10)

        title = QLabel(f"Части видео проекта «{self.project.name}»:", self)
        title.setStyleSheet("font-size: 15px; font-weight: bold;")
        title.setAccessibleName("Заголовок списка частей видео")
        layout.addWidget(title)

        hint = QLabel(
            "Для части с уже созданными комментариями при пересоздании старые "
            "комментарии этой части будут удалены и созданы заново. "
            "Комментарии других частей не затрагиваются.",
            self,
        )
        hint.setWordWrap(True)
        hint.setStyleSheet("font-size: 12px; color: #B0C4DE;")
        hint.setAccessibleName("Пояснение о пересоздании комментариев выбранной части")
        layout.addWidget(hint)

        self.table = QTableWidget(self)
        self.table.setColumnCount(6)
        self.table.setHorizontalHeaderLabels([
            '№ части', 'Начало', 'Конец', 'Длительность',
            'Тифлокомментарии', 'Файл части',
        ])
        self.table.horizontalHeader().setSectionResizeMode(5, QHeaderView.Stretch)
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SingleSelection)
        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.table.setAccessibleName("Таблица частей видео")
        self.table.setAccessibleDescription(
            "Столбцы: номер части, начало, конец, длительность, наличие "
            "тифлокомментариев и имя файла части. Выберите строку стрелками "
            "вверх и вниз."
        )
        self.table.itemSelectionChanged.connect(self._update_buttons)
        self.table.itemDoubleClicked.connect(lambda _item: self._generate_selected())
        layout.addWidget(self.table, 1)

        self.lbl_status = QLabel("", self)
        self.lbl_status.setStyleSheet("font-size: 12px; color: #AAAAAA;")
        self.lbl_status.setAccessibleName("Сводная информация по частям")
        layout.addWidget(self.lbl_status)

        self.table.setRowCount(len(self._rows))
        for row, (idx, st, et, name, count, exists, processed) in enumerate(self._rows):
            if count > 0:
                status = f"Есть ({count})"
            elif processed:
                status = "Обработана (0 комм.)"
            elif exists:
                status = "Нет"
            else:
                status = "Не нарезана"
            values = [
                str(idx),
                format_duration_sec(st),
                format_duration_sec(et),
                format_duration_sec(max(0.0, et - st)),
                status,
                name,
            ]
            for col, val in enumerate(values):
                item = QTableWidgetItem(val)
                item.setFlags(item.flags() & ~Qt.ItemIsEditable)
                self.table.setItem(row, col, item)

        if self._rows:
            self.table.selectRow(0)

        total_chunks = len(self._rows)
        done = sum(1 for r in self._rows if r[4] > 0)
        self.lbl_status.setText(
            f"Всего частей: {total_chunks}. С комментариями: {done}. "
            f"Без комментариев: {total_chunks - done}."
        )

        buttons = QHBoxLayout()
        self.btn_selected = QPushButton('Создать для выбранной части', self)
        self.btn_selected.setAccessibleName(
            'Создать или пересоздать тифлокомментарии для выбранной части'
        )
        self.btn_selected.clicked.connect(self._generate_selected)

        self.btn_all = QPushButton('Создать для всех необработанных', self)
        self.btn_all.setAccessibleName(
            'Создать тифлокомментарии для всех необработанных частей'
        )
        self.btn_all.clicked.connect(self._generate_all)

        self.btn_close = QPushButton('Закрыть', self)
        self.btn_close.setAccessibleName('Закрыть список частей видео')
        self.btn_close.clicked.connect(self.reject)

        buttons.addWidget(self.btn_selected)
        buttons.addWidget(self.btn_all)
        buttons.addStretch(1)
        buttons.addWidget(self.btn_close)
        layout.addLayout(buttons)

        self._update_buttons()

    def _update_buttons(self):
        """Кнопка выбранной части активна только при выделенной строке."""
        if hasattr(self, 'btn_selected'):
            self.btn_selected.setEnabled(self.table.currentRow() >= 0)

    def _generate_selected(self):
        """Запускает создание комментариев для выделенной части."""
        row = self.table.currentRow()
        if row < 0 or row >= len(self._rows):
            return

        idx, st, et, name, count, exists, processed = self._rows[row]

        if count > 0:
            reply = QMessageBox.question(
                self,
                'Пересоздать часть',
                f"Для части № {idx} уже есть комментариев: {count}.\n\n"
                "Они будут удалены, и для этой части будут созданы новые.\n"
                "Комментарии остальных частей останутся без изменений.\n\n"
                "Продолжить?",
                QMessageBox.Yes | QMessageBox.No,
                QMessageBox.No,
            )
            if reply != QMessageBox.Yes:
                return

        self.generate_indices = [idx]
        self.accept()

    def _generate_all(self):
        """Запускает создание комментариев для всех частей без комментариев."""
        pending = [r for r in self._rows if r[4] == 0]
        if not pending:
            QMessageBox.information(
                self,
                'Все части обработаны',
                "Для всех частей уже есть тифлокомментарии.\n"
                "Чтобы пересоздать конкретную часть, выберите её в таблице.",
            )
            return

        self.generate_indices = [int(r[0]) for r in pending]
        self.accept()
