# -*- coding: utf-8 -*-
"""
Модуль цифровой обработки звука (DSP):
- Ускорение речи без изменения тона (Pitch-preserving time stretch через atempo)
- Автоматический дакинг (плавное приглушение звука фильма при репликах)
- Упреждающий компрессор / пик-лимитер (-2 dBFS, 5 мс lookahead, 120 мс release)
- Точная синхронизация видео и аудио с учетом 5 мс задержки
"""

import os
import subprocess
import threading
import math
import struct
import time
import wave
from typing import List, Dict, Any, Tuple, Optional, Callable
import numpy as np
from core.app_paths import get_ffmpeg_path, get_ffprobe_path


def format_duration_sec(seconds: float) -> str:
    """Форматирует секунды в строку HH:MM:SS или MM:SS."""
    if seconds < 0:
        seconds = 0.0
    sec_int = int(seconds)
    m, s = divmod(sec_int, 60)
    h, m = divmod(m, 60)
    if h > 0:
        return f"{h:02d}:{m:02d}:{s:02d}"
    return f"{m:02d}:{s:02d}"


def run_ffmpeg_with_progress(
    cmd: List[str],
    total_duration_sec: float = 0.0,
    progress_callback: Optional[Callable[[float, str, str], None]] = None,
    cancel_event=None,
    process_holder: Optional[List[Any]] = None
) -> bool:
    """
    Запускает команду FFmpeg с отслеживанием прогресса в реальном времени
    и поддержкой мгновенной отмены (прерывания процесса).
    """
    startupinfo = None
    if os.name == 'nt':
        startupinfo = subprocess.STARTUPINFO()
        startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW

    full_cmd = list(cmd)
    if "-progress" not in full_cmd:
        full_cmd.extend(["-progress", "pipe:1", "-nostats"])

    try:
        proc = subprocess.Popen(
            full_cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            startupinfo=startupinfo,
            bufsize=1,
            encoding="utf-8",
            errors="replace"
        )
        if process_holder is not None:
            process_holder.clear()
            process_holder.append(proc)

        stderr_lines = []

        def drain_stderr():
            try:
                for err_line in proc.stderr:
                    stderr_lines.append(err_line)
            except Exception:
                pass

        stderr_thread = threading.Thread(target=drain_stderr, daemon=True)
        stderr_thread.start()

        current_sec = 0.0
        speed_str = "1.0x"

        for line in proc.stdout:
            if cancel_event and cancel_event.is_set():
                try:
                    proc.terminate()
                    proc.wait(timeout=2.0)
                except Exception:
                    proc.kill()
                return False

            line = line.strip()
            if not line:
                continue

            if "=" in line:
                k, v = line.split("=", 1)
                k = k.strip()
                v = v.strip()

                if k == "out_time_us":
                    try:
                        current_sec = int(v) / 1_000_000.0
                    except ValueError:
                        pass
                elif k == "out_time_ms":
                    # В FFmpeg поле out_time_ms передается в микросекундах (а не в миллисекундах)
                    try:
                        current_sec = int(v) / 1_000_000.0
                    except ValueError:
                        pass
                elif k == "out_time":
                    # Формат HH:MM:SS.microsec
                    try:
                        parts = v.split(":")
                        if len(parts) == 3:
                            h = float(parts[0])
                            m = float(parts[1])
                            s = float(parts[2])
                            current_sec = h * 3600.0 + m * 60.0 + s
                    except Exception:
                        pass
                elif k == "speed":
                    speed_str = v
                elif k == "progress" and progress_callback:
                    frac = 0.0
                    if total_duration_sec > 0:
                        # Во время рендера ограничиваем 0.99, чтобы 100% отображалось только по завершении
                        frac = min(0.99, max(0.0, current_sec / total_duration_sec))
                    cur_str = format_duration_sec(current_sec)
                    progress_callback(frac, cur_str, speed_str)

        proc.stdout.close()
        proc.wait()
        stderr_thread.join(timeout=2.0)

        if cancel_event and cancel_event.is_set():
            return False

        if proc.returncode != 0:
            err = "".join(stderr_lines)
            print(f"FFmpeg error (code {proc.returncode}): {err}")
            return False

        if progress_callback:
            progress_callback(1.0, format_duration_sec(total_duration_sec or current_sec), speed_str)
        return True

    except Exception as e:
        print(f"Ошибка выполнения FFmpeg: {e}")
        return False


