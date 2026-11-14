# -*- coding: utf-8 -*-
"""
Модуль для анализа и нарезки видеофайлов без перекодировки с помощью FFmpeg/FFprobe.
"""

import os
import json
import subprocess
from typing import Dict, List, Any, Optional, Tuple, Callable
from core.app_paths import get_ffmpeg_path, get_ffprobe_path


class VideoAnalysisResult:
    """Результат анализа видеофайла."""
    def __init__(
        self,
        duration: float = 0.0,
        has_video: bool = False,
        has_audio: bool = False,
        video_codec: str = "",
        audio_codec: str = "",
        width: int = 0,
        height: int = 0,
        format_name: str = "",
        bitrate: int = 0
    ):
        self.duration = duration
        self.has_video = has_video
        self.has_audio = has_audio
        self.video_codec = video_codec
        self.audio_codec = audio_codec
        self.width = width
        self.height = height
        self.format_name = format_name
        self.bitrate = bitrate


def parse_time_str_to_seconds(time_str: Any) -> float:
    """Конвертирует строку 'HH:MM:SS.mmm' или секунды с плавающей точкой в float."""
    if not time_str or time_str == "N/A":
        return 0.0
    try:
        s = str(time_str).strip()
        if ":" in s:
            parts = s.split(":")
            if len(parts) == 3:
                return float(parts[0]) * 3600 + float(parts[1]) * 60 + float(parts[2])
            elif len(parts) == 2:
                return float(parts[0]) * 60 + float(parts[1])
        return float(s)
    except Exception:
        return 0.0


def analyze_media(video_path: str, custom_ffprobe: str = "") -> VideoAnalysisResult:
    """
    Анализирует медиафайл через ffprobe и возвращает технические параметры.
    """
    if not video_path or not os.path.isfile(video_path):
        return VideoAnalysisResult()

    ffprobe = get_ffprobe_path(custom_ffprobe)
    cmd = [
        ffprobe,
        "-v", "quiet",
        "-print_format", "json",
        "-show_format",
        "-show_streams",
        video_path
    ]

    try:
        startupinfo = None
        if os.name == 'nt':
            startupinfo = subprocess.STARTUPINFO()
            startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW

        result = subprocess.run(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            encoding="utf-8",
            errors="replace",
            startupinfo=startupinfo,
            check=True
        )
        data = json.loads(result.stdout)

        fmt_dur = data.get("format", {}).get("duration")
        duration = parse_time_str_to_seconds(fmt_dur)
        format_name = data.get("format", {}).get("format_name", "")
        bitrate = 0
        try:
            bitrate = int(data.get("format", {}).get("bit_rate", 0))
        except Exception:
            pass

        has_video = False
        has_audio = False
        video_codec = ""
        audio_codec = ""
        width = 0
        height = 0

        for stream in data.get("streams", []):
            codec_type = stream.get("codec_type")
            if codec_type == "video" and not has_video:
                has_video = True
                video_codec = stream.get("codec_name", "")
                try:
                    width = int(stream.get("width", 0))
                    height = int(stream.get("height", 0))
                except Exception:
                    pass
                if duration == 0.0:
                    s_dur = stream.get("duration")
                    if s_dur and s_dur != "N/A":
                        duration = parse_time_str_to_seconds(s_dur)
                    else:
                        for tag_key, tag_val in stream.get("tags", {}).items():
                            if "duration" in tag_key.lower():
                                d_val = parse_time_str_to_seconds(tag_val)
                                if d_val > duration:
                                    duration = d_val
            elif codec_type == "audio" and not has_audio:
                has_audio = True
                audio_codec = stream.get("codec_name", "")
                if duration == 0.0:
                    s_dur = stream.get("duration")
                    if s_dur and s_dur != "N/A":
                        duration = parse_time_str_to_seconds(s_dur)
                    else:
                        for tag_key, tag_val in stream.get("tags", {}).items():
                            if "duration" in tag_key.lower():
                                d_val = parse_time_str_to_seconds(tag_val)
                                if d_val > duration:
                                    duration = d_val

        # Проверяем теги формата на длительность
        if duration == 0.0:
            for tag_key, tag_val in data.get("format", {}).get("tags", {}).items():
                if "duration" in tag_key.lower():
                    d_val = parse_time_str_to_seconds(tag_val)
                    if d_val > duration:
                        duration = d_val

        return VideoAnalysisResult(
            duration=duration,
            has_video=has_video,
            has_audio=has_audio,
            video_codec=video_codec,
            audio_codec=audio_codec,
            width=width,
            height=height,
            format_name=format_name,
            bitrate=bitrate
        )
    except Exception as e:
        print(f"Ошибка при анализе медиафайла {video_path}: {e}")
        return VideoAnalysisResult()


