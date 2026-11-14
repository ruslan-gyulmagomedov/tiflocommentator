# -*- coding: utf-8 -*-
"""
Модуль интеграции с Google Gemini API для генерации тифлокомментариев и синтеза речи.
"""

import os
import json
import time
import re
import wave
from typing import Dict, List, Any, Optional, Tuple, Callable
import warnings
warnings.filterwarnings('ignore')
import google.generativeai as genai


SYSTEM_INSTRUCTION_TIFLO = """ВЫ — ПРОФЕССИОНАЛЬНЫЙ ТИФЛОКОММЕНТАТОР ВЫСШЕЙ КАТЕГОРИИ И ПЕРЕВОДЧИК КИНО.
Ваша цель — создать профессиональное, лаконичное, художественно точное тифлоописание (аудиодескрипцию) к предоставленному фрагменту видео для незрячих и слабовидящих зрителей.

ГЛАВНЫЕ И НЕПРЕЛОЖНЫЕ ПРАВИЛА ТИФЛОКОММЕНТИРОВАНИЯ:
1. КАТЕГОРИЧЕСКИЙ ЗАПРЕТ НА ПЕРЕКРЫТИЕ РЕЧИ И ЗНАЧИМЫХ ЗВУКОВ:
   - Тифлокомментарий ДОЛЖЕН звучать ТОЛЬКО в паузах между репликами героев, важными звуковыми эффектами или ключевой закадровой музыкой.
   - Никогда не начинайте комментарий, пока герой говорит. Завершайте комментарий до начала следующей реплики.
   - СТРОГОЕ ПРАВИЛО ФОРМАТА ТАЙМКОДОВ:
     * Время начала (start_time) и окончания (end_time) каждого комментария ВСЕГДА указывайте в виде строки с двоеточиями: "ЧЧ:ММ:СС.ммм" (например, "00:00:10.500", "00:01:18.000", "00:07:56.200", "00:12:15.000") или "ММ:СС.ммм" (например, "00:10.500", "01:18.000", "07:56.200", "12:15.000").
     * КАТЕГОРИЧЕСКИ ЗАПРЕЩЕНО соединять минуты и секунды в единое число (например, запрещено писать 756 вместо "07:56.000" или 1215 вместо "12:15.000"!).
     * Все таймкоды отсчитываются от начала (00:00:00.000) предоставленного видеофрагмента.

2. КАРТОЧКИ ГЕРОЕВ И ИДЕНТИФИКАЦИЯ:
   - Как только в кадре впервые появляется новый персонаж, создайте для него карточку:
     * Опишите его внешность, возраст, отличительные черты, одежду.
     * Укажите точный таймкод (frame_timestamp_sec), на котором лицо/персонаж виден максимально четко крупным или средним планом для захвата скриншота.
     * Если имя персонажа пока неизвестно, дайте понятное временное обозначение роли (например: "Мужчина в сером пальто", "Водитель такси").
   - Как только в диалоге, титрах или сюжете раскрывается имя персонажа:
     * Обновите карточку персонажа его настоящим именем.
     * Во ВСЕХ последующих тифлокомментариях ОБЯЗАТЕЛЬНО называйте героя по имени!
   - При появлении новой ключевой информации о герое (смена внешности, изменение статуса: "Жена главного героя") дополните существующую карточку новым описанием и новым таймкодом для скриншота.

3. ПЕРЕВОД ИНОЯЗЫЧНОЙ РЕЧИ:
   - Если в видео звучит речь на любом иностранном языке (кроме русского) и отсутствует русская озвучка/дубляж, вы ОБЯЗАНЫ перевести сказанное на русский язык и включить в комментарий с типом "translated_speech".

4. ТИТРЫ, СУБТИТРЫ, НАДПИСИ И ТЕКСТ В КАДРЕ:
   - Если в кадре появляются начальные/финальные титры, субтитры, надписи на табличках, экранах телефонов, дорожных указателях, тексты писем или документов:
     * Обязательно озвучьте их, предварительно пояснив зрителю источник (например: "Титр на экране: Москва, 1941 год", "Надпись на вывеске: Закрыто на учет", "Текст сообщения: Жду тебя в парке").
     * Если надпись на иностранном языке — обязательно дайте её точный перевод на русский язык.

5. СТИЛЬ И ЯЗЫК КОММЕНТАРИЕВ:
   - Русский язык, грамматически безупречный, нейтральный, выразительный.
   - Описывайте визуальные действия в настоящем времени ("Олег открывает дверь", "Машина резко тормозит").
   - Не высказывайте оценочных суждений, не спойлерите будущие события — описывайте исключительно визуальный ряд: действия, позы, мимику, жесты, смену локаций, визуальные эффекты.

6. ДИАГНОСТИКА ПОТОКОВ:
   - Проверьте наличие и корректность видео- и аудиодорожек.
   - Если видеоряд отсутствует или поврежден: установите video_status: "missing" и commentary_allowed: false.
   - Если аудиоряд отсутствует: установите audio_status: "missing", commentary_allowed: true, requires_user_confirmation: true.

7. АБСОЛЮТНЫЙ И НАИВЫСШИЙ ПРИОРИТЕТ ПОЖЕЛАНИЙ И ИНСТРУКЦИЙ ПОЛЬЗОВАТЕЛЯ (USER INSTRUCTIONS):
   - Пожелания, сюжет, сценарий, требования к переводу или стилю от пользователя (User Instructions / Wishes), переданные в блоке «ПОЖЕЛАНИЯ И ДОПОЛНИТЕЛЬНЫЕ УКАЗАНИЯ ПОЛЬЗОВАТЕЛЯ», имеют АБСОЛЮТНЫЙ И НАИВЫСШИЙ ПРИОРИТЕТ над любыми другими правилами системного промта.
   - Если пользователь о чём-то просит в таком пожелании, его просьбу необходимо строго и неукоснительно выполнить, даже если она прямо противоречит другим инструкциям и правилам в этом системном промте.
   - Например, пользователь может попросить сделать не тифлокомментарии, а полный перевод фильма на какой-либо язык, сосредоточиться на определенных персонажах или деталях, изменить стиль или формат, не комментировать определенные сцены — в любых подобных случаях приоритет ВСЕГДА безоговорочно отдается требованиям пользователя!

ОТВЕТ ДОЛЖЕН БЫТЬ В ФОРМАТЕ ЧИСТОГО JSON БЕЗ Markdown разметки!
"""


