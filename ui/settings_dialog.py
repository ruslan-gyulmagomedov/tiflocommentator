# -*- coding: utf-8 -*-
"""
Диалоговое окно настроек приложения:
- Google Gemini API ключ и загрузка актуального списка моделей
- Выбор модели для тифлокомментирования и модели/голоса для Gemini TTS
- Выбор голоса, скорости и громкости SAPI5 с возможностью прослушивания примера
- Настройка длительности частей (по умолчанию 50 мин)
- Настройка регуляторов громкости (50%-300%), авто-дакинга и лимита ускорения (по умолчанию 3.0x)
- Настройка упреждающего компрессора (-2 dBFS, 5 мс lookahead, 120 мс release)
Полная поддержка скринридеров NVDA / JAWS.
"""

from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QLineEdit, QPushButton,
    QComboBox, QSpinBox, QDoubleSpinBox, QSlider, QCheckBox, QTabWidget,
    QWidget, QFormLayout, QMessageBox
)
from PySide6.QtCore import Qt, QUrl
from PySide6.QtMultimedia import QMediaPlayer, QAudioOutput
import os
from core.tts_engine import SAPI5Engine
from core.gemini_client import GeminiClient
from core.proxy_manager import apply_proxy_settings, get_proxy_status_description
from core.app_paths import get_voice_samples_dir
from ui.accessible_slider import AccessibleSmoothSlider, STEP_BUTTON_STYLE, STEP_LABEL_STYLE


