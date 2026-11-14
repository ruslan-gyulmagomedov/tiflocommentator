# -*- coding: utf-8 -*-
"""
Диалоговое окно управления карточками героев фильма.
Обеспечивает:
- Полноэкранный высококонтрастный интерфейс для Windows High Contrast и скринридеров NVDA / JAWS.
- Полный просмотр, фильтрацию, добавление, редактирование и удаление персонажей.
- Галерею скриншотов персонажа с возможностью удаления и загрузки из файлов.
- Встроенный видеоплеер с таймлайном и звуком для поиска нужных моментов в фильме и захвата кадров.
- Экспорт и импорт списка персонажей со скриншотами (ZIP/JSON) для сериалов.
"""

import os
from typing import Dict, List, Any, Optional

from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QListWidget, QListWidgetItem,
    QLineEdit, QTextEdit, QPushButton, QSplitter, QWidget, QMessageBox,
    QFileDialog, QSizePolicy, QStyle, QFrame, QSlider
)
from PySide6.QtGui import QPixmap, QKeySequence, QShortcut, QKeyEvent, QAccessible, QAccessibleEvent
from PySide6.QtCore import Qt, QUrl, Slot
from PySide6.QtMultimedia import QMediaPlayer, QAudioOutput
from PySide6.QtMultimediaWidgets import QVideoWidget

from core.character_manager import CharacterManager
from ui.accessible_dialogs import confirm_destructive
from ui.accessible_slider import AccessibleSmoothSlider


DIALOG_STYLE = """
QDialog {
    background-color: #000000;
    color: #FFFFFF;
}

QLabel {
    color: #FFFFFF;
    font-size: 14px;
}

QLabel#heading {
    color: #FFFF00;
    font-size: 16px;
    font-weight: bold;
}

QLineEdit, QTextEdit {
    background-color: #050505;
    color: #FFFFFF;
    border: 2px solid #FFFFFF;
    border-radius: 4px;
    padding: 6px;
    font-size: 15px;
    selection-background-color: #00FFFF;
    selection-color: #000000;
}

QLineEdit:focus, QTextEdit:focus {
    border: 2px solid #00FFFF;
}

QListWidget {
    background-color: #050505;
    color: #FFFFFF;
    border: 2px solid #FFFFFF;
    border-radius: 4px;
    font-size: 15px;
    padding: 4px;
}

QListWidget::item {
    padding: 8px;
    border-bottom: 1px solid #333333;
}

QListWidget::item:hover {
    background-color: #222222;
    color: #FFFF00;
}

QListWidget::item:selected {
    background-color: #004466;
    color: #00FFFF;
    border: 2px solid #00FFFF;
    font-weight: bold;
}

QPushButton {
    background-color: #111111;
    color: #FFFFFF;
    border: 2px solid #FFFFFF;
    border-radius: 4px;
    padding: 6px 14px;
    font-size: 14px;
    font-weight: bold;
    min-height: 36px;
}

QPushButton:hover {
    background-color: #00E5FF;
    color: #000000;
    border: 2px solid #FFFF00;
}

QPushButton:pressed {
    background-color: #FFFFFF;
    color: #000000;
}

QPushButton:focus {
    border: 2px solid #00FFFF;
    outline: none;
}

QPushButton#btn_capture {
    background-color: #003311;
    color: #00FF66;
    border: 2px solid #00FF66;
    font-size: 15px;
    font-weight: bold;
    min-height: 44px;
}

QPushButton#btn_capture:hover {
    background-color: #00FF66;
    color: #000000;
    border: 2px solid #FFFFFF;
}

QPushButton#btn_capture:focus {
    border: 3px solid #FFFF00;
}

QSplitter::handle {
    background-color: #444444;
    width: 6px;
}

QSplitter::handle:hover {
    background-color: #00FFFF;
}
"""


def format_seconds_to_timecode(seconds: float) -> str:
    """Форматирует секунды в строку ЧЧ:ММ:СС.ммм."""
    if seconds < 0:
        seconds = 0.0
    m, s = divmod(seconds, 60.0)
    h, m = divmod(m, 60.0)
    int_h, int_m, int_s = int(h), int(m), int(s)
    ms = int(round((seconds - int(seconds)) * 1000.0))
    if ms >= 1000:
        ms = 999
    return f"{int_h:02d}:{int_m:02d}:{int_s:02d}.{ms:03d}"