def parse_time_to_seconds(t_val, max_duration: float = 0.0) -> float:
    """
    Конвертирует строку времени (HH:MM:SS.mmm, MM:SS.mmm) или секунды в float.
    Включает защиту от слитной нотации MMSS (например, 756 -> 07:56 = 476.0с, 1215 -> 12:15 = 735.0с),
    если передан max_duration и исходное значение превышает длительность фрагмента.
    """
    if t_val is None:
        return 0.0

    if isinstance(t_val, (int, float)):
        val = float(t_val)
    else:
        s = str(t_val).strip()
        if not s or s == "N/A":
            return 0.0

        if ":" in s:
            parts = s.split(":")
            try:
                if len(parts) == 3:
                    return round(float(parts[0]) * 3600 + float(parts[1]) * 60 + float(parts[2]), 3)
                elif len(parts) == 2:
                    return round(float(parts[0]) * 60 + float(parts[1]), 3)
                elif len(parts) == 1:
                    val = float(parts[0])
            except Exception:
                return 0.0
        else:
            try:
                val = float(s)
            except ValueError:
                return 0.0

    # Проверка на слитную нотацию MMSS (например, 756 -> 7 мин 56 сек, 1215 -> 12 мин 15 сек)
    if max_duration > 0.0 and val > (max_duration + 1.0) and val >= 100.0:
        int_val = int(val)
        mins = int_val // 100
        secs = (int_val % 100) + (val - int_val)
        if secs < 60.0:
            candidate = mins * 60.0 + secs
            if candidate <= (max_duration + 5.0):
                return round(candidate, 3)

    return round(val, 3)


