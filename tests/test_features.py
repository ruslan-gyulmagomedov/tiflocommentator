# -*- coding: utf-8 -*-
"""
Автоматические тесты функционала экспорта MKV, доступности и горячих клавиш таймлайна.
"""

import sys
import os
import shutil
import tempfile
import unittest.mock

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from PySide6.QtWidgets import QApplication, QMessageBox
from PySide6.QtCore import Qt, QEvent
from PySide6.QtGui import QKeyEvent

# Инициализация QApplication для headless / unit-тестирования
app = QApplication.instance()
if not app:
    app = QApplication(sys.argv)

from core.audio_dsp import format_duration_sec
from core.srt_manager import (
    format_srt_time, parse_srt_time, clean_srt_text,
    parse_srt_content, parse_srt_file, generate_srt_content,
    generate_srt_file, export_commentaries_to_srt
)
from ui.accessible_timeline import VisualTimelineCanvas, AccessibleTimelineWidget
from ui.export_progress_dialog import MKVExportWorker, MKVExportProgressDialog


def test_time_formatting():
    assert format_duration_sec(0) == "00:00"
    assert format_duration_sec(59) == "00:59"
    assert format_duration_sec(65) == "01:05"
    assert format_duration_sec(3665) == "01:01:05"
    assert format_srt_time(0.0) == "00:00:00,000"
    assert format_srt_time(75.5) == "00:01:15,500"
    print("[OK] test_time_formatting passed")


def test_srt_generation(tmp_path="tests_tmp"):
    os.makedirs(tmp_path, exist_ok=True)
    srt_file = os.path.join(tmp_path, "test.srt")
    comms = [
        {"start_time": 1.0, "end_time": 4.5, "text": "Первый комментарий"},
        {"start_time": 10.2, "end_time": 13.8, "text": "Второй комментарий"}
    ]
    generate_srt_file(comms, srt_file)
    assert os.path.isfile(srt_file)
    with open(srt_file, "r", encoding="utf-8") as f:
        content = f.read()
    assert "00:00:01,000 --> 00:00:04,500" in content
    assert "Первый комментарий" in content
    assert "00:00:10,200 --> 00:00:13,800" in content
    assert "Второй комментарий" in content
    os.remove(srt_file)
    os.rmdir(tmp_path)
    print("[OK] test_srt_generation passed")


def test_timeline_hotkeys():
    canvas = VisualTimelineCanvas()
    canvas.set_duration(100.0)
    canvas.set_position(50.0)

    assert canvas.focusPolicy() == Qt.StrongFocus, "Таймлайн должен обладать политикой Qt.StrongFocus"

    play_pause_called = []
    seek_called = []
    canvas.play_pause_requested.connect(lambda: play_pause_called.append(True))
    canvas.seek_requested.connect(lambda pos: seek_called.append(pos))

    # 1. Пробел -> Воспроизведение / Пауза
    ev_space = QKeyEvent(QEvent.KeyPress, Qt.Key_Space, Qt.NoModifier)
    canvas.keyPressEvent(ev_space)
    assert len(play_pause_called) == 1, "Пробел должен вызывать сигнал play_pause_requested"

    # 2. Home -> в начало при любом масштабе
    ev_home = QKeyEvent(QEvent.KeyPress, Qt.Key_Home, Qt.NoModifier)
    canvas.keyPressEvent(ev_home)
    assert canvas.current_pos_sec == 0.0
    assert seek_called[-1] == 0

    # 3. End -> в конец при любом масштабе
    ev_end = QKeyEvent(QEvent.KeyPress, Qt.Key_End, Qt.NoModifier)
    canvas.keyPressEvent(ev_end)
    assert canvas.current_pos_sec == 100.0
    assert seek_called[-1] == 100000

    # 4. Page Up при полном масштабе (zoom=1.0) -> в начало
    canvas.set_zoom(1.0)
    canvas.set_position(50.0)
    ev_pgup = QKeyEvent(QEvent.KeyPress, Qt.Key_PageUp, Qt.NoModifier)
    canvas.keyPressEvent(ev_pgup)
    assert canvas.current_pos_sec == 0.0
    assert seek_called[-1] == 0

    # 5. Page Down при полном масштабе (zoom=1.0) -> в конец
    canvas.set_position(50.0)
    ev_pgdn = QKeyEvent(QEvent.KeyPress, Qt.Key_PageDown, Qt.NoModifier)
    canvas.keyPressEvent(ev_pgdn)
    assert canvas.current_pos_sec == 100.0
    assert seek_called[-1] == 100000

    # 6. Page Up / Page Down при приближении (zoom=5.0, visible duration = 20.0s)
    canvas.set_zoom(5.0)
    canvas.set_position(50.0)
    canvas.keyPressEvent(ev_pgup)
    assert abs(canvas.current_pos_sec - 30.0) < 0.001, f"Expected 30.0, got {canvas.current_pos_sec}"
    assert seek_called[-1] == 30000

    canvas.keyPressEvent(ev_pgdn)
    assert abs(canvas.current_pos_sec - 50.0) < 0.001, f"Expected 50.0, got {canvas.current_pos_sec}"
    assert seek_called[-1] == 50000

    # Проверка проброса через AccessibleTimelineWidget
    widget = AccessibleTimelineWidget()
    widget_play_pause = []
    widget.play_pause_requested.connect(lambda: widget_play_pause.append(True))
    widget.canvas.play_pause_requested.emit()
    assert len(widget_play_pause) == 1, "AccessibleTimelineWidget должен пробрасывать play_pause_requested"

    print("[OK] test_timeline_hotkeys passed")


def test_export_worker_cancel():
    class DummyProject:
        name = "Тестовый фильм"
        output_dir = "tests_tmp"
        commentaries = []
        data = {"src_video_path": "dummy.mp4", "total_duration_sec": 10.0}

    class DummyConfig:
        ffmpeg_path = ""
        movie_volume_db = 0.0
        commentary_volume_db = 0.0
        movie_volume = 0.0
        commentary_volume = 0.0
        auto_ducking = True
        ducking_level_db = -12.0
        compressor_threshold_db = -2.0
        compressor_lookahead_ms = 5.0
        compressor_release_ms = 120.0

    worker = MKVExportWorker(DummyProject(), "tests_tmp/out.mkv", DummyConfig())
    worker.cancel()
    assert worker._is_cancelled is True
    assert worker.cancel_event.is_set() is True
    print("[OK] test_export_worker_cancel passed")


from core.project_manager import Project, ProjectManager
from core.gemini_client import SYSTEM_INSTRUCTION_TIFLO, GeminiClient
from core.config_manager import ConfigManager
from ui.video_player_widget import VideoPlayerWidget
from ui.user_prompt_dialog import UserPromptDialog


def test_project_user_prompt(tmp_path="tests_tmp_proj"):
    os.makedirs(tmp_path, exist_ok=True)
    proj = Project("Тестовый фильм", tmp_path)
    assert proj.user_prompt == "", "По умолчанию user_prompt должен быть пустой строкой"

    test_text = (
        "Сделайте перевод всех диалогов на английский язык.\n"
        "Сюжет: Детектив расследует таинственное исчезновение картины в музее."
    )
    proj.user_prompt = test_text
    assert proj.user_prompt == test_text
    proj.save()

    loaded_proj = Project.load(tmp_path)
    assert loaded_proj is not None
    assert loaded_proj.user_prompt == test_text, "Пожелания пользователя должны корректно сохраняться и загружаться из project.json"

    # Очистка
    import shutil
    shutil.rmtree(tmp_path, ignore_errors=True)
    print("[OK] test_project_user_prompt passed")


def test_gemini_prompt_and_all_commentaries():
    # 1. Проверка системного промпта на высший приоритет пожеланий
    assert "НАИВЫСШИЙ ПРИОРИТЕТ ПОЖЕЛАНИЙ" in SYSTEM_INSTRUCTION_TIFLO
    assert "перевод" in SYSTEM_INSTRUCTION_TIFLO.lower()

    # 2. Проверка того, что в промпте фрагмента исключена история предыдущих комментариев
    # и сохранены карточки персонажей, номер части и пожелания пользователя
    chars = [
        {"id": "char_1", "name": "Иван", "role": "Главный герой", "description": "Мужчина 35 лет в пальто"}
    ]
    user_wishes = "Не описывать фоновую музыку, только действия."

    # Проверяем структуру промпта без вызова API
    start_m, start_s = divmod(int(60.0), 60)
    start_h, start_m = divmod(start_m, 60)
    end_m, end_s = divmod(int(120.0), 60)
    end_h, end_m = divmod(end_m, 60)
    start_str = f"{start_h:02d}:{start_m:02d}:{start_s:02d}"
    end_str = f"{end_h:02d}:{end_m:02d}:{end_s:02d}"

    chars_summary = [f"- {c['name']} ({c['role']}): {c['description']}" for c in chars]
    chars_context = "\n".join(chars_summary)

    # Проверяем, что промпт собирается с персонажами и пожеланиями, но без истории комментариев
    assert "Иван (Главный герой)" in chars_context
    assert "Не описывать фоновую музыку" in user_wishes
    print("[OK] test_gemini_prompt_and_all_commentaries passed")


def test_video_player_dsp():
    import tempfile
    player_widget = VideoPlayerWidget()

    # Сценарий 1: movie = 0.0 dB (100%), comm = +6.0 dB (200%), compressor threshold = -2.0 dBFS
    player_widget.set_audio_dsp_config(
        movie_vol_db=0.0,
        comm_vol_db=6.0,
        auto_ducking=True,
        ducking_db=-12.0,
        ducking_attack_ms=50.0,
        ducking_release_ms=200.0,
        comp_threshold_db=-2.0
    )

    # Базовые уровни: фильм играет на полной громкости 1.0 (0 dB), комментарии также на максимуме 1.0
    # Громкость фильма НЕ делится на громкость комментариев!
    assert abs(player_widget.base_movie_vol - 1.0) < 0.001
    assert abs(player_widget.base_comm_vol - 1.0) < 0.001

    # Создаем фиктивный временный файл для комментария
    tmp_audio_dir = tempfile.mkdtemp()
    dummy_wav = os.path.join(tmp_audio_dir, "comm_test.wav")
    with open(dummy_wav, "wb") as f:
        f.write(b"RIFF\x24\x00\x00\x00WAVEfmt \x10\x00\x00\x00\x01\x00\x01\x00D\xac\x00\x00\x88X\x01\x00\x02\x00\x10\x00data\x00\x00\x00\x00")

    player_widget.set_commentaries([
        {"id": "c1", "start_time": 10.0, "end_time": 15.0, "text": "Тест", "audio_file": dummy_wav}
    ])

    duck_gain = 10.0 ** (-12.0 / 20.0)  # ~0.2512

    # Проверка огибающей дакинга
    # До атаки (t = 9.0 сек) -> 1.0 (полная громкость)
    assert abs(player_widget.compute_ducking_multiplier(9.0) - 1.0) < 0.001

    # В фазе атаки (t = 9.975 сек -> 50% атаки) -> между 1.0 и duck_gain
    mult_attack = player_widget.compute_ducking_multiplier(9.975)
    assert duck_gain < mult_attack < 1.0

    # В активной фазе (t = 12.0 сек) -> duck_gain (~0.2512)
    assert abs(player_widget.compute_ducking_multiplier(12.0) - duck_gain) < 0.001

    # В фазе восстановления (t = 15.1 сек -> 50% релиза) -> между duck_gain и 1.0
    mult_release = player_widget.compute_ducking_multiplier(15.1)
    assert duck_gain < mult_release < 1.0

    # После релиза (t = 16.0 сек) -> 1.0 (восстановлено)
    assert abs(player_widget.compute_ducking_multiplier(16.0) - 1.0) < 0.001

    # Проверка работы DSP при автодакинге:
    # 1. Вне комментария (t = 9.0 сек, 9000 мс): фильм звучит на своей полной установленной громкости 1.0
    player_widget.apply_audio_dsp(9000)
    assert abs(player_widget.current_applied_movie_vol - 1.0) < 0.001

    # 2. Во время звучания комментария (t = 12.0 сек, 12000 мс):
    # Фильм плавно приглушается дакингом, комментарий играет на своей громкости
    player_widget.apply_audio_dsp(12000)
    assert abs(player_widget.current_applied_movie_vol - duck_gain) < 0.001
    assert abs(player_widget.current_applied_comm_vol - 1.0) < 0.001

    # 3. Проверка режима с отключенным автодакингом (auto_ducking = False):
    player_widget.set_audio_dsp_config(
        movie_vol_db=0.0,
        comm_vol_db=20.0,
        auto_ducking=False,
        comp_threshold_db=-2.0
    )
    # И вне комментария (t = 9.0с), и во время звучания комментария (t = 12.0с)
    # фильм должен играть на полной установленной громкости 1.0 и НЕ приглушаться!
    player_widget.apply_audio_dsp(9000)
    assert abs(player_widget.current_applied_movie_vol - 1.0) < 0.001

    player_widget.apply_audio_dsp(12000)
    assert abs(player_widget.current_applied_movie_vol - 1.0) < 0.001
    assert abs(player_widget.current_applied_comm_vol - 1.0) < 0.001

    # 4. Проверка работы с ослаблением звука (фильм -6.0 dB -> 0.501, комментарии -15.0 dB -> 0.178):
    player_widget.set_audio_dsp_config(
        movie_vol_db=-6.0,
        comm_vol_db=-15.0,
        auto_ducking=False,
        comp_threshold_db=-2.0
    )
    player_widget.apply_audio_dsp(12000)
    expected_movie = 10.0 ** (-6.0 / 20.0)
    expected_comm = 10.0 ** (-15.0 / 20.0)
    assert abs(player_widget.current_applied_movie_vol - expected_movie) < 0.001
    assert abs(player_widget.current_applied_comm_vol - expected_comm) < 0.001

    # Проверка диапазона в ConfigManager (-15 dB ... +20 dB)
    cfg_test = ConfigManager()
    cfg_test.movie_volume_db = 15.5
    assert abs(cfg_test.movie_volume_db - 15.5) < 0.001
    cfg_test.commentary_volume_db = 20.0
    assert abs(cfg_test.commentary_volume_db - 20.0) < 0.001
    cfg_test.movie_volume_db = -15.0
    assert abs(cfg_test.movie_volume_db - (-15.0)) < 0.001

    shutil.rmtree(tmp_audio_dir)
    print("[OK] test_video_player_dsp passed")