def get_audio_duration_sec(audio_path: str, custom_ffprobe: str = "") -> float:
    """Определяет точную длительность аудиофайла в секундах."""
    if not os.path.isfile(audio_path):
        return 0.0
    ffprobe = get_ffprobe_path(custom_ffprobe)
    cmd = [
        ffprobe,
        "-v", "error",
        "-show_entries", "format=duration",
        "-of", "default=noprint_wrappers=1:nokey=1",
        audio_path
    ]
    try:
        startupinfo = None
        if os.name == 'nt':
            startupinfo = subprocess.STARTUPINFO()
            startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW
        res = subprocess.run(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            encoding="utf-8",
            errors="replace",
            startupinfo=startupinfo,
            check=True
        )
        return float(res.stdout.strip())
    except Exception as e:
        print(f"Ошибка определения длительности аудио {audio_path}: {e}")
        return 0.0


def build_atempo_filter_chain(factor: float) -> str:
    """
    Формирует цепочку фильтров atempo для FFmpeg.
    Каждый фильтр atempo принимает значение от 0.5 до 2.0.
    Для коэффициентов > 2.0 фильтры связываются каскадно (например, 3.0 -> atempo=2.0,atempo=1.5).
    """
    if factor <= 1.001:
        return "anull"

    factors = []
    rem = factor
    while rem > 2.0:
        factors.append(2.0)
        rem /= 2.0
    factors.append(rem)

    return ",".join(f"atempo={f:.4f}" for f in factors)


def time_stretch_audio(
    input_wav: str,
    output_wav: str,
    target_factor: float,
    max_speedup: float = 3.0,
    custom_ffmpeg: str = ""
) -> Tuple[bool, float]:
    """
    Ускоряет аудио без изменения высоты тона и применяет вещательную нормализацию громкости
    (EBU R128 loudnorm) для сочного и громкого звучания синтезатора речи.
    Ограничивает ускорение параметром max_speedup.
    Возвращает (успех, примененный_коэффициент).
    """
    effective_factor = max(1.0, min(target_factor, max_speedup))
    ffmpeg = get_ffmpeg_path(custom_ffmpeg)

    norm_filter = "loudnorm=I=-14:TP=-1.0:LRA=7"

    if effective_factor <= 1.001:
        filter_str = norm_filter
    else:
        tempo_str = build_atempo_filter_chain(effective_factor)
        filter_str = f"{tempo_str},{norm_filter}"

    cmd = [
        ffmpeg, "-y",
        "-i", input_wav,
        "-filter:a", filter_str,
        "-ar", "44100",
        "-ac", "2",
        output_wav
    ]

    try:
        startupinfo = None
        if os.name == 'nt':
            startupinfo = subprocess.STARTUPINFO()
            startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW
        subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, startupinfo=startupinfo, check=True)
        return True, effective_factor
    except Exception as e:
        print(f"Ошибка ускорения/нормализации аудио {input_wav}: {e}")
        return False, 1.0


def ensure_extracted_source_audio(src_video_path: str, project_dir: str = "", custom_ffmpeg: str = "") -> str:
    """
    Быстро извлекает аудиодорожку из исходного видеофайла в несжатый PCM WAV (48 кГц stereo).
    Кэширует результат для ускорения последующего микширования и компрессии.
    """
    if not os.path.isfile(src_video_path):
        return src_video_path

    ext = os.path.splitext(src_video_path)[1].lower()
    if ext in (".wav", ".aif", ".aiff", ".flac"):
        return src_video_path

    target_dir = project_dir if (project_dir and os.path.isdir(project_dir)) else os.path.dirname(os.path.abspath(src_video_path))
    cached_wav = os.path.join(target_dir, "source_audio.wav")

    if os.path.isfile(cached_wav) and os.path.getsize(cached_wav) > 1000:
        return cached_wav

    ffmpeg = get_ffmpeg_path(custom_ffmpeg)
    startupinfo = None
    if os.name == 'nt':
        startupinfo = subprocess.STARTUPINFO()
        startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW

    cmd = [
        ffmpeg, "-y",
        "-i", src_video_path,
        "-vn",
        "-ar", "48000",
        "-ac", "2",
        "-c:a", "pcm_s16le",
        cached_wav
    ]
    try:
        subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, startupinfo=startupinfo, check=True)
        if os.path.isfile(cached_wav) and os.path.getsize(cached_wav) > 1000:
            return cached_wav
    except Exception as e:
        print(f"Предупреждение при кэшировании аудио {src_video_path}: {e}")

    return src_video_path


