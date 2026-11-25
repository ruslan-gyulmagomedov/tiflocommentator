# -*- coding: utf-8 -*-
"""
Модуль для анализа и нарезки видеофайлов без перекодировки с помощью FFmpeg/FFprobe.

Границы частей и вырезаемых фрагментов выравниваются по ключевым кадрам:
ffmpeg с -c copy не умеет начинать с произвольного кадра, поэтому «идеальное»
время начала и реальное начало файла раньше расходились, и комментарии
запаздывали.
"""

import os
import json
import subprocess
from typing import Dict, List, Any, Optional, Tuple, Callable
from core.app_paths import get_ffmpeg_path, get_ffprobe_path


# Кэш ключевых кадров: путь -> (mtime, размер, список времён)
_KEYFRAME_CACHE: Dict[str, Tuple[float, int, List[float]]] = {}
# Кэш длительности, посчитанной по пакетам: путь -> (mtime, размер, секунды)
_DURATION_FALLBACK_CACHE: Dict[str, Tuple[float, int, float]] = {}


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


def get_keyframe_times(video_path: str, custom_ffprobe: str = "") -> List[float]:
    """
    Возвращает отсортированный список времён ключевых кадров (в секундах).

    Результат кэшируется по пути, дате изменения и размеру файла: список
    нужен и при планировании частей, и при вырезании фрагментов, а полный
    проход по пакетам на длинном видео небыстрый.
    """
    if not video_path or not os.path.isfile(video_path):
        return []

    try:
        st = os.stat(video_path)
        key = os.path.abspath(video_path)
        cached = _KEYFRAME_CACHE.get(key)
        if cached and cached[0] == st.st_mtime and cached[1] == st.st_size:
            return list(cached[2])
    except Exception:
        st = None

    ffprobe = get_ffprobe_path(custom_ffprobe)
    cmd = [
        ffprobe,
        "-v", "error",
        "-select_streams", "v:0",
        "-skip_frame", "nokey",
        "-show_entries", "frame=pts_time",
        "-of", "csv=p=0",
        video_path
    ]

    times: List[float] = []
    try:
        startupinfo = None
        if os.name == 'nt':
            startupinfo = subprocess.STARTUPINFO()
            startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW

        proc = subprocess.Popen(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            text=True,
            encoding="utf-8",
            errors="replace",
            startupinfo=startupinfo
        )
        for line in proc.stdout:
            s = line.strip().strip(",")
            if not s:
                continue
            try:
                times.append(float(s.split(",")[0]))
            except Exception:
                continue
        proc.stdout.close()
        proc.wait(timeout=10)
    except Exception as e:
        print(f"Не удалось получить список ключевых кадров {video_path}: {e}")
        return []

    times = sorted(t for t in times if t >= 0)
    try:
        if st is not None:
            _KEYFRAME_CACHE[os.path.abspath(video_path)] = (st.st_mtime, st.st_size, list(times))
    except Exception:
        pass
    return times


def _probe_duration_by_demux(video_path: str, custom_ffprobe: str = "") -> float:
    """
    Запасное определение длительности: проходит по пакетам потока и берёт
    максимальную сумму pts + duration. Нужно для файлов, у которых в
    заголовке длительность не прописана (некоторые MKV/TS после монтажа).
    """
    if not video_path or not os.path.isfile(video_path):
        return 0.0

    try:
        st = os.stat(video_path)
        key = os.path.abspath(video_path)
        cached = _DURATION_FALLBACK_CACHE.get(key)
        if cached and cached[0] == st.st_mtime and cached[1] == st.st_size:
            return cached[2]
    except Exception:
        st = None

    ffprobe = get_ffprobe_path(custom_ffprobe)
    best = 0.0

    startupinfo = None
    if os.name == 'nt':
        startupinfo = subprocess.STARTUPINFO()
        startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW

    for stream_sel in ("v:0", "a:0"):
        try:
            cmd = [
                ffprobe,
                "-v", "error",
                "-select_streams", stream_sel,
                "-show_entries", "packet=pts_time,duration_time",
                "-of", "csv=p=0",
                video_path
            ]
            proc = subprocess.Popen(
                cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.DEVNULL,
                text=True,
                encoding="utf-8",
                errors="replace",
                startupinfo=startupinfo
            )
            for line in proc.stdout:
                s = line.strip()
                if not s:
                    continue
                parts = s.split(",")
                try:
                    pts = float(parts[0]) if parts[0] not in ("", "N/A") else 0.0
                except Exception:
                    continue
                dur = 0.0
                if len(parts) > 1 and parts[1] not in ("", "N/A"):
                    try:
                        dur = float(parts[1])
                    except Exception:
                        dur = 0.0
                if pts >= 0:
                    best = max(best, pts + dur)
            proc.stdout.close()
            proc.wait(timeout=10)
        except Exception:
            continue

    if best > 0 and st is not None:
        try:
            _DURATION_FALLBACK_CACHE[os.path.abspath(video_path)] = (st.st_mtime, st.st_size, best)
        except Exception:
            pass
    return round(best, 3)


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

        # Заголовок не дал длительность — считаем по пакетам
        if duration == 0.0:
            duration = _probe_duration_by_demux(video_path, custom_ffprobe)

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