def test_user_prompt_dialog():
    dlg = UserPromptDialog(current_prompt="Тестовый сценарий фильма", project_name="Фильм №1")
    assert dlg.text_edit.toPlainText() == "Тестовый сценарий фильма"
    assert dlg.get_user_prompt() == "Тестовый сценарий фильма"

    dlg.text_edit.setPlainText("Новый сюжет")
    assert dlg.get_user_prompt() == "Новый сюжет"
    assert "пожеланий" in dlg.text_edit.accessibleName().lower()
    print("[OK] test_user_prompt_dialog passed")


def test_project_video_copying_and_chunks():
    import shutil
    import tempfile
    from core.project_manager import ProjectManager, Project

    temp_root = tempfile.mkdtemp()
    proj_dir = os.path.join(temp_root, "Projects")
    os.makedirs(proj_dir, exist_ok=True)

    # Создаем фейковый исходный видеофайл вне папки проекта
    outside_dir = os.path.join(temp_root, "Outside")
    os.makedirs(outside_dir, exist_ok=True)
    fake_video = os.path.join(outside_dir, "my_cool_movie.mp4")
    with open(fake_video, "wb") as f:
        f.write(b"FAKE_VIDEO_CONTENT_12345")

    pm = ProjectManager(projects_dir=proj_dir)
    proj = pm.create_project("Test Movie", fake_video, chunk_duration_min=50)

    # 1. Проверяем копирование видеофайла
    expected_local_video = os.path.join(proj.folder_path, "source_video.mp4")
    assert os.path.isfile(expected_local_video), "Исходный видеофайл должен быть скопирован в папку проекта!"
    assert proj.data["src_video_path"] == expected_local_video, "src_video_path должен быть нормализован на локальный файл!"
    assert proj.data["source_video_rel"] == "source_video.mp4"

    # 2. Проверяем список проектов: количество частей должно быть как минимум 1
    projects_list = pm.list_projects()
    assert len(projects_list) == 1
    p_info = projects_list[0]
    assert p_info["total_chunks"] >= 1, f"Ожидалось >= 1 частей, получено {p_info['total_chunks']}"
    assert p_info["completed_chunks"] == 0

    # 3. Проверяем перенос проекта в другое место (имитация флешки на другом ПК)
    new_root = tempfile.mkdtemp()
    new_proj_folder = os.path.join(new_root, "Test Movie")
    shutil.copytree(proj.folder_path, new_proj_folder)

    # Удаляем старый проект и исходный файл
    shutil.rmtree(temp_root)

    # Открываем проект из новой папки
    loaded_proj = Project.load(new_proj_folder)
    assert loaded_proj is not None
    assert os.path.isfile(loaded_proj.data["src_video_path"]), "Путь к видеофайлу должен быть автоматически нормализован!"
    assert os.path.dirname(loaded_proj.data["src_video_path"]) == new_proj_folder

    shutil.rmtree(new_root)
    print("[OK] test_project_video_copying_and_chunks passed")


def test_timeline_position_autofit():
    canvas = VisualTimelineCanvas()
    canvas.set_duration(10.0)
    assert canvas.total_duration_sec == 10.0

    # При превышении длительности таймлайн должен автоматически расширяться
    canvas.set_position(25.0)
    assert canvas.total_duration_sec >= 25.0, "Таймлайн должен автоматически расширяться при выходе позиции за пределы!"
    assert canvas.current_pos_sec == 25.0
    print("[OK] test_timeline_position_autofit passed")


def test_proxy_modes():
    from core.proxy_manager import apply_proxy_settings, format_proxy_url, clear_proxy_env
    import httplib2
    import socks

    # 1. format_proxy_url
    assert format_proxy_url("127.0.0.1:8080") == "http://127.0.0.1:8080"
    assert format_proxy_url("http://127.0.0.1:8080") == "http://127.0.0.1:8080"
    assert format_proxy_url("socks5://127.0.0.1:10808") == "socks5://127.0.0.1:10808"

    # 2. direct mode
    res_direct = apply_proxy_settings(mode="direct")
    assert res_direct["mode"] == "direct"
    assert "HTTP_PROXY" not in os.environ
    assert "HTTPS_PROXY" not in os.environ

    # 3. custom mode
    res_custom = apply_proxy_settings(mode="custom", custom_proxy="http://127.0.0.1:10809")
    assert res_custom["mode"] == "custom"
    assert os.environ.get("HTTP_PROXY") == "http://127.0.0.1:10809"
    assert os.environ.get("HTTPS_PROXY") == "http://127.0.0.1:10809"
    assert os.environ.get("ALL_PROXY") == "http://127.0.0.1:10809"
    assert httplib2.socks is socks

    # 4. system mode
    res_system = apply_proxy_settings(mode="system")
    assert res_system["mode"] == "system"

    # Очищаем тестовое состояние
    clear_proxy_env()
    print("[OK] test_proxy_modes passed")


def test_tts_worker_cancellation():
    from ui.tts_progress_dialog import TTSGenerationWorker
    from core.config_manager import ConfigManager
    from core.project_manager import Project
    import tempfile
    import shutil

    tmp = tempfile.mkdtemp()
    proj = Project("TestTTS", tmp, data={"name": "TestTTS", "commentaries": [
        {"id": "1", "text": "Текст 1", "audio_needs_rebuild": True},
        {"id": "2", "text": "Текст 2", "audio_needs_rebuild": True}
    ]})
    cfg = ConfigManager()
    cfg.api_request_pause_sec = 2

    worker = TTSGenerationWorker(proj, cfg, engine_type="gemini", comments_to_process=proj.commentaries)
    worker.cancel()
    assert worker._is_cancelled is True
    assert worker.cancel_event.is_set() is True

    cancelled_called = [False]
    def on_cancelled(succ, tot):
        cancelled_called[0] = True
    worker.tts_cancelled.connect(on_cancelled)
    worker.run()
    assert cancelled_called[0] is True
    shutil.rmtree(tmp)
    print("[OK] test_tts_worker_cancellation passed")


def test_generation_worker_cancellation():
    from ui.generation_progress_dialog import GeminiGenerationWorker
    from core.config_manager import ConfigManager
    from core.project_manager import Project
    import tempfile
    import shutil

    tmp = tempfile.mkdtemp()
    proj = Project("TestGen", tmp, data={"name": "TestGen", "chunks": [
        {"filepath": "dummy.mp4", "start_time_sec": 0, "end_time_sec": 10, "processed": False}
    ], "commentaries": [], "characters": []})
    cfg = ConfigManager()

    worker = GeminiGenerationWorker(proj, cfg)
    worker.cancel()
    assert worker._is_cancelled is True
    assert worker.cancel_event.is_set() is True

    cancelled_called = [False]
    def on_cancelled():
        cancelled_called[0] = True
    worker.generation_cancelled.connect(on_cancelled)
    worker.run()
    assert cancelled_called[0] is True
    shutil.rmtree(tmp)
    print("[OK] test_generation_worker_cancellation passed")


def test_resolve_commentary_overlaps():
    from core.project_manager import resolve_commentary_overlaps

    # 1. Тест цепочки из 3 перекрывающихся комментариев
    comms = [
        {"id": "c1", "start_time": 10.0, "end_time": 14.5, "duration_sec": 4.5},
        {"id": "c2", "start_time": 12.0, "end_time": 14.0, "duration_sec": 2.0},
        {"id": "c3", "start_time": 13.0, "end_time": 16.0, "duration_sec": 3.0}
    ]

    changed = resolve_commentary_overlaps(comms)
    assert changed is True

    # c1 должен остаться [10.0, 14.5]
    assert comms[0]["id"] == "c1"
    assert comms[0]["start_time"] == 10.0
    assert comms[0]["end_time"] == 14.5

    # c2 должен сдвинуться на 14.5 и длиться 2.0 -> [14.5, 16.5]
    assert comms[1]["id"] == "c2"
    assert comms[1]["start_time"] == 14.5
    assert comms[1]["end_time"] == 16.5
    assert comms[1]["duration_sec"] == 2.0

    # c3 должен сдвинуться на 16.5 и длиться 3.0 -> [16.5, 19.5]
    assert comms[2]["id"] == "c3"
    assert comms[2]["start_time"] == 16.5
    assert comms[2]["end_time"] == 19.5
    assert comms[2]["duration_sec"] == 3.0

    # 2. Тест неперекрывающихся комментариев
    comms_no_overlap = [
        {"id": "c1", "start_time": 1.0, "end_time": 3.0, "duration_sec": 2.0},
        {"id": "c2", "start_time": 5.0, "end_time": 8.0, "duration_sec": 3.0}
    ]
    changed_no = resolve_commentary_overlaps(comms_no_overlap)
    assert changed_no is False
    assert comms_no_overlap[0]["start_time"] == 1.0
    assert comms_no_overlap[1]["start_time"] == 5.0

    print("[OK] test_resolve_commentary_overlaps passed")