class SettingsDialog(QDialog):
    """Диалог настроек приложения."""

    def __init__(self, config_manager, parent=None):
        super().__init__(parent)
        self.config = config_manager
        self.setWindowTitle("Настройки программы тифлокомментирования")
        self.setWindowFlags(self.windowFlags() | Qt.WindowMaximizeButtonHint | Qt.WindowMinimizeButtonHint)
        self.setWindowState(Qt.WindowState.WindowMaximized)
        self.resize(800, 600)
        self.setModal(True)

        # Плеер для прослушивания образцов голосов
        self.voice_player = QMediaPlayer(self)
        self.voice_audio_out = QAudioOutput(self)
        self.voice_player.setAudioOutput(self.voice_audio_out)

        self.init_ui()
        self.load_current_settings()

    def showEvent(self, event):
        super().showEvent(event)
        self.showMaximized()

    def init_ui(self):
        main_layout = QVBoxLayout(self)

        self.tabs = QTabWidget(self)
        self.tabs.setAccessibleName("Вкладки настроек")

        # Вкладка 1: Gemini API и модели
        tab_gemini = QWidget()
        layout_gemini = QVBoxLayout(tab_gemini)
        form_gemini = QFormLayout()

        self.txt_api_key = QLineEdit(self)
        self.txt_api_key.setEchoMode(QLineEdit.PasswordEchoOnEdit)
        self.txt_api_key.setAccessibleName("API ключ Google AI Studio")
        self.txt_api_key.setAccessibleDescription("Введите ваш ключ Google Gemini API")
        form_gemini.addRow("API-ключ Gemini:", self.txt_api_key)

        self.btn_fetch_models = QPushButton("Загрузить список моделей", self)
        self.btn_fetch_models.setAccessibleName("Кнопка Загрузить список моделей Gemini")
        self.btn_fetch_models.setAccessibleDescription("Запрашивает актуальный список доступных моделей с серверов Google")
        self.btn_fetch_models.clicked.connect(self.fetch_gemini_models)
        form_gemini.addRow("", self.btn_fetch_models)

        self.combo_comment_model = QComboBox(self)
        self.combo_comment_model.setAccessibleName("Выбор модели для создания тифлокомментариев")
        form_gemini.addRow("Модель для комментирования:", self.combo_comment_model)

        self.combo_tts_model = QComboBox(self)
        self.combo_tts_model.setAccessibleName("Выбор модели Gemini для синтеза речи")
        form_gemini.addRow("Модель Gemini TTS:", self.combo_tts_model)

        self.combo_tts_voice = QComboBox(self)
        self.combo_tts_voice.setAccessibleName("Выбор голоса Gemini TTS")
        self.combo_tts_voice.setAccessibleDescription("Выберите голос для озвучки Gemini TTS. При выборе сразу воспроизводится демонстрационный образец")
        self.combo_tts_voice.addItems([
            "Puck", "Charon", "Kore", "Fenrir", "Aoede",
            "Zephyr", "Orus", "Leda", "Pegasus"
        ])
        self.combo_tts_voice.activated.connect(self.play_gemini_voice_sample)

        self.btn_preview_gemini_voice = QPushButton("Прослушать образец голоса", self)
        self.btn_preview_gemini_voice.setAccessibleName("Кнопка Прослушать образец голоса Gemini")
        self.btn_preview_gemini_voice.setAccessibleDescription("Воспроизводит демонстрационный образец звучания выбранного голоса Gemini TTS")
        self.btn_preview_gemini_voice.clicked.connect(self.play_gemini_voice_sample)

        h_voice = QHBoxLayout()
        h_voice.addWidget(self.combo_tts_voice)
        h_voice.addWidget(self.btn_preview_gemini_voice)
        form_gemini.addRow("Голос Gemini TTS:", h_voice)

        self.spin_chunk_duration = QSpinBox(self)
        self.spin_chunk_duration.setRange(1, 180)
        self.spin_chunk_duration.setValue(50)
        self.spin_chunk_duration.setSuffix(" мин.")
        self.spin_chunk_duration.setAccessibleName("Продолжительность одной части видео в минутах")
        form_gemini.addRow("Длительность части видео:", self.spin_chunk_duration)

        self.spin_api_pause = QSpinBox(self)
        self.spin_api_pause.setRange(0, 300)
        self.spin_api_pause.setValue(20)
        self.spin_api_pause.setSuffix(" сек.")
        self.spin_api_pause.setAccessibleName("Пауза между обращениями к Gemini API в секундах для соблюдения лимитов (по умолчанию 20 секунд)")
        self.spin_api_pause.setAccessibleDescription("Интервал задержки перед каждым запросом к серверам Google")
        form_gemini.addRow("Пауза между запросами API:", self.spin_api_pause)

        self.btn_open_tokens = QPushButton("📊 Посмотреть расход токенов...", self)
        self.btn_open_tokens.setAccessibleName("Открыть статистику расхода токенов")
        self.btn_open_tokens.setAccessibleDescription("Открывает окно статистики расхода входящих и исходящих токенов по моделям")
        self.btn_open_tokens.clicked.connect(self._open_token_stats)
        form_gemini.addRow("Статистика токенов:", self.btn_open_tokens)

        layout_gemini.addLayout(form_gemini)
        layout_gemini.addStretch()
        self.tabs.addTab(tab_gemini, "Google Gemini")

        # Вкладка 2: Сеть и Прокси
        tab_proxy = QWidget()
        layout_proxy = QVBoxLayout(tab_proxy)
        form_proxy = QFormLayout()

        self.combo_proxy_mode = QComboBox(self)
        self.combo_proxy_mode.addItem("Использовать системный прокси Windows (по умолчанию)", "system")
        self.combo_proxy_mode.addItem("Пользовательский (ручной) прокси", "custom")
        self.combo_proxy_mode.addItem("Без прокси (прямое подключение)", "direct")
        self.combo_proxy_mode.setAccessibleName("Режим использования прокси-сервера")
        self.combo_proxy_mode.setAccessibleDescription("Выберите режим: системный прокси Windows, ручной ввод адреса или прямое подключение без прокси")
        self.combo_proxy_mode.currentIndexChanged.connect(self._on_proxy_mode_changed)
        form_proxy.addRow("Режим прокси:", self.combo_proxy_mode)

        self.txt_custom_proxy = QLineEdit(self)
        self.txt_custom_proxy.setPlaceholderText("Например: http://127.0.0.1:10809 или socks5://127.0.0.1:10808")
        self.txt_custom_proxy.setAccessibleName("Адрес пользовательского прокси-сервера")
        self.txt_custom_proxy.setAccessibleDescription("Введите адрес и порт прокси-сервера, например http://127.0.0.1:10809")
        form_proxy.addRow("Адрес ручного прокси:", self.txt_custom_proxy)

        self.lbl_proxy_status = QLabel(self)
        self.lbl_proxy_status.setWordWrap(True)
        self.lbl_proxy_status.setAccessibleName("Информация о системном прокси Windows")
        form_proxy.addRow("Статус системы:", self.lbl_proxy_status)

        self.btn_refresh_proxy = QPushButton("Обновить статус системного прокси", self)
        self.btn_refresh_proxy.setAccessibleName("Кнопка Обновить статус системного прокси")
        self.btn_refresh_proxy.setAccessibleDescription("Заново считывает параметры прокси из реестра Windows")
        self.btn_refresh_proxy.clicked.connect(self.update_proxy_status_ui)
        form_proxy.addRow("", self.btn_refresh_proxy)

        layout_proxy.addLayout(form_proxy)
        layout_proxy.addStretch()
        self.tabs.addTab(tab_proxy, "Сеть и Прокси")


        # Вкладка 2: Синтез SAPI5
        tab_sapi = QWidget()
        form_sapi = QFormLayout(tab_sapi)

        self.combo_sapi_voice = QComboBox(self)
        self.combo_sapi_voice.setAccessibleName("Список установленных в системе SAPI5 голосов")
        form_sapi.addRow("Голос SAPI5:", self.combo_sapi_voice)

        # Регулятор скорости речи SAPI5 (с плавным шагом 0.1, внутренний диапазон -100..100)
        self.slider_sapi_rate = AccessibleSmoothSlider(Qt.Horizontal, self)
        self.slider_sapi_rate.setRange(-100, 100)
        self.slider_sapi_rate.setValue(0)
        self.slider_sapi_rate.setSingleStep(5)   # шаг 0.5 для клавиатуры
        self.slider_sapi_rate.setPageStep(20)    # шаг 2.0 для PageUp/PageDown
        self.slider_sapi_rate.setAccessibleName("Скорость речи SAPI5: 0 (Нормальная)")
        self.slider_sapi_rate.setAccessibleDescription("Регулировка скорости синтезатора речи SAPI5 от -10 до +10 с плавной настройкой")

        self.btn_rate_down = QPushButton("◀ Медленнее", self)
        self.btn_rate_down.setStyleSheet(STEP_BUTTON_STYLE)
        self.btn_rate_down.setAccessibleName("Уменьшить скорость речи SAPI5 на единицу")
        self.btn_rate_down.clicked.connect(lambda: self.slider_sapi_rate.setValue(max(-100, self.slider_sapi_rate.value() - 10)))

        self.btn_rate_up = QPushButton("Быстрее ▶", self)
        self.btn_rate_up.setStyleSheet(STEP_BUTTON_STYLE)
        self.btn_rate_up.setAccessibleName("Увеличить скорость речи SAPI5 на единицу")
        self.btn_rate_up.clicked.connect(lambda: self.slider_sapi_rate.setValue(min(100, self.slider_sapi_rate.value() + 10)))

        self.btn_rate_reset = QPushButton("Сброс (0)", self)
        self.btn_rate_reset.setStyleSheet(STEP_BUTTON_STYLE)
        self.btn_rate_reset.setAccessibleName("Сбросить скорость речи SAPI5 на стандартное значение 0")
        self.btn_rate_reset.clicked.connect(lambda: self.slider_sapi_rate.setValue(0))

        self.lbl_sapi_rate_val = QLabel("0 (Нормальная)", self)
        self.lbl_sapi_rate_val.setStyleSheet(STEP_LABEL_STYLE)
        self.lbl_sapi_rate_val.setMinimumWidth(160)

        self.slider_sapi_rate.valueChanged.connect(self._on_sapi_rate_changed)

        h_rate = QHBoxLayout()
        h_rate.addWidget(self.btn_rate_down)
        h_rate.addWidget(self.slider_sapi_rate, 1)
        h_rate.addWidget(self.btn_rate_up)
        h_rate.addWidget(self.lbl_sapi_rate_val)
        h_rate.addWidget(self.btn_rate_reset)
        form_sapi.addRow("Скорость речи:", h_rate)

        # Регулятор громкости SAPI5
        self.slider_sapi_volume = AccessibleSmoothSlider(Qt.Horizontal, self)
        self.slider_sapi_volume.setRange(0, 100)
        self.slider_sapi_volume.setValue(100)
        self.slider_sapi_volume.setSingleStep(1)
        self.slider_sapi_volume.setPageStep(10)
        self.slider_sapi_volume.setAccessibleName("Громкость речи SAPI5: 100%")
        self.slider_sapi_volume.setAccessibleDescription("Регулировка громкости синтезатора SAPI5 от 0 до 100 процентов")

        self.btn_sapi_vol_down = QPushButton("◀ -5%", self)
        self.btn_sapi_vol_down.setStyleSheet(STEP_BUTTON_STYLE)
        self.btn_sapi_vol_down.setAccessibleName("Уменьшить громкость SAPI5 на 5 процентов")
        self.btn_sapi_vol_down.clicked.connect(lambda: self.slider_sapi_volume.setValue(max(0, self.slider_sapi_volume.value() - 5)))

        self.btn_sapi_vol_up = QPushButton("+5% ▶", self)
        self.btn_sapi_vol_up.setStyleSheet(STEP_BUTTON_STYLE)
        self.btn_sapi_vol_up.setAccessibleName("Увеличить громкость SAPI5 на 5 процентов")
        self.btn_sapi_vol_up.clicked.connect(lambda: self.slider_sapi_volume.setValue(min(100, self.slider_sapi_volume.value() + 5)))

        self.lbl_sapi_vol_val = QLabel("100%", self)
        self.lbl_sapi_vol_val.setStyleSheet(STEP_LABEL_STYLE)
        self.lbl_sapi_vol_val.setMinimumWidth(80)

        self.slider_sapi_volume.valueChanged.connect(self._on_sapi_vol_changed)

        h_vol = QHBoxLayout()
        h_vol.addWidget(self.btn_sapi_vol_down)
        h_vol.addWidget(self.slider_sapi_volume, 1)
        h_vol.addWidget(self.btn_sapi_vol_up)
        h_vol.addWidget(self.lbl_sapi_vol_val)
        form_sapi.addRow("Громкость SAPI5:", h_vol)

        self.spin_max_speedup = QDoubleSpinBox(self)
        self.spin_max_speedup.setRange(1.0, 5.0)
        self.spin_max_speedup.setSingleStep(0.1)
        self.spin_max_speedup.setValue(3.0)
        self.spin_max_speedup.setSuffix(" x")
        self.spin_max_speedup.setAccessibleName("Максимально допустимый предел ускорения речи (по умолчанию 3.0x)")
        form_sapi.addRow("Макс. разгон речи (лимит):", self.spin_max_speedup)

        self.btn_preview_voice = QPushButton("Прослушать пример звучания", self)
        self.btn_preview_voice.setAccessibleName("Кнопка Прослушать пример звучания SAPI5")
        self.btn_preview_voice.setAccessibleDescription("Воспроизводит пример звучания выбранного системного голоса SAPI5 с установленной скоростью и громкостью")
        self.btn_preview_voice.clicked.connect(self.preview_sapi_voice)
        form_sapi.addRow("", self.btn_preview_voice)

        self.tabs.addTab(tab_sapi, "Синтез SAPI5")

        main_layout.addWidget(self.tabs)

        # Нижние кнопки
        bottom_layout = QHBoxLayout()
        bottom_layout.setContentsMargins(10, 15, 10, 10)
        bottom_layout.setSpacing(15)

        self.btn_save = QPushButton("Сохранить настройки", self)
        self.btn_save.setAccessibleName("Кнопка Сохранить настройки")
        self.btn_save.setAccessibleDescription("Сохраняет текущие настройки программы и закрывает окно")
        self.btn_save.setMinimumHeight(40)
        self.btn_save.setMinimumWidth(200)
        font_save = self.btn_save.font()
        font_save.setPointSize(10)
        font_save.setBold(True)
        self.btn_save.setFont(font_save)
        self.btn_save.setDefault(True)
        self.btn_save.clicked.connect(self.save_settings)

        self.btn_cancel = QPushButton("Отмена", self)
        self.btn_cancel.setAccessibleName("Кнопка Отмена")
        self.btn_cancel.setAccessibleDescription("Закрывает окно настроек без сохранения изменений")
        self.btn_cancel.setMinimumHeight(40)
        self.btn_cancel.setMinimumWidth(130)
        font_cancel = self.btn_cancel.font()
        font_cancel.setPointSize(10)
        font_cancel.setBold(True)
        self.btn_cancel.setFont(font_cancel)
        self.btn_cancel.clicked.connect(self.reject)

        bottom_layout.addStretch()
        bottom_layout.addWidget(self.btn_save)
        bottom_layout.addWidget(self.btn_cancel)
        main_layout.addLayout(bottom_layout)

    def _open_token_stats(self):
        """Открывает диалог статистики расхода токенов."""
        from ui.token_usage_dialog import TokenUsageDialog
        dlg = TokenUsageDialog(self.config, self)
        dlg.exec()

    def _on_proxy_mode_changed(self):
        mode = self.combo_proxy_mode.currentData()
        is_custom = (mode == "custom")
        self.txt_custom_proxy.setEnabled(is_custom)

    def _on_sapi_rate_changed(self, val: int):
        float_rate = val / 10.0
        int_rate = int(round(float_rate))
        if abs(float_rate) < 0.05:
            txt = "0 (Нормальная)"
        elif float_rate > 0:
            val_str = f"{int_rate:+d}" if abs(float_rate - int_rate) < 0.05 else f"{float_rate:+.1f}"
            txt = f"{val_str} (Быстрее)"
        else:
            val_str = f"{int_rate:+d}" if abs(float_rate - int_rate) < 0.05 else f"{float_rate:+.1f}"
            txt = f"{val_str} (Медленнее)"
        self.lbl_sapi_rate_val.setText(txt)
        self.slider_sapi_rate.setAccessibleName(f"Скорость речи SAPI5: {txt}")

    def _on_sapi_vol_changed(self, val: int):
        self.lbl_sapi_vol_val.setText(f"{val}%")
        self.slider_sapi_volume.setAccessibleName(f"Громкость речи SAPI5: {val} процентов")

    def update_proxy_status_ui(self):
        desc = get_proxy_status_description()
        self.lbl_proxy_status.setText(desc)

    def load_current_settings(self):
        # Gemini
        self.txt_api_key.setText(self.config.api_key)
        cur_model = self.config.gemini_model
        if cur_model:
            self.combo_comment_model.addItem(cur_model)
            self.combo_comment_model.setCurrentText(cur_model)

        cur_tts_model = self.config.gemini_tts_model
        if cur_tts_model:
            self.combo_tts_model.addItem(cur_tts_model)
            self.combo_tts_model.setCurrentText(cur_tts_model)

        cur_voice = self.config.gemini_tts_voice
        if cur_voice:
            idx = self.combo_tts_voice.findText(cur_voice)
            if idx >= 0:
                self.combo_tts_voice.setCurrentIndex(idx)

        self.spin_chunk_duration.setValue(self.config.chunk_duration_minutes)
        self.spin_api_pause.setValue(self.config.api_request_pause_sec)

        # Proxy
        mode = self.config.proxy_mode
        idx = self.combo_proxy_mode.findData(mode)
        if idx >= 0:
            self.combo_proxy_mode.setCurrentIndex(idx)
        else:
            self.combo_proxy_mode.setCurrentIndex(0)
        self.txt_custom_proxy.setText(self.config.custom_proxy)
        self._on_proxy_mode_changed()
        self.update_proxy_status_ui()

        # SAPI5 & Timing
        self.populate_sapi_voices()
        rate_internal = int(round(self.config.sapi5_rate * 10))
        self.slider_sapi_rate.setValue(rate_internal)
        self._on_sapi_rate_changed(rate_internal)

        vol_val = self.config.sapi5_volume
        self.slider_sapi_volume.setValue(vol_val)
        self._on_sapi_vol_changed(vol_val)

        self.spin_max_speedup.setValue(self.config.max_speedup)

    def populate_sapi_voices(self):
        self.combo_sapi_voice.clear()
        voices = SAPI5Engine.get_installed_voices()
        saved_voice = self.config.sapi5_voice.strip().lower()
        selected_idx = 0
        for idx, v in enumerate(voices):
            v_name = v["name"]
            self.combo_sapi_voice.addItem(v_name, v_name)
            if saved_voice and saved_voice == v_name.strip().lower():
                selected_idx = idx
            elif saved_voice and saved_voice in v_name.strip().lower() and selected_idx == 0:
                selected_idx = idx
        if voices:
            self.combo_sapi_voice.setCurrentIndex(selected_idx)

    def fetch_gemini_models(self):
        key = self.txt_api_key.text().strip()
        if not key:
            QMessageBox.warning(self, "Внимание", "Пожалуйста, сначала введите API-ключ Google Gemini.")
            return

        # Применяем настройки прокси перед запросом
        mode = self.combo_proxy_mode.currentData() or "system"
        custom_proxy = self.txt_custom_proxy.text().strip()
        apply_proxy_settings(mode, custom_proxy)

        try:
            client = GeminiClient(key)
            text_models, tts_models = client.fetch_available_models()

            if not text_models:
                QMessageBox.warning(self, "Результат", "Не найдено доступных моделей для данного ключа.")
                return

            self.combo_comment_model.clear()
            for m in text_models:
                self.combo_comment_model.addItem(m)

            self.combo_tts_model.clear()
            for m in tts_models:
                self.combo_tts_model.addItem(m)

            QMessageBox.information(
                self, "Успешно",
                f"Загружен актуальный список моделей с серверов Google Gemini:\nМоделей для комментирования: {len(text_models)}\nМоделей для TTS: {len(tts_models)}"
            )
        except Exception as e:
            QMessageBox.critical(self, "Ошибка", f"Не удалось получить список моделей:\n{e}")

    def play_gemini_voice_sample(self):
        """Воспроизводит WAV-образец звучания выбранного голоса Gemini TTS."""
        SAPI5Engine.stop_preview()
        voice_name = self.combo_tts_voice.currentText().strip()
        if not voice_name:
            return

        sample_path = os.path.join(get_voice_samples_dir(), "gemini", f"{voice_name}.wav")
        if os.path.isfile(sample_path):
            self.voice_player.stop()
            self.voice_player.setSource(QUrl.fromLocalFile(sample_path))
            self.voice_player.play()
        else:
            print(f"Образец голоса «{voice_name}» не найден по пути: {sample_path}")

    def preview_sapi_voice(self):
        self.voice_player.stop()
        voice_name = self.combo_sapi_voice.currentText()
        rate = int(round(self.slider_sapi_rate.value() / 10.0))
        vol = self.slider_sapi_volume.value()
        SAPI5Engine.preview_voice(voice_name, rate, vol, "Это пример звучания выбранного голоса синтезатора речи.")

    def closeEvent(self, event):
        self.voice_player.stop()
        SAPI5Engine.stop_preview()
        super().closeEvent(event)

    def reject(self):
        self.voice_player.stop()
        SAPI5Engine.stop_preview()
        super().reject()

    def accept(self):
        self.voice_player.stop()
        SAPI5Engine.stop_preview()
        super().accept()

    def save_settings(self):
        self.voice_player.stop()
        SAPI5Engine.stop_preview()
        # Gemini
        self.config.api_key = self.txt_api_key.text().strip()
        if self.combo_comment_model.currentText():
            self.config.gemini_model = self.combo_comment_model.currentText()
        if self.combo_tts_model.currentText():
            self.config.gemini_tts_model = self.combo_tts_model.currentText()
        self.config.gemini_tts_voice = self.combo_tts_voice.currentText()
        self.config.chunk_duration_minutes = self.spin_chunk_duration.value()
        self.config.api_request_pause_sec = self.spin_api_pause.value()

        # Proxy
        mode = self.combo_proxy_mode.currentData() or "system"
        custom_proxy = self.txt_custom_proxy.text().strip()
        self.config.proxy_mode = mode
        self.config.custom_proxy = custom_proxy
        apply_proxy_settings(mode, custom_proxy)

        # SAPI5 & Timing
        if self.combo_sapi_voice.currentText():
            self.config.sapi5_voice = self.combo_sapi_voice.currentText()
        self.config.sapi5_rate = int(round(self.slider_sapi_rate.value() / 10.0))
        self.config.sapi5_volume = self.slider_sapi_volume.value()
        self.config.max_speedup = self.spin_max_speedup.value()

        self.config.save()
        self.accept()