def plan_chunk_boundaries(
    src_video_path: str,
    chunk_duration_sec: float,
    custom_ffprobe: str = "",
    total_duration: Optional[float] = None,
    info: Optional[Dict[str, Any]] = None
) -> List[float]:
    """
    Планирует границы частей: каждая граница — существующий ключевой кадр.

    Возвращает список временных меток от 0.0 до конца видео. Если ключевые
    кадры получить не удалось, границы ставятся по идеальному шагу.
    """
    if total_duration is None:
        media_info = analyze_media(src_video_path, custom_ffprobe)
        total_duration = media_info.duration
    total_duration = float(total_duration or 0.0)
    if total_duration <= 0:
        return [0.0]

    keyframes = get_keyframe_times(src_video_path, custom_ffprobe)
    if info is not None:
        info["keyframe_aligned"] = bool(keyframes)

    boundaries = [0.0]
    if keyframes:
        cur = 0.0
        while cur + 0.05 < total_duration:
            target = cur + chunk_duration_sec
            if target >= total_duration - 0.05:
                break
            nxt = None
            for kf in keyframes:
                if kf > target + 0.001:
                    nxt = kf
                    break
            if nxt is None or nxt >= total_duration - 0.05:
                break
            boundaries.append(round(float(nxt), 3))
            cur = float(nxt)
    else:
        cur = 0.0
        while cur + chunk_duration_sec < total_duration - 0.05:
            cur += chunk_duration_sec
            boundaries.append(round(cur, 3))

    boundaries.append(round(total_duration, 3))
    return boundaries