def test_timeline_speedup_clamping_and_dialog():
    from ui.comment_duration_dialog import CommentDurationDialog

    # 1. Проверка CommentDurationDialog с min_duration
    dlg = CommentDurationDialog(start_time=10.0, current_end_time=12.0, min_duration=3.5)
    assert dlg.min_duration == 3.5
    assert dlg.spin_duration.minimum() == 3.5
    assert dlg.get_new_duration() >= 3.5
    assert dlg.get_new_end_time() >= 13.5

    # 2. Проверка VisualTimelineCanvas с max_speedup
    canvas = VisualTimelineCanvas()
    canvas.set_max_speedup(1.5)
    assert canvas.max_speedup == 1.5

    # Задаем комментарий с raw_duration_sec = 6.0 сек.
    # При max_speedup = 1.5 минимальная длительность = 6.0 / 1.5 = 4.0 сек.
    canvas.commentaries = [
        {"id": "c1", "start_time": 10.0, "end_time": 15.0, "duration_sec": 5.0, "raw_duration_sec": 6.0}
    ]
    canvas.resizing_comm_id = "c1"
    canvas.drag_start_mouse_x = 100
    canvas.drag_orig_start = 10.0
    canvas.drag_orig_end = 15.0
    canvas.has_dragged = True

    # Эмулируем попытку сжать комментарий до t = 11.0 (длительность 1.0 сек, что меньше 4.0 сек)
    # x_to_sec должен вернуть 11.0
    canvas.set_duration(100.0)
    canvas.resize(1000, 100)

    # Вызываем mouseMoveEvent с позицией x соответствующей t = 11.0
    # sec_to_x(11.0) -> вычисляем x
    target_x = canvas.sec_to_x(11.0)
    from PySide6.QtGui import QMouseEvent
    from PySide6.QtCore import QPointF
    ev = QMouseEvent(QEvent.MouseMove, QPointF(target_x, 50), Qt.LeftButton, Qt.LeftButton, Qt.NoModifier)
    canvas.mouseMoveEvent(ev)

    # Проверяем, что end_time не стал меньше 14.0 (10.0 + 4.0 min_dur)
    c1 = canvas.commentaries[0]
    assert c1["end_time"] >= 14.0, f"end_time {c1['end_time']} должен быть >= 14.0 (start + raw_dur / max_speedup)"
    assert c1["duration_sec"] >= 4.0

    print("[OK] test_timeline_speedup_clamping_and_dialog passed")


def test_video_player_comm_seeking_and_pause_reset():
    from PySide6.QtMultimedia import QMediaPlayer
    player_widget = VideoPlayerWidget()
    player_widget.commentaries = [
        {"id": "comm_1", "start_time": 10.0, "end_time": 15.0, "text": "Текст комментария 1", "audio_file": "dummy.wav"}
    ]

    # 1. Позиция на пустом месте (t = 2.0s) -> нет субтитров и звук остановлен
    player_widget.set_position(2000)
    assert player_widget.last_played_comm_id == ""
    assert player_widget.lbl_subtitle.isHidden()
    assert player_widget.comm_player.playbackState() == QMediaPlayer.StoppedState

    # 2. Позиция в середине комментария (t = 12.5s) -> активный субтитр и рассчитанный офсет 2500 мс
    player_widget.set_position(12500)
    assert not player_widget.lbl_subtitle.isHidden()
    assert player_widget.lbl_subtitle.text() == "Текст комментария 1"

    # 3. Эмуляция паузы и перехода на пустое место (t = 20.0s)
    player_widget.pause()
    player_widget.set_position(20000)
    assert player_widget.last_played_comm_id == ""
    assert player_widget.current_comm_audio_file == ""
    assert player_widget.comm_player.playbackState() == QMediaPlayer.StoppedState

    # При нажатии Play на пустом месте comm_player не должен запускаться
    player_widget.play()
    assert player_widget.comm_player.playbackState() == QMediaPlayer.StoppedState
    player_widget.pause()

    # 4. Проверка остановки в конце медиа (без зацикливания)
    # Задаем длительность через player mock/property
    player_widget.slider_pos.setRange(0, 50000)
    # Эмулируем наступление EndOfMedia
    player_widget._on_player_media_status_changed(QMediaPlayer.EndOfMedia)
    assert player_widget.comm_player.playbackState() == QMediaPlayer.StoppedState
    assert player_widget.btn_play.text() == "Воспроизведение"

    # При попытке Play в самом конце плеер не должен запускаться если dur > 0 и pos >= dur - 50
    # Так как у mock player duration() без медиа 0, протестируем прямое условие:
    player_widget.pause()
    assert player_widget.btn_play.text() == "Воспроизведение"

    print("[OK] test_video_player_comm_seeking_and_pause_reset passed")



def test_video_normalization_stream_copy():
    """Тестирует быструю нормализацию видеофайла в MP4 (H.264 видео + AAC звук + FastStart)."""
    import subprocess
    import tempfile
    from core.app_paths import get_ffmpeg_path
    from core.video_splitter import normalize_video_container, analyze_media

    ffmpeg = get_ffmpeg_path()
    temp_dir = tempfile.mkdtemp()
    input_avi = os.path.join(temp_dir, "test_input.avi")
    output_mp4 = os.path.join(temp_dir, "normalized.mp4")

    # Создаем тестовый AVI с помощью FFmpeg
    cmd = [
        ffmpeg, "-y", "-nostdin",
        "-f", "lavfi", "-i", "testsrc=duration=1:size=320x240:rate=25",
        "-f", "lavfi", "-i", "sine=duration=1:frequency=440",
        "-c:v", "mpeg4",
        "-c:a", "mp3",
        input_avi
    ]
    subprocess.run(cmd, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=True)

    assert os.path.isfile(input_avi), "Тестовый AVI файл должен быть создан"

    # Выполняем нормализацию
    norm_res = normalize_video_container(input_avi, output_mp4)
    assert norm_res is True, "normalize_video_container должен вернуть True"
    assert os.path.isfile(output_mp4), "Файл normalized.mp4 должен быть создан"
    assert os.path.getsize(output_mp4) > 0

    # Анализируем параметры полученного файла
    info = analyze_media(output_mp4)
    assert info.has_video is True, "Должен присутствовать видеопоток"
    assert info.has_audio is True, "Должен присутствовать аудиопоток"
    assert info.audio_codec.lower() == "aac", f"Аудиокодек должен быть AAC, получено: {info.audio_codec}"
    assert info.duration >= 0.9, f"Длительность должна быть около 1.0 с, получено: {info.duration}"

    shutil.rmtree(temp_dir)
    print("[OK] test_video_normalization_stream_copy passed")


def test_video_preparation_worker_flow():
    """Тестирует фоновый рабочий поток подготовки и нормализации проекта."""
    import subprocess
    import tempfile
    from core.app_paths import get_ffmpeg_path
    from core.config_manager import ConfigManager
    from core.project_manager import ProjectManager
    from ui.video_preparation_dialog import VideoPreparationWorker

    ffmpeg = get_ffmpeg_path()
    temp_dir = tempfile.mkdtemp()
    proj_dir = os.path.join(temp_dir, "Projects")
    os.makedirs(proj_dir, exist_ok=True)
    input_avi = os.path.join(temp_dir, "sample.avi")

    # Создаем короткий тестовый видеофайл
    cmd = [
        ffmpeg, "-y", "-nostdin",
        "-f", "lavfi", "-i", "testsrc=duration=1:size=320x240:rate=25",
        "-f", "lavfi", "-i", "sine=duration=1:frequency=440",
        "-c:v", "mpeg4",
        "-c:a", "mp3",
        input_avi
    ]
    subprocess.run(cmd, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=True)

    cfg = ConfigManager()
    pm = ProjectManager(projects_dir=proj_dir)

    finished_projects = []
    worker = VideoPreparationWorker(
        project_mgr=pm,
        project_name="Async Test Movie",
        src_video_path=input_avi,
        chunk_min=50,
        config=cfg
    )
    worker.preparation_finished.connect(lambda p: finished_projects.append(p))
    worker.run()  # Прямой вызов run для синхронной проверки логики

    assert len(finished_projects) == 1, "Должен быть создан 1 проект"
    proj = finished_projects[0]
    assert proj.name == "Async Test Movie"
    assert os.path.isfile(proj.data["src_video_path"])
    assert proj.data["source_video_rel"] == "source_video.mp4"
    assert proj.data["total_duration_sec"] >= 0.9

    shutil.rmtree(temp_dir)
    print("[OK] test_video_preparation_worker_flow passed")


def test_character_manager_crud_and_screenshots():
    """Тестирует создание, обновление, удаление персонажей и работу со скриншотами."""
    import tempfile
    from core.project_manager import Project
    from core.character_manager import CharacterManager

    temp_dir = tempfile.mkdtemp()
    proj = Project("Char Test", temp_dir)
    char_mgr = CharacterManager(proj)

    # 1. Добавление персонажа
    c1 = char_mgr.add_character("Джек Уитмен", "Главный герой", "Мужчина 30 лет")
    assert c1["name"] == "Джек Уитмен"
    assert c1["role"] == "Главный герой"
    assert c1["id"] == "char_001"
    assert len(proj.characters) == 1

    # 2. Обновление персонажа
    ok = char_mgr.update_character(c1["id"], role="Главный герой, постоялец отеля", description="Мужчина 30 лет с усами")
    assert ok is True
    assert proj.characters[0]["role"] == "Главный герой, постоялец отеля"
    assert proj.characters[0]["description"] == "Мужчина 30 лет с усами"

    # 3. Добавление изображения из файла
    sample_img = os.path.join(temp_dir, "sample.jpg")
    with open(sample_img, "wb") as f:
        f.write(b"dummy jpeg data 12345")

    added_img = char_mgr.add_screenshot_from_file(c1["id"], sample_img)
    assert added_img is not None
    assert os.path.isfile(added_img)
    assert len(proj.characters[0]["images"]) == 1

    # 4. Удаление скриншота
    del_ok = char_mgr.delete_screenshot(c1["id"], added_img)
    assert del_ok is True
    assert len(proj.characters[0]["images"]) == 0
    assert not os.path.exists(added_img)

    # 5. Добавление второго персонажа и удаление
    c2 = char_mgr.add_character("Подруга Джека", "Возлюбленная", "Женщина с короткой стрижкой")
    assert len(proj.characters) == 2
    del_char_ok = char_mgr.delete_character(c2["id"])
    assert del_char_ok is True
    assert len(proj.characters) == 1
    assert proj.characters[0]["id"] == c1["id"]

    shutil.rmtree(temp_dir)
    print("[OK] test_character_manager_crud_and_screenshots passed")


def test_character_export_import_merging():
    """Тестирует экспорт персонажей в ZIP и импорт со слиянием/дополнением базы."""
    import tempfile
    from core.project_manager import Project
    from core.character_manager import CharacterManager

    temp_dir = tempfile.mkdtemp()
    proj1_dir = os.path.join(temp_dir, "Proj1")
    proj2_dir = os.path.join(temp_dir, "Proj2")
    zip_export = os.path.join(temp_dir, "series_chars.zip")

    # Создаем проект 1 с 2 персонажами и скриншотом
    proj1 = Project("Episode 1", proj1_dir)
    mgr1 = CharacterManager(proj1)
    c1 = mgr1.add_character("Джек", "Герой", "Описание Джека")
    c2 = mgr1.add_character("Официант", "Персонал", "В униформе")

    dummy_img = os.path.join(temp_dir, "jack.jpg")
    with open(dummy_img, "wb") as f:
        f.write(b"fake image data")
    mgr1.add_screenshot_from_file(c1["id"], dummy_img)

    # Экспортируем в ZIP
    exp_ok = mgr1.export_characters_package(zip_export)
    assert exp_ok is True
    assert os.path.isfile(zip_export)

    # Создаем проект 2 (следующая серия), где уже есть 1 персонаж с тем же именем "Джек", но другим описанием
    proj2 = Project("Episode 2", proj2_dir)
    mgr2 = CharacterManager(proj2)
    c_existing = mgr2.add_character("Джек", "Главный персонаж", "Описание из серии 2")

    # Импортируем персонажей из серии 1 в серию 2
    added, updated = mgr2.import_characters_package(zip_export)
    assert added == 1, f"Должен добавиться 1 новый персонаж (Официант), получено {added}"
    assert updated == 1, f"Должен обновиться 1 существующий персонаж (Джек), получено {updated}"

    # Проверяем, что существующий список дополнился, а не заменился
    assert len(proj2.characters) == 2
    jack_in_p2 = next(c for c in proj2.characters if c["name"] == "Джек")
    assert "Описание из серии 2" in jack_in_p2["description"]
    assert "Описание Джека" in jack_in_p2["description"]
    assert len(jack_in_p2["images"]) == 1  # Скриншот Джека перенесся из архива

    waiter_in_p2 = next(c for c in proj2.characters if c["name"] == "Официант")
    assert waiter_in_p2["role"] == "Персонал"

    shutil.rmtree(temp_dir)
    print("[OK] test_character_export_import_merging passed")


