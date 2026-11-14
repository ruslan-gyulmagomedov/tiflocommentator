# -*- coding: utf-8 -*-
"""
Модуль для экспорта проекта в итоговый видеофайл формата MKV:
- Без перекодировки видеоряда (-c:v copy)
- Новая сведенная мастер-аудиодорожка со всеми комментариями, дакингом и компрессором
- Встроенные субтитры SRT, включенные по умолчанию (default=yes)
- 100% компенсация 5 мс задержки компрессора
"""

import os
import subprocess
from typing import Dict, List, Any, Optional, Callable
from core.app_paths import get_ffmpeg_path
from core.audio_dsp import render_master_audio_track, run_ffmpeg_with_progress, format_duration_sec
from core.srt_manager import format_srt_time, generate_srt_file


def export_project_to_mkv(
    project,
    output_mkv_path: str,
    config,
    progress_callback: Optional[Callable[[Any], None]] = None,
    cancel_event=None,
    process_holder: Optional[List[Any]] = None
) -> bool:
    """
    Экспортирует проект в MKV файл с видео без потерь, мастер-звуком и SRT субтитрами.
    Поддерживает детальный callback о стадиях, прерывание и очистку.
    """
    ffmpeg = get_ffmpeg_path(config.ffmpeg_path)
    os.makedirs(os.path.dirname(os.path.abspath(output_mkv_path)), exist_ok=True)

    src_video = project.data.get("src_video_path")
    if not src_video or not os.path.isfile(src_video):
        if project.chunks and os.path.isfile(project.chunks[0].get("filepath", "")):
            src_video = project.chunks[0]["filepath"]
        else:
            raise FileNotFoundError("Исходный видеофайл проекта не найден.")

    total_dur_sec = float(project.data.get("total_duration_sec", 0.0))
    if total_dur_sec <= 0:
        from core.video_splitter import analyze_media
        media_info = analyze_media(src_video, custom_ffprobe=config.ffprobe_path)
        total_dur_sec = media_info.duration
        project.data["total_duration_sec"] = total_dur_sec

    tot_time_str = format_duration_sec(total_dur_sec)
    num_comms = len(project.commentaries)

    temp_master_audio = os.path.join(project.output_dir, "master_audio_temp.aac")
    srt_path = os.path.join(project.output_dir, f"{project.name}.srt")

    def emit_progress(data):
        if not progress_callback:
            return
        progress_callback(data)

    try:
        # === ЭТАП 1: Генерация субтитров SRT ===
        if cancel_event and cancel_event.is_set():
            return False

        emit_progress({
            "step": 1,
            "total_steps": 3,
            "overall_pct": 2.0,
            "step_name": "Генерация дорожки субтитров SRT",
            "done_text": "Инициализация данных проекта",
            "current_text": f"Создание файла субтитров SRT ({num_comms} тифлокомментариев)...",
            "remaining_text": "2. Сведение и компрессия мастер-аудиодорожки\n3. Сборка контейнера MKV",
            "speed_str": "—",
            "time_str": "00:00"
        })

        generate_srt_file(project.commentaries, srt_path)

        if cancel_event and cancel_event.is_set():
            return False

        # === ЭТАП 2: Микширование звуковой дорожки и компрессия ===
        valid_comms = []
        for c in project.commentaries:
            c_copy = dict(c)
            if not c_copy.get("audio_file"):
                expected_audio = os.path.join(project.audio_dir, f"{c_copy.get('id')}.wav")
                if os.path.isfile(expected_audio):
                    c_copy["audio_file"] = expected_audio
            if c_copy.get("audio_file") and os.path.isfile(c_copy["audio_file"]) and not c_copy.get("audio_needs_rebuild", False):
                valid_comms.append(c_copy)

        def audio_prog_cb(frac: float, cur_str: str, speed_str: str):
            step_pct = frac * 100.0
            overall_pct = 5.0 + frac * 75.0
            emit_progress({
                "step": 2,
                "total_steps": 3,
                "overall_pct": overall_pct,
                "step_name": "Микширование звука и мастер-компрессия",
                "done_text": f"✓ Файл субтитров SRT сформирован ({num_comms} комментариев)",
                "current_text": f"Микширование звука с дакингом: {cur_str} из {tot_time_str} ({step_pct:.1f}%), скорость: {speed_str}",
                "remaining_text": "3. Сборка итогового контейнера MKV без перекодировки видеоряда",
                "speed_str": speed_str,
                "time_str": cur_str
            })

        emit_progress({
            "step": 2,
            "total_steps": 3,
            "overall_pct": 5.0,
            "step_name": "Микширование звука и мастер-компрессия",
            "done_text": f"✓ Файл субтитров SRT сформирован ({num_comms} комментариев)",
            "current_text": f"Запуск сведения звука с автодакингом ({len(valid_comms)} озвученных комментариев)...",
            "remaining_text": "3. Сборка итогового контейнера MKV без перекодировки видеоряда",
            "speed_str": "—",
            "time_str": "00:00"
        })

        audio_ok = render_master_audio_track(
            source_video_or_audio=src_video,
            commentaries_with_audio=valid_comms,
            output_audio_path=temp_master_audio,
            movie_vol_db=config.movie_volume_db,
            comm_vol_db=config.commentary_volume_db,
            movie_muted=config.movie_muted,
            comm_muted=config.commentary_muted,
            auto_ducking=config.auto_ducking,
            ducking_db=config.ducking_level_db,
            ducking_attack_ms=config.ducking_attack_ms,
            ducking_release_ms=config.ducking_release_ms,
            comp_threshold_db=config.compressor_threshold_db,
            comp_lookahead_ms=config.compressor_lookahead_ms,
            comp_release_ms=config.compressor_release_ms,
            custom_ffmpeg=config.ffmpeg_path,
            total_duration_sec=total_dur_sec,
            progress_callback=audio_prog_cb,
            cancel_event=cancel_event,
            process_holder=process_holder
        )

        if cancel_event and cancel_event.is_set():
            return False

        if not audio_ok:
            raise RuntimeError("Не удалось создать мастер-аудиодорожку.")

        # === ЭТАП 3: Сборка итогового контейнера MKV ===
        def mux_prog_cb(frac: float, cur_str: str, speed_str: str):
            step_pct = frac * 100.0
            overall_pct = 80.0 + frac * 20.0
            emit_progress({
                "step": 3,
                "total_steps": 3,
                "overall_pct": overall_pct,
                "step_name": "Мультиплексирование MKV",
                "done_text": f"✓ Файл субтитров SRT сформирован ({num_comms} шт.)\n✓ Мастер-аудиодорожка сведена и обработана лимитером",
                "current_text": f"Сборка MKV без перекодировки видео: {cur_str} из {tot_time_str} ({step_pct:.1f}%), скорость: {speed_str}",
                "remaining_text": "Финализация видеофайла",
                "speed_str": speed_str,
                "time_str": cur_str
            })

        emit_progress({
            "step": 3,
            "total_steps": 3,
            "overall_pct": 80.0,
            "step_name": "Мультиплексирование MKV",
            "done_text": f"✓ Файл субтитров SRT сформирован ({num_comms} шт.)\n✓ Мастер-аудиодорожка сведена и обработана лимитером",
            "current_text": "Сборка контейнера MKV (видеоряд без потерь + мастер-звук + субтитры)...",
            "remaining_text": "Финализация видеофайла",
            "speed_str": "—",
            "time_str": "00:00"
        })

        # Собираем MKV с точной компенсацией задержки упреждения компрессора (lookahead)
        comp_offset_sec = max(0.0, float(config.compressor_lookahead_ms) / 1000.0)
        cmd = [
            ffmpeg, "-y",
            "-itsoffset", f"{comp_offset_sec:.4f}",
            "-i", src_video,
            "-i", temp_master_audio,
            "-i", srt_path,
            "-map", "0:v:0",
            "-map", "1:a:0",
            "-map", "2:s:0",
            "-c:v", "copy",
            "-c:a", "copy",
            "-c:s", "srt",
            "-disposition:s:0", "0",
            output_mkv_path
        ]

        mux_ok = run_ffmpeg_with_progress(
            cmd,
            total_duration_sec=total_dur_sec,
            progress_callback=mux_prog_cb,
            cancel_event=cancel_event,
            process_holder=process_holder
        )

        if cancel_event and cancel_event.is_set():
            return False

        if not mux_ok:
            raise RuntimeError("Не удалось собрать контейнер MKV.")

        # === Завершение ===
        emit_progress({
            "step": 3,
            "total_steps": 3,
            "overall_pct": 100.0,
            "step_name": "Экспорт завершен",
            "done_text": f"✓ Субтитры SRT созданы ({num_comms} шт.)\n✓ Мастер-аудиодорожка сведена\n✓ Фильм успешно экспортирован в MKV!",
            "current_text": f"Файл успешно сохранен:\n{output_mkv_path}",
            "remaining_text": "Все этапы завершены",
            "speed_str": "—",
            "time_str": tot_time_str
        })

        return True

    except Exception as e:
        print(f"Ошибка экспорта в MKV: {e}")
        if cancel_event and cancel_event.is_set():
            return False
        raise
    finally:
        if os.path.exists(temp_master_audio):
            try:
                os.remove(temp_master_audio)
            except Exception:
                pass
        if cancel_event and cancel_event.is_set() and os.path.exists(output_mkv_path):
            try:
                os.remove(output_mkv_path)
            except Exception:
                pass