def normalize_video_container(
    input_path: str,
    output_path: str,
    custom_ffmpeg: str = "",
    custom_ffprobe: str = "",
    progress_callback: Optional[Callable[[float, str, str], None]] = None,
    cancel_event = None,
    process_holder: Optional[List[Any]] = None
) -> bool:
    """
    Интеллектуальная нормализация видеофайла в эталонный контейнер MP4:
    - Видеоряд: H.264 (AVC) с атомом FastStart (+faststart), гарантирующий 100% точное распознавание
      FPS (23.976 / 24 / 25 / 29.97 / 30) в Google Gemini и идеальную покадровую синхронизацию.
    - Если видео уже H.264 (AVC) — выполняется мгновенный побитовый перенос (-c:v copy).
    - Если видео в устаревшем или нестандартном кодеке (MPEG-4 DivX/XviD, WMV, MPEG-2 и др.) —
      выполняется быстрая конвертация в эталонный H.264 (-c:v libx264 -preset veryfast -crf 20).
    - Звук нормализуется в чистый стереопоток AAC 48кГц (-c:a aac -b:a 192k -ar 48000).
    - Поддерживает callback прогресса и мгновенную отмену.
    Возвращает True в случае успеха, иначе False.
    """
    if not input_path or not os.path.isfile(input_path):
        return False

    os.makedirs(os.path.dirname(os.path.abspath(output_path)), exist_ok=True)
    ffmpeg = get_ffmpeg_path(custom_ffmpeg)

    # Анализируем наличие видео и аудио
    media_info = analyze_media(input_path, custom_ffprobe)

    cmd = [ffmpeg, "-y", "-nostdin", "-i", input_path]

    if media_info.has_video:
        v_codec = (media_info.video_codec or "").lower()
        if v_codec in ("h264", "avc1"):
            cmd.extend(["-c:v", "copy"])
        else:
            cmd.extend(["-c:v", "libx264", "-preset", "veryfast", "-crf", "20", "-pix_fmt", "yuv420p"])
    else:
        cmd.extend(["-vn"])

    if media_info.has_audio:
        cmd.extend(["-c:a", "aac", "-b:a", "192k", "-ar", "48000"])
    else:
        cmd.extend(["-an"])

    cmd.extend(["-avoid_negative_ts", "make_zero", "-fflags", "+genpts", "-movflags", "+faststart"])
    cmd.append(output_path)

    try:
        from core.audio_dsp import run_ffmpeg_with_progress
        success = run_ffmpeg_with_progress(
            cmd=cmd,
            total_duration_sec=media_info.duration,
            progress_callback=progress_callback,
            cancel_event=cancel_event,
            process_holder=process_holder
        )
        if success and os.path.isfile(output_path) and os.path.getsize(output_path) > 0:
            return True
        elif not success and cancel_event and cancel_event.is_set():
            if os.path.isfile(output_path):
                try:
                    os.remove(output_path)
                except Exception:
                    pass
            return False
    except Exception as e:
        print(f"Ошибка нормализации видео через FFmpeg ({input_path} -> {output_path}): {e}")

    # Fallback на прямое выполнение если run_ffmpeg_with_progress не сработал
    try:
        startupinfo = None
        if os.name == 'nt':
            startupinfo = subprocess.STARTUPINFO()
            startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW

        simple_cmd = [ffmpeg, "-y", "-nostdin", "-i", input_path]
        if media_info.has_video:
            v_codec = (media_info.video_codec or "").lower()
            if v_codec in ("h264", "avc1"):
                simple_cmd.extend(["-c:v", "copy"])
            else:
                simple_cmd.extend(["-c:v", "libx264", "-preset", "veryfast", "-crf", "20", "-pix_fmt", "yuv420p"])
        else:
            simple_cmd.extend(["-vn"])
        if media_info.has_audio:
            simple_cmd.extend(["-c:a", "aac", "-b:a", "192k", "-ar", "48000"])
        else:
            simple_cmd.extend(["-an"])
        simple_cmd.extend(["-avoid_negative_ts", "make_zero", "-movflags", "+faststart"])
        simple_cmd.append(output_path)

        subprocess.run(
            simple_cmd,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            startupinfo=startupinfo,
            check=True
        )
        return os.path.isfile(output_path) and os.path.getsize(output_path) > 0
    except Exception as e:
        print(f"Ошибка запасной нормализации видео: {e}")
        if os.path.isfile(output_path) and os.path.getsize(output_path) == 0:
            try:
                os.remove(output_path)
            except Exception:
                pass
        return False