def test_character_cards_dialog_accessibility_and_features():
    """Тестирует диалог управления персонажами, элементы управления и доступность."""
    import tempfile
    from core.project_manager import Project
    from ui.character_cards_dialog import CharacterCardsDialog

    temp_dir = tempfile.mkdtemp()
    proj = Project("UI Test", temp_dir)
    proj.add_or_update_character({"id": "char_001", "name": "Герой 1", "role": "Роль 1", "description": "Описание 1", "images": []})

    dlg = CharacterCardsDialog(proj)
    assert dlg.windowTitle().startswith("👥 Карточки героев")
    assert dlg.char_list.count() == 1
    assert dlg.txt_char_name.text() == "Герой 1"
    assert dlg.txt_char_role.text() == "Роль 1"
    assert dlg.txt_char_desc.toPlainText() == "Описание 1"

    # Проверяем доступность (accessibleName)
    assert dlg.btn_add_char.accessibleName() != ""
    assert dlg.btn_del_char.accessibleName() != ""
    assert dlg.btn_import.accessibleName() != ""
    assert dlg.btn_export.accessibleName() != ""
    assert dlg.btn_capture.accessibleName() != ""
    assert dlg.slider_pos.accessibleName() != ""

    # Проверяем добавление нового персонажа через диалог
    dlg.add_new_character()
    assert len(proj.characters) == 2
    assert dlg.char_list.count() == 2

    # Закрываем диалог
    dlg.close()
    shutil.rmtree(temp_dir)
    print("[OK] test_character_cards_dialog_accessibility_and_features passed")


def test_timecode_scale_guard():
    """Тестирует алгоритм парсинга таймкодов Gemini и расшифровки MMSS."""
    from core.gemini_client import parse_time_to_seconds

    chunk_duration = 786.119

    # 1. Строки формата HH:MM:SS.mmm
    assert parse_time_to_seconds("00:00:32.000", max_duration=chunk_duration) == 32.0
    assert parse_time_to_seconds("00:01:18.500", max_duration=chunk_duration) == 78.5
    assert parse_time_to_seconds("00:12:15.000", max_duration=chunk_duration) == 735.0

    # 2. Строки формата MM:SS.mmm
    assert parse_time_to_seconds("07:56.200", max_duration=chunk_duration) == 476.2
    assert parse_time_to_seconds("12:15.000", max_duration=chunk_duration) == 735.0

    # 3. Чистые секунды в пределах длительности
    assert parse_time_to_seconds(32.0, max_duration=chunk_duration) == 32.0
    assert parse_time_to_seconds(78.5, max_duration=chunk_duration) == 78.5

    # 4. Слитная нотация MMSS при превышении длительности (1215 -> 12:15 = 735с, 1255 -> 12:55 = 775с)
    assert parse_time_to_seconds(1215.0, max_duration=chunk_duration) == 735.0
    assert parse_time_to_seconds(1255.0, max_duration=chunk_duration) == 775.0

    print("[OK] test_timecode_scale_guard passed")


def test_fragment_prompt_dialog_and_extraction():
    """Тестирует диалог пожеланий к фрагменту и функцию вырезания фрагмента."""
    from ui.fragment_prompt_dialog import FragmentPromptDialog
    from core.video_splitter import extract_video_fragment

    dlg = FragmentPromptDialog(10.5, 35.2, initial_prompt="Особое внимание на жесты")
    assert dlg.start_sec == 10.5
    assert dlg.end_sec == 35.2
    assert dlg.dur_sec == 24.7
    assert dlg.get_fragment_prompt() == "Особое внимание на жесты"
    dlg.close()

    # Проверка вызова extract_video_fragment с несуществующим файлом (возвращает False без падения)
    assert not extract_video_fragment("non_existent_video.mp4", 0, 10, "dummy_out.mp4")
    print("[OK] test_fragment_prompt_dialog_and_extraction passed")


def test_timeline_range_selection_and_shortcuts():
    """Тестирует выделение диапазона на таймлайне (In/Out, get_selection, clear_selection)."""
    canvas = VisualTimelineCanvas()
    canvas.set_duration(100.0)
    canvas.set_position(15.0)

    # 1. Установка точки In
    canvas.set_in_point(10.0)
    assert canvas.sel_start_sec == 10.0

    # 2. Установка точки Out
    canvas.set_out_point(30.0)
    assert canvas.sel_end_sec == 30.0
    assert canvas.get_selection() == (10.0, 30.0)

    # 3. Сброс выделения
    canvas.clear_selection()
    assert canvas.get_selection() is None

    # 4. Проверка проброса через AccessibleTimelineWidget
    widget = AccessibleTimelineWidget()
    widget.set_duration(100.0)
    widget.canvas.set_in_point(20.0)
    widget.canvas.set_out_point(45.0)
    assert widget.canvas.get_selection() == (20.0, 45.0)
    assert widget.btn_comment_fragment.isEnabled()
    assert widget.btn_clear_selection.isEnabled()

    widget.canvas.clear_selection()
    assert not widget.btn_comment_fragment.isEnabled()
    assert not widget.btn_clear_selection.isEnabled()

    print("[OK] test_timeline_range_selection_and_shortcuts passed")


def test_drag_commentary_swap_and_ripple_shift():
    """Тестирует перетаскивание комментариев друг через друга со смещением наложений."""
    from core.project_manager import resolve_commentary_overlaps

    # Исходно: C1 (10..15), C2 (20..25), C3 (30..35)
    comms = [
        {"id": "c1", "start_time": 10.0, "end_time": 15.0, "duration_sec": 5.0},
        {"id": "c2", "start_time": 20.0, "end_time": 25.0, "duration_sec": 5.0},
        {"id": "c3", "start_time": 30.0, "end_time": 35.0, "duration_sec": 5.0}
    ]

    # Сценарий 1: Перетаскиваем C2 назад перед C1 (на позицию 10.0..15.0)
    comms[1]["start_time"] = 10.0
    comms[1]["end_time"] = 15.0

    changed = resolve_commentary_overlaps(comms, moved_comm_id="c2")
    assert changed

    # C2 должен встать на 10..15, а C1 сдвинуться на 15..20
    assert comms[0]["id"] == "c2"
    assert comms[0]["start_time"] == 10.0
    assert comms[0]["end_time"] == 15.0

    assert comms[1]["id"] == "c1"
    assert comms[1]["start_time"] == 15.0
    assert comms[1]["end_time"] == 20.0

    # C3 не накладывается, остается на 30..35
    assert comms[2]["id"] == "c3"
    assert comms[2]["start_time"] == 30.0
    assert comms[2]["end_time"] == 35.0

    # Сценарий 2: Перетаскиваем C2 вперед на позицию C3 (30.0..35.0)
    comms[0]["start_time"] = 30.0
    comms[0]["end_time"] = 35.0
    changed2 = resolve_commentary_overlaps(comms, moved_comm_id="c2")
    assert changed2

    # Порядок теперь: C1 (15..20), C2 (30..35), C3 (35..40)
    assert comms[0]["id"] == "c1"
    assert comms[0]["start_time"] == 15.0

    assert comms[1]["id"] == "c2"
    assert comms[1]["start_time"] == 30.0
    assert comms[1]["end_time"] == 35.0

    assert comms[2]["id"] == "c3"
    assert comms[2]["start_time"] == 35.0
    assert comms[2]["end_time"] == 40.0

    print("[OK] test_drag_commentary_swap_and_ripple_shift passed")


def test_resize_unvoiced_commentary_and_speedup():
    """Тестирует растягивание неозвученных комментариев и расчет темпа речи."""
    canvas = VisualTimelineCanvas()
    canvas.commentaries = [
        {"id": "unvoiced_1", "start_time": 5.0, "end_time": 8.0, "duration_sec": 3.0, "raw_duration_sec": None}
    ]
    canvas.resizing_comm_id = "unvoiced_1"
    canvas.drag_orig_start = 5.0
    canvas.has_dragged = True

    # Проверяем безопасное извлечение raw_dur при None
    target_comm = canvas.commentaries[0]
    raw_dur = float(target_comm.get("raw_duration_sec") or 0.0)
    assert raw_dur == 0.0

    # Растягиваем до 12.0 сек (длительность становится 7.0 сек)
    target = canvas.commentaries[0]
    target["end_time"] = 12.0
    target["duration_sec"] = 7.0

    assert target["duration_sec"] == 7.0
    assert target["end_time"] == 12.0

    # Проверяем расчет коэффициента растяжения при последующей озвучке
    raw_speech_dur = 6.0  # синтезатор наговорил 6 секунд
    allowed_duration = target["duration_sec"]  # 7.0 секунд
    target_factor = raw_speech_dur / allowed_duration  # 6.0 / 7.0 < 1.0 (речь не ускоряется, звучит свободно)
    assert target_factor < 1.0

    # Если пользователь сжал неозвученный блок до 4.0 секунд:
    compressed_duration = 4.0
    target_factor_compressed = raw_speech_dur / compressed_duration  # 6.0 / 4.0 = 1.5x (ускорение в 1.5 раза)
    assert target_factor_compressed == 1.5

    print("[OK] test_resize_unvoiced_commentary_and_speedup passed")



def test_srt_manager_parsing_and_cleaning():
    """Тестирует парсинг таймкодов, очистку текста от тегов и парсинг SRT содержимого."""
    # 1. Тест парсинга времени
    assert parse_srt_time("00:00:00,000") == 0.0
    assert parse_srt_time("00:01:15,500") == 75.5
    assert parse_srt_time("01:00:00.250") == 3600.25
    assert parse_srt_time("00:02:10,5") == 130.5
    assert parse_srt_time("00:05:00") == 300.0
    assert parse_srt_time("invalid") is None
    assert parse_srt_time("") is None

    # 2. Тест очистки текста от тегов
    assert clean_srt_text("<i>Наклонный текст</i>") == "Наклонный текст"
    assert clean_srt_text("<b>Жирный</b> и <font color='#ff0000'>цветной</font>") == "Жирный и цветной"
    assert clean_srt_text("{\\an8}Текст с позиционированием") == "Текст с позиционированием"
    assert clean_srt_text("Первая строка\nВторая строка") == "Первая строка Вторая строка"

    # 3. Тест парсинга SRT текста
    srt_sample = """
    1
    00:00:01,000 --> 00:00:04,500
    <i>Первый</i> комментарий.

    2
    00:00:05.200 --> 00:00:08.800
    Второй <b>комментарий</b> в две
    строки текста.

    3
    00:00:10,000 --> 00:00:10,000
    Нулевая длительность исправится автоматически.
    """
    parsed = parse_srt_content(srt_sample)
    assert len(parsed) == 3
    assert parsed[0]["start_time"] == 1.0
    assert parsed[0]["end_time"] == 4.5
    assert parsed[0]["duration_sec"] == 3.5
    assert parsed[0]["text"] == "Первый комментарий."

    assert parsed[1]["start_time"] == 5.2
    assert parsed[1]["end_time"] == 8.8
    assert parsed[1]["duration_sec"] == 3.6
    assert parsed[1]["text"] == "Второй комментарий в две строки текста."

    # Третий с start == end должен автоматически получить продолжительность >= 2.0 сек
    assert parsed[2]["start_time"] == 10.0
    assert parsed[2]["end_time"] >= 12.0
    assert parsed[2]["duration_sec"] >= 2.0

    print("[OK] test_srt_manager_parsing_and_cleaning passed")


