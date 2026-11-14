# -*- coding: utf-8 -*-
"""
Диалоговое окно списка проектов:
- Просмотр всех созданных проектов, их статусов и количества комментариев
- Создание нового проекта с запросом имени и выбором видеофайла
- Открытие любого проекта для предпросмотра и редактирования
- Возможность запустить продолжение тифлокомментирования незавершенного проекта
- Удаление проектов
Полная доступность для NVDA/JAWS.
"""

import os
import time
from typing import Optional
from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QTableWidget, QTableWidgetItem,
    QPushButton, QFileDialog, QInputDialog, QMessageBox, QHeaderView, QAbstractItemView
)
from PySide6.QtCore import Qt

from ui.accessible_dialogs import confirm_destructive
from core.project_manager import ProjectManager, Project
from core.video_splitter import analyze_media, split_video_into_chunks
from ui.video_preparation_dialog import VideoPreparationProgressDialog


class ProjectListDialog(QDialog):
    """Диалог управления проектами тифлокомментирования."""

    def __init__(self, project_manager: ProjectManager, config_manager, parent=None):
        super().__init__(parent)
        self.project_mgr = project_manager
        self.config = config_manager
        self.selected_project: Optional[Project] = None
        self.resume_requested = False

        self.setWindowTitle("Менеджер проектов тифлокомментирования")
        self.resize(800, 450)
        self.setModal(True)

        self.init_ui()
        self.refresh_projects_table()

    def init_ui(self):
        main_layout = QVBoxLayout(self)

        lbl = QLabel("Список всех проектов тифлокомментирования:", self)
        lbl.setAccessibleName("Список всех проектов тифлокомментирования")
        main_layout.addWidget(lbl)

        self.table = QTableWidget(self)
        self.table.setColumnCount(6)
        self.table.setHorizontalHeaderLabels([
            "Название проекта", "Статус", "Комментариев", "Персонажей", "Частей", "Изменен"
        ])
        self.table.horizontalHeader().setSectionResizeMode(0, QHeaderView.Stretch)
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SingleSelection)
        self.table.setAccessibleName("Таблица проектов")
        self.table.setAccessibleDescription(
            "Используйте стрелки вверх и вниз для выбора проекта. Tab переводит фокус на кнопки под таблицей."
        )
        # Tab должен выходить из таблицы, а не перебирать ячейки — иначе
        # скринридер не может покинуть список.
        self.table.setTabKeyNavigation(False)
        self.table.setFocusPolicy(Qt.StrongFocus)
        self.table.itemDoubleClicked.connect(self.open_selected_project)
        main_layout.addWidget(self.table)

        btn_layout = QHBoxLayout()

        self.btn_new = QPushButton("Создать новый проект...", self)
        self.btn_new.setAccessibleName("Кнопка Создать новый проект")
        self.btn_new.setAccessibleDescription("Открывает выбор видеофайла и ввод названия проекта")
        self.btn_new.clicked.connect(self.create_new_project)

        self.btn_open = QPushButton("Открыть проект", self)
        self.btn_open.setAccessibleName("Кнопка Открыть выбранный проект")
        self.btn_open.clicked.connect(self.open_selected_project)

        self.btn_resume = QPushButton("Продолжить комментирование", self)
        self.btn_resume.setAccessibleName("Кнопка Продолжить генерацию тифлокомментариев")
        self.btn_resume.setAccessibleDescription("Возобновляет генерацию комментариев с прерванного места")
        self.btn_resume.clicked.connect(self.resume_selected_project)

        self.btn_delete = QPushButton("Удалить проект", self)
        self.btn_delete.setAccessibleName("Кнопка Удалить выбранный проект")
        self.btn_delete.clicked.connect(self.delete_selected_project)

        btn_layout.addWidget(self.btn_new)
        btn_layout.addWidget(self.btn_open)
        btn_layout.addWidget(self.btn_resume)
        btn_layout.addWidget(self.btn_delete)
        main_layout.addLayout(btn_layout)

    def refresh_projects_table(self):
        projects = self.project_mgr.list_projects()
        self.table.setRowCount(len(projects))

        for row, p in enumerate(projects):
            name_item = QTableWidgetItem(p["name"])
            name_item.setData(Qt.UserRole, p["folder"])

            status_str = "Готов" if p["status"] == "completed" else "В процессе"
            status_item = QTableWidgetItem(status_str)
            comms_item = QTableWidgetItem(str(p["commentaries_count"]))
            chars_item = QTableWidgetItem(str(p["characters_count"]))
            chunks_str = f"{p['completed_chunks']}/{p['total_chunks']}"
            chunks_item = QTableWidgetItem(chunks_str)

            updated_t = time.strftime("%d.%m.%Y %H:%M", time.localtime(p["updated_at"])) if p["updated_at"] else "-"
            updated_item = QTableWidgetItem(updated_t)

            for col, item in enumerate([name_item, status_item, comms_item, chars_item, chunks_item, updated_item]):
                item.setFlags(item.flags() & ~Qt.ItemIsEditable)
                self.table.setItem(row, col, item)

        if len(projects) > 0:
            self.table.selectRow(0)

    def get_selected_folder(self) -> Optional[str]:
        row = self.table.currentRow()
        if row < 0:
            return None
        item = self.table.item(row, 0)
        return item.data(Qt.UserRole) if item else None

    def create_new_project(self):
        # 1. Выбор видеофайла
        video_filters = "Видеофайлы (*.mp4 *.mkv *.avi *.mov *.vob *.mpg *.mpeg *.wmv *.ts *.webm);;Все файлы (*.*)"
        video_path, _ = QFileDialog.getOpenFileName(self, "Выберите видеофайл для тифлокомментирования", "", video_filters)
        if not video_path:
            return

        # 2. Запрос названия проекта
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
            self.selected_project = prep_dlg.result_project
            self.resume_requested = True
            self.config.last_project = self.selected_project.folder_path
            self.config.save()
            self.accept()

    def open_selected_project(self):
        folder = self.get_selected_folder()
        if not folder:
            QMessageBox.warning(self, "Внимание", "Пожалуйста, выберите проект из таблицы.")
            return

        prep_dlg = VideoPreparationProgressDialog(
            project_mgr=self.project_mgr,
            project_name="",
            src_video_path="",
            chunk_min=50,
            config=self.config,
            is_opening=True,
            project_folder=folder,
            parent=self
        )
        if prep_dlg.exec() and prep_dlg.result_project:
            self.selected_project = prep_dlg.result_project
            self.resume_requested = False
            self.config.last_project = self.selected_project.folder_path
            self.config.save()
            self.accept()

    def resume_selected_project(self):
        folder = self.get_selected_folder()
        if not folder:
            QMessageBox.warning(self, "Внимание", "Пожалуйста, выберите проект из таблицы.")
            return

        prep_dlg = VideoPreparationProgressDialog(
            project_mgr=self.project_mgr,
            project_name="",
            src_video_path="",
            chunk_min=50,
            config=self.config,
            is_opening=True,
            project_folder=folder,
            parent=self
        )
        if prep_dlg.exec() and prep_dlg.result_project:
            self.selected_project = prep_dlg.result_project
            self.resume_requested = True
            self.config.last_project = self.selected_project.folder_path
            self.config.save()
            self.accept()

    def delete_selected_project(self):
        folder = self.get_selected_folder()
        if not folder:
            QMessageBox.warning(self, "Внимание", "Пожалуйста, выберите проект из таблицы.")
            return

        confirmed = confirm_destructive(
            self, "Удаление проекта",
            f"Удалить проект и все его материалы?\n{folder}",
            accept_text="Удалить проект",
        )
        if confirmed:
            # Если удаляемый проект открыт в главном окне, выгружаем его медиа и дескрипторы
            parent_win = self.parent()
            if parent_win and hasattr(parent_win, "current_project") and parent_win.current_project:
                current_folder = os.path.normcase(os.path.abspath(parent_win.current_project.folder_path))
                target_folder = os.path.normcase(os.path.abspath(folder))
                if current_folder == target_folder:
                    parent_win.close_current_project()

            if self.config.last_project:
                cfg_folder = os.path.normcase(os.path.abspath(self.config.last_project))
                target_folder = os.path.normcase(os.path.abspath(folder))
                if cfg_folder == target_folder:
                    self.config.last_project = ""
                    self.config.save()

            success = self.project_mgr.delete_project(folder)
            self.refresh_projects_table()
            if success:
                QMessageBox.information(self, "Успешно", "Проект успешно удален.")
            else:
                QMessageBox.critical(
                    self, "Ошибка удаления",
                    f"Не удалось удалить папку проекта.\nВозможно, файлы проекта заблокированы другим процессом или открыты в сторонней программе.\n\nПуть: {folder}"
                )
