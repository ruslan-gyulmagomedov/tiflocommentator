# -*- mode: python ; coding: utf-8 -*-
from PyInstaller.utils.hooks import collect_data_files

datas = [('D:\\Python\\Tiflocommentaator\\Tiflocommentator\\bin', 'bin'), ('D:\\Python\\Tiflocommentaator\\Tiflocommentator\\voice_samples', 'voice_samples'), ('D:\\Python\\Tiflocommentaator\\Tiflocommentator\\Help', 'Help'), ('D:\\Python\\Tiflocommentaator\\Tiflocommentator\\logo.ico', '.'), ('D:\\Python\\Tiflocommentaator\\Tiflocommentator\\logo.jpg', '.')]
datas += collect_data_files('google.generativeai')


a = Analysis(
    ['D:\\Python\\Tiflocommentaator\\Tiflocommentator\\main.py'],
    pathex=[],
    binaries=[],
    datas=datas,
    hiddenimports=['PySide6.QtMultimedia', 'PySide6.QtMultimediaWidgets', 'google.generativeai', 'googleapiclient', 'httplib2', 'socks', 'win32com.client', 'numpy'],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=['scipy', 'matplotlib', 'torch', 'torchvision', 'torchaudio', 'transformers'],
    noarchive=False,
    optimize=0,
)
pyz = PYZ(a.pure)
splash = Splash(
    'D:\\Python\\Tiflocommentaator\\Tiflocommentator\\logo.jpg',
    binaries=a.binaries,
    datas=a.datas,
    text_pos=None,
    text_size=12,
    minify_script=True,
    always_on_top=True,
)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    splash,
    splash.binaries,
    [],
    name='Tiflocommentator',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=['D:\\Python\\Tiflocommentaator\\Tiflocommentator\\logo.ico'],
)
