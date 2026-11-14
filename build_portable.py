# -*- coding: utf-8 -*-
"""
Скрипт для сборки полностью портабельной (portable) версии приложения с помощью PyInstaller.
Создает единый исполняемый файл Tiflocommentator.exe с иконкой и сплэш-экраном (logo.jpg),
включает статический FFmpeg, FFprobe, образцы голосов, документацию Help и зависимости.
Помещает готовый автономный пакет в папку Portable/ (вместе с Settings.ini и Projects/).
"""

import os
import sys
import subprocess
import shutil
from PIL import Image


def ensure_icon(app_dir: str):
    """Гарантирует существование многослойного файла logo.ico."""
    ico_path = os.path.join(app_dir, "logo.ico")
    jpg_path = os.path.join(app_dir, "logo.jpg")

    if not os.path.isfile(ico_path) and os.path.isfile(jpg_path):
        print("Генерация многослойного logo.ico из logo.jpg...")
        img = Image.open(jpg_path)
        img.save(ico_path, format="ICO", sizes=[(16, 16), (24, 24), (32, 32), (48, 48), (64, 64), (128, 128), (256, 256)])
        print("Файл logo.ico успешно создан.")


def build():
    app_dir = os.path.dirname(os.path.abspath(__file__))
    bin_dir = os.path.join(app_dir, "bin")
    voice_samples_dir = os.path.join(app_dir, "voice_samples")
    help_dir = os.path.join(app_dir, "Help")
    logo_jpg = os.path.join(app_dir, "logo.jpg")
    logo_ico = os.path.join(app_dir, "logo.ico")
    portable_dir = os.path.join(app_dir, "Portable")

    ensure_icon(app_dir)

    # Проверка наличия бинарных файлов FFmpeg
    ffmpeg_exe = os.path.join(bin_dir, "ffmpeg.exe")
    ffprobe_exe = os.path.join(bin_dir, "ffprobe.exe")

    if not os.path.isfile(ffmpeg_exe) or not os.path.isfile(ffprobe_exe):
        print("Внимание: ffmpeg.exe или ffprobe.exe отсутствуют в папке bin!")

    # Формируем команду сборки PyInstaller в режиме Onefile без консоли
    cmd = [
        sys.executable,
        "-m", "PyInstaller",
        "--name=Tiflocommentator",
        "--onefile",
        "--windowed",
        "--noconfirm",
        "--clean",
        "--noupx",
        f"--icon={logo_ico}",
        f"--splash={logo_jpg}",
        f"--add-data={bin_dir};bin",
        f"--add-data={voice_samples_dir};voice_samples",
        f"--add-data={help_dir};Help",
        f"--add-data={logo_ico};.",
        f"--add-data={logo_jpg};.",
        "--collect-data=google.generativeai",
        "--hidden-import=PySide6.QtMultimedia",
        "--hidden-import=PySide6.QtMultimediaWidgets",
        "--hidden-import=google.generativeai",
        "--hidden-import=googleapiclient",
        "--hidden-import=httplib2",
        "--hidden-import=socks",
        "--hidden-import=win32com.client",
        "--hidden-import=numpy",
        "--exclude-module=scipy",
        "--exclude-module=matplotlib",
        "--exclude-module=torch",
        "--exclude-module=torchvision",
        "--exclude-module=torchaudio",
        "--exclude-module=transformers",
        os.path.join(app_dir, "main.py")
    ]

    print("Запуск сборки автономной Onefile версии...")
    print(" ".join(cmd))
    subprocess.run(cmd, check=True)

    # Подготовка каталога Portable
    print("\nФормирование каталога Portable...")
    os.makedirs(portable_dir, exist_ok=True)
    os.makedirs(os.path.join(portable_dir, "Projects"), exist_ok=True)

    dist_exe = os.path.join(app_dir, "dist", "Tiflocommentator.exe")
    target_exe = os.path.join(portable_dir, "Tiflocommentator.exe")

    if os.path.isfile(dist_exe):
        print(f"Копирование {dist_exe} -> {target_exe}...")
        shutil.copy2(dist_exe, target_exe)
    else:
        print(f"Ошибка: Не найден скомпилированный файл {dist_exe}!")
        return

    # Копируем Settings.ini наружу рядом с EXE
    src_settings = os.path.join(app_dir, "Settings.ini")
    dst_settings = os.path.join(portable_dir, "Settings.ini")
    if os.path.isfile(src_settings):
        print(f"Копирование настроек Settings.ini в {dst_settings}...")
        shutil.copy2(src_settings, dst_settings)

    print("\n=======================================================")
    print("Сборка портабельной версии успешно завершена!")
    print(f"Готовый каталог для переноса на флешку: {portable_dir}")
    print("Содержимое каталога Portable:")
    for item in os.listdir(portable_dir):
        print(f"  - {item}")
    print("=======================================================\n")


if __name__ == "__main__":
    build()