def read_wav_as_float32(wav_path: str, target_sr: int = 48000) -> Optional[np.ndarray]:
    """
    Читает WAV файл и возвращает numpy массив float32 формы (N, 2) с частотой target_sr.
    """
    if not os.path.isfile(wav_path):
        return None
    try:
        with wave.open(wav_path, 'rb') as wf:
            n_channels = wf.getnchannels()
            sampwidth = wf.getsampwidth()
            sr = wf.getframerate()
            n_frames = wf.getnframes()
            raw_data = wf.readframes(n_frames)

        if sampwidth == 2:
            data = np.frombuffer(raw_data, dtype=np.int16).astype(np.float32) / 32768.0
        elif sampwidth == 4:
            data = np.frombuffer(raw_data, dtype=np.int32).astype(np.float32) / 2147483648.0
        elif sampwidth == 1:
            data = (np.frombuffer(raw_data, dtype=np.uint8).astype(np.float32) - 128.0) / 128.0
        else:
            # Fallback для 24-bit PCM или IEEE float
            try:
                import scipy.io.wavfile
                sr, s_data = scipy.io.wavfile.read(wav_path)
                if s_data.dtype == np.int16:
                    data = s_data.astype(np.float32) / 32768.0
                else:
                    data = s_data.astype(np.float32)
                n_channels = 1 if s_data.ndim == 1 else s_data.shape[1]
            except Exception:
                data = np.frombuffer(raw_data, dtype=np.int16).astype(np.float32) / 32768.0

        # Приводим к 2 каналам (стерео)
        if n_channels > 1:
            audio = data.reshape(-1, n_channels)
            if audio.shape[1] > 2:
                audio = audio[:, :2]
            elif audio.shape[1] == 1:
                audio = np.column_stack((audio[:, 0], audio[:, 0]))
        else:
            audio = np.column_stack((data, data))

        # Ресемплинг к target_sr
        if sr != target_sr and len(audio) > 0:
            target_len = int(round(len(audio) * float(target_sr) / float(sr)))
            if target_len > 0:
                old_x = np.linspace(0.0, 1.0, len(audio), endpoint=False)
                new_x = np.linspace(0.0, 1.0, target_len, endpoint=False)
                ch0 = np.interp(new_x, old_x, audio[:, 0])
                ch1 = np.interp(new_x, old_x, audio[:, 1])
                audio = np.column_stack((ch0, ch1)).astype(np.float32)

        return audio.astype(np.float32)
    except Exception as e:
        print(f"Ошибка чтения аудиофайла комментария {wav_path}: {e}")
        return None