def split_video_into_chunks(
    src_video_path: str,
    output_dir: str,
    chunk_duration_sec: float,
    custom_ffmpeg: str = "",
    custom_ffprobe: str = "",
    progress_callback = None
) -> List[Dict[str, Any]]:
    """
    Нарезает видео на части без перекодировки (-c copy), выравнивая границы
    по ключевым кадрам.

    Почему это важно для синхронизации тифлокомментариев:
    FFmpeg с -c copy физически не может начать часть с произвольного кадра —
    он всегда начинает с ближайшего ключевого кадра (GOP может достигать
    5-10 секунд). Раньше метаданные части указывали на «идеальное» время
    (например, 15:00), а файл фактически начинался с ключевого кадра раньше
    (например, 14:55). В результате ВСЕ комментарии этой части на таймлайне
    запаздывали на эту разницу.

    Теперь границы частей заранее выбираются по ключевым кадрам, поэтому
    start_time_sec точно совпадает с первым кадром файла части.
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

    plan_info: Dict[str, Any] = {}
    boundaries = plan_chunk_boundaries(
        src_video_path,
        chunk_duration_sec,
        custom_ffprobe=custom_ffprobe,
        total_duration=total_duration,
        info=plan_info
    )

    chunks: List[Dict[str, Any]] = []
    total_chunks = max(1, len(boundaries) - 1)

    startupinfo = None
    if os.name == 'nt':
        startupinfo = subprocess.STARTUPINFO()
        startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW

    for idx in range(total_chunks):
        current_start = boundaries[idx]
        current_end = boundaries[idx + 1]
        duration_chunk = max(0.1, current_end - current_start)
        chunk_idx = idx + 1
        part_filename = f"part_{chunk_idx:03d}{ext}"
        part_path = os.path.join(output_dir, part_filename)

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

        chunks.append({
            "index": chunk_idx,
            "filename": part_filename,
            "filepath": part_path,
            "start_time_sec": round(current_start, 3),
            "end_time_sec": round(current_end, 3),
            "duration_sec": round(duration_chunk, 3),
            "keyframe_aligned": bool(plan_info.get("keyframe_aligned")),
            "processed": False
        })

        if progress_callback:
            progress_callback(chunk_idx, total_chunks)

    return chunks


def repair_legacy_chunk_timing(project, custom_ffprobe: str = "") -> bool:
    """
    Исправляет метаданные частей, созданных старой версией программы.
    Старая нарезка указывала «идеальное» начало части, а файл фактически
    начинался с предыдущего ключевого кадра — из-за этого все комментарии
    такой части запаздывали. Здесь начало части заменяется на реальный
    ключевой кадр. Конец части у старых файлов уже совпадал с номинальным.

    Возвращает True, если что-то было исправлено.
    """
    try:
        chunks = project.chunks
        if not chunks:
            return False
        if all(c.get("keyframe_aligned") for c in chunks):
            return False

        src = project.data.get("src_video_path", "")
        keyframes = get_keyframe_times(src, custom_ffprobe)
        if not keyframes:
            return False

        changed = False
        for ch in chunks:
            if ch.get("keyframe_aligned"):
                continue
            nominal = float(ch.get("start_time_sec", 0.0) or 0.0)
            if nominal > 0.001:
                actual = 0.0
                for kf in keyframes:
                    if kf <= nominal + 0.001:
                        actual = float(kf)
                        continue
                    break
                if 0.0 < actual < nominal - 0.01:
                    ch["legacy_nominal_start_sec"] = round(nominal, 3)
                    ch["start_time_sec"] = round(actual, 3)
                    changed = True
            ch["keyframe_aligned"] = True

        if changed:
            project.save()
        return changed
    except Exception as e:
        print(f"Не удалось исправить тайминги старых частей: {e}")
        return False


def align_fragment_to_keyframes(
    src_video_path: str,
    start_sec: float,
    end_sec: float,
    custom_ffprobe: str = ""
) -> Tuple[float, float]:
    """
    Выравнивает границы фрагмента по ключевым кадрам.

    -c copy начинает фрагмент с ближайшего ключевого кадра раньше запрошенного
    времени, из-за чего таймкоды модели запаздывали. Начало округляем вниз до
    ключевого кадра, конец — вверх до следующего ключевого кадра; небольшое
    расширение выделения допустимо. Возвращает реальные (start, end), по
    которым и надо смещать таймкоды.
    """
    try:
        start_sec = max(0.0, float(start_sec or 0.0))
    except Exception:
        start_sec = 0.0
    try:
        end_sec = float(end_sec or 0.0)
    except Exception:
        end_sec = start_sec + 0.1
    if end_sec <= start_sec + 0.1:
        end_sec = start_sec + 0.1

    keyframes = get_keyframe_times(src_video_path, custom_ffprobe)
    if not keyframes:
        return (round(start_sec, 3), round(end_sec, 3))

    aligned_start = 0.0
    for kf in keyframes:
        if kf <= start_sec + 0.001:
            aligned_start = float(kf)
            continue
        break

    aligned_end = end_sec
    for kf in keyframes:
        if kf >= end_sec - 0.001:
            aligned_end = float(kf)
            break

    if aligned_end <= aligned_start + 0.1:
        aligned_end = max(end_sec, aligned_start + 0.1)

    return (round(aligned_start, 3), round(aligned_end, 3))


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
    custom_ffmpeg: str = "",
    custom_ffprobe: str = "",
    align_to_keyframes: bool = False,
    info: Optional[Dict[str, Any]] = None
) -> bool:
    """
    Вырезает заданный фрагмент видео (от start_sec до end_sec) в эталонном для Gemini формате MP4 (H.264/AAC).

    Границы по умолчанию выравниваются по ключевым кадрам, потому что -c copy
    не умеет начинать с произвольного кадра. Реальные границы возвращаются через
    словарь info (ключи start_sec, end_sec) — по ним нужно смещать таймкоды
    комментариев, иначе они запаздывают.
    """
    if not os.path.isfile(src_video_path):
        return False

    ffmpeg = get_ffmpeg_path(custom_ffmpeg)
    os.makedirs(os.path.dirname(os.path.abspath(output_path)), exist_ok=True)

    try:
        req_start = max(0.0, float(start_sec or 0.0))
    except Exception:
        req_start = 0.0
    try:
        req_end = float(end_sec or 0.0)
    except Exception:
        req_end = req_start + 0.1

    if req_end <= req_start + 0.1:
        req_end = req_start + 0.1

    if align_to_keyframes:
        actual_start, actual_end = align_fragment_to_keyframes(
            src_video_path, req_start, req_end, custom_ffprobe
        )
    else:
        actual_start, actual_end = round(req_start, 3), round(req_end, 3)

    if info is not None:
        info["requested_start_sec"] = round(req_start, 3)
        info["requested_end_sec"] = round(req_end, 3)
        info["start_sec"] = round(actual_start, 3)
        info["end_sec"] = round(actual_end, 3)
        info["keyframe_aligned"] = bool(
            align_to_keyframes and actual_start != round(req_start, 3)
        )

    # Сдвиг на 2 мс от самого ключевого кадра: так ffmpeg не промахивается
    # на кадр назад при позиционировании ровно по ключевому кадру.
    seek_start = max(0.0, actual_start + (0.002 if actual_start > 0 else 0.0))
    dur = max(0.1, round(actual_end - actual_start, 3))

    startupinfo = None
    if os.name == 'nt':
        startupinfo = subprocess.STARTUPINFO()
        startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW

    # Пробуем быстрое извлечение с stream copy, если контейнер MP4
    cmd_copy = [
        ffmpeg,
        "-y",
        "-nostdin",
        "-ss", str(round(seek_start, 3)),
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
        "-i", src_video_path,
        "-ss", str(round(seek_start, 3)),
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