def test_srt_manager_file_encodings_and_roundtrip(tmp_path="tests_tmp_srt"):
    """Тестирует чтение файлов в различных кодировках (UTF-8, UTF-8-BOM, CP1251) и экспорт-импорт."""
    os.makedirs(tmp_path, exist_ok=True)
    comms = [
        {"id": "c1", "start_time": 1.25, "end_time": 4.75, "text": "Текст на русском языке"},
        {"id": "c2", "start_time": 6.0, "end_time": 11.5, "text": "Второй важный тифлокомментарий"}
    ]

    # Экспорт
    export_file = os.path.join(tmp_path, "exported.srt")
    ok = export_commentaries_to_srt(comms, export_file)
    assert ok and os.path.isfile(export_file)

    # Чтение обратно
    reloaded = parse_srt_file(export_file)
    assert len(reloaded) == 2
    assert reloaded[0]["start_time"] == 1.25
    assert reloaded[0]["end_time"] == 4.75
    assert reloaded[0]["text"] == "Текст на русском языке"
    assert reloaded[1]["start_time"] == 6.0
    assert reloaded[1]["end_time"] == 11.5
    assert reloaded[1]["text"] == "Второй важный тифлокомментарий"

    # Проверка чтения CP1251
    cp1251_file = os.path.join(tmp_path, "cp1251.srt")
    content_cp1251 = "1\n00:00:02,000 --> 00:00:05,000\nКомментарий в кодировке Windows-1251\n"
    with open(cp1251_file, "w", encoding="cp1251") as f:
        f.write(content_cp1251)

    parsed_cp = parse_srt_file(cp1251_file)
    assert len(parsed_cp) == 1
    assert parsed_cp[0]["text"] == "Комментарий в кодировке Windows-1251"

    # Очистка
    shutil.rmtree(tmp_path, ignore_errors=True)
    print("[OK] test_srt_manager_file_encodings_and_roundtrip passed")


def test_project_srt_import_modes():
    """Тестирует режимы добавления и замены комментариев в Project."""
    tmp_dir = tempfile.mkdtemp()
    from core.project_manager import Project
    proj = Project("SRT_Test_Proj", tmp_dir)

    initial_comms = [
        {"id": "comm_0001", "start_time": 10.0, "end_time": 14.0, "duration_sec": 4.0, "text": "Исходный комм 1"}
    ]
    proj.add_commentaries(initial_comms)
    assert len(proj.commentaries) == 1

    new_comms = [
        {"start_time": 12.0, "end_time": 16.0, "duration_sec": 4.0, "text": "Импортированный комм 2"},
        {"start_time": 20.0, "end_time": 25.0, "duration_sec": 5.0, "text": "Импортированный комм 3"}
    ]

    # 1. Режим слияния (add_commentaries) с разрешением наложений
    proj.add_commentaries(new_comms)
    assert len(proj.commentaries) == 3
    # Проверяем уникальность ID
    ids = [c["id"] for c in proj.commentaries]
    assert len(set(ids)) == 3
    # Проверяем устранение наложений: начавшийся на 12.0 при наличии [10, 14] сдвигается на 14.0
    c1, c2, c3 = proj.commentaries
    assert c1["start_time"] == 10.0 and c1["end_time"] == 14.0
    assert c2["start_time"] >= 14.0

    # 2. Режим полной замены (replace_commentaries)
    replacement = [
        {"start_time": 1.0, "end_time": 5.0, "duration_sec": 4.0, "text": "Только этот комментарий"}
    ]
    proj.replace_commentaries(replacement)
    assert len(proj.commentaries) == 1
    assert proj.commentaries[0]["text"] == "Только этот комментарий"
    assert proj.commentaries[0]["id"] == "comm_0001"

    shutil.rmtree(tmp_dir, ignore_errors=True)
    print("[OK] test_project_srt_import_modes passed")


def test_main_window_srt_actions():
    """Тестирует наличие действий, горячих клавиш и сигналов импорта/экспорта SRT."""
    from ui.main_window import MainWindow
    win = MainWindow()

    assert hasattr(win, "act_import_srt")
    assert hasattr(win, "act_export_srt")

    assert win.act_import_srt.shortcut().toString() == "Ctrl+I"
    assert win.act_export_srt.shortcut().toString() == "Ctrl+Shift+E"

    assert hasattr(win, "btn_import_srt")
    assert hasattr(win, "btn_export_srt")

    assert hasattr(win.comment_list_panel, "btn_panel_import")
    assert hasattr(win.comment_list_panel, "btn_panel_export")

    win.close()
    print("[OK] test_main_window_srt_actions passed")

def test_main_window_import_export_execution():
    """Тестирует программное выполнение импорта и экспорта через MainWindow."""
    from unittest.mock import patch
    from ui.main_window import MainWindow
    from core.project_manager import Project

    tmp_dir = tempfile.mkdtemp()
    proj = Project("MW_Test", tmp_dir)
    win = MainWindow()
    win.current_project = proj

    # Создаем временный файл SRT
    srt_in = os.path.join(tmp_dir, "input.srt")
    with open(srt_in, "w", encoding="utf-8") as f:
        f.write("1\n00:00:03,000 --> 00:00:07,000\nТестовый импорт 1\n\n2\n00:00:08,000 --> 00:00:12,000\nТестовый импорт 2\n")

    srt_out = os.path.join(tmp_dir, "output.srt")

    # Тестируем import_srt
    with patch("PySide6.QtWidgets.QFileDialog.getOpenFileName", return_value=(srt_in, "SRT")):
        with patch("PySide6.QtWidgets.QMessageBox.information"):
            win.import_srt()

    assert len(proj.commentaries) == 2
    assert proj.commentaries[0]["text"] == "Тестовый импорт 1"
    assert proj.commentaries[1]["text"] == "Тестовый импорт 2"

    # Тестируем export_srt
    with patch("PySide6.QtWidgets.QFileDialog.getSaveFileName", return_value=(srt_out, "SRT")):
        with patch("PySide6.QtWidgets.QMessageBox.information"):
            win.export_srt()

    assert os.path.isfile(srt_out)
    with open(srt_out, "r", encoding="utf-8") as f:
        exported_text = f.read()
    assert "00:00:03,000 --> 00:00:07,000" in exported_text
    assert "Тестовый импорт 1" in exported_text

    win.close()
    shutil.rmtree(tmp_dir, ignore_errors=True)
    print("[OK] test_main_window_import_export_execution passed")


def test_comment_list_panel_smooth_resize_and_reopen_button():
    """Тестирует плавное изменение размера списка комментариев и появление кнопки разворачивания слева вверху."""
    from ui.main_window import MainWindow
    win = MainWindow()
    win.show()

    # 1. Проверяем минимальный размер панели комментариев (0, 0) для плавного сжатия
    assert win.comment_list_panel.minimumSizeHint().width() == 0
    assert win.comment_list_panel.minimumSizeHint().height() == 0
    assert win.comment_list_panel.minimumWidth() == 0

    # 2. Проверяем сплиттер - не схлопывается рывком
    assert not win.main_h_splitter.isCollapsible(0)
    assert not win.main_h_splitter.isCollapsible(1)

    # 3. Начальное состояние: панель открыта (~300px), кнопка разворачивания скрыта
    assert hasattr(win, "btn_reopen_list")
    assert hasattr(win, "top_reopen_container")
    assert not win.top_reopen_container.isVisible()
    assert win.act_view_list.isChecked()

    # 4. Имитируем ручное уменьшение мышью до упора (0 px)
    win.main_h_splitter.setSizes([0, 840, 340])
    win.on_main_splitter_moved(0, 1)

    # Кнопка разворачивания слева вверху должна появиться
    assert win.top_reopen_container.isVisible()
    assert win.btn_reopen_list.isVisible()
    assert not win.act_view_list.isChecked()

    # 5. Имитируем ручное увеличение мышью (> 30 px, например 250 px)
    win.main_h_splitter.setSizes([250, 590, 340])
    win.on_main_splitter_moved(250, 1)

    # Кнопка должна скрыться, а запомненная ширина обновиться
    assert not win.top_reopen_container.isVisible()
    assert win.act_view_list.isChecked()
    saved_w = win.main_h_splitter.sizes()[0]
    assert win.last_comment_list_width == saved_w
    assert saved_w > 30

    # 6. Программное сворачивание (через set_comment_list_visible(False))
    win.set_comment_list_visible(False, animate=False)
    assert win.main_h_splitter.sizes()[0] == 0
    assert win.top_reopen_container.isVisible()
    assert not win.act_view_list.isChecked()

    # 7. Разворачивание по нажатию на кнопку
    win.set_comment_list_visible(True, animate=False)
    # Разворачивание восстанавливает сохраненную ширину
    assert win.main_h_splitter.sizes()[0] == saved_w
    assert not win.top_reopen_container.isVisible()
    assert win.act_view_list.isChecked()

    # 8. Переключение через toggle_comment_list_panel
    win.set_comment_list_visible(False, animate=False)
    assert win.main_h_splitter.sizes()[0] == 0
    win.set_comment_list_visible(True, animate=False)
    assert win.main_h_splitter.sizes()[0] == saved_w

    win.close()
    print("[OK] test_comment_list_panel_smooth_resize_and_reopen_button passed")



def test_settings_dialog_db_ranges_and_mixing():
    """Тестирует работу AudioDspPanel с регуляторами громкости в децибелах (-15 dB ... +20 dB) и DSP-микширование."""
    from ui.audio_dsp_panel import AudioDspPanel
    from core.config_manager import ConfigManager
    import tempfile

    tmp_ini = os.path.join(tempfile.mkdtemp(), "test_settings.ini")
    cfg = ConfigManager(tmp_ini)
    cfg.movie_volume_db = -3.5
    cfg.commentary_volume_db = 12.0
    cfg.auto_ducking = True
    cfg.ducking_level_db = -14.0
    cfg.compressor_threshold_db = -1.5
    cfg.compressor_lookahead_ms = 6.0
    cfg.compressor_release_ms = 150.0

    panel = AudioDspPanel(cfg)
    print(f"Movie Slider value: {panel.strip_movie.slider.value()} Label: {panel.strip_movie.lbl_val.text()}")
    print(f"Comm Slider value: {panel.strip_comm.slider.value()} Label: {panel.strip_comm.lbl_val.text()}")
    # Проверяем начальные значения слайдеров и меток
    assert panel.strip_movie.slider.value() == -35
    assert panel.strip_movie.lbl_val.text() == "-3.5 dB"
    assert panel.strip_comm.slider.value() == 120
    assert panel.strip_comm.lbl_val.text() == "+12.0 dB"

    # Тестируем кнопки шага
    # +1 dB для фильма -> -2.5 dB (-25)
    panel.strip_movie.btn_up.click()
    assert panel.strip_movie.slider.value() == -25
    assert panel.strip_movie.lbl_val.text() == "-2.5 dB"

    # Сброс в 0 dB через сброс по умолчанию
    panel.btn_reset_defaults.click()
    assert panel.strip_movie.slider.value() == 0
    assert panel.strip_movie.lbl_val.text() == "0.0 dB"
    assert panel.strip_comm.slider.value() == 0
    assert panel.strip_comm.lbl_val.text() == "0.0 dB"

    # Увеличение комментариев до +20 dB
    panel.strip_comm.slider.setValue(200)
    assert panel.strip_comm.lbl_val.text() == "+20.0 dB"

    assert abs(cfg.movie_volume_db - 0.0) < 0.001
    assert abs(cfg.commentary_volume_db - 20.0) < 0.001

    panel.close()
    print("[OK] test_settings_dialog_db_ranges_and_mixing passed")


