# -*- coding: utf-8 -*-
"""
Модуль для импорта и экспорта тифлокомментариев в формате субтитров SubRip (.SRT).
Обеспечивает:
- Преобразование секунд в стандартный формат SRT (ЧЧ:ММ:СС,ммм) и обратно.
- Чтение файлов SRT с автоопределением кодировок (UTF-8, UTF-8 BOM, CP1251, CP1252).
- Очистку текста субтитров от HTML/VTT тегов (<i>, <b>, <font>, {\\an8}) для корректной работы синтезаторов речи.
- Преобразование распарсенных данных в формат тифлокомментариев проекта.
- Экспорт тифлокомментариев в валидный файл .SRT.
"""

import os
import re
from typing import List, Dict, Any, Optional


def format_srt_time(seconds: float) -> str:
    """
    Форматирует секунды с плавающей точкой в стандартный таймкод SRT: ЧЧ:ММ:СС,ммм
    Пример: 75.500 -> "00:01:15,500"
    """
    if seconds < 0:
        seconds = 0.0
    sec_int = int(seconds)
    ms = int(round((seconds - sec_int) * 1000))
    if ms >= 1000:
        sec_int += 1
        ms = 0
    m, s = divmod(sec_int, 60)
    h, m = divmod(m, 60)
    return f"{h:02d}:{m:02d}:{s:02d},{ms:03d}"


def parse_srt_time(time_str: str) -> Optional[float]:
    """
    Парсит строку таймкода SRT в секунды (float).
    Поддерживает разделители ',' и '.', часы, минуты, секунды и миллисекунды.
    """
    if not time_str or not isinstance(time_str, str):
        return None

    cleaned = time_str.strip().replace(',', '.')
    match = re.match(r'^(?:(?:(\d+):)?(\d{1,2}):)?(\d{1,2})(?:\.(\d+))?$', cleaned)
    if not match:
        return None

    h_str, m_str, s_str, ms_str = match.groups()
    h = int(h_str) if h_str is not None else 0
    m = int(m_str) if m_str is not None else 0
    s = int(s_str) if s_str is not None else 0

    ms_val = 0.0
    if ms_str:
        ms_clean = ms_str[:3].ljust(3, '0')
        ms_val = int(ms_clean) / 1000.0

    return round(h * 3600.0 + m * 60.0 + s + ms_val, 3)


def clean_srt_text(text: str) -> str:
    """
    Очищает текст комментария от тегов разметки HTML, WebVTT и ASS/SSA тегов.
    """
    if not text:
        return ""

    cleaned = re.sub(r'<[^>]+>', '', text)
    cleaned = re.sub(r'\{[^\}]*\}', '', cleaned)
    lines = [line.strip() for line in cleaned.splitlines()]
    result = " ".join([l for l in lines if l])
    result = re.sub(r'\s+', ' ', result).strip()
    return result



def parse_srt_content(content: str) -> List[Dict[str, Any]]:
    """
    Парсит текстовое содержимое файла субтитров SRT в список словарей комментариев.
    """
    if not content:
        return []

    normalized = content.replace('\r\n', '\n').replace('\r', '\n')
    raw_blocks = re.split(r'\n\s*\n', normalized.strip())

    commentaries: List[Dict[str, Any]] = []
    timing_regex = re.compile(
        r'((?:\d+:)?(?:\d+:)?\d+[,\.]\d+)\s*-->\s*((?:\d+:)?(?:\d+:)?\d+[,\.]\d+)'
    )

    for block in raw_blocks:
        lines = [l.strip() for l in block.split('\n') if l.strip()]
        if not lines:
            continue

        timing_line_idx = -1
        start_sec = None
        end_sec = None

        for idx, line in enumerate(lines):
            match = timing_regex.search(line)
            if match:
                st_str, et_str = match.groups()
                start_sec = parse_srt_time(st_str)
                end_sec = parse_srt_time(et_str)
                timing_line_idx = idx
                break

        if timing_line_idx == -1 or start_sec is None or end_sec is None:
            continue

        text_lines = lines[timing_line_idx + 1:]
        raw_text = "\n".join(text_lines)
        cleaned_text = clean_srt_text(raw_text)

        if not cleaned_text:
            continue

        if end_sec <= start_sec:
            end_sec = round(start_sec + 2.0, 3)

        dur_sec = round(end_sec - start_sec, 3)

        commentaries.append({
            "start_time": round(start_sec, 3),
            "end_time": round(end_sec, 3),
            "duration_sec": dur_sec,
            "text": cleaned_text,
            "type": "imported",
            "audio_needs_rebuild": True
        })

    commentaries.sort(key=lambda c: float(c.get("start_time", 0.0)))
    return commentaries


def parse_srt_file(file_path: str) -> List[Dict[str, Any]]:
    """
    Считывает и парсит файл субтитров SRT с поддержкой различных кодировок.
    """
    if not file_path or not os.path.isfile(file_path):
        return []

    encodings = ["utf-8-sig", "utf-8", "cp1251", "cp1252", "latin1"]
    content = ""

    for enc in encodings:
        try:
            with open(file_path, "r", encoding=enc) as f:
                content = f.read()
            break
        except UnicodeDecodeError:
            continue
        except Exception as e:
            print(f"Ошибка чтения файла {file_path} с кодировкой {enc}: {e}")
            break

    if not content:
        try:
            with open(file_path, "r", encoding="utf-8", errors="replace") as f:
                content = f.read()
        except Exception as e:
            print(f"Критическая ошибка чтения {file_path}: {e}")
            return []

    return parse_srt_content(content)


def generate_srt_content(commentaries: List[Dict[str, Any]]) -> str:
    """
    Формирует стандартный текст формата SRT из списка комментариев.
    """
    if not commentaries:
        return ""

    sorted_comms = sorted(commentaries, key=lambda c: float(c.get("start_time", 0.0)))
    blocks = []

    for idx, comm in enumerate(sorted_comms, start=1):
        st_sec = float(comm.get("start_time", 0.0))
        et_sec = float(comm.get("end_time", st_sec + 2.0))
        if et_sec <= st_sec:
            et_sec = st_sec + max(0.5, float(comm.get("duration_sec") or 2.0))

        st_str = format_srt_time(st_sec)
        et_str = format_srt_time(et_sec)
        text = str(comm.get("text", "")).strip()

        blocks.append(f"{idx}\n{st_str} --> {et_str}\n{text}\n")

    return "\n".join(blocks).strip() + "\n"


def generate_srt_file(commentaries: List[Dict[str, Any]], output_srt_path: str) -> bool:
    """
    Записывает комментарии в файл субтитров SRT в кодировке UTF-8.
    """
    return export_commentaries_to_srt(commentaries, output_srt_path)


def export_commentaries_to_srt(commentaries: List[Dict[str, Any]], output_srt_path: str) -> bool:
    """
    Экспортирует список тифлокомментариев в файл .SRT.
    Возвращает True в случае успешной записи.
    """
    if not output_srt_path:
        return False

    try:
        os.makedirs(os.path.dirname(os.path.abspath(output_srt_path)), exist_ok=True)
        content = generate_srt_content(commentaries)
        with open(output_srt_path, "w", encoding="utf-8") as f:
            f.write(content)
        return os.path.isfile(output_srt_path)
    except Exception as e:
        print(f"Ошибка экспорта комментариев в SRT ({output_srt_path}): {e}")
        return False
