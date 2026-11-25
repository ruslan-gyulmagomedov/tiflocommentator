# -*- coding: utf-8 -*-
"""
Модуль для определения путей приложения и поиска переносимых (portable) бинарных файлов.
"""

import os
import sys
import shutil


def get_app_dir() -> str:
    """
    Возвращает корневую директорию приложения.
    Корректно работает как в режиме запуска скрипта, так и в скомпилированном PyInstaller (portable).
    """
    if getattr(sys, 'frozen', False):
        # Если запущено из скомпилированного exe
        return os.path.dirname(os.path.abspath(sys.executable))
    # Если запущено как обычный python скрипт
    return os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def get_bundle_dir() -> str:
    """Возвращает временную директорию ресурсов PyInstaller (_MEIPASS) или app_dir."""
    if getattr(sys, 'frozen', False) and hasattr(sys, '_MEIPASS'):
        return sys._MEIPASS
    return get_app_dir()


def get_settings_path() -> str:
    """Возвращает абсолютный путь к файлу Settings.ini в корне приложения."""
    return os.path.join(get_app_dir(), "Settings.ini")


def get_projects_dir() -> str:
    """Возвращает путь к каталогу проектов Projects/."""
    projects_dir = os.path.join(get_app_dir(), "Projects")
    os.makedirs(projects_dir, exist_ok=True)
    return projects_dir


def get_ffmpeg_path(custom_path: str = "") -> str:
    """
    Находит исполняемый файл ffmpeg.exe.
    Приоритет поиска:
    1. Переданный пользовательский путь (если существует).
    2. Папка bin/ в корне приложения (portable).
    3. Папка _MEIPASS/bin (для PyInstaller onefile/onedir).
    4. Поиск в системном PATH.
    """
    if custom_path and os.path.isfile(custom_path):
        return os.path.abspath(custom_path)

    # Локальная папка bin
    local_bin = os.path.join(get_app_dir(), "bin", "ffmpeg.exe")
    if os.path.isfile(local_bin):
        return local_bin

    # Внутри bundle PyInstaller
    bundle_bin = os.path.join(get_bundle_dir(), "bin", "ffmpeg.exe")
    if os.path.isfile(bundle_bin):
        return bundle_bin

    # Системный путь
    sys_path = shutil.which("ffmpeg")
    if sys_path:
        return sys_path

    # Стандартный путь в DownloadHelper если есть
    dh_path = r"C:\Program Files\DownloadHelper CoApp\ffmpeg.exe"
    if os.path.isfile(dh_path):
        return dh_path

    return "ffmpeg"


def get_ffprobe_path(custom_path: str = "") -> str:
    """
    Находит исполняемый файл ffprobe.exe.
    """
    if custom_path and os.path.isfile(custom_path):
        return os.path.abspath(custom_path)

    local_bin = os.path.join(get_app_dir(), "bin", "ffprobe.exe")
    if os.path.isfile(local_bin):
        return local_bin

    bundle_bin = os.path.join(get_bundle_dir(), "bin", "ffprobe.exe")
    if os.path.isfile(bundle_bin):
        return bundle_bin

    sys_path = shutil.which("ffprobe")
    if sys_path:
        return sys_path

    dh_path = r"C:\Program Files\DownloadHelper CoApp\ffprobe.exe"
    if os.path.isfile(dh_path):
        return dh_path

    return "ffprobe"


def get_icon_path() -> str:
    """Возвращает путь к иконке приложения (.ico)."""
    # 1. В бандле ресурсов PyInstaller (_MEIPASS)
    bundle_ico = os.path.join(get_bundle_dir(), "logo.ico")
    if os.path.isfile(bundle_ico):
        return bundle_ico
    # 2. В корне рабочей директории приложения
    app_ico = os.path.join(get_app_dir(), "logo.ico")
    if os.path.isfile(app_ico):
        return app_ico
    return ""


def get_logo_path() -> str:
    """Возвращает путь к изображению логотипа приложения (.jpg)."""
    # 1. В бандле ресурсов PyInstaller (_MEIPASS)
    bundle_jpg = os.path.join(get_bundle_dir(), "logo.jpg")
    if os.path.isfile(bundle_jpg):
        return bundle_jpg
    # 2. В корне рабочей директории приложения
    app_jpg = os.path.join(get_app_dir(), "logo.jpg")
    if os.path.isfile(app_jpg):
        return app_jpg
    return ""


def get_voice_samples_dir() -> str:
    """Возвращает путь к каталогу с демонстрационными образцами голосов."""
    # Сначала проверяем в bundle/ресурсах
    bundle_path = os.path.join(get_bundle_dir(), "voice_samples")
    if os.path.isdir(bundle_path):
        return bundle_path
    # Затем в рабочей папке приложения
    app_path = os.path.join(get_app_dir(), "voice_samples")
    os.makedirs(app_path, exist_ok=True)
    return app_path



def get_logs_dir() -> str:
    """
    Возвращает каталог журналов программы.
    В исходниках журналы лежат в logs/ рядом с проектом.
    В собранном EXE — в LOCALAPPDATA, чтобы рядом с программой
    остались только Projects и Settings.ini.
    """
    if getattr(sys, 'frozen', False):
        base = os.environ.get('LOCALAPPDATA') or os.path.expanduser('~')
        path = os.path.join(base, 'Tiflocommentator', 'logs')
    else:
        path = os.path.join(get_app_dir(), 'logs')
    os.makedirs(path, exist_ok=True)
    return path


def get_help_index_path() -> str:
    """Возвращает абсолютный путь к файлу руководства пользователя Help/index.html."""
    # 1. В бандле ресурсов PyInstaller (_MEIPASS)
    bundle_help = os.path.join(get_bundle_dir(), "Help", "index.html")
    if os.path.isfile(bundle_help):
        return bundle_help
    # 2. В рабочей папке приложения
    app_help = os.path.join(get_app_dir(), "Help", "index.html")
    if os.path.isfile(app_help):
        return app_help
    return ""

