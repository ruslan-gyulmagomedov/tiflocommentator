# -*- coding: utf-8 -*-
"""
Интерактивный масштабируемый таймлайн тифлокомментариев:
- Визуальное отображение блоков комментариев
- Масштабирование шкалы времени колесом мыши с зажатой клавишей Ctrl (Ctrl + Mouse Wheel)
- Горизонтальная прокрутка колесом мыши в режиме приближения
- Перемещение курсора воспроизведения в любую точку таймлайна простым кликом мыши
- Перемещение блоков мышью по шкале времени (drag-and-drop с порогом смещения)
- Сжатие/растягивание блоков за правый край
- Двойной клик для редактирования текста комментария
- Контекстное меню для каждого комментария
"""

import os
from typing import List, Dict, Any, Optional, Tuple
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton, QMenu, QMessageBox
)
from PySide6.QtGui import QPainter, QColor, QPen, QBrush, QFont, QCursor, QAction
from PySide6.QtCore import Qt, QRectF, Signal, QPointF, QPoint

from ui.comment_edit_dialog import CommentEditDialog
from ui.comment_duration_dialog import CommentDurationDialog
from ui.accessible_dialogs import confirm_destructive


class VisualTimelineCanvas(QWidget):
    """Графический холст таймлайна с поддержкой масштабирования, выделения диапазона, drag-and-drop и контекстного меню."""

    seek_requested = Signal(int)
    play_pause_requested = Signal()
    commentary_moved = Signal(str, float, float)
    commentary_resized = Signal(str, float, float)
    commentary_double_clicked = Signal(str)
    context_menu_requested = Signal(str, QPoint)
    canvas_context_menu_requested = Signal(QPoint, float)
    zoom_changed = Signal(float)
    selection_changed = Signal(float, float)
    fragment_commentary_requested = Signal(float, float)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.commentaries: List[Dict[str, Any]] = []
        self.total_duration_sec: float = 100.0
        self.current_pos_sec: float = 0.0

        # Выделение диапазона на таймлайне
        self.sel_start_sec: Optional[float] = None
        self.sel_end_sec: Optional[float] = None
        self.is_selecting_range: bool = False
        self.range_select_origin_x: float = 0.0

        # Масштабирование и видимый диапазон
        self.zoom_level: float = 1.0       # от 1.0 (весь проект) до 50.0
        self.view_start_sec: float = 0.0

        self.dragging_comm_id: Optional[str] = None
        self.resizing_comm_id: Optional[str] = None
        self.drag_start_mouse_x = 0
        self.drag_orig_start = 0.0
        self.drag_orig_end = 0.0
        self.has_dragged = False
        self.max_speedup: float = 3.0

        self.setMinimumHeight(100)
        self.setMouseTracking(True)
        self.setFocusPolicy(Qt.StrongFocus)
        self.setAccessibleName("Графический таймлайн тифлокомментариев")
        self.setAccessibleDescription(
            "Интерактивная шкала времени с фокусом клавиатуры. "
            "Клавиши: Пробел — Воспроизведение/Пауза, "
            "I — точка входа выделения, O — точка выхода выделения, Esc — сброс выделения, "
            "Ctrl+Shift+G — комментировать выделенный фрагмент, "
            "PageUp/PageDown — на экран назад/вперед, "
            "Home/End — в начало/конец, "
            "Стрелки влево/вправо — перемотка на 5 секунд. "
            "Ctrl + Колесо мыши — масштабирование."
        )

    def set_in_point(self, pos_sec: Optional[float] = None):
        """Устанавливает точку входа (начало) выделенного диапазона."""
        p = self.current_pos_sec if pos_sec is None else max(0.0, float(pos_sec))
        self.sel_start_sec = round(p, 3)
        if self.sel_end_sec is not None and self.sel_end_sec <= self.sel_start_sec:
            self.sel_end_sec = round(min(self.total_duration_sec, self.sel_start_sec + 5.0), 3)
        self.selection_changed.emit(self.sel_start_sec, self.sel_end_sec or self.sel_start_sec)
        self.update()

    def set_out_point(self, pos_sec: Optional[float] = None):
        """Устанавливает точку выхода (конец) выделенного диапазона."""
        p = self.current_pos_sec if pos_sec is None else max(0.0, float(pos_sec))
        if self.sel_start_sec is None:
            self.sel_start_sec = 0.0
        if p < self.sel_start_sec:
            self.sel_start_sec, p = p, self.sel_start_sec
        self.sel_end_sec = round(p, 3)
        self.selection_changed.emit(self.sel_start_sec, self.sel_end_sec)
        self.update()

    def clear_selection(self):
        """Сбрасывает выделение диапазона на таймлайне."""
        self.sel_start_sec = None
        self.sel_end_sec = None
        self.is_selecting_range = False
        self.selection_changed.emit(0.0, 0.0)
        self.update()

    def get_selection(self) -> Optional[Tuple[float, float]]:
        """Возвращает (start_sec, end_sec) если выделен валидный диапазон."""
        if self.sel_start_sec is not None and self.sel_end_sec is not None:
            st = min(self.sel_start_sec, self.sel_end_sec)
            et = max(self.sel_start_sec, self.sel_end_sec)
            if et - st >= 0.1:
                return (st, et)
        return None

    def format_sec_short(self, sec: float) -> str:
        m, s = divmod(int(sec), 60)
        hh, m = divmod(m, 60)
        frac = int(round((sec - int(sec)) * 10))
        if hh > 0:
            return f"{hh:02d}:{m:02d}:{int(s):02d}"
        return f"{m:02d}:{int(s):02d}.{frac}"

    def set_duration(self, duration_sec: float):
        self.total_duration_sec = max(1.0, duration_sec)
        self.clamp_view()

    def set_max_speedup(self, val: float):
        """Устанавливает максимально допустимое ускорение речи для расчёта лимита ресайза."""
        self.max_speedup = max(1.0, float(val or 3.0))
        self.update()

    def set_position(self, pos_sec: float):
        pos_sec = max(0.0, pos_sec)
        if pos_sec > self.total_duration_sec:
            self.total_duration_sec = pos_sec
            self.clamp_view()
        self.current_pos_sec = pos_sec
        # Автоскролл за курсором при приближении
        if self.zoom_level > 1.0:
            vis_dur = self.total_duration_sec / self.zoom_level
            if pos_sec < self.view_start_sec or pos_sec > (self.view_start_sec + vis_dur):
                max_start = max(0.0, self.total_duration_sec - vis_dur)
                self.view_start_sec = max(0.0, min(max_start, pos_sec - vis_dur * 0.15))
        self.update()

    def set_commentaries(self, commentaries: List[Dict[str, Any]]):
        self.commentaries = commentaries or []
        self.update()

    def clamp_view(self):
        vis_dur = self.total_duration_sec / self.zoom_level
        max_start = max(0.0, self.total_duration_sec - vis_dur)
        self.view_start_sec = max(0.0, min(max_start, self.view_start_sec))

    def sec_to_x(self, sec: float) -> float:
        w = max(1.0, self.width() - 20.0)
        vis_dur = max(0.1, self.total_duration_sec / self.zoom_level)
        return 10.0 + ((sec - self.view_start_sec) / vis_dur) * w

    def x_to_sec(self, x: float) -> float:
        w = max(1.0, self.width() - 20.0)
        vis_dur = max(0.1, self.total_duration_sec / self.zoom_level)
        sec = self.view_start_sec + ((x - 10.0) / w) * vis_dur
        return max(0.0, min(self.total_duration_sec, sec))

    def get_comment_rect(self, comm: Dict[str, Any]) -> QRectF:
        st = float(comm.get("start_time") or 0.0)
        et = float(comm.get("end_time") or (st + 2.0))
        x1 = self.sec_to_x(st)
        x2 = max(x1 + 6.0, self.sec_to_x(et))
        return QRectF(x1, 35, max(6.0, x2 - x1), 55)

    def set_zoom(self, zoom: float, center_time: Optional[float] = None):
        new_zoom = max(1.0, min(50.0, zoom))
        if new_zoom == self.zoom_level and new_zoom == 1.0:
            return

        if center_time is None:
            center_time = self.current_pos_sec

        if new_zoom <= 1.0:
            self.zoom_level = 1.0
            self.view_start_sec = 0.0
        else:
            old_vis_dur = self.total_duration_sec / self.zoom_level
            new_vis_dur = self.total_duration_sec / new_zoom
            rel_pos = (center_time - self.view_start_sec) / old_vis_dur if old_vis_dur > 0 else 0.5
            rel_pos = max(0.0, min(1.0, rel_pos))
            self.zoom_level = new_zoom
            self.view_start_sec = center_time - rel_pos * new_vis_dur
            self.clamp_view()

        self.zoom_changed.emit(self.zoom_level)
        self.update()

    def wheelEvent(self, event):
        num_degrees = event.angleDelta().y() / 8.0
        num_steps = num_degrees / 15.0

        if event.modifiers() & Qt.ControlModifier:
            mouse_x = event.position().x()
            mouse_time = self.x_to_sec(mouse_x)

            factor = 1.25 ** num_steps
            new_zoom = max(1.0, min(50.0, self.zoom_level * factor))
            self.set_zoom(new_zoom, center_time=mouse_time)
            event.accept()
        else:
            if self.zoom_level > 1.0:
                vis_dur = self.total_duration_sec / self.zoom_level
                scroll_delta = -num_steps * (vis_dur * 0.1)
                max_start = max(0.0, self.total_duration_sec - vis_dur)
                self.view_start_sec = max(0.0, min(max_start, self.view_start_sec + scroll_delta))
                self.update()
                event.accept()
            else:
                super().wheelEvent(event)

    def _draw_comment_block(self, painter: QPainter, comm: Dict[str, Any], vis_dur: float, is_dragged: bool = False):
        st = float(comm.get("start_time") or 0.0)
        et = float(comm.get("end_time") or (st + 2.0))
        if et < self.view_start_sec or st > self.view_start_sec + vis_dur:
            return

        rect = self.get_comment_rect(comm)
        c_type = comm.get("type", "commentary")

        # Цвет блока в зависимости от типа
        if c_type == "title" or c_type == "subtitle":
            bg_color = QColor(60, 120, 200, 230 if is_dragged else 210)
            border_color = QColor(255, 255, 0) if is_dragged else QColor(100, 180, 255)
        elif c_type == "translated_speech":
            bg_color = QColor(180, 120, 40, 230 if is_dragged else 210)
            border_color = QColor(255, 255, 0) if is_dragged else QColor(255, 180, 60)
        else:
            bg_color = QColor(35, 140, 95, 230 if is_dragged else 210)
            border_color = QColor(255, 255, 0) if is_dragged else QColor(70, 220, 140)

        painter.setBrush(QBrush(bg_color))
        painter.setPen(QPen(border_color, 2.5 if is_dragged else 1.5))
        painter.drawRoundedRect(rect, 4, 4)

        # Правый край (ручка изменения размера)
        painter.setBrush(QBrush(QColor(255, 255, 0 if is_dragged else 255, 200)))
        painter.drawRect(QRectF(rect.right() - 5, rect.top() + 4, 4, rect.height() - 8))

        # Текст комментария
        painter.setPen(QColor(255, 255, 255))
        text = comm.get("text", "")
        painter.drawText(rect.adjusted(6, 4, -8, -4), Qt.AlignLeft | Qt.AlignVCenter | Qt.TextSingleLine, text)

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)

        w = self.width()
        h = self.height()

        # Фоновая заливка
        painter.fillRect(0, 0, w, h, QColor(25, 27, 33))

        vis_dur = max(0.1, self.total_duration_sec / self.zoom_level)

        # Отрисовка выделенного диапазона времени
        sel = self.get_selection()
        if sel:
            sel_st, sel_et = sel
            if sel_et >= self.view_start_sec and sel_st <= self.view_start_sec + vis_dur:
                sel_x1 = max(0.0, self.sec_to_x(sel_st))
                sel_x2 = min(float(w), self.sec_to_x(sel_et))
                painter.fillRect(QRectF(sel_x1, 0, max(2.0, sel_x2 - sel_x1), h), QColor(0, 180, 255, 55))
                painter.setPen(QPen(QColor(0, 220, 255), 2, Qt.DashLine))
                painter.drawLine(int(sel_x1), 0, int(sel_x1), h)
                painter.drawLine(int(sel_x2), 0, int(sel_x2), h)
                painter.setPen(QColor(0, 255, 220))
                painter.setFont(QFont("Segoe UI", 8, QFont.Bold))
                painter.drawText(int(sel_x1) + 4, 15, f"[In: {self.format_sec_short(sel_st)}]")
                painter.drawText(int(sel_x2) - 60, 15, f"[Out: {self.format_sec_short(sel_et)}]")

        # Шкала времени
        painter.setPen(QPen(QColor(100, 100, 115), 1))
        painter.drawLine(10, 25, w - 10, 25)

        # Адаптивные метки времени
        font = QFont("Segoe UI", 8)
        painter.setFont(font)
        painter.setPen(QColor(180, 185, 195))

        raw_step = vis_dur / 8.0
        possible_steps = [0.1, 0.2, 0.5, 1.0, 2.0, 5.0, 10.0, 15.0, 30.0, 60.0, 120.0, 300.0, 600.0, 1800.0, 3600.0]
        step_sec = possible_steps[-1]
        for s in possible_steps:
            if s >= raw_step:
                step_sec = s
                break

        t = (int(self.view_start_sec / step_sec)) * step_sec
        end_t = self.view_start_sec + vis_dur
        while t <= end_t + step_sec:
            if 0.0 <= t <= self.total_duration_sec:
                x = self.sec_to_x(t)
                if 8 <= x <= w - 8:
                    painter.drawLine(int(x), 20, int(x), 25)
                    m, s = divmod(int(t), 60)
                    hh, m = divmod(m, 60)
                    if step_sec < 1.0:
                        frac = int(round((t - int(t)) * 10))
                        time_str = f"{m:02d}:{int(s):02d}.{frac}"
                    elif hh > 0:
                        time_str = f"{hh:02d}:{m:02d}:{int(s):02d}"
                    else:
                        time_str = f"{m:02d}:{int(s):02d}"
                    painter.drawText(int(x) - 22, 15, time_str)
            t += step_sec

        # Отрисовка блоков тифлокомментариев (перетаскиваемый рисуется поверх остальных)
        dragged_comm = None
        for comm in self.commentaries:
            if comm.get("id") == self.dragging_comm_id and self.has_dragged:
                dragged_comm = comm
                continue
            self._draw_comment_block(painter, comm, vis_dur, is_dragged=False)

        if dragged_comm:
            self._draw_comment_block(painter, dragged_comm, vis_dur, is_dragged=True)

        # Текущий указатель воспроизведения (красная линия)
        if self.view_start_sec <= self.current_pos_sec <= self.view_start_sec + vis_dur:
            play_x = self.sec_to_x(self.current_pos_sec)
            painter.setPen(QPen(QColor(255, 50, 50), 2))
            painter.drawLine(int(play_x), 5, int(play_x), h - 5)
            painter.setBrush(QBrush(QColor(255, 50, 50)))
            painter.drawPolygon([QPointF(play_x - 5, 5), QPointF(play_x + 5, 5), QPointF(play_x, 15)])

        # Высококонтрастная рамка фокуса клавиатуры
        if self.hasFocus():
            painter.setPen(QPen(QColor(255, 255, 0), 2))
            painter.setBrush(Qt.NoBrush)
            painter.drawRect(1, 1, w - 2, h - 2)

    def mousePressEvent(self, event):
        self.setFocus(Qt.MouseFocusReason)
        if event.button() == Qt.LeftButton:
            x = event.position().x()
            sec = self.x_to_sec(x)

            self.dragging_comm_id = None
            self.resizing_comm_id = None
            self.has_dragged = False

            # Выделение диапазона с зажатым Shift
            if event.modifiers() & Qt.ShiftModifier:
                self.is_selecting_range = True
                self.range_select_origin_x = x
                self.sel_start_sec = sec
                self.sel_end_sec = sec
                self.selection_changed.emit(self.sel_start_sec, self.sel_end_sec)
                self.update()
                return

            # Проверяем клик по блокам комментариев для возможного перетаскивания/ресайза
            for comm in reversed(self.commentaries):
                rect = self.get_comment_rect(comm)
                if rect.contains(event.position()):
                    if abs(x - rect.right()) <= 8:
                        self.resizing_comm_id = comm.get("id")
                    else:
                        self.dragging_comm_id = comm.get("id")
                    self.drag_start_mouse_x = x
                    self.drag_orig_start = float(comm.get("start_time", 0.0))
                    self.drag_orig_end = float(comm.get("end_time", 0.0))
                    break

            # Если кликнули мимо блоков комментариев, перемещаем курсор воспроизведения
            if not self.dragging_comm_id and not self.resizing_comm_id:
                self.seek_requested.emit(int(sec * 1000))

    def mouseMoveEvent(self, event):
        x = event.position().x()
        if self.is_selecting_range:
            t1 = self.x_to_sec(self.range_select_origin_x)
            t2 = self.x_to_sec(x)
            self.sel_start_sec = round(min(t1, t2), 3)
            self.sel_end_sec = round(max(t1, t2), 3)
            self.selection_changed.emit(self.sel_start_sec, self.sel_end_sec)
            self.update()
            return

        if self.resizing_comm_id:
            if not self.has_dragged and abs(x - self.drag_start_mouse_x) > 3:
                self.has_dragged = True
            if self.has_dragged:
                new_end = self.x_to_sec(x)
                # Определяем минимально допустимую длительность с учетом лимита ускорения речи max_speedup
                target_comm = next((c for c in self.commentaries if c.get("id") == self.resizing_comm_id), None)
                raw_dur = float(target_comm.get("raw_duration_sec") or 0.0) if target_comm else 0.0
                if raw_dur > 0.0 and self.max_speedup > 0.0:
                    min_dur = max(0.2, round(raw_dur / self.max_speedup, 3))
                else:
                    min_dur = 0.2

                new_end = max(self.drag_orig_start + min_dur, new_end)
                for c in self.commentaries:
                    if c.get("id") == self.resizing_comm_id:
                        c["end_time"] = round(new_end, 3)
                        c["duration_sec"] = round(new_end - self.drag_orig_start, 3)
                        break
                self.update()
        elif self.dragging_comm_id:
            if not self.has_dragged and abs(x - self.drag_start_mouse_x) > 3:
                self.has_dragged = True
            if self.has_dragged:
                delta_sec = self.x_to_sec(x) - self.x_to_sec(self.drag_start_mouse_x)
                dur = self.drag_orig_end - self.drag_orig_start
                new_start = max(0.0, self.drag_orig_start + delta_sec)
                new_end = new_start + dur
                for c in self.commentaries:
                    if c.get("id") == self.dragging_comm_id:
                        c["start_time"] = round(new_start, 3)
                        c["end_time"] = round(new_end, 3)
                        c["duration_sec"] = round(dur, 3)
                        break
                self.update()
        else:
            hover_resize = False
            for comm in self.commentaries:
                rect = self.get_comment_rect(comm)
                if rect.contains(event.position()) and abs(x - rect.right()) <= 8:
                    hover_resize = True
                    break
            self.setCursor(Qt.SizeHorCursor if hover_resize else Qt.ArrowCursor)

    def mouseReleaseEvent(self, event):
        if event.button() == Qt.LeftButton:
            if self.is_selecting_range:
                self.is_selecting_range = False
                if self.sel_start_sec is not None and self.sel_end_sec is not None:
                    if abs(self.sel_end_sec - self.sel_start_sec) < 0.1:
                        self.clear_selection()
                    else:
                        self.selection_changed.emit(self.sel_start_sec, self.sel_end_sec)
            elif self.resizing_comm_id and self.has_dragged:
                target = next((c for c in self.commentaries if c.get("id") == self.resizing_comm_id), None)
                if target:
                    self.commentary_resized.emit(
                        self.resizing_comm_id,
                        float(target.get("start_time", 0.0)),
                        float(target.get("end_time", 0.0))
                    )
            elif self.dragging_comm_id and self.has_dragged:
                target = next((c for c in self.commentaries if c.get("id") == self.dragging_comm_id), None)
                if target:
                    self.commentary_moved.emit(
                        self.dragging_comm_id,
                        float(target.get("start_time", 0.0)),
                        float(target.get("end_time", 0.0))
                    )
            elif not self.has_dragged:
                sec = self.x_to_sec(event.position().x())
                self.seek_requested.emit(int(sec * 1000))

        self.dragging_comm_id = None
        self.resizing_comm_id = None
        self.has_dragged = False

    def mouseDoubleClickEvent(self, event):
        for comm in self.commentaries:
            rect = self.get_comment_rect(comm)
            if rect.contains(event.position()):
                self.commentary_double_clicked.emit(comm.get("id"))
                break

    def contextMenuEvent(self, event):
        pos = event.pos()
        sec = self.x_to_sec(pos.x())
        for comm in reversed(self.commentaries):
            rect = self.get_comment_rect(comm)
            if rect.contains(QPointF(pos)):
                self.context_menu_requested.emit(comm.get("id"), event.globalPos())
                event.accept()
                return
        self.canvas_context_menu_requested.emit(event.globalPos(), sec)
        event.accept()

    def keyPressEvent(self, event):
        key = event.key()
        modifiers = event.modifiers()
        if key == Qt.Key_Space:
            self.play_pause_requested.emit()
            event.accept()
            return
        elif key == Qt.Key_I or key == Qt.Key_BracketLeft:
            self.set_in_point(self.current_pos_sec)
            event.accept()
            return
        elif key == Qt.Key_O or key == Qt.Key_BracketRight:
            self.set_out_point(self.current_pos_sec)
            event.accept()
            return
        elif key == Qt.Key_Escape:
            self.clear_selection()
            event.accept()
            return
        elif key == Qt.Key_G and (modifiers & Qt.ShiftModifier) and (modifiers & Qt.ControlModifier):
            sel = self.get_selection()
            if sel:
                self.fragment_commentary_requested.emit(sel[0], sel[1])
            event.accept()
            return
        elif key == Qt.Key_PageUp:
            vis_dur = max(0.1, self.total_duration_sec / self.zoom_level)
            if self.zoom_level <= 1.001 or vis_dur >= self.total_duration_sec:
                new_pos = 0.0
                self.view_start_sec = 0.0
            else:
                new_pos = max(0.0, self.current_pos_sec - vis_dur)
                self.view_start_sec = max(0.0, self.view_start_sec - vis_dur)
                self.clamp_view()
            self.set_position(new_pos)
            self.seek_requested.emit(int(new_pos * 1000))
            event.accept()
            return
        elif key == Qt.Key_PageDown:
            vis_dur = max(0.1, self.total_duration_sec / self.zoom_level)
            if self.zoom_level <= 1.001 or vis_dur >= self.total_duration_sec:
                new_pos = self.total_duration_sec
                self.clamp_view()
            else:
                new_pos = min(self.total_duration_sec, self.current_pos_sec + vis_dur)
                self.view_start_sec = min(max(0.0, self.total_duration_sec - vis_dur), self.view_start_sec + vis_dur)
                self.clamp_view()
            self.set_position(new_pos)
            self.seek_requested.emit(int(new_pos * 1000))
            event.accept()
            return
        elif key == Qt.Key_Home:
            new_pos = 0.0
            self.view_start_sec = 0.0
            self.set_position(new_pos)
            self.seek_requested.emit(0)
            event.accept()
            return
        elif key == Qt.Key_End:
            new_pos = self.total_duration_sec
            if self.zoom_level > 1.0:
                vis_dur = self.total_duration_sec / self.zoom_level
                self.view_start_sec = max(0.0, self.total_duration_sec - vis_dur)
            self.set_position(new_pos)
            self.seek_requested.emit(int(new_pos * 1000))
            event.accept()
            return
        elif key == Qt.Key_Left:
            step = 1.0 if (event.modifiers() & Qt.ShiftModifier) else 5.0
            new_pos = max(0.0, self.current_pos_sec - step)
            self.set_position(new_pos)
            self.seek_requested.emit(int(new_pos * 1000))
            event.accept()
            return
        elif key == Qt.Key_Right:
            step = 1.0 if (event.modifiers() & Qt.ShiftModifier) else 5.0
            new_pos = min(self.total_duration_sec, self.current_pos_sec + step)
            self.set_position(new_pos)
            self.seek_requested.emit(int(new_pos * 1000))
            event.accept()
            return
        super().keyPressEvent(event)