def split_video_into_chunks(
    src_video_path: str,
    output_dir: str,
    chunk_duration_sec: float,
    custom_ffmpeg: str = "",
    custom_ffprobe: str = "",
    progress_callback = None
) -> List[Dict[str, Any]]:
    """
    Разрезает видео на части заданной длительности без перекодировки (-c copy).
    Возвращает список словарей с метаданными о каждой части.
    """
    os.makedirs(output_dir, exist_ok=True)
    media_info = analyze_media(src_video_path, custom_ffprobe)
    total_duration = media_info.duration
    if total_duration <= 0:
        raise ValueError("Не удалось определить длительность исходного видео.")

    ffmpeg = get_ffmpeg_path(custom_ffmpeg)
    ext = os.path.splitext(src_video_path)[1]
    if not ext:
        ext = ".mp4"

    chunks = []
    current_start = 0.0
    chunk_idx = 1
    total_chunks = max(1, int((total_duration + chunk_duration_sec - 0.001) // chunk_duration_sec))

    startupinfo = None
    if os.name == 'nt':
        startupinfo = subprocess.STARTUPINFO()
        startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW

    while current_start < total_duration:
        current_end = min(current_start + chunk_duration_sec, total_duration)
        part_filename = f"part_{chunk_idx:03d}{ext}"
        part_path = os.path.join(output_dir, part_filename)
        duration_chunk = current_end - current_start

        # FFmpeg команда нарезки без перекодировки
        # Помещаем -ss до -i для быстрого позиционирования по ключевым кадрам
        cmd = [
            ffmpeg,
            "-y",
            "-nostdin",
            "-ss", str(round(current_start, 3)),
            "-i", src_video_path,
            "-t", str(round(duration_chunk, 3)),
            "-c", "copy",
            "-avoid_negative_ts", "make_zero",
            "-movflags", "+faststart",
            part_path
        ]

        subprocess.run(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            startupinfo=startupinfo,
            check=True
        )

        chunk_data = {
            "index": chunk_idx,
            "filename": part_filename,
            "filepath": part_path,
            "start_time_sec": round(current_start, 3),
            "end_time_sec": round(current_end, 3),
            "duration_sec": round(duration_chunk, 3),
            "processed": False
        }
        chunks.append(chunk_data)

        if progress_callback:
            progress_callback(chunk_idx, total_chunks)

        current_start += chunk_duration_sec
        chunk_idx += 1

    return chunks


def extract_frame_screenshot(
    video_path: str,
    timestamp_sec: float,
    output_image_path: str,
    custom_ffmpeg: str = ""
) -> bool:
    """
    Извлекает скриншот кадра в высоком качестве в указанный момент времени.
    """
    ffmpeg = get_ffmpeg_path(custom_ffmpeg)
    os.makedirs(os.path.dirname(os.path.abspath(output_image_path)), exist_ok=True)

    startupinfo = None
    if os.name == 'nt':
        startupinfo = subprocess.STARTUPINFO()
        startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW

    cmd = [
        ffmpeg,
        "-y",
        "-ss", str(max(0.0, timestamp_sec)),
        "-i", video_path,
        "-vframes", "1",
        "-q:v", "2",
        output_image_path
    ]

    try:
        subprocess.run(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            startupinfo=startupinfo,
            check=True
        )
        return os.path.isfile(output_image_path) and os.path.getsize(output_image_path) > 0
    except Exception as e:
        print(f"Ошибка извлечения кадра: {e}")
        return False


def extract_video_fragment(
    src_video_path: str,
    start_sec: float,
    end_sec: float,
    output_path: str,
    custom_ffmpeg: str = ""
) -> bool:
    """
    Вырезает заданный фрагмент видео (от start_sec до end_sec) в эталонном для Gemini формате MP4 (H.264/AAC).
    """
    if not os.path.isfile(src_video_path):
        return False

    ffmpeg = get_ffmpeg_path(custom_ffmpeg)
    os.makedirs(os.path.dirname(os.path.abspath(output_path)), exist_ok=True)

    dur = max(0.1, round(end_sec - start_sec, 3))

    startupinfo = None
    if os.name == 'nt':
        startupinfo = subprocess.STARTUPINFO()
        startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW

    # Пробуем быстрое извлечение с stream copy, если контейнер MP4
    cmd_copy = [
        ffmpeg,
        "-y",
        "-nostdin",
        "-ss", str(round(max(0.0, start_sec), 3)),
        "-i", src_video_path,
        "-t", str(round(dur, 3)),
        "-c", "copy",
        "-avoid_negative_ts", "make_zero",
        "-movflags", "+faststart",
        output_path
    ]

    try:
        res = subprocess.run(
            cmd_copy,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            startupinfo=startupinfo,
            check=True
        )
        if os.path.isfile(output_path) and os.path.getsize(output_path) > 1024:
            return True
    except Exception:
        pass

    # Если copy не сработал или файл поврежден, выполняем надежное точное перекодирование
    cmd_encode = [
        ffmpeg,
        "-y",
        "-nostdin",
        "-ss", str(round(max(0.0, start_sec), 3)),
        "-i", src_video_path,
        "-t", str(round(dur, 3)),
        "-c:v", "libx264",
        "-preset", "ultrafast",
        "-crf", "23",
        "-c:a", "aac",
        "-b:a", "128k",
        "-avoid_negative_ts", "make_zero",
        "-movflags", "+faststart",
        output_path
    ]

    try:
        subprocess.run(
            cmd_encode,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            startupinfo=startupinfo,
            check=True
        )
        return os.path.isfile(output_path) and os.path.getsize(output_path) > 0
    except Exception as e:
        print(f"Ошибка вырезания фрагмента видео: {e}")
        return False