def _record_token_usage(model_name: str, response: Any):
    """Извлекает токены из ответа Gemini и передает их в TokenTracker."""
    try:
        from core.token_tracker import TokenTracker
        usage = getattr(response, "usage_metadata", None)
        in_tok = 0
        out_tok = 0
        if usage is not None:
            in_tok = int(getattr(usage, "prompt_token_count", 0) or 0)
            out_tok = int(getattr(usage, "candidates_token_count", 0) or 0)
        TokenTracker.record_usage(model_name, in_tok, out_tok)
    except Exception as e:
        print(f"Предупреждение при фиксации расхода токенов: {e}")


class GeminiClient:
    """Клиент для взаимодействия с Google Gemini API."""

    def __init__(self, api_key: str):
        self.api_key = api_key.strip()
        from core.proxy_manager import ensure_proxy_configured
        ensure_proxy_configured()

        if self.api_key:
            genai.configure(api_key=self.api_key, transport="rest")

    def set_api_key(self, api_key: str):
        self.api_key = api_key.strip()
        from core.proxy_manager import ensure_proxy_configured
        ensure_proxy_configured()
        if self.api_key:
            genai.configure(api_key=self.api_key, transport="rest")

    def fetch_available_models(self) -> Tuple[List[str], List[str]]:
        """
        Получает полный список всех моделей с серверов Google Gemini без фильтрации.
        Возвращает кортеж: (список_всех_моделей, список_всех_моделей).
        """
        if not self.api_key:
            raise ValueError("API-ключ Gemini не установлен!")

        models_list = []

        try:
            for model in genai.list_models():
                name = model.name
                if name.startswith("models/"):
                    name = name[len("models/"):]
                models_list.append(name)

            def sort_key(m_name: str):
                score = 0
                m_low = m_name.lower()
                if "3.7" in m_low:
                    score += 500
                elif "3.6" in m_low:
                    score += 450
                elif "3.5" in m_low:
                    score += 400
                elif "3.1" in m_low:
                    score += 350
                elif "3" in m_low:
                    score += 300
                elif "2.5" in m_low:
                    score += 250
                elif "2.0" in m_low or "2-" in m_low:
                    score += 200
                elif "1.5" in m_low:
                    score += 150

                if "tts" in m_low:
                    score += 30
                if "flash" in m_low:
                    score += 20
                if "pro" in m_low:
                    score += 15
                return score

            models_list.sort(key=sort_key, reverse=True)

            # Оба списка содержат абсолютно все доступные модели без фильтрации
            text_models = list(models_list)
            tts_models = list(models_list)

            return text_models, tts_models

        except Exception as e:
            err_str = str(e)
            print(f"Ошибка получения списка моделей: {err_str}")
            if "User location is not supported" in err_str or "location" in err_str.lower() or "400" in err_str:
                raise RuntimeError(
                    "Google Gemini недоступен для прямого подключения в вашем регионе.\n"
                    "Пожалуйста, убедитесь, что в Windows включен прокси-сервер или укажите рабочий прокси в Настройках программы (Вкладка «Сеть и Прокси»)."
                ) from e
            raise

    def upload_file_and_wait(self, filepath: str, progress_callback: Optional[Callable[[str], None]] = None) -> Any:
        """Загружает видеофайл в Gemini File API и ждет завершения обработки."""
        from core.proxy_manager import ensure_proxy_configured
        ensure_proxy_configured()

        if progress_callback:
            progress_callback(f"Загрузка файла {os.path.basename(filepath)} в Google Gemini...")

        try:
            uploaded_file = genai.upload_file(path=filepath)
        except Exception as e:
            err_str = str(e)
            print(f"Ошибка загрузки файла в Gemini API: {err_str}")
            if "User location is not supported" in err_str or "location" in err_str.lower() or "400" in err_str:
                raise RuntimeError(
                    "Google Gemini недоступен для прямого подключения в вашем регионе (User location is not supported).\n"
                    "Пожалуйста, убедитесь, что в Windows включен рабочий прокси-сервер или укажите пользовательский прокси в меню Настройки -> Сеть и Прокси."
                ) from e
            raise

        if progress_callback:
            progress_callback("Файл передан. Ожидание индексации видео моделью...")

        while uploaded_file.state.name == "PROCESSING":
            time.sleep(2)
            try:
                uploaded_file = genai.get_file(uploaded_file.name)
            except Exception as e:
                err_str = str(e)
                if "User location is not supported" in err_str or "location" in err_str.lower():
                    raise RuntimeError(
                        "Google Gemini недоступен для прямого подключения в вашем регионе.\n"
                        "Пожалуйста, проверьте настройки прокси-сервера (Настройки -> Сеть и Прокси)."
                    ) from e
                raise

        if uploaded_file.state.name == "FAILED":
            raise RuntimeError(f"Ошибка обработки видео в Google Gemini File API: {uploaded_file.error.message}")

        if progress_callback:
            progress_callback("Видео успешно проиндексировано.")
        return uploaded_file

    def generate_commentary_for_chunk(
        self,
        chunk_file_path: str,
        chunk_index: int,
        total_chunks: int,
        start_abs_sec: float,
        end_abs_sec: float,
        existing_characters: List[Dict[str, Any]],
        previous_commentaries: Optional[List[Dict[str, Any]]] = None,
        user_prompt: str = "",
        model_name: str = "gemini-2.0-flash",
        progress_callback: Optional[Callable[[str], None]] = None
    ) -> Dict[str, Any]:
        """
        Анализирует часть видео и генерирует тифлокомментарии и карточки персонажей.
        Включает карточки персонажей из предыдущих частей и пожелания пользователя.
        Комментарии предыдущих частей намеренно не передаются, чтобы модель не путала тайминги.
        """
        if not self.api_key:
            raise ValueError("API-ключ Gemini не задан!")

        uploaded_file = None
        try:
            uploaded_file = self.upload_file_and_wait(chunk_file_path, progress_callback)

            # Формируем контекстную информацию для модели
            start_m, start_s = divmod(int(start_abs_sec), 60)
            start_h, start_m = divmod(start_m, 60)
            end_m, end_s = divmod(int(end_abs_sec), 60)
            end_h, end_m = divmod(end_m, 60)
            start_str = f"{start_h:02d}:{start_m:02d}:{start_s:02d}"
            end_str = f"{end_h:02d}:{end_m:02d}:{end_s:02d}"

            chars_summary = []
            for c in existing_characters:
                c_name = c.get("name", "Неизвестный")
                c_role = c.get("role", "")
                c_desc = c.get("description", "")
                chars_summary.append(f"- {c_name} ({c_role}): {c_desc}")
            chars_context = "\n".join(chars_summary) if chars_summary else "Персонажи пока не зафиксированы."

            # Формируем блок пожеланий пользователя с наивысшим приоритетом
            user_prompt_clean = (user_prompt or "").strip()
            if user_prompt_clean:
                user_wishes_str = f"""ПОЖЕЛАНИЯ И ДОПОЛНИТЕЛЬНЫЕ УКАЗАНИЯ ПОЛЬЗОВАТЕЛЯ К ФИЛЬМУ (НАИВЫСШИЙ ПРИОРИТЕТ):
ВНИМАНИЕ: Ниже приведены особые пожелания пользователя, синопсис, сценарий или индивидуальные требования к фильму.
Данные указания пользователя имеют АБСОЛЮТНЫЙ И НАИВЫСШИЙ ПРИОРИТЕТ над любыми общими правилами. Вы обязаны строго следовать им:
\"\"\"
{user_prompt_clean}
\"\"\""""
            else:
                user_wishes_str = "ПОЖЕЛАНИЯ ПОЛЬЗОВАТЕЛЯ:\nПользователь не указал особых пожеланий. Строго следуйте стандартным профессиональным правилам тифлокомментирования."

            prompt = f"""
КОНТЕКСТ ТЕКУЩЕГО ФРАГМЕНТА:
- Номер текущей части: {chunk_index} из {total_chunks}
- Временной интервал данной части в полном фильме: от {start_str} до {end_str}
- Предыдущие завершенные части фильма: с 1 по {chunk_index - 1} (их персонажи приведены ниже)
- Оставшиеся части фильма после текущей: {total_chunks - chunk_index}
- Модель продолжает непрерывную работу над фильмом с соблюдением преемственности сюжета, стиля и имен персонажей.

{user_wishes_str}

СПИСОК УЖЕ ИЗВЕСТНЫХ ПЕРСОНАЖЕЙ ИЗ ВСЕХ ПРЕДЫДУЩИХ ЧАСТЕЙ:
{chars_context}

ЗАДАЧА:
1. Тщательно проанализируйте видео и звук текущей части № {chunk_index}.
2. Проверьте статус видео и аудио потоков.
3. Дополните карточки персонажей новыми героями или уточните существующие (с указанием таймкода внутри текущей части в виде строки "ЧЧ:ММ:СС.ммм", например "00:00:12.500", для захвата качественного скриншота лица).
4. Создайте хронологические тифлокомментарии к этой части с обязательным указанием start_time и end_time в виде строки "ЧЧ:ММ:СС.ммм" (например, "00:00:05.200", "00:07:56.000"). Все таймкоды строго отсчитываются от начала предоставленного видеофайла (00:00:00.000). Запрещено соединять минуты и секунды в единое число! Не перекрывайте речь героев фильма!
5. Если звучит иностранная речь без русского перевода — переведите её в комментарии (тип translated_speech).
6. Если появляются титры, субтитры или надписи — озвучьте их и переведите на русский язык.
7. Неукоснительно учитывайте все пожелания пользователя, обладающие высшим приоритетом.

Верните ответ строго в формате JSON:
{{
  "diagnostics": {{
    "video_status": "ok", // или "missing" / "corrupted"
    "audio_status": "ok", // или "missing"
    "language_detected": "ru",
    "commentary_allowed": true,
    "warning_message": ""
  }},
  "characters": [
    {{
      "id": "char_...",
      "name": "Имя или описание роли",
      "role": "Роль",
      "description": "Визуальное описание внешности и одежды",
      "frame_timestamp": "00:00:12.500"
    }}
  ],
  "commentaries": [
    {{
      "id": "comm_...",
      "start_time": "00:00:05.200",
      "end_time": "00:00:09.800",
      "type": "commentary", // "commentary" | "title" | "subtitle" | "translated_speech"
      "text": "Текст тифлокомментария на чистом русском языке",
      "visual_description": "Краткое техническое описание визуального действия"
    }}
  ]
}}
"""
            if progress_callback:
                progress_callback(f"Запрос анализа в модель {model_name}...")

            model = genai.GenerativeModel(
                model_name=model_name,
                system_instruction=SYSTEM_INSTRUCTION_TIFLO,
                generation_config={
                    "response_mime_type": "application/json",
                    "max_output_tokens": 65536
                }
            )

            response = model.generate_content([uploaded_file, prompt])
            _record_token_usage(model_name, response)
            raw_text = response.text.strip()

            # Удаляем markdown кавычки если есть
            if raw_text.startswith("```json"):
                raw_text = raw_text[7:]
            if raw_text.startswith("```"):
                raw_text = raw_text[3:]
            if raw_text.endswith("```"):
                raw_text = raw_text[:-3]

            parsed_data = json.loads(raw_text.strip())
            return parsed_data

        finally:
            if uploaded_file:
                try:
                    genai.delete_file(uploaded_file.name)
                except Exception:
                    pass

    def generate_commentary_for_fragment(
        self,
        fragment_file_path: str,
        start_abs_sec: float,
        end_abs_sec: float,
        existing_characters: List[Dict[str, Any]],
        fragment_prompt: str = "",
        model_name: str = "gemini-2.0-flash",
        progress_callback: Optional[Callable[[str], None]] = None
    ) -> Dict[str, Any]:
        """
        Анализирует произвольный выделенный фрагмент видео.
        Передает системный промпт, карточки персонажей и индивидуальные пожелания пользователя
        к этому фрагменту. Пожелания всего проекта и история комментариев не передаются.
        """
        if not self.api_key:
            raise ValueError("API-ключ Gemini не задан!")

        uploaded_file = None
        try:
            uploaded_file = self.upload_file_and_wait(fragment_file_path, progress_callback)

            # Временные метки фрагмента в фильме
            start_m, start_s = divmod(int(start_abs_sec), 60)
            start_h, start_m = divmod(start_m, 60)
            end_m, end_s = divmod(int(end_abs_sec), 60)
            end_h, end_m = divmod(end_m, 60)
            start_str = f"{start_h:02d}:{start_m:02d}:{start_s:02d}"
            end_str = f"{end_h:02d}:{end_m:02d}:{end_s:02d}"
            frag_dur_sec = max(0.1, round(end_abs_sec - start_abs_sec, 3))

            chars_summary = []
            for c in existing_characters:
                c_name = c.get("name", "Неизвестный")
                c_role = c.get("role", "")
                c_desc = c.get("description", "")
                chars_summary.append(f"- {c_name} ({c_role}): {c_desc}")
            chars_context = "\n".join(chars_summary) if chars_summary else "Персонажи пока не зафиксированы."

            frag_prompt_clean = (fragment_prompt or "").strip()
            if frag_prompt_clean:
                user_wishes_str = f"""ИНДИВИДУАЛЬНЫЕ ПОЖЕЛАНИЯ И ИНСТРУКЦИИ К ДАННОМУ ВЫДЕЛЕННОМУ ФРАГМЕНТУ (НАИВЫСШИЙ ПРИОРИТЕТ):
ВНИМАНИЕ: Ниже приведены особые пожелания пользователя исключительно к комментированию этого фрагмента видео.
Данные указания пользователя имеют АБСОЛЮТНЫЙ И НАИВЫСШИЙ ПРИОРИТЕТ над любыми общими правилами. Вы обязаны строго следовать им:
\"\"\"
{frag_prompt_clean}
\"\"\""""
            else:
                user_wishes_str = "ПОЖЕЛАНИЯ ПОЛЬЗОВАТЕЛЯ К ФРАГМЕНТУ:\nПользователь не указал особых инструкций к этому фрагменту. Строго следуйте стандартным профессиональным правилам тифлокомментирования."

            prompt = f"""
КОНТЕКСТ ВЫДЕЛЕННОГО ФРАГМЕНТА:
- Временной интервал фрагмента в полном фильме: от {start_str} до {end_str} (длительность: {frag_dur_sec:.1f} сек)
- Модель выполняет целевое комментирование (или повторное комментирование) данного участка фильма с соблюдением стиля и имен персонажей.

{user_wishes_str}

СПИСОК УЖЕ ИЗВЕСТНЫХ ПЕРСОНАЖЕЙ ИЗ ФИЛЬМА:
{chars_context}

ЗАДАЧА:
1. Тщательно проанализируйте видео и звук предоставленного выделенного фрагмента.
2. Проверьте статус видео и аудио потоков.
3. Дополните карточки персонажей новыми героями или уточните существующие (с указанием таймкода внутри текущего файла в виде строки "ЧЧ:ММ:СС.ммм", например "00:00:05.500", для захвата качественного скриншота лица).
4. Создайте хронологические тифлокомментарии к данному фрагменту с обязательным указанием start_time и end_time в виде строки "ЧЧ:ММ:СС.ммм" (например, "00:00:02.100", "00:00:15.400"). Все таймкоды строго отсчитываются от начала предоставленного видеофайла (00:00:00.000). Запрещено соединять минуты и секунды в единое число! Не перекрывайте речь героев фильма!
5. Если звучит иностранная речь без русского перевода — переведите её в комментарии (тип translated_speech).
6. Если появляются титры, субтитры или надписи — озвучьте их и переведите на русский язык.
7. Неукоснительно учитывайте все пожелания пользователя к данному фрагменту, обладающие высшим приоритетом.

Верните ответ строго в формате JSON:
{{
  "diagnostics": {{
    "video_status": "ok", // или "missing" / "corrupted"
    "audio_status": "ok", // или "missing"
    "language_detected": "ru",
    "commentary_allowed": true,
    "warning_message": ""
  }},
  "characters": [
    {{
      "id": "char_...",
      "name": "Имя или описание роли",
      "role": "Роль",
      "description": "Визуальное описание внешности и одежды",
      "frame_timestamp": "00:00:05.500"
    }}
  ],
  "commentaries": [
    {{
      "id": "comm_...",
      "start_time": "00:00:02.100",
      "end_time": "00:00:06.500",
      "type": "commentary", // "commentary" | "title" | "subtitle" | "translated_speech"
      "text": "Текст тифлокомментария на чистом русском языке",
      "visual_description": "Краткое техническое описание визуального действия"
    }}
  ]
}}
"""
            if progress_callback:
                progress_callback(f"Запрос анализа фрагмента в модель {model_name}...")

            model = genai.GenerativeModel(
                model_name=model_name,
                system_instruction=SYSTEM_INSTRUCTION_TIFLO,
                generation_config={
                    "response_mime_type": "application/json",
                    "max_output_tokens": 65536
                }
            )

            response = model.generate_content([uploaded_file, prompt])
            _record_token_usage(model_name, response)
            raw_text = response.text.strip()

            if raw_text.startswith("```json"):
                raw_text = raw_text[7:]
            if raw_text.startswith("```"):
                raw_text = raw_text[3:]
            if raw_text.endswith("```"):
                raw_text = raw_text[:-3]

            parsed_data = json.loads(raw_text.strip())
            return parsed_data

        finally:
            if uploaded_file:
                try:
                    genai.delete_file(uploaded_file.name)
                except Exception:
                    pass


    def synthesize_speech(
        self,
        text: str,
        output_wav_path: str,
        voice_name: str = "Puck",
        model_name: str = "gemini-3.1-flash-tts-preview"
    ) -> bool:
        """
        Синтезирует речь с помощью модели Gemini TTS и сохраняет в WAV файл.
        """
        if not self.api_key:
            raise ValueError("API-ключ Gemini не задан!")

        from core.proxy_manager import ensure_proxy_configured
        ensure_proxy_configured()

        os.makedirs(os.path.dirname(os.path.abspath(output_wav_path)), exist_ok=True)

        try:
            model = genai.GenerativeModel(model_name=model_name)
            prompt = f"Please read the following Russian audio description text clearly and expressively with high quality:\n{text}"

            gen_config = {
                "response_modalities": ["AUDIO"],
                "speech_config": {
                    "voice_config": {
                        "prebuilt_voice_config": {
                            "voice_name": voice_name or "Puck"
                        }
                    }
                }
            }

            response = model.generate_content(prompt, generation_config=gen_config)
            _record_token_usage(model_name, response)

            for candidate in response.candidates:
                for part in candidate.content.parts:
                    if hasattr(part, "inline_data") and part.inline_data:
                        audio_data = part.inline_data.data
                        # Сохраняем PCM в стандартный WAV файл
                        try:
                            with wave.open(output_wav_path, "wb") as wav_file:
                                wav_file.setnchannels(1)
                                wav_file.setsampwidth(2)  # 16 бит
                                wav_file.setframerate(24000)
                                wav_file.writeframes(audio_data)
                            return True
                        except Exception as wav_err:
                            print(f"Предупреждение при записи wave: {wav_err}, попытка через FFmpeg...")
                            temp_audio = output_wav_path + ".temp"
                            with open(temp_audio, "wb") as f:
                                f.write(audio_data)
                            from core.app_paths import get_ffmpeg_path
                            import subprocess
                            ffmpeg = get_ffmpeg_path()
                            cmd = [ffmpeg, "-y", "-i", temp_audio, "-ar", "44100", "-ac", "2", output_wav_path]
                            startupinfo = None
                            if os.name == 'nt':
                                startupinfo = subprocess.STARTUPINFO()
                                startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW
                            subprocess.run(cmd, startupinfo=startupinfo, check=True)
                            if os.path.exists(temp_audio):
                                os.remove(temp_audio)
                            return True

            return False
        except Exception as e:
            err_str = str(e)
            print(f"Ошибка Gemini TTS синтеза: {err_str}")
            if "User location is not supported" in err_str or "location" in err_str.lower():
                raise RuntimeError(
                    "Google Gemini недоступен для прямого подключения в вашем регионе.\n"
                    "Пожалуйста, проверьте настройки прокси-сервера (Настройки -> Сеть и Прокси)."
                ) from e
            return False