class AccessibleTimelineWidget(QWidget):
    """
    Интерактивный виджет таймлайна с панелью масштабирования, выделением фрагментов и контекстным меню.
    """

    seek_requested = Signal(int)
    play_pause_requested = Signal()
    commentary_timing_changed = Signal(str)           # comm_id при изменении длительности/границ
    commentary_moved = Signal(str, float, float)      # comm_id, new_start, new_end
    commentary_resized = Signal(str, float, float)    # comm_id, new_start, new_end
    commentary_text_edited = Signal(str)              # comm_id при изменении текста
    commentary_updated = Signal(str)                  # comm_id (обратная совместимость)
    commentary_deleted = Signal(str)                  # comm_id
    commentaries_deleted = Signal(list)               # List[str]
    commentary_audio_deleted = Signal(list)           # List[str]
    commentaries_resynthesize_requested = Signal(list, str)   # (List[str], engine_type)
    add_commentary_requested = Signal()
    fragment_commentary_requested = Signal(float, float)      # (start_sec, end_sec)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.commentaries: List[Dict[str, Any]] = []
        self.max_speedup: float = 3.0
        self.init_ui()

    def set_max_speedup(self, val: float):
        """Устанавливает максимальный лимит разгона речи для контроля границ."""
        self.max_speedup = max(1.0, float(val or 3.0))
        self.canvas.set_max_speedup(val)

    def init_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(2)

        # Визуальный масштабируемый холст таймлайна
        self.canvas = VisualTimelineCanvas(self)
        self.canvas.seek_requested.connect(self.seek_requested.emit)
        self.canvas.play_pause_requested.connect(self.play_pause_requested.emit)
        self.canvas.commentary_moved.connect(self.on_commentary_moved)
        self.canvas.commentary_resized.connect(self.on_commentary_resized)
        self.canvas.commentary_double_clicked.connect(self.edit_commentary_by_id)
        self.canvas.context_menu_requested.connect(self.show_canvas_context_menu)
        self.canvas.canvas_context_menu_requested.connect(self.show_empty_context_menu)
        self.canvas.zoom_changed.connect(self.on_zoom_changed)
        self.canvas.selection_changed.connect(self.on_selection_changed)
        self.canvas.fragment_commentary_requested.connect(self.fragment_commentary_requested.emit)
        layout.addWidget(self.canvas, 1)

        # Нижняя строка управления масштабом и выделением фрагментов
        bar_layout = QHBoxLayout()
        bar_layout.setContentsMargins(8, 2, 8, 2)
        bar_layout.setSpacing(6)

        self.btn_comment_fragment = QPushButton("🎬 Прокомментировать фрагмент (Ctrl+Shift+G)", self)
        self.btn_comment_fragment.setEnabled(False)
        self.btn_comment_fragment.setStyleSheet(
            "QPushButton { font-weight: bold; font-size: 11px; padding: 2px 8px; min-height: 24px; "
            "background-color: #007755; color: #FFFFFF; border: 1px solid #00AA77; border-radius: 4px; } "
            "QPushButton:disabled { background-color: #2a2a2a; color: #666666; border-color: #444444; } "
            "QPushButton:hover:!disabled { background-color: #009966; }"
        )
        self.btn_comment_fragment.setAccessibleName("Кнопка Прокомментировать выделенный фрагмент видео")
        self.btn_comment_fragment.clicked.connect(self.on_comment_fragment_clicked)
        bar_layout.addWidget(self.btn_comment_fragment)

        self.lbl_selection = QLabel("Фрагмент не выделен (Shift+Мышь или I / O)", self)
        self.lbl_selection.setStyleSheet("font-size: 11px; color: #88CCFF;")
        self.lbl_selection.setAccessibleName("Информация о выделенном диапазоне")
        bar_layout.addWidget(self.lbl_selection)

        self.btn_clear_selection = QPushButton("❌ Сбросить", self)
        self.btn_clear_selection.setEnabled(False)
        self.btn_clear_selection.setFixedHeight(24)
        self.btn_clear_selection.setStyleSheet("font-size: 11px; padding: 2px 6px;")
        self.btn_clear_selection.clicked.connect(self.canvas.clear_selection)
        bar_layout.addWidget(self.btn_clear_selection)

        bar_layout.addStretch(1)

        self.lbl_zoom = QLabel("🔍 1.0x", self)
        self.lbl_zoom.setStyleSheet("font-weight: bold; font-size: 12px; color: #00FFCC;")
        bar_layout.addWidget(self.lbl_zoom)

        btn_zoom_out = QPushButton("➖", self)
        btn_zoom_out.setFixedSize(26, 22)
        btn_zoom_out.clicked.connect(lambda: self.canvas.set_zoom(self.canvas.zoom_level / 1.3))
        bar_layout.addWidget(btn_zoom_out)

        btn_zoom_reset = QPushButton("100%", self)
        btn_zoom_reset.setFixedHeight(22)
        btn_zoom_reset.setStyleSheet("padding: 2px 6px; font-size: 11px;")
        btn_zoom_reset.clicked.connect(lambda: self.canvas.set_zoom(1.0))
        bar_layout.addWidget(btn_zoom_reset)

        btn_zoom_in = QPushButton("➕", self)
        btn_zoom_in.setFixedSize(26, 22)
        btn_zoom_in.clicked.connect(lambda: self.canvas.set_zoom(self.canvas.zoom_level * 1.3))
        bar_layout.addWidget(btn_zoom_in)

        layout.addLayout(bar_layout)

    def on_zoom_changed(self, zoom: float):
        self.lbl_zoom.setText(f"🔍 {zoom:.1f}x")

    def on_selection_changed(self, start_sec: float, end_sec: float):
        dur = max(0.0, end_sec - start_sec)
        if dur >= 0.1:
            st_str = self.canvas.format_sec_short(start_sec)
            et_str = self.canvas.format_sec_short(end_sec)
            self.lbl_selection.setText(f"🎬 {st_str} — {et_str} ({dur:.1f}с)")
            self.btn_comment_fragment.setEnabled(True)
            self.btn_clear_selection.setEnabled(True)
        else:
            self.lbl_selection.setText("Фрагмент не выделен (Shift+Мышь или I / O)")
            self.btn_comment_fragment.setEnabled(False)
            self.btn_clear_selection.setEnabled(False)

    def on_comment_fragment_clicked(self):
        sel = self.canvas.get_selection()
        if sel:
            self.fragment_commentary_requested.emit(sel[0], sel[1])

    def set_duration(self, duration_sec: float):
        self.canvas.set_duration(duration_sec)

    def set_position(self, pos_sec: float):
        self.canvas.set_position(pos_sec)

    def set_commentaries(self, commentaries: List[Dict[str, Any]]):
        self.commentaries = commentaries or []
        self.canvas.set_commentaries(self.commentaries)

    def refresh_table(self):
        self.canvas.update()

    def on_commentary_moved(self, comm_id: str, new_start: float, new_end: float):
        for c in self.commentaries:
            if c.get("id") == comm_id:
                c["start_time"] = round(new_start, 3)
                c["end_time"] = round(new_end, 3)
                c["duration_sec"] = round(new_end - new_start, 3)
                self.commentary_moved.emit(comm_id, new_start, new_end)
                break
        self.refresh_table()

    def on_commentary_resized(self, comm_id: str, new_start: float, new_end: float):
        for c in self.commentaries:
            if c.get("id") == comm_id:
                c["start_time"] = round(new_start, 3)
                c["end_time"] = round(new_end, 3)
                c["duration_sec"] = round(new_end - new_start, 3)
                self.commentary_resized.emit(comm_id, new_start, new_end)
                self.commentary_timing_changed.emit(comm_id)
                break
        self.refresh_table()

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
                self.canvas.update()

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
            self.commentary_resized.emit(comm_id, st, new_end)
            self.commentary_timing_changed.emit(comm_id)
            self.refresh_table()
            self.canvas.update()

    def delete_selected_audio(self, selected_ids: Optional[List[str]] = None):
        target_ids = selected_ids or []
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
        target_ids = selected_ids or []
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

    def show_canvas_context_menu(self, comm_id: str, global_pos: QPoint):
        self.show_context_menu_for_ids([comm_id], global_pos)

    def show_empty_context_menu(self, global_pos: QPoint, sec: float):
        menu = QMenu(self)
        sel = self.canvas.get_selection()
        if sel:
            st_str = self.canvas.format_sec_short(sel[0])
            et_str = self.canvas.format_sec_short(sel[1])
            act_frag = QAction(f"🎬 Прокомментировать выделенный фрагмент ({st_str} — {et_str}) (Ctrl+Shift+G)", self)
            act_frag.triggered.connect(lambda: self.fragment_commentary_requested.emit(sel[0], sel[1]))
            menu.addAction(act_frag)

            act_clr = QAction("❌ Сбросить выделение фрагмента (Esc)", self)
            act_clr.triggered.connect(self.canvas.clear_selection)
            menu.addAction(act_clr)
            menu.addSeparator()

        act_in = QAction(f"📍 Установить точку начала фрагмента [In] ({self.canvas.format_sec_short(sec)}) (I)", self)
        act_in.triggered.connect(lambda: self.canvas.set_in_point(sec))
        menu.addAction(act_in)

        act_out = QAction(f"📍 Установить точку конца фрагмента [Out] ({self.canvas.format_sec_short(sec)}) (O)", self)
        act_out.triggered.connect(lambda: self.canvas.set_out_point(sec))
        menu.addAction(act_out)
        menu.addSeparator()

        act_add = QAction("➕ Добавить комментарий на текущей позиции (Ctrl+T / Ins)", self)
        act_add.triggered.connect(self.add_commentary_requested.emit)
        menu.addAction(act_add)

        menu.exec(global_pos)

    def show_context_menu_for_ids(self, comm_ids: List[str], global_pos: QPoint):
        if not comm_ids:
            return

        menu = QMenu(self)
        count = len(comm_ids)

        sel = self.canvas.get_selection()
        if sel:
            st_str = self.canvas.format_sec_short(sel[0])
            et_str = self.canvas.format_sec_short(sel[1])
            act_frag = QAction(f"🎬 Прокомментировать выделенный фрагмент ({st_str} — {et_str}) (Ctrl+Shift+G)", self)
            act_frag.triggered.connect(lambda: self.fragment_commentary_requested.emit(sel[0], sel[1]))
            menu.addAction(act_frag)

            act_clr = QAction("❌ Сбросить выделение фрагмента (Esc)", self)
            act_clr.triggered.connect(self.canvas.clear_selection)
            menu.addAction(act_clr)
            menu.addSeparator()

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

        menu.exec(global_pos)