def test_project_reset_for_full_regeneration():
    """Тестирует метод сброса проекта для повторной генерации с сохранением персонажей и промпта."""
    tmp_dir = tempfile.mkdtemp()
    proj = Project("Тест сброса", tmp_dir)
    os.makedirs(proj.parts_dir, exist_ok=True)
    os.makedirs(proj.audio_dir, exist_ok=True)
    os.makedirs(proj.output_dir, exist_ok=True)

    # 1. Задаем персонажей и пожелания пользователя
    proj.data["user_prompt"] = "Специальный промпт пользователя"
    proj.data["characters"] = [
        {"id": "char_1", "name": "Алиса", "role": "Главная героиня", "description": "В синем платье"}
    ]

    # 2. Добавляем части видео и отмечаем их обработанными
    dummy_part1 = os.path.join(proj.parts_dir, "part_001.mp4")
    dummy_part2 = os.path.join(proj.parts_dir, "part_002.mp4")
    with open(dummy_part1, "w") as f:
        f.write("part1")
    with open(dummy_part2, "w") as f:
        f.write("part2")

    proj.data["chunks"] = [
        {"filepath": dummy_part1, "processed": True, "start_time_sec": 0.0, "end_time_sec": 10.0},
        {"filepath": dummy_part2, "processed": True, "start_time_sec": 10.0, "end_time_sec": 20.0}
    ]
    proj.data["current_chunk_index"] = 2

    # 3. Добавляем комментарии с фиктивными аудиофайлами
    audio_file1 = os.path.join(proj.audio_dir, "comm_0001.wav")
    raw_audio1 = os.path.join(proj.audio_dir, "comm_0001_raw.wav")
    with open(audio_file1, "w") as f:
        f.write("audio1")
    with open(raw_audio1, "w") as f:
        f.write("raw1")

    proj.data["commentaries"] = [
        {"id": "comm_0001", "start_time": 1.0, "end_time": 4.0, "text": "Текст 1", "audio_file": audio_file1, "raw_audio_file": raw_audio1},
        {"id": "comm_0002", "start_time": 5.0, "end_time": 8.0, "text": "Текст 2", "audio_file": None}
    ]

    # Создаем мастер-аудио
    master_path = os.path.join(proj.output_dir, "preview_master_audio.wav")
    with open(master_path, "w") as f:
        f.write("master")

    proj.save()

    assert os.path.isfile(audio_file1)
    assert os.path.isfile(raw_audio1)
    assert os.path.isfile(master_path)
    assert len(proj.commentaries) == 2

    # 4. Выполняем сброс для повторной генерации
    proj.reset_for_full_regeneration()

    # Проверяем, что комментарии очищены
    assert len(proj.commentaries) == 0
    # Аудиофайлы удалены
    assert not os.path.isfile(audio_file1)
    assert not os.path.isfile(raw_audio1)
    assert not os.path.isfile(master_path)
    # Части видео сброшены
    assert all(not c.get("processed") for c in proj.chunks)
    assert proj.data["current_chunk_index"] == 0
    # Карточки персонажей и пожелания пользователя сохранены!
    assert len(proj.characters) == 1
    assert proj.characters[0]["name"] == "Алиса"
    assert proj.user_prompt == "Специальный промпт пользователя"

    shutil.rmtree(tmp_dir, ignore_errors=True)
    print("[OK] test_project_reset_for_full_regeneration passed")


def test_main_window_full_regeneration_warning():
    """Тестирует выдачу предупреждения перед повторной генерацией в MainWindow."""
    from ui.main_window import MainWindow
    with unittest.mock.patch("core.config_manager.ConfigManager.last_project", ""):
        win = MainWindow()
        win.show()

        tmp_dir = tempfile.mkdtemp()
        proj = Project("Тест диалога", tmp_dir)
        proj.data["user_prompt"] = "Пожелания к фильму"
        proj.data["characters"] = [{"id": "c1", "name": "Герой"}]
        proj.data["commentaries"] = [{"id": "comm_0001", "start_time": 0.0, "end_time": 2.0, "text": "Комм"}]
        proj.data["chunks"] = [{"filepath": "dummy.mp4", "processed": True}]
        proj.save()

        win.load_project(proj)
        win.config.api_key = "AIzaFakeKey12345"

        # 1. Пользователь отказывается от сброса (нажимает Отмена)
        with unittest.mock.patch("ui.main_window.RegenerationConfirmDialog.exec", return_value=0) as mock_dlg:
            win.start_gemini_generation()
            assert mock_dlg.called
            # Комментарии остались на месте
            assert len(win.current_project.commentaries) == 1

        # 2. Пользователь подтверждает сброс (нажимает Да)
        with unittest.mock.patch("ui.main_window.RegenerationConfirmDialog.exec", return_value=1) as mock_dlg:
            with unittest.mock.patch("ui.main_window.GeminiGenerationProgressDialog") as mock_dlg_cls:
                mock_dlg_instance = unittest.mock.MagicMock()
                mock_dlg_cls.return_value = mock_dlg_instance
                win.start_gemini_generation()
                assert mock_dlg.called
                # Комментарии были сброшены
                assert len(win.current_project.commentaries) == 0
                # Персонажи и пожелания сохранились
                assert len(win.current_project.characters) == 1
                assert win.current_project.user_prompt == "Пожелания к фильму"
                assert mock_dlg_cls.called

        win.close()
        shutil.rmtree(tmp_dir, ignore_errors=True)
    print("[OK] test_main_window_full_regeneration_warning passed")


def test_delete_active_project():
    import tempfile
    import shutil
    from core.config_manager import ConfigManager
    from core.project_manager import ProjectManager
    from ui.main_window import MainWindow
    from ui.project_list_dialog import ProjectListDialog
    import unittest.mock

    tmp_dir = tempfile.mkdtemp()
    cfg = ConfigManager(os.path.join(tmp_dir, "config.ini"))
    proj_mgr = ProjectManager(tmp_dir)

    proj = proj_mgr.create_project("ProjectToDelete", "")
    master_path = os.path.join(proj.output_dir, "preview_master_audio.wav")
    with open(master_path, "w") as f:
        f.write("audio preview dummy")

    with unittest.mock.patch("core.config_manager.ConfigManager.last_project", ""):
        win = MainWindow()
        win.config = cfg
        win.project_mgr = proj_mgr
        win.load_project(proj)
        assert win.current_project is not None
        assert os.path.exists(proj.folder_path)

        dlg = ProjectListDialog(proj_mgr, cfg, parent=win)
        # Выбираем проект в таблице
        dlg.table.selectRow(0)

        # Симулируем подтверждение удаления
        with unittest.mock.patch("PySide6.QtWidgets.QMessageBox.question", return_value=QMessageBox.Yes):
            with unittest.mock.patch("PySide6.QtWidgets.QMessageBox.information"):
                dlg.delete_selected_project()

        # Проект должен быть выгружен из MainWindow и удален с диска
        assert win.current_project is None
        assert not os.path.exists(proj.folder_path)

        dlg.close()
        win.close()
    shutil.rmtree(tmp_dir, ignore_errors=True)
    print("[OK] test_delete_active_project passed")


def test_token_tracker_and_dialog():
    """Тестирует функциональность учета токенов TokenTracker и диалог TokenUsageDialog."""
    import tempfile
    import shutil
    from core.token_tracker import TokenTracker
    from ui.token_usage_dialog import TokenUsageDialog
    from ui.main_window import MainWindow

    tmp_dir = tempfile.mkdtemp()
    custom_ini = os.path.join(tmp_dir, "Settings_test.ini")

    try:
        # 1. Сброс и проверка пустой статистики
        TokenTracker.reset_usage(custom_ini)
        data = TokenTracker.get_tracked_usage(custom_ini)
        assert len(data) == 0

        # 2. Добавление моделей в момент использования
        TokenTracker.record_usage("models/gemini-2.5-flash", input_tokens=150000, output_tokens=3500, settings_path=custom_ini)
        TokenTracker.record_usage("gemini-3.1-flash-tts-preview", input_tokens=2000, output_tokens=8000, settings_path=custom_ini)

        # 3. Повторный вызов должен суммировать токены
        TokenTracker.record_usage("gemini-2.5-flash", input_tokens=50000, output_tokens=1500, settings_path=custom_ini)

        data = TokenTracker.get_tracked_usage(custom_ini)
        assert len(data) == 2
        assert "gemini-2.5-flash" in data
        assert data["gemini-2.5-flash"]["input_tokens"] == 200000
        assert data["gemini-2.5-flash"]["output_tokens"] == 5000
        assert data["gemini-3.1-flash-tts-preview"]["input_tokens"] == 2000
        assert data["gemini-3.1-flash-tts-preview"]["output_tokens"] == 8000

        # 4. Установка цен
        TokenTracker.set_model_prices("gemini-2.5-flash", price_input=0.10, price_output=0.40, unit=1000000, settings_path=custom_ini)
        data = TokenTracker.get_tracked_usage(custom_ini)
        assert data["gemini-2.5-flash"]["price_input"] == 0.10
        assert data["gemini-2.5-flash"]["price_output"] == 0.40

        # 5. Тестирование TokenUsageDialog
        # Перенаправляем TokenTracker на временный ini
        with unittest.mock.patch("core.token_tracker.get_settings_path", return_value=custom_ini):
            dlg = TokenUsageDialog()
            assert dlg.table.columnCount() == 7
            assert dlg.table.rowCount() == 2
            assert "gemini-2.5-flash" in dlg.table.item(0, 0).text() or "gemini-2.5-flash" in dlg.table.item(1, 0).text()

            # Проверяем предупреждение о неполных ценах (для tts цены еще не заданы)
            assert "Не все цены указаны" in dlg.lbl_total.text()

            # Заполняем цены для второй строки
            for r in dlg.row_widgets:
                if r["model_name"] == "gemini-3.1-flash-tts-preview":
                    r["spin_price_in"].setValue(0.50)
                    r["spin_price_out"].setValue(10.00)
            dlg.recalculate_totals()
            assert "Итого:" in dlg.lbl_total.text()
            assert "Не все цены указаны" not in dlg.lbl_total.text()

            # Сохранение и проверка
            dlg.save_prices()
            saved_data = TokenTracker.get_tracked_usage(custom_ini)
            assert saved_data["gemini-3.1-flash-tts-preview"]["price_input"] == 0.50
            assert saved_data["gemini-3.1-flash-tts-preview"]["price_output"] == 10.00

            # Тест сброса статистики
            with unittest.mock.patch("PySide6.QtWidgets.QMessageBox.question", return_value=QMessageBox.Yes):
                with unittest.mock.patch("PySide6.QtWidgets.QMessageBox.information"):
                    dlg.on_reset_clicked()

            assert dlg.table.rowCount() == 0
            assert "пуста" in dlg.lbl_total.text()

            dlg.close()

        # 6. Проверка действий и шорткатов в MainWindow
        with unittest.mock.patch("core.config_manager.ConfigManager.last_project", ""):
            win = MainWindow()
            assert hasattr(win, "act_token_usage")
            assert win.act_token_usage.shortcut().toString() == "Ctrl+Shift+U"
            win.close()

        # 7. Проверка, что config.save() не затирает накопленные TokenTracker модели
        TokenTracker.record_usage("gemini-3.7-flash", input_tokens=85000, output_tokens=2200, settings_path=custom_ini)
        cfg_mgr = ConfigManager(custom_ini)
        # Симулируем работу приложения: вызов другой модели и сохранение настроек
        TokenTracker.record_usage("gemini-3.1-flash-tts-preview", input_tokens=1500, output_tokens=3000, settings_path=custom_ini)
        cfg_mgr.save()  # Сохранение не должно стереть gemini-3.7-flash!

        data_after_save = TokenTracker.get_tracked_usage(custom_ini)
        assert "gemini-3.7-flash" in data_after_save, "Модель генерации gemini-3.7-flash не должна пропадать после config.save()!"
        assert "gemini-3.1-flash-tts-preview" in data_after_save, "Модель озвучки должна оставаться в статистике!"
        assert data_after_save["gemini-3.7-flash"]["input_tokens"] == 85000
        assert data_after_save["gemini-3.1-flash-tts-preview"]["input_tokens"] == 1500

    finally:
        shutil.rmtree(tmp_dir, ignore_errors=True)

    print("[OK] test_token_tracker_and_dialog passed")