class CharacterCardsDialog(QDialog):
    """Диалог управления карточками персонажей фильма."""

    def __init__(self, project, parent=None):
        super().__init__(parent)
        self.project = project
        self.char_mgr = CharacterManager(project)

        self.setWindowTitle(f"👥 Карточки героев (персонажей) фильма — {project.name}")
        self.resize(1350, 820)
        self.setMinimumSize(960, 600)
        self.setStyleSheet(DIALOG_STYLE)
        self.setModal(True)

        self.current_char_id: Optional[str] = None
        self.current_images: List[str] = []
        self.current_img_idx: int = 0
        self.is_updating_ui: bool = False

        self.init_ui()
        self.init_player()
        self.setup_shortcuts()
        self.populate_characters()

    def showEvent(self, event):
        super().showEvent(event)
        # Открываем окно на весь экран для максимального удобства и высокой контрастности
        self.showMaximized()

    def init_ui(self):
        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(10, 10, 10, 10)
        main_layout.setSpacing(8)

        splitter = QSplitter(Qt.Horizontal, self)
        splitter.setAccessibleName("Разделитель панелей персонажей, карточки и видеоплеера")
        # Панели нельзя схлопнуть в ноль: иначе фокус может уйти в невидимый
        # список персонажей, и скринридер «теряет» место ввода.
        splitter.setChildrenCollapsible(False)

        # ==========================================
        # 1. ЛЕВАЯ ПАНЕЛЬ: Список персонажей и импорт/экспорт
        # ==========================================
        left_widget = QWidget(self)
        left_layout = QVBoxLayout(left_widget)
        left_layout.setContentsMargins(4, 4, 4, 4)
        left_layout.setSpacing(6)

        lbl_chars_title = QLabel("👥 Список персонажей фильма:", self)
        lbl_chars_title.setObjectName("heading")
        lbl_chars_title.setAccessibleName("Заголовок Список персонажей фильма")
        left_layout.addWidget(lbl_chars_title)

        # Поле поиска
        self.txt_search = QLineEdit(self)
        self.txt_search.setPlaceholderText("🔍 Поиск по имени или роли...")
        self.txt_search.setAccessibleName("Поле поиска персонажей")
        self.txt_search.setAccessibleDescription("Введите часть имени или роли для фильтрации списка")
        self.txt_search.textChanged.connect(self.filter_characters)
        left_layout.addWidget(self.txt_search)

        # Список персонажей
        self.char_list = QListWidget(self)
        self.char_list.setAccessibleName("Список всех персонажей фильма")
        self.char_list.setAccessibleDescription(
            "Используйте стрелки вверх и вниз для выбора персонажа. Tab переводит фокус к следующему элементу окна."
        )
        # Tab должен выходить из списка, а не перебирать элементы.
        self.char_list.setTabKeyNavigation(False)
        self.char_list.setFocusPolicy(Qt.StrongFocus)
        self.char_list.currentRowChanged.connect(self.on_character_selected)
        left_layout.addWidget(self.char_list, 1)

        self.lbl_char_count = QLabel("Всего персонажей: 0", self)
        self.lbl_char_count.setStyleSheet("font-size: 13px; color: #FFFF00;")
        self.lbl_char_count.setAccessibleName("Количество персонажей в картотеке")
        left_layout.addWidget(self.lbl_char_count)

        # Кнопки добавления / удаления персонажа
        char_btn_layout = QHBoxLayout()
        self.btn_add_char = QPushButton("➕ Добавить (Alt+A)", self)
        self.btn_add_char.setAccessibleName("Добавить нового персонажа")
        self.btn_add_char.setAccessibleDescription("Создать новую карточку персонажа в проекте")
        self.btn_add_char.clicked.connect(self.add_new_character)
        char_btn_layout.addWidget(self.btn_add_char)

        self.btn_del_char = QPushButton("🗑 Удалить (Alt+D)", self)
        self.btn_del_char.setAccessibleName("Удалить выбранного персонажа")
        self.btn_del_char.setAccessibleDescription("Удалить карточку выбранного персонажа и все его скриншоты")
        self.btn_del_char.clicked.connect(self.delete_current_character)
        char_btn_layout.addWidget(self.btn_del_char)
        left_layout.addLayout(char_btn_layout)

        # Кнопки импорта и экспорта
        io_btn_layout = QHBoxLayout()
        self.btn_import = QPushButton("📥 Импорт (Alt+I)", self)
        self.btn_import.setAccessibleName("Импортировать список персонажей")
        self.btn_import.setAccessibleDescription("Импортировать персонажей из архива ZIP или файла JSON и дополнить текущую базу")
        self.btn_import.clicked.connect(self.import_characters)
        io_btn_layout.addWidget(self.btn_import)

        self.btn_export = QPushButton("📤 Экспорт (Alt+E)", self)
        self.btn_export.setAccessibleName("Экспортировать список персонажей")
        self.btn_export.setAccessibleDescription("Экспортировать всех персонажей со скриншотами в ZIP или JSON для других серий")
        self.btn_export.clicked.connect(self.export_characters)
        io_btn_layout.addWidget(self.btn_export)
        left_layout.addLayout(io_btn_layout)

        splitter.addWidget(left_widget)


        # ==========================================
        # 2. ЦЕНТРАЛЬНАЯ ПАНЕЛЬ: Карточка персонажа и галерея кадров
        # ==========================================
        center_widget = QWidget(self)
        center_layout = QVBoxLayout(center_widget)
        center_layout.setContentsMargins(4, 4, 4, 4)
        center_layout.setSpacing(6)

        lbl_card_title = QLabel("📝 Карточка выбранного персонажа:", self)
        lbl_card_title.setObjectName("heading")
        lbl_card_title.setAccessibleName("Заголовок Карточка выбранного персонажа")
        center_layout.addWidget(lbl_card_title)

        # Поля редактирования
        lbl_name = QLabel("Имя персонажа:", self)
        lbl_name.setAccessibleName("Метка Имя персонажа")
        center_layout.addWidget(lbl_name)

        self.txt_char_name = QLineEdit(self)
        self.txt_char_name.setPlaceholderText("Например: Джек Уитмен, Майор Смирнов...")
        self.txt_char_name.setAccessibleName("Поле ввода имени персонажа")
        self.txt_char_name.textChanged.connect(self.on_field_changed)
        center_layout.addWidget(self.txt_char_name)

        lbl_role = QLabel("Роль / статус в сюжете:", self)
        lbl_role.setAccessibleName("Метка Роль и статус")
        center_layout.addWidget(lbl_role)

        self.txt_char_role = QLineEdit(self)
        self.txt_char_role.setPlaceholderText("Например: Главный герой, постоялец отеля, официант...")
        self.txt_char_role.setAccessibleName("Поле ввода роли персонажа")
        self.txt_char_role.textChanged.connect(self.on_field_changed)
        center_layout.addWidget(self.txt_char_role)

        lbl_desc = QLabel("Визуальное описание внешности, возраста и одежды:", self)
        lbl_desc.setAccessibleName("Метка Описание внешности и одежды")
        center_layout.addWidget(lbl_desc)

        self.txt_char_desc = QTextEdit(self)
        self.txt_char_desc.setPlaceholderText(
            "Детально опишите внешность: возраст, телосложение, лицо, цвет и длину волос, "
            "прическу, усы/бороду, отличительные приметы, очки, одежду и аксессуары..."
        )
        self.txt_char_desc.setAccessibleName("Поле описания внешности персонажа")
        self.txt_char_desc.setAccessibleDescription("Большое текстовое поле для подробного описания героя фильма")
        self.txt_char_desc.setMinimumHeight(140)
        self.txt_char_desc.textChanged.connect(self.on_field_changed)
        center_layout.addWidget(self.txt_char_desc, 2)

        self.btn_save_char = QPushButton("💾 Сохранить изменения персонажа (Ctrl+S)", self)
        self.btn_save_char.setAccessibleName("Сохранить изменения персонажа")
        self.btn_save_char.clicked.connect(self.save_current_character)
        center_layout.addWidget(self.btn_save_char)

        # Разделительная линия
        sep = QFrame(self)
        sep.setFrameShape(QFrame.HLine)
        sep.setStyleSheet("color: #444444;")
        center_layout.addWidget(sep)

        # Галерея скриншотов
        lbl_gallery_title = QLabel("🖼 Скриншоты персонажа:", self)
        lbl_gallery_title.setObjectName("heading")
        lbl_gallery_title.setAccessibleName("Заголовок Скриншоты персонажа")
        center_layout.addWidget(lbl_gallery_title)

        self.lbl_image = QLabel("Нет скриншотов", self)
        self.lbl_image.setAlignment(Qt.AlignCenter)
        self.lbl_image.setMinimumSize(320, 200)
        self.lbl_image.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        self.lbl_image.setStyleSheet("border: 2px solid #555555; background-color: #080808; color: #FFFFFF; font-size: 15px;")
        self.lbl_image.setAccessibleName("Просмотр скриншота персонажа")
        center_layout.addWidget(self.lbl_image, 3)

        # Навигация по скриншотам
        img_nav_layout = QHBoxLayout()
        self.btn_prev_img = QPushButton("◀ Пред. (Alt+Left)", self)
        self.btn_prev_img.setAccessibleName("Предыдущий скриншот персонажа")
        self.btn_prev_img.clicked.connect(self.prev_image)
        img_nav_layout.addWidget(self.btn_prev_img)

        self.lbl_img_counter = QLabel("0 / 0", self)
        self.lbl_img_counter.setAlignment(Qt.AlignCenter)
        self.lbl_img_counter.setStyleSheet("font-size: 15px; font-weight: bold; color: #00FFFF; min-width: 70px;")
        self.lbl_img_counter.setAccessibleName("Индикатор номера текущего кадра")
        img_nav_layout.addWidget(self.lbl_img_counter)

        self.btn_next_img = QPushButton("След. (Alt+Right) ▶", self)
        self.btn_next_img.setAccessibleName("Следующий скриншот персонажа")
        self.btn_next_img.clicked.connect(self.next_image)
        img_nav_layout.addWidget(self.btn_next_img)
        center_layout.addLayout(img_nav_layout)

        # Действия со скриншотами: удаление и добавление из файла
        img_act_layout = QHBoxLayout()
        self.btn_del_img = QPushButton("🗑 Удалить этот кадр", self)
        self.btn_del_img.setAccessibleName("Удалить текущий скриншот персонажа")
        self.btn_del_img.setAccessibleDescription("Удаляет выбранный скриншот из карточки героя и с диска")
        self.btn_del_img.clicked.connect(self.delete_current_screenshot)
        img_act_layout.addWidget(self.btn_del_img)

        self.btn_add_img_file = QPushButton("📁 Загрузить фото из файла...", self)
        self.btn_add_img_file.setAccessibleName("Загрузить изображение персонажа из файла")
        self.btn_add_img_file.setAccessibleDescription("Выбрать файл JPG или PNG на диске и добавить в карточку героя")
        self.btn_add_img_file.clicked.connect(self.add_screenshot_from_file)
        img_act_layout.addWidget(self.btn_add_img_file)
        center_layout.addLayout(img_act_layout)

        splitter.addWidget(center_widget)


        # ==========================================
        # 3. ПРАВАЯ ПАНЕЛЬ: Встроенный видеоплеер и таймлайн фильма
        # ==========================================
        right_widget = QWidget(self)
        right_layout = QVBoxLayout(right_widget)
        right_layout.setContentsMargins(4, 4, 4, 4)
        right_layout.setSpacing(6)

        lbl_player_title = QLabel("🎬 Поиск кадров в видеофильме:", self)
        lbl_player_title.setObjectName("heading")
        lbl_player_title.setAccessibleName("Заголовок Поиск кадров в видеофильме")
        right_layout.addWidget(lbl_player_title)

        # Контейнер видео
        self.video_container = QWidget(self)
        self.video_container.setMinimumSize(420, 240)
        self.video_container.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        self.video_container.setStyleSheet("background-color: #000000; border: 2px solid #333333;")
        video_vbox = QVBoxLayout(self.video_container)
        video_vbox.setContentsMargins(0, 0, 0, 0)
        video_vbox.setSpacing(0)

        self.video_widget = QVideoWidget(self.video_container)
        self.video_widget.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        self.video_widget.setAccessibleName("Область видеокадра фильма")
        video_vbox.addWidget(self.video_widget)
        right_layout.addWidget(self.video_container, 4)

        # Таймлайн воспроизведения
        row_slider = QHBoxLayout()
        self.slider_pos = AccessibleSmoothSlider(Qt.Horizontal, self)
        self.slider_pos.setRange(0, 1000)
        self.slider_pos.setAccessibleName("Таймлайн воспроизведения фильма")
        self.slider_pos.setAccessibleDescription("Используйте стрелки влево и вправо или клик мыши для перемещения по фильму")
        self.slider_pos.sliderMoved.connect(self.on_slider_moved)
        row_slider.addWidget(self.slider_pos, 1)

        self.lbl_time = QLabel("00:00:00.000 / 00:00:00.000", self)
        self.lbl_time.setStyleSheet("font-weight: bold; color: #FFFF00; font-size: 14px; min-width: 210px;")
        self.lbl_time.setAccessibleName("Текущая позиция и общая длительность фильма")
        row_slider.addWidget(self.lbl_time)
        right_layout.addLayout(row_slider)

        # Кнопки управления воспроизведением
        row_ctrls = QHBoxLayout()
        self.btn_play = QPushButton("▶ Воспроизведение (Пробел)", self)
        self.btn_play.setIcon(self.style().standardIcon(QStyle.SP_MediaPlay))
        self.btn_play.setAccessibleName("Воспроизведение и пауза")
        self.btn_play.setAccessibleDescription("Клавиша Пробел запускает и останавливает видео")
        self.btn_play.clicked.connect(self.toggle_play)
        row_ctrls.addWidget(self.btn_play)

        self.btn_back5 = QPushButton("◀ 5с", self)
        self.btn_back5.setAccessibleName("Перемотка назад на 5 секунд")
        self.btn_back5.clicked.connect(lambda: self.seek_relative(-5000))
        row_ctrls.addWidget(self.btn_back5)

        self.btn_back1 = QPushButton("◀ 1с", self)
        self.btn_back1.setAccessibleName("Перемотка назад на 1 секунду")
        self.btn_back1.clicked.connect(lambda: self.seek_relative(-1000))
        row_ctrls.addWidget(self.btn_back1)

        self.btn_fwd1 = QPushButton("1с ▶", self)
        self.btn_fwd1.setAccessibleName("Перемотка вперед на 1 секунду")
        self.btn_fwd1.clicked.connect(lambda: self.seek_relative(1000))
        row_ctrls.addWidget(self.btn_fwd1)

        self.btn_fwd5 = QPushButton("5с ▶", self)
        self.btn_fwd5.setAccessibleName("Перемотка вперед на 5 секунд")
        self.btn_fwd5.clicked.connect(lambda: self.seek_relative(5000))
        row_ctrls.addWidget(self.btn_fwd5)

        lbl_vol = QLabel("🔊 Звук:", self)
        lbl_vol.setAccessibleName("Регулятор громкости")
        row_ctrls.addWidget(lbl_vol)

        self.slider_vol = QSlider(Qt.Horizontal, self)
        self.slider_vol.setRange(0, 100)
        self.slider_vol.setValue(100)
        self.slider_vol.setFixedWidth(80)
        self.slider_vol.setAccessibleName("Громкость звука в плеере")
        self.slider_vol.valueChanged.connect(self.on_volume_changed)
        row_ctrls.addWidget(self.slider_vol)

        right_layout.addLayout(row_ctrls)

        # Главная кнопка захвата кадра в карточку персонажа
        self.btn_capture = QPushButton("📸 Добавить текущий кадр в карточку героя (Ctrl+Shift+C / F8)", self)
        self.btn_capture.setObjectName("btn_capture")
        self.btn_capture.setAccessibleName("Добавить кадр из фильма в карточку выбранного героя")
        self.btn_capture.setAccessibleDescription("Делает скриншот фильма на текущей секунде и прикрепляет к выбранному персонажу")
        self.btn_capture.clicked.connect(self.capture_current_frame)
        right_layout.addWidget(self.btn_capture)

        splitter.addWidget(right_widget)

        # Пропорции колонок
        splitter.setStretchFactor(0, 2)  # Список
        splitter.setStretchFactor(1, 3)  # Карточка и фото
        splitter.setStretchFactor(2, 4)  # Плеер
        main_layout.addWidget(splitter, 1)

        # ==========================================
        # 4. НИЖНЯЯ ПАНЕЛЬ: Строка статуса и Закрыть
        # ==========================================
        bottom_layout = QHBoxLayout()
        self.lbl_status = QLabel("Готово к работе", self)
        self.lbl_status.setStyleSheet("font-size: 14px; font-weight: bold; color: #00FFCC; padding-left: 4px;")
        self.lbl_status.setAccessibleName("Строка состояния персонажей")
        bottom_layout.addWidget(self.lbl_status, 1)

        self.btn_close = QPushButton("Закрыть (Esc)", self)
        self.btn_close.setAccessibleName("Закрыть окно персонажей")
        self.btn_close.clicked.connect(self.accept)
        bottom_layout.addWidget(self.btn_close)
        main_layout.addLayout(bottom_layout)


    def init_player(self):
        """Инициализирует видеоплеер и загружает видеофайл проекта."""
        self.player = QMediaPlayer(self)
        self.audio_output = QAudioOutput(self)
        self.player.setAudioOutput(self.audio_output)
        self.player.setVideoOutput(self.video_widget)

        self.player.positionChanged.connect(self.on_player_pos_changed)
        self.player.durationChanged.connect(self.on_player_dur_changed)
        self.player.mediaStatusChanged.connect(self.on_player_media_status_changed)

        video_path = self.project.video_path
        if video_path and os.path.isfile(video_path):
            self.player.setSource(QUrl.fromLocalFile(video_path))
            self.player.pause()
            self.lbl_status.setText(f"Видеофайл успешно загружен: {os.path.basename(video_path)}")
        else:
            self.lbl_status.setText("Видеофайл проекта не найден. Ручное добавление и загрузка фото из файлов доступны.")
            self.btn_play.setEnabled(False)
            self.btn_capture.setEnabled(False)

    def on_player_media_status_changed(self, status):
        """Переводит плеер в паузу при загрузке медиа для отображения первого кадра."""
        if status in (QMediaPlayer.LoadedMedia, QMediaPlayer.BufferedMedia):
            if self.player.playbackState() == QMediaPlayer.StoppedState:
                self.player.pause()

    def setup_shortcuts(self):
        """Настраивает доступные горячие клавиши для всех операций."""
        QShortcut(QKeySequence("Alt+A"), self, self.add_new_character)
        QShortcut(QKeySequence("Ctrl+N"), self, self.add_new_character)
        QShortcut(QKeySequence("Alt+D"), self, self.delete_current_character)
        QShortcut(QKeySequence("Ctrl+S"), self, self.save_current_character)
        QShortcut(QKeySequence("Alt+I"), self, self.import_characters)
        QShortcut(QKeySequence("Alt+E"), self, self.export_characters)
        QShortcut(QKeySequence("Alt+Left"), self, self.prev_image)
        QShortcut(QKeySequence("Alt+Right"), self, self.next_image)
        QShortcut(QKeySequence("Ctrl+Shift+C"), self, self.capture_current_frame)
        QShortcut(QKeySequence("F8"), self, self.capture_current_frame)
        QShortcut(QKeySequence("Space"), self, self.toggle_play)

    def populate_characters(self, select_char_id: Optional[str] = None):
        """Заполняет список персонажей с учетом фильтра."""
        self.char_list.blockSignals(True)
        self.char_list.clear()

        characters = self.project.characters
        filter_text = self.txt_search.text().strip().lower()

        matched_count = 0
        target_row = -1

        for idx, char in enumerate(characters):
            cid = char.get("id", "")
            name = char.get("name", "Без имени")
            role = char.get("role", "")
            display_text = f"{name} ({role})" if role else name

            if filter_text:
                if filter_text not in name.lower() and filter_text not in role.lower() and filter_text not in char.get("description", "").lower():
                    continue

            item = QListWidgetItem(display_text)
            item.setData(Qt.UserRole, cid)
            self.char_list.addItem(item)

            if select_char_id and cid == select_char_id:
                target_row = matched_count
            elif target_row == -1 and not select_char_id and cid == self.current_char_id:
                target_row = matched_count

            matched_count += 1

        self.char_list.blockSignals(False)

        total_all = len(characters)
        if filter_text:
            self.lbl_char_count.setText(f"Найдено: {matched_count} из {total_all} героев")
        else:
            self.lbl_char_count.setText(f"Всего персонажей: {total_all}")

        if self.char_list.count() > 0:
            if target_row >= 0:
                self.char_list.setCurrentRow(target_row)
            else:
                self.char_list.setCurrentRow(0)
        else:
            self.clear_card_fields()

    def filter_characters(self):
        """Слот фильтрации списка персонажей."""
        self.populate_characters()

    def clear_card_fields(self):
        """Очищает поля карточки, когда список пуст."""
        self.current_char_id = None
        self.is_updating_ui = True
        self.txt_char_name.clear()
        self.txt_char_role.clear()
        self.txt_char_desc.clear()
        self.lbl_image.setText("Персонажи отсутствуют")
        self.lbl_image.setPixmap(QPixmap())
        self.lbl_img_counter.setText("0 / 0")
        self.btn_prev_img.setEnabled(False)
        self.btn_next_img.setEnabled(False)
        self.btn_del_img.setEnabled(False)
        self.btn_add_img_file.setEnabled(False)
        self.btn_save_char.setEnabled(False)
        self.is_updating_ui = False


    def on_character_selected(self, row: int):
        """Слот выбора персонажа в списке."""
        if row < 0:
            return

        item = self.char_list.item(row)
        if not item:
            return

        cid = item.data(Qt.UserRole)
        char = self.char_mgr.get_character_by_id(cid)
        if not char:
            return

        self.current_char_id = cid
        self.is_updating_ui = True

        self.txt_char_name.setText(char.get("name", ""))
        self.txt_char_role.setText(char.get("role", ""))
        self.txt_char_desc.setPlainText(char.get("description", ""))

        self.btn_del_char.setEnabled(True)
        self.btn_save_char.setEnabled(True)
        self.btn_del_img.setEnabled(True)
        self.btn_add_img_file.setEnabled(True)

        self.is_updating_ui = False

        self.current_images = self.char_mgr.get_character_images(char)
        self.current_img_idx = 0
        self.update_image_display()

    def on_field_changed(self):
        """Слот отслеживания изменений в полях (автосинхронизация)."""
        if self.is_updating_ui or not self.current_char_id:
            return
        # Автоматически обновляем данные в объекте проекта
        char = self.char_mgr.get_character_by_id(self.current_char_id)
        if char:
            char["name"] = self.txt_char_name.text().strip()
            char["role"] = self.txt_char_role.text().strip()
            char["description"] = self.txt_char_desc.toPlainText().strip()

    def save_current_character(self):
        """Сохраняет текущую карточку персонажа и обновляет список."""
        if not self.current_char_id:
            return

        char = self.char_mgr.get_character_by_id(self.current_char_id)
        if not char:
            return

        name = self.txt_char_name.text().strip() or "Без имени"
        role = self.txt_char_role.text().strip()
        desc = self.txt_char_desc.toPlainText().strip()

        self.char_mgr.update_character(self.current_char_id, name=name, role=role, description=desc)

        # Обновляем текст текущего элемента в списке
        cur_row = self.char_list.currentRow()
        if cur_row >= 0:
            item = self.char_list.item(cur_row)
            if item:
                display_text = f"{name} ({role})" if role else name
                item.setText(display_text)

        self.lbl_status.setText(f"Карточка персонажа «{name}» успешно сохранена.")
        QMessageBox.information(self, "Сохранено", f"Данные персонажа «{name}» успешно сохранены.")

    def add_new_character(self):
        """Создает нового персонажа и переводит фокус на ввод имени."""
        new_char = self.char_mgr.add_character(
            name="Новый персонаж",
            role="",
            description=""
        )
        self.populate_characters(select_char_id=new_char["id"])
        self.txt_char_name.selectAll()
        self.txt_char_name.setFocus()
        self.lbl_status.setText("Создана новая карточка персонажа. Введите имя и роль.")

    def delete_current_character(self):
        """Удаляет выбранного персонажа после подтверждения."""
        if not self.current_char_id:
            QMessageBox.information(self, "Информация", "Выберите персонажа для удаления.")
            return

        char = self.char_mgr.get_character_by_id(self.current_char_id)
        name = char.get("name", "Персонаж") if char else "Персонаж"

        ans = confirm_destructive(
            self,
            "Удаление персонажа",
            f"Удалить карточку персонажа «{name}» и все связанные с ним скриншоты?",
            accept_text="Удалить персонажа",
        )
        if ans:
            self.char_mgr.delete_character(self.current_char_id, delete_images=True)
            self.lbl_status.setText(f"Персонаж «{name}» удален.")
            self.populate_characters()

    def update_image_display(self):
        """Обновляет показ текущего скриншота персонажа."""
        if not self.current_images:
            self.lbl_image.setText("Скриншоты отсутствуют.\n\nНайдите нужный кадр в плеере справа и нажмите\n«Добавить текущий кадр в карточку героя»")
            self.lbl_image.setPixmap(QPixmap())
            self.lbl_img_counter.setText("0 / 0")
            self.btn_prev_img.setEnabled(False)
            self.btn_next_img.setEnabled(False)
            self.btn_del_img.setEnabled(False)
            return

        total_imgs = len(self.current_images)
        self.current_img_idx = max(0, min(self.current_img_idx, total_imgs - 1))
        self.lbl_img_counter.setText(f"{self.current_img_idx + 1} / {total_imgs}")
        self.btn_prev_img.setEnabled(self.current_img_idx > 0)
        self.btn_next_img.setEnabled(self.current_img_idx < total_imgs - 1)
        self.btn_del_img.setEnabled(True)

        img_path = self.current_images[self.current_img_idx]
        if os.path.isfile(img_path):
            pixmap = QPixmap(img_path)
            if not pixmap.isNull():
                self.lbl_image.setPixmap(pixmap.scaled(
                    self.lbl_image.size(), Qt.KeepAspectRatio, Qt.SmoothTransformation
                ))
            else:
                self.lbl_image.setText("Ошибка загрузки файла кадра")
        else:
            self.lbl_image.setText("Файл кадра не найден на диске")

    def resizeEvent(self, event):
        """Перерисовывает изображение с правильным масштабированием при изменении размера окна."""
        super().resizeEvent(event)
        if self.current_images and 0 <= self.current_img_idx < len(self.current_images):
            img_path = self.current_images[self.current_img_idx]
            if os.path.isfile(img_path):
                pixmap = QPixmap(img_path)
                if not pixmap.isNull():
                    self.lbl_image.setPixmap(pixmap.scaled(
                        self.lbl_image.size(), Qt.KeepAspectRatio, Qt.SmoothTransformation
                    ))


    def prev_image(self):
        """Переход к предыдущему скриншоту."""
        if self.current_img_idx > 0:
            self.current_img_idx -= 1
            self.update_image_display()

    def next_image(self):
        """Переход к следующему скриншоту."""
        if self.current_img_idx < len(self.current_images) - 1:
            self.current_img_idx += 1
            self.update_image_display()

    def delete_current_screenshot(self):
        """Удаляет текущий отображаемый скриншот персонажа."""
        if not self.current_char_id or not self.current_images:
            return

        cur_img_path = self.current_images[self.current_img_idx]
        ans = confirm_destructive(
            self,
            "Удаление скриншота",
            "Удалить этот скриншот персонажа?",
            accept_text="Удалить скриншот",
        )
        if ans:
            self.char_mgr.delete_screenshot(self.current_char_id, cur_img_path)
            char = self.char_mgr.get_character_by_id(self.current_char_id)
            self.current_images = self.char_mgr.get_character_images(char) if char else []
            self.current_img_idx = max(0, min(self.current_img_idx, len(self.current_images) - 1))
            self.update_image_display()
            self.lbl_status.setText("Скриншот удален.")

    def add_screenshot_from_file(self):
        """Загружает файл изображения с диска в карточку персонажа."""
        if not self.current_char_id:
            QMessageBox.information(self, "Информация", "Сначала выберите персонажа.")
            return

        file_path, _ = QFileDialog.getOpenFileName(
            self,
            "Выберите изображение персонажа",
            "",
            "Изображения (*.jpg *.jpeg *.png *.webp *.bmp);;Все файлы (*.*)"
        )
        if file_path and os.path.isfile(file_path):
            res_path = self.char_mgr.add_screenshot_from_file(self.current_char_id, file_path)
            if res_path:
                char = self.char_mgr.get_character_by_id(self.current_char_id)
                self.current_images = self.char_mgr.get_character_images(char) if char else []
                self.current_img_idx = len(self.current_images) - 1
                self.update_image_display()
                self.lbl_status.setText("Изображение успешно прикреплено к карточке персонажа.")
            else:
                QMessageBox.warning(self, "Ошибка", "Не удалось загрузить изображение.")

    def capture_current_frame(self):
        """Захватывает текущий кадр из видеоплеера и прикрепляет к персонажу."""
        if not self.current_char_id:
            QMessageBox.information(self, "Информация", "Сначала выберите или создайте персонажа в списке слева.")
            return

        char = self.char_mgr.get_character_by_id(self.current_char_id)
        if not char:
            return

        pos_ms = self.player.position()
        pos_sec = pos_ms / 1000.0
        timecode = format_seconds_to_timecode(pos_sec)

        self.lbl_status.setText(f"Захват кадра на отметке {timecode}...")

        saved_path = self.char_mgr.add_screenshot_from_video(self.current_char_id, pos_sec)
        if saved_path:
            self.current_images = self.char_mgr.get_character_images(char)
            self.current_img_idx = len(self.current_images) - 1
            self.update_image_display()
            char_name = char.get("name", "персонажу")
            msg = f"Кадр на отметке {timecode} успешно добавлен к карточке героя «{char_name}»!"
            self.lbl_status.setText(msg)
        else:
            QMessageBox.warning(
                self,
                "Ошибка захвата",
                "Не удалось извлечь кадр из видео. Убедитесь, что видеофайл доступен."
            )
            self.lbl_status.setText("Ошибка захвата кадра.")

    def toggle_play(self):
        """Запуск / пауза видеоплеера."""
        if self.player.playbackState() == QMediaPlayer.PlayingState:
            self.player.pause()
            self.btn_play.setText("▶ Воспроизведение (Пробел)")
            self.btn_play.setIcon(self.style().standardIcon(QStyle.SP_MediaPlay))
        else:
            self.player.play()
            self.btn_play.setText("⏸ Пауза (Пробел)")
            self.btn_play.setIcon(self.style().standardIcon(QStyle.SP_MediaPause))

    def seek_relative(self, delta_ms: int):
        """Относительное перемещение по видео."""
        if self.player.playbackState() == QMediaPlayer.StoppedState:
            self.player.pause()
        new_pos = max(0, min(self.player.position() + delta_ms, self.player.duration()))
        self.player.setPosition(new_pos)

    def on_slider_moved(self, value: int):
        """Перемещение ползунка таймлайна пользователем."""
        dur = self.player.duration()
        if dur > 0:
            if self.player.playbackState() == QMediaPlayer.StoppedState:
                self.player.pause()
            target_pos = int((value / 1000.0) * dur)
            self.player.setPosition(target_pos)


    def on_player_pos_changed(self, pos_ms: int):
        """Обновление позиции таймлайна и индикатора времени."""
        dur_ms = self.player.duration()
        if dur_ms > 0:
            pct = int((pos_ms / dur_ms) * 1000)
            self.slider_pos.blockSignals(True)
            self.slider_pos.setValue(pct)
            self.slider_pos.blockSignals(False)

        pos_str = format_seconds_to_timecode(pos_ms / 1000.0)
        dur_str = format_seconds_to_timecode(dur_ms / 1000.0)
        self.lbl_time.setText(f"{pos_str} / {dur_str}")

    def on_player_dur_changed(self, dur_ms: int):
        """Обновление общей длительности видео при загрузке."""
        pos_str = format_seconds_to_timecode(self.player.position() / 1000.0)
        dur_str = format_seconds_to_timecode(dur_ms / 1000.0)
        self.lbl_time.setText(f"{pos_str} / {dur_str}")
        self.btn_play.setEnabled(dur_ms > 0)
        self.btn_capture.setEnabled(dur_ms > 0)

    def on_volume_changed(self, val: int):
        """Регулировка громкости звука в плеере."""
        self.audio_output.setVolume(val / 100.0)

    def export_characters(self):
        """Экспортирует базу персонажей для повторного использования в сериалах."""
        if not self.project.characters:
            QMessageBox.information(self, "Информация", "Список персонажей пуст. Нечего экспортировать.")
            return

        def_filename = f"{self.project.name}_characters.zip"
        target_path, _ = QFileDialog.getSaveFileName(
            self,
            "Экспорт списка персонажей",
            def_filename,
            "Пакет персонажей со скриншотами (*.zip);;JSON файл (*.json)"
        )
        if not target_path:
            return

        ok = self.char_mgr.export_characters_package(target_path)
        if ok:
            QMessageBox.information(
                self,
                "Экспорт завершен",
                f"Успешно экспортировано {len(self.project.characters)} персонажей в:\n{target_path}"
            )
            self.lbl_status.setText(f"Экспортировано {len(self.project.characters)} персонажей.")
        else:
            QMessageBox.warning(self, "Ошибка", "Не удалось экспортировать список персонажей.")

    def import_characters(self):
        """Импортирует персонажей из другой серии/файла и ДОПОЛНЯЕТ текущую базу."""
        source_path, _ = QFileDialog.getOpenFileName(
            self,
            "Импорт списка персонажей",
            "",
            "Пакеты и файлы персонажей (*.zip *.tiflochars *.json);;Пакет персонажей (*.zip);;JSON файл (*.json)"
        )
        if not source_path or not os.path.isfile(source_path):
            return

        added, updated = self.char_mgr.import_characters_package(source_path)
        self.populate_characters()

        msg = f"Импорт завершен успешно!\n\n• Добавлено новых героев: {added}\n• Дополнено существующих героев: {updated}"
        QMessageBox.information(self, "Импорт персонажей", msg)
        self.lbl_status.setText(f"Импорт завершен: +{added} новых, {updated} обновлено.")

    def closeEvent(self, event):
        """Останавливает воспроизведение при закрытии диалога."""
        if hasattr(self, "player") and self.player:
            self.player.stop()
        if hasattr(self, "audio_output") and self.audio_output:
            self.audio_output.setMuted(True)
        super().closeEvent(event)

