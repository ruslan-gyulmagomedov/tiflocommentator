# -*- coding: utf-8 -*-
"""
Точка входа приложения для создания тифлокомментариев к видео.
Фреймворк: PySide6.
Полная поддержка скринридеров NVDA / JAWS.
"""

import sys
import os
import ctypes
import traceback

# Добавляем корневую директорию проекта в sys.path
root_dir = os.path.dirname(os.path.abspath(__file__))
if root_dir not in sys.path:
    sys.path.insert(0, root_dir)

# Установка явного идентификатора модели приложения в Windows для корректного отображения иконки на панели задач
try:
    myappid = 'tiflocommentator.app.portable.1.0'
    ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(myappid)
except Exception:
    pass

# Глобальный перехватчик исключений для логирования в файл crash.log рядом с EXE
def log_uncaught_exceptions(exctype, value, tb):
    error_msg = "".join(traceback.format_exception(exctype, value, tb))
    try:
        from core.app_paths import get_app_dir
        log_file = os.path.join(get_app_dir(), "crash.log")
        with open(log_file, "a", encoding="utf-8") as f:
            f.write(f"\n--- CRASH REPORT ---\n{error_msg}\n")
    except Exception:
        pass
    # Закрываем сплэш если возникло падение
    try:
        import pyi_splash
        pyi_splash.close()
    except Exception:
        pass
    sys.__excepthook__(exctype, value, tb)

sys.excepthook = log_uncaught_exceptions

from PySide6.QtWidgets import QApplication
from PySide6.QtGui import QIcon
from PySide6.QtCore import Qt
from core.app_paths import get_icon_path, get_logo_path
from core.config_manager import ConfigManager
from core.proxy_manager import apply_proxy_settings
from ui.main_window import MainWindow


def main():
    # Настройка масштабирования High-DPI
    QApplication.setHighDpiScaleFactorRoundingPolicy(
        Qt.HighDpiScaleFactorRoundingPolicy.PassThrough
    )

    app = QApplication(sys.argv)
    app.setApplicationName("Тифлокомментатор видео")
    app.setOrganizationName("Tiflocommentator")

    # Применяем настройки прокси (системный Windows по умолчанию)
    try:
        cfg = ConfigManager()
        apply_proxy_settings(mode=cfg.proxy_mode, custom_proxy=cfg.custom_proxy)
    except Exception as e:
        print(f"Ошибка применения настроек прокси при запуске: {e}")

    # Установка иконки приложения для всех окон и диалогов
    icon_path = get_icon_path()
    if not icon_path or not os.path.isfile(icon_path):
        icon_path = get_logo_path()

    if icon_path and os.path.isfile(icon_path):
        app_icon = QIcon(icon_path)
        app.setWindowIcon(app_icon)
    else:
        app_icon = None

    # Всплывающие подсказки строго по цветам текущей системной темы Windows
    app.setStyleSheet("""
        QToolTip {
            color: palette(window-text);
            background-color: palette(window);
            border: 2px solid palette(highlight);
            font-size: 13px;
            padding: 4px 8px;
        }
    """)

    window = MainWindow()
    if app_icon:
        window.setWindowIcon(app_icon)
    window.showMaximized()

    # Закрываем сплэш-экран PyInstaller сразу после создания и показа главного окна
    try:
        import pyi_splash
        pyi_splash.close()
    except (ImportError, Exception):
        pass

    sys.exit(app.exec())


if __name__ == "__main__":
    main()