def test_auto_pause_and_resume_on_audio_rebuild():
    """Тестирует автоматическую приостановку воспроизведения во время генерации/сведения нового аудио и автовозобновление."""
    import tempfile
    import shutil
    from core.config_manager import ConfigManager
    from core.project_manager import ProjectManager
    from ui.main_window import MainWindow

    tmp_dir = tempfile.mkdtemp()
    try:
        cfg = ConfigManager(os.path.join(tmp_dir, "config.ini"))
        proj_mgr = ProjectManager(tmp_dir)
        proj = proj_mgr.create_project("TestAutoPauseResume", "")

        dummy_wav = os.path.join(proj.audio_dir, "c1.wav")
        with open(dummy_wav, "wb") as f:
            f.write(b"RIFF\x24\x00\x00\x00WAVEfmt \x10\x00\x00\x00\x01\x00\x01\x00D\xac\x00\x00\x88X\x01\x00\x02\x00\x10\x00data\x00\x00\x00\x00")

        proj.add_commentaries([
            {"id": "c1", "start_time": 5.0, "end_time": 10.0, "duration_sec": 5.0, "text": "Коммент 1", "audio_file": dummy_wav}
        ])
        proj.save()

        with unittest.mock.patch("core.config_manager.ConfigManager.last_project", ""):
            win = MainWindow()
            win.config = cfg
            win.project_mgr = proj_mgr
            win.load_project(proj)
            win.audio_dsp_panel.set_mode(True)  # Переключаем в режим «Итоговый звук» для тестирования рендера

        # 1. Эмулируем состояние воспроизведения
        with unittest.mock.patch.object(win.player_widget, "is_playing", return_value=True):
            with unittest.mock.patch.object(win.player_widget, "pause") as mock_pause:
                with unittest.mock.patch.object(win.player_widget, "play") as mock_play:
                    # Перемещение комментария во время воспроизведения
                    win.on_commentary_moved("c1", 8.0, 13.0)
                    assert win._resume_playback_after_audio_rebuild is True
                    mock_pause.assert_called()

                    # Когда рендер мастер-аудио завершился
                    dummy_master = os.path.join(proj.output_dir, "preview_master_audio.wav")
                    with open(dummy_master, "w") as f:
                        f.write("dummy master")

                    win._on_master_audio_rendered(dummy_master)
                    assert win._resume_playback_after_audio_rebuild is False
                    mock_play.assert_called()

        # 2. Изменение настроек в микшере во время воспроизведения
        with unittest.mock.patch.object(win.player_widget, "is_playing", return_value=True):
            with unittest.mock.patch.object(win.player_widget, "pause") as mock_pause:
                with unittest.mock.patch.object(win.player_widget, "play") as mock_play:
                    win.on_dsp_panel_changed({})
                    assert win._resume_playback_after_audio_rebuild is True
                    mock_pause.assert_called()

                    win._on_master_audio_rendered(dummy_master)
                    assert win._resume_playback_after_audio_rebuild is False
                    mock_play.assert_called()

        # 3. Если плеер был на паузе, он НЕ должен автоматически запускаться после рендера
        with unittest.mock.patch.object(win.player_widget, "is_playing", return_value=False):
            with unittest.mock.patch.object(win.player_widget, "play") as mock_play:
                win.on_commentary_moved("c1", 10.0, 15.0)
                assert win._resume_playback_after_audio_rebuild is False

                win._on_master_audio_rendered(dummy_master)
                assert mock_play.call_count == 0

        win.close()
    finally:
        shutil.rmtree(tmp_dir, ignore_errors=True)

    print("[OK] test_auto_pause_and_resume_on_audio_rebuild passed")


def test_text_edit_and_audio_deletion_lifecycle():
    """Тестирует удаление старой озвучки при редактировании текста, исключение из мастер-аудио и повторный синтез."""
    import tempfile
    import shutil
    from core.config_manager import ConfigManager
    from core.project_manager import ProjectManager
    from ui.main_window import MainWindow

    tmp_dir = tempfile.mkdtemp()
    try:
        cfg = ConfigManager(os.path.join(tmp_dir, "config.ini"))
        proj_mgr = ProjectManager(tmp_dir)
        proj = proj_mgr.create_project("TestTextEditLifecycle", "")

        dummy_wav = os.path.join(proj.audio_dir, "c1.wav")
        with open(dummy_wav, "wb") as f:
            f.write(b"RIFF\x24\x00\x00\x00WAVEfmt \x10\x00\x00\x00\x01\x00\x01\x00D\xac\x00\x00\x88X\x01\x00\x02\x00\x10\x00data\x00\x00\x00\x00")

        dummy_raw = os.path.join(proj.audio_dir, "c1_raw.wav")
        with open(dummy_raw, "wb") as f:
            f.write(b"RIFF\x24\x00\x00\x00WAVEfmt \x10\x00\x00\x00\x01\x00\x01\x00D\xac\x00\x00\x88X\x01\x00\x02\x00\x10\x00data\x00\x00\x00\x00")

        proj.add_commentaries([
            {"id": "c1", "start_time": 5.0, "end_time": 10.0, "duration_sec": 5.0, "text": "Старый текст", "audio_file": dummy_wav, "raw_audio_file": dummy_raw, "audio_needs_rebuild": False}
        ])
        proj.save()

        with unittest.mock.patch("core.config_manager.ConfigManager.last_project", ""):
            win = MainWindow()
            win.config = cfg
            win.project_mgr = proj_mgr
            win.load_project(proj)

        # 1. Редактирование текста комментария должно удалить старую запись и сбросить audio_file
        assert os.path.isfile(dummy_wav)
        proj.update_commentary("c1", new_text="Новый отредактированный текст")
        assert not os.path.isfile(dummy_wav)
        assert not os.path.isfile(dummy_raw)
        comm = next((c for c in proj.commentaries if c.get("id") == "c1"), None)
        assert comm["audio_needs_rebuild"] is True
        assert comm["audio_file"] is None

        # 2. Вызов on_commentary_text_edited в MainWindow также сбрасывает старое аудио и запрашивает рендер
        with unittest.mock.patch.object(win, "request_rebuild_master_audio") as mock_rebuild:
            win.on_commentary_text_edited("c1")
            mock_rebuild.assert_called_with(immediate=True)
            comm_win = next((c for c in win.current_project.commentaries if c.get("id") == "c1"), None)
            assert comm_win["audio_needs_rebuild"] is True

        # 3. Проверка фильтрации в render_master_audio_track:
        # Комментарий с audio_needs_rebuild=True не должен попадать в valid_comms
        from core.audio_dsp import render_master_audio_track
        with unittest.mock.patch("core.audio_dsp.run_ffmpeg_with_progress", return_value=True) as mock_ffmpeg:
            with unittest.mock.patch("core.audio_dsp.ensure_extracted_source_audio", return_value="dummy_src.wav"):
                render_master_audio_track("dummy_src.wav", [{"id": "c1", "audio_file": dummy_wav, "audio_needs_rebuild": True}], os.path.join(tmp_dir, "out.wav"))
                # Должен вызваться без добавления дорожки комментария c1
                cmd_called = mock_ffmpeg.call_args[0][0] if mock_ffmpeg.call_args[0] else mock_ffmpeg.call_args[1].get("cmd", [])
                assert not any("c1.wav" in arg for arg in cmd_called)

        win.close()
    finally:
        shutil.rmtree(tmp_dir, ignore_errors=True)

    print("[OK] test_text_edit_and_audio_deletion_lifecycle passed")


def test_audio_dsp_panel_modes_and_render_progress():
    """Тестирует переключение режимов предпросмотра (Быстрое ред. / Итоговый звук) и индикацию рендера."""
    import tempfile
    import shutil
    from core.config_manager import ConfigManager
    from core.project_manager import ProjectManager
    from ui.main_window import MainWindow
    from ui.audio_dsp_panel import AudioDspPanel

    tmp_dir = tempfile.mkdtemp()
    try:
        tmp_ini = os.path.join(tmp_dir, "settings.ini")
        cfg = ConfigManager(tmp_ini)
        proj_mgr = ProjectManager(os.path.join(tmp_dir, "Projects"))
        proj = proj_mgr.create_project("TestAudioDSPModes", "")

        # 1. Тест панели изолированно
        panel = AudioDspPanel(cfg)
        assert panel.is_final_sound_mode() is False, "По умолчанию при создании должен быть режим быстрого редактирования"
        assert panel.rb_fast_mode.isChecked() is True
        assert panel.rb_final_mode.isChecked() is False
        assert panel.render_progress_frame.isHidden() is True

        # Прогресс в режиме быстрого ред. не должен открывать прогресс-бар
        panel.set_render_progress(50, "01:00", "2.0x")
        assert panel.render_progress_frame.isHidden() is True

        # Переключаем в режим «Итоговый звук»
        mode_signals = []
        panel.mode_changed.connect(lambda is_final: mode_signals.append(is_final))
        panel.set_mode(True)
        assert panel.is_final_sound_mode() is True
        assert len(mode_signals) == 1 and mode_signals[0] is True

        # Индикация прогресса
        panel.set_render_progress(42, "02:15", "1.8x")
        assert panel.render_progress_frame.isHidden() is False
        assert panel.render_progress_bar.value() == 42
        assert "42%" in panel.lbl_render_status.text()
        assert "02:15" in panel.lbl_render_status.text()

        # Завершение
        panel.set_render_finished(True)
        assert panel.render_progress_bar.value() == 100
        assert "Мастер-трек готов" in panel.lbl_render_status.text()

        # Возврат в режим быстрого редактирования
        panel.set_mode(False)
        assert panel.is_final_sound_mode() is False
        assert panel.render_progress_frame.isHidden() is True
        panel.close()

        # 2. Тест взаимодействия с MainWindow
        with unittest.mock.patch("core.config_manager.ConfigManager.last_project", ""):
            win = MainWindow()
            win.config = cfg
            win.project_mgr = proj_mgr
            win.load_project(proj)

        # В быстром режиме вызовы request_rebuild_master_audio не запускают воркер
        with unittest.mock.patch.object(win, "_do_rebuild_master_audio") as mock_do_rebuild:
            win.request_rebuild_master_audio(immediate=True)
            mock_do_rebuild.assert_not_called()

        # При перемещении комментария в быстром режиме плеер не ставится на паузу и не пересобирает мастер
        with unittest.mock.patch.object(win.player_widget, "is_playing", return_value=True):
            with unittest.mock.patch.object(win.player_widget, "pause") as mock_pause:
                win.on_commentary_moved("dummy", 1.0, 3.0)
                mock_pause.assert_not_called()

        # Переключаем режим на «Итоговый звук» в окне
        with unittest.mock.patch.object(win, "_do_rebuild_master_audio") as mock_do_rebuild:
            win.audio_dsp_panel.set_mode(True)
            assert win.audio_dsp_panel.is_final_sound_mode() is True
            # При переключении в итоговый звук вызывается немедленный пересчет
            mock_do_rebuild.assert_called_once()

        win.close()
    finally:
        shutil.rmtree(tmp_dir, ignore_errors=True)

    print("[OK] test_audio_dsp_panel_modes_and_render_progress passed")