def build_combined_commentaries_track(
    commentaries: List[Dict[str, Any]],
    output_wav_path: str,
    target_sr: int = 48000
) -> bool:
    """
    Быстро объединяет аудиофайлы тифлокомментариев в единую непрерывную стерео WAV дорожку 48 кГц.
    Использует прямую запись PCM данных на диск (memmap) с учетом времени start_time и громкости volume_db.
    """
    if not commentaries:
        return False

    valid_items = []
    max_end_sample = 0

    for c in commentaries:
        fpath = c.get("audio_file")
        if not fpath or not os.path.isfile(fpath):
            continue
        start_sec = max(0.0, float(c.get("start_time", 0.0)))
        start_sample = int(round(start_sec * target_sr))
        vol_db = float(c.get("volume_db", 0.0))
        gain = 10.0 ** (vol_db / 20.0)
        valid_items.append((start_sample, fpath, gain))

    if not valid_items:
        return False

    # Читаем фрагменты и определяем общую длину дорожки
    loaded_clips = []
    for start_sample, fpath, gain in valid_items:
        samples = read_wav_as_float32(fpath, target_sr=target_sr)
        if samples is not None and len(samples) > 0:
            end_sample = start_sample + len(samples)
            if end_sample > max_end_sample:
                max_end_sample = end_sample
            loaded_clips.append((start_sample, samples, gain))

    if not loaded_clips or max_end_sample <= 0:
        return False

    # Добавляем 1 секунду тишины в конце
    total_samples = max_end_sample + target_sr

    try:
        os.makedirs(os.path.dirname(os.path.abspath(output_wav_path)), exist_ok=True)
        num_channels = 2
        bits_per_sample = 16
        byte_rate = target_sr * num_channels * (bits_per_sample // 8)
        block_align = num_channels * (bits_per_sample // 8)
        data_size = total_samples * block_align
        riff_chunk_size = 36 + data_size

        with open(output_wav_path, "wb") as f:
            f.write(b'RIFF')
            f.write(struct.pack('<I', riff_chunk_size))
            f.write(b'WAVEfmt ')
            f.write(struct.pack('<IHHIIHH', 16, 1, num_channels, target_sr, byte_rate, block_align, bits_per_sample))
            f.write(b'data')
            f.write(struct.pack('<I', data_size))
            # Инициализируем файл нужным размером
            f.seek(44 + data_size - 1)
            f.write(b'\x00')

        # Отображаем data секцию в память через memmap и накладываем комментарии
        m = np.memmap(output_wav_path, dtype=np.int16, mode='r+', offset=44, shape=(total_samples, 2))
        for start_sample, samples, gain in loaded_clips:
            n = len(samples)
            if start_sample + n > total_samples:
                n = total_samples - start_sample
                samples = samples[:n]
            if n <= 0:
                continue
            scaled = samples * (gain * 32767.0)
            cur_region = m[start_sample : start_sample + n].astype(np.float32)
            cur_region += scaled
            np.clip(cur_region, -32768.0, 32767.0, out=cur_region)
            m[start_sample : start_sample + n] = cur_region.astype(np.int16)

        del m  # Сбрасывает буфер на диск
        return True
    except Exception as e:
        print(f"Ошибка формирования объединенной дорожки комментариев: {e}")
        return False


def render_master_audio_track(
    source_video_or_audio: str,
    commentaries_with_audio: List[Dict[str, Any]],
    output_audio_path: str,
    movie_vol_db: float = 0.0,
    comm_vol_db: float = 0.0,
    comp_threshold_db: float = -2.0,
    comp_lookahead_ms: float = 5.0,
    comp_release_ms: float = 120.0,
    movie_muted: bool = False,
    comm_muted: bool = False,
    custom_ffmpeg: str = "",
    total_duration_sec: float = 0.0,
    progress_callback: Optional[Callable[[float, str, str], None]] = None,
    cancel_event=None,
    process_holder: Optional[List[Any]] = None,
    **kwargs
) -> bool:
    """
    Создает сведенный мастер-аудиопоток со всеми тифлокомментариями под упреждающим компрессором.
    Регулировка громкости фильма и комментариев: от -15 dB до +20 dB, с поддержкой Mute (отключения звука).
    Поддерживает контроль прогресса и мгновенную отмену.
    """
    ffmpeg = get_ffmpeg_path(custom_ffmpeg)
    os.makedirs(os.path.dirname(os.path.abspath(output_audio_path)), exist_ok=True)

    if "movie_muted" in kwargs:
        movie_muted = bool(kwargs["movie_muted"])
    if "comm_muted" in kwargs:
        comm_muted = bool(kwargs["comm_muted"])

    # Обработка обратной совместимости, если переданы проценты
    if "movie_vol_pct" in kwargs:
        pct = float(kwargs["movie_vol_pct"])
        movie_vol_db = 20.0 * math.log10(max(0.01, pct / 100.0))
    elif movie_vol_db > 20.0:  # Значение явно передано в старых процентах
        movie_vol_db = 20.0 * math.log10(max(0.01, movie_vol_db / 100.0))

    if "comm_vol_pct" in kwargs:
        pct = float(kwargs["comm_vol_pct"])
        comm_vol_db = 20.0 * math.log10(max(0.01, pct / 100.0))
    elif comm_vol_db > 20.0:  # Значение явно передано в старых процентах
        comm_vol_db = 20.0 * math.log10(max(0.01, comm_vol_db / 100.0))

    # Фильтруем комментарии, имеющие реальные готовые аудиофайлы (и не требующие пересборки)
    valid_comms = []
    if not comm_muted:
        valid_comms = [
            c for c in commentaries_with_audio
            if c.get("audio_file") and os.path.isfile(c.get("audio_file")) and not c.get("audio_needs_rebuild", False)
        ]

    movie_vol_gain = 0.0 if movie_muted else (10.0 ** (max(-15.0, min(20.0, float(movie_vol_db))) / 20.0))
    comm_vol_gain = 0.0 if comm_muted else (10.0 ** (max(-15.0, min(20.0, float(comm_vol_db))) / 20.0))

    effective_source_audio = ensure_extracted_source_audio(source_video_or_audio, custom_ffmpeg=custom_ffmpeg)

    out_lower = output_audio_path.lower()
    if out_lower.endswith(".wav"):
        codec_args = ["-c:a", "pcm_s16le"]
    elif out_lower.endswith(".mp3"):
        codec_args = ["-c:a", "libmp3lame", "-b:a", "192k", "-q:a", "2"]
    else:
        codec_args = ["-c:a", "aac", "-b:a", "192k"]

    # Если комментариев нет, просто применяем громкость фильма и лимитер
    if not valid_comms:
        comp_filter = f"volume={movie_vol_gain:.4f},alimiter=limit={comp_threshold_db:.1f}dB:attack={comp_lookahead_ms:.1f}:release={comp_release_ms:.1f}:asc=0"
        cmd = [
            ffmpeg, "-y",
            "-i", effective_source_audio,
            "-vn",
            "-filter:a", comp_filter,
            "-ar", "48000",
            "-ac", "2",
            *codec_args,
            output_audio_path
        ]
        return run_ffmpeg_with_progress(
            cmd,
            total_duration_sec=total_duration_sec,
            progress_callback=progress_callback,
            cancel_event=cancel_event,
            process_holder=process_holder
        )

    # Если есть комментарии, объединяем их в единую непрерывную дорожку
    temp_comms_wav = os.path.join(
        os.path.dirname(os.path.abspath(output_audio_path)),
        f"temp_comms_{int(time.time() * 1000)}.wav"
    )

    comms_built = build_combined_commentaries_track(valid_comms, temp_comms_wav, target_sr=48000)

    try:
        if comms_built and os.path.isfile(temp_comms_wav):
            # Смешиваем дорожку фильма (вход 0) и общую дорожку комментариев (вход 1)
            filter_complex = [
                f"[0:a]volume={movie_vol_gain:.4f},aresample=48000[main_aud]",
                f"[1:a]volume={comm_vol_gain:.4f},aresample=48000[comm_aud]",
                "[main_aud][comm_aud]amix=inputs=2:duration=first:dropout_transition=0:normalize=0[mixed]",
                f"[mixed]alimiter=limit={comp_threshold_db:.1f}dB:attack={comp_lookahead_ms:.1f}:release={comp_release_ms:.1f}:asc=0[out_a]"
            ]
            full_filter_str = ";".join(filter_complex)

            cmd = [
                ffmpeg, "-y",
                "-i", effective_source_audio,
                "-i", temp_comms_wav,
                "-filter_complex", full_filter_str,
                "-map", "[out_a]",
                "-ar", "48000",
                "-ac", "2",
                *codec_args,
                output_audio_path
            ]
            return run_ffmpeg_with_progress(
                cmd,
                total_duration_sec=total_duration_sec,
                progress_callback=progress_callback,
                cancel_event=cancel_event,
                process_holder=process_holder
            )
        else:
            # Fallback если не удалось сформировать комментарии
            comp_filter = f"volume={movie_vol_gain:.4f},alimiter=limit={comp_threshold_db:.1f}dB:attack={comp_lookahead_ms:.1f}:release={comp_release_ms:.1f}:asc=0"
            cmd = [
                ffmpeg, "-y",
                "-i", effective_source_audio,
                "-vn",
                "-filter:a", comp_filter,
                "-ar", "48000",
                "-ac", "2",
                *codec_args,
                output_audio_path
            ]
            return run_ffmpeg_with_progress(
                cmd,
                total_duration_sec=total_duration_sec,
                progress_callback=progress_callback,
                cancel_event=cancel_event,
                process_holder=process_holder
            )
    finally:
        if os.path.isfile(temp_comms_wav):
            try:
                os.remove(temp_comms_wav)
            except Exception:
                pass