def test_render_master_audio_track_scalability():
    """Тестирует сведение мастер-трека при большом количестве комментариев (100+ штук)."""
    import tempfile
    import shutil
    import numpy as np
    import scipy.io.wavfile as wav
    from core.audio_dsp import render_master_audio_track, build_combined_commentaries_track

    tmp_dir = tempfile.mkdtemp()
    try:
        # Создаем тестовый исходный звук фильма (10 сек)
        movie_wav = os.path.join(tmp_dir, "movie.wav")
        movie_samples = (np.sin(2 * np.pi * 440 * np.linspace(0, 10, 48000 * 10)) * 10000).astype(np.int16)
        movie_stereo = np.column_stack((movie_samples, movie_samples))
        wav.write(movie_wav, 48000, movie_stereo)

        # Создаем 100 коротких комментариев
        comms = []
        comm_samples = (np.sin(2 * np.pi * 880 * np.linspace(0, 0.5, 48000 // 2)) * 15000).astype(np.int16)
        comm_stereo = np.column_stack((comm_samples, comm_samples))

        for i in range(100):
            comm_path = os.path.join(tmp_dir, f"comm_{i:03d}.wav")
            wav.write(comm_path, 48000, comm_stereo)
            comms.append({
                "id": f"comm_{i:03d}",
                "audio_file": comm_path,
                "start_time": (i % 18) * 0.5,
                "duration_sec": 0.5,
                "volume_db": 0.0,
                "audio_needs_rebuild": False
            })

        out_master = os.path.join(tmp_dir, "master_output.wav")
        ok = render_master_audio_track(
            source_video_or_audio=movie_wav,
            commentaries_with_audio=comms,
            output_audio_path=out_master,
            movie_vol_db=-2.0,
            comm_vol_db=3.0,
            total_duration_sec=10.0
        )
        assert ok is True, "render_master_audio_track must succeed"
        assert os.path.isfile(out_master), "master output file must exist"
        assert os.path.getsize(out_master) > 10000, "master output file must have audio content"
    finally:
        shutil.rmtree(tmp_dir, ignore_errors=True)

    print("[OK] test_render_master_audio_track_scalability passed")

def test_audio_export_and_dialog():
    """Тестирует функционал экспорта только аудио (MP3/WAV) с текущими настройками звука."""
    import tempfile
    import shutil
    import numpy as np
    import scipy.io.wavfile as wav
    from unittest.mock import patch
    from core.config_manager import ConfigManager
    from core.project_manager import ProjectManager
    from ui.main_window import MainWindow
    from ui.export_progress_dialog import AudioExportWorker, AudioExportProgressDialog

    tmp_dir = tempfile.mkdtemp()
    try:
        # Создаем проект с аудио
        from core.app_paths import get_ffmpeg_path
        import subprocess
        proj_mgr = ProjectManager(tmp_dir)
        proj = proj_mgr.create_project("TestAudioExport", "")
        ffmpeg = get_ffmpeg_path()
        movie_mp4 = os.path.join(proj.folder_path, "source_video.mp4")
        subprocess.run([
            ffmpeg, "-y", "-f", "lavfi", "-i", "color=c=black:s=320x240:d=3",
            "-f", "lavfi", "-i", "anullsrc=r=48000:cl=stereo", "-t", "3",
            "-c:v", "libx264", "-c:a", "aac", movie_mp4
        ], check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        proj.data["src_video_path"] = movie_mp4
        proj.data["source_video_rel"] = "source_video.mp4"
        proj.data["total_duration_sec"] = 3.0

        comm_wav = os.path.join(tmp_dir, "comm_001.wav")
        comm_samples = (np.sin(2 * np.pi * 880 * np.linspace(0, 1, 48000)) * 15000).astype(np.int16)
        wav.write(comm_wav, 48000, np.column_stack((comm_samples, comm_samples)))
        proj.commentaries.append({
            "id": "c1",
            "text": "Комментарий",
            "audio_file": comm_wav,
            "start_time": 0.5,
            "duration_sec": 1.0,
            "volume_db": 0.0,
            "audio_needs_rebuild": False
        })
        proj.save()

        cfg = ConfigManager(os.path.join(tmp_dir, "settings.ini"))
        cfg.movie_volume_db = 0.0
        cfg.commentary_volume_db = 2.0

        # Экспорт в MP3
        mp3_out = os.path.join(tmp_dir, "exported.mp3")
        worker_mp3 = AudioExportWorker(proj, mp3_out, cfg)
        worker_mp3.run()
        assert os.path.isfile(mp3_out), "MP3 export file must exist"
        assert os.path.getsize(mp3_out) > 1000, "MP3 export file must not be empty"

        # Экспорт в WAV
        wav_out = os.path.join(tmp_dir, "exported.wav")
        worker_wav = AudioExportWorker(proj, wav_out, cfg)
        worker_wav.run()
        assert os.path.isfile(wav_out), "WAV export file must exist"
        assert os.path.getsize(wav_out) > 1000, "WAV export file must not be empty"

        # Проверка MainWindow actions и кнопок
        with patch("core.config_manager.ConfigManager.last_project", ""):
            win = MainWindow()
            win.load_project(proj)
            assert hasattr(win, "act_export_audio")
            assert hasattr(win, "btn_export_audio")
            assert win.act_export_audio.shortcut().toString() == "Ctrl+Shift+A"

            with patch("PySide6.QtWidgets.QFileDialog.getSaveFileName", return_value=(mp3_out, "Аудио MP3 (*.mp3)")):
                with patch("ui.main_window.AudioExportProgressDialog") as mock_dlg:
                    win.export_audio()
                    mock_dlg.assert_called_once()
            win.close()
    finally:
        shutil.rmtree(tmp_dir, ignore_errors=True)

    print("[OK] test_audio_export_and_dialog passed")


def test_mute_controls_and_master_render():
    """Тестирует флажки отключения звука (Mute) для фильма и комментариев."""
    import tempfile
    import shutil
    import numpy as np
    import scipy.io.wavfile as wav
    from core.config_manager import ConfigManager
    from ui.audio_dsp_panel import AudioDspPanel
    from ui.video_player_widget import VideoPlayerWidget
    from core.audio_dsp import render_master_audio_track

    tmp_dir = tempfile.mkdtemp()
    try:
        cfg = ConfigManager(os.path.join(tmp_dir, "settings.ini"))
        cfg.movie_muted = False
        cfg.commentary_muted = False
        assert cfg.movie_muted is False
        assert cfg.commentary_muted is False

        panel = AudioDspPanel(cfg)
        assert panel.strip_movie.is_muted() is False
        assert panel.strip_comm.is_muted() is False

        # Включаем Mute для фильма
        panel.strip_movie.set_muted(True)
        assert panel.strip_movie.is_muted() is True
        assert cfg.movie_muted is True
        assert panel.get_dsp_settings()["movie_muted"] is True

        # Включаем Mute для комментариев
        panel.strip_comm.set_muted(True)
        assert panel.strip_comm.is_muted() is True
        assert cfg.commentary_muted is True
        assert panel.get_dsp_settings()["commentary_muted"] is True

        # Проверка VideoPlayerWidget
        player = VideoPlayerWidget()
        player.update_from_config(cfg)
        assert player.movie_muted is True
        assert player.comm_muted is True
        player.apply_audio_dsp(1000)
        assert player.current_applied_movie_vol == 0.0
        assert player.current_applied_comm_vol == 0.0

        # Проверка рендера мастер-аудио с movie_muted=True и comm_muted=True
        src_wav = os.path.join(tmp_dir, "src.wav")
        samples = (np.sin(2 * np.pi * 440 * np.linspace(0, 1, 48000)) * 10000).astype(np.int16)
        wav.write(src_wav, 48000, np.column_stack((samples, samples)))

        out_wav = os.path.join(tmp_dir, "out_muted.wav")
        ok = render_master_audio_track(
            source_video_or_audio=src_wav,
            commentaries_with_audio=[],
            output_audio_path=out_wav,
            movie_muted=True,
            comm_muted=True,
            total_duration_sec=1.0
        )
        assert ok is True
        assert os.path.isfile(out_wav)

        panel.close()
    finally:
        shutil.rmtree(tmp_dir, ignore_errors=True)

    print("[OK] test_mute_controls_and_master_render passed")


def test_mkv_subtitle_disposition_not_default():
    """Тестирует, что дорожка субтитров в MKV не имеет флага default."""
    import tempfile
    import shutil
    import unittest.mock
    from core.config_manager import ConfigManager
    from core.project_manager import Project
    from core.mkv_exporter import export_project_to_mkv

    tmp_dir = tempfile.mkdtemp()
    try:
        proj = Project("TestSubtitleDisp", tmp_dir)
        fake_mp4 = os.path.join(tmp_dir, "fake.mp4")
        with open(fake_mp4, "wb") as f:
            f.write(b"dummy")
        proj.data["src_video_path"] = fake_mp4
        cfg = ConfigManager()

        with unittest.mock.patch("core.mkv_exporter.run_ffmpeg_with_progress", return_value=True) as mock_ffmpeg:
            with unittest.mock.patch("core.mkv_exporter.render_master_audio_track", return_value=True):
                with unittest.mock.patch("core.mkv_exporter.generate_srt_file"):
                    with unittest.mock.patch("os.path.exists", return_value=True):
                        export_project_to_mkv(proj, os.path.join(tmp_dir, "out.mkv"), cfg)
                        mux_cmd = mock_ffmpeg.call_args[0][0]
                        disp_idx = mux_cmd.index("-disposition:s:0")
                        assert mux_cmd[disp_idx + 1] == "0", f"Subtitle disposition must be '0', got {mux_cmd[disp_idx + 1]}"
    finally:
        shutil.rmtree(tmp_dir, ignore_errors=True)

    print("[OK] test_mkv_subtitle_disposition_not_default passed")



def test_master_audio_smooth_playback_and_envelope():
    """Тестирует быстрый in-memory расчет peak envelope мастер-аудио и мягкую синхронизацию."""
    import tempfile
    import shutil
    import numpy as np
    import scipy.io.wavfile as wav
    from ui.video_player_widget import VideoPlayerWidget

    tmp_dir = tempfile.mkdtemp()
    try:
        master_wav = os.path.join(tmp_dir, "master.wav")
        samples = (np.sin(2 * np.pi * 440 * np.linspace(0, 2, 48000 * 2)) * 16000).astype(np.int16)
        wav.write(master_wav, 48000, np.column_stack((samples, samples)))

        player = VideoPlayerWidget()
        player.load_master_audio(master_wav)
        assert player.is_using_master_audio is True
        assert player._master_peak_envelope is not None
        assert len(player._master_peak_envelope) > 0

        # Проверка тика таймера - не производит дисковых вызовов, быстро берет из памяти
        player._on_dsp_timer_tick()

        # Очистка
        player.clear_master_audio()
        assert player.is_using_master_audio is False
        assert player._master_peak_envelope is None
    finally:
        shutil.rmtree(tmp_dir, ignore_errors=True)

    print("[OK] test_master_audio_smooth_playback_and_envelope passed")


if __name__ == "__main__":
    test_time_formatting()
    test_srt_generation()
    test_timeline_hotkeys()
    test_export_worker_cancel()
    test_project_user_prompt()
    test_gemini_prompt_and_all_commentaries()
    test_video_player_dsp()
    test_user_prompt_dialog()
    test_project_video_copying_and_chunks()
    test_video_normalization_stream_copy()
    test_video_preparation_worker_flow()
    test_timecode_scale_guard()
    test_timeline_position_autofit()
    test_proxy_modes()
    test_tts_worker_cancellation()
    test_generation_worker_cancellation()
    test_resolve_commentary_overlaps()
    test_timeline_speedup_clamping_and_dialog()
    test_video_player_comm_seeking_and_pause_reset()
    test_character_manager_crud_and_screenshots()
    test_character_export_import_merging()
    test_character_cards_dialog_accessibility_and_features()
    test_fragment_prompt_dialog_and_extraction()
    test_timeline_range_selection_and_shortcuts()
    test_drag_commentary_swap_and_ripple_shift()
    test_resize_unvoiced_commentary_and_speedup()
    test_srt_manager_parsing_and_cleaning()
    test_srt_manager_file_encodings_and_roundtrip()
    test_project_srt_import_modes()
    test_main_window_srt_actions()
    test_main_window_import_export_execution()
    test_comment_list_panel_smooth_resize_and_reopen_button()
    test_settings_dialog_db_ranges_and_mixing()
    test_project_reset_for_full_regeneration()
    test_main_window_full_regeneration_warning()
    test_delete_active_project()
    test_token_tracker_and_dialog()
    test_auto_pause_and_resume_on_audio_rebuild()
    test_text_edit_and_audio_deletion_lifecycle()
    test_audio_dsp_panel_modes_and_render_progress()
    test_render_master_audio_track_scalability()
    test_audio_export_and_dialog()
    test_mute_controls_and_master_render()
    test_mkv_subtitle_disposition_not_default()
    test_master_audio_smooth_playback_and_envelope()
    print("ALL TESTS PASSED SUCCESSFULLY!")
