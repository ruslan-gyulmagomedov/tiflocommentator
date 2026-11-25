# -*- coding: utf-8 -*-
"""
Движок синтеза речи: SAPI5 и Gemini TTS.
Осуществляет генерацию речи, измерение длительности и адаптивное ускорение без изменения тона.
"""

import os
import time
import shutil
from typing import List, Dict, Any, Optional, Callable
import win32com.client
from core.audio_dsp import get_audio_duration_sec, time_stretch_audio


class SAPI5Engine:
    """Обертка над системным синтезатором Microsoft Speech API 5."""

    _preview_speaker = None

    @staticmethod
    def _apply_voice(speaker, voice_name: str):
        """Устанавливает выбранный голос синтезатора, если он задан и найден среди доступных в системе."""
        if not voice_name:
            return
        voice_clean = voice_name.strip().lower()
        try:
            voices = speaker.GetVoices()
            # 1. Поиск по точному совпадению имени или ID
            for i in range(voices.Count):
                v = voices.Item(i)
                desc = v.GetDescription().strip().lower()
                vid = getattr(v, "Id", "").strip().lower()
                if voice_clean == desc or voice_clean == vid:
                    speaker.Voice = v
                    return
            # 2. Поиск по вхождению подстроки
            for i in range(voices.Count):
                v = voices.Item(i)
                desc = v.GetDescription().strip().lower()
                if voice_clean in desc or desc in voice_clean:
                    speaker.Voice = v
                    return
        except Exception as e:
            print(f"Предупреждение при выборе голоса SAPI5 '{voice_name}': {e}")

    @classmethod
    def get_installed_voices(cls) -> List[Dict[str, str]]:
        """Возвращает динамический список всех установленных в системе SAPI5 голосов."""
        voices_list = []
        try:
            import pythoncom
            pythoncom.CoInitialize()
        except Exception:
            pass

        try:
            speaker = win32com.client.Dispatch("SAPI.SpVoice")
            voices = speaker.GetVoices()
            for i in range(voices.Count):
                v = voices.Item(i)
                desc = v.GetDescription()
                voice_id = getattr(v, "Id", "")
                voices_list.append({
                    "index": i,
                    "name": desc,
                    "description": desc,
                    "id": voice_id
                })
        except Exception as e:
            print(f"Ошибка получения SAPI5 голосов: {e}")
        return voices_list

    @classmethod
    def stop_preview(cls):
        """Останавливает текущее воспроизведение примера звучания SAPI5."""
        try:
            if cls._preview_speaker is not None:
                # 1 = SVSFlagsAsync, 2 = SVSFPurgeBeforeSpeak
                cls._preview_speaker.Speak("", 1 | 2)
        except Exception as e:
            print(f"Предупреждение при остановке SAPI5: {e}")

    @classmethod
    def preview_voice(
        cls,
        voice_name: str = "",
        rate: int = 0,
        volume: int = 100,
        text: str = "Это пример звучания выбранного голоса синтезатора речи."
    ):
        """Воспроизводит тестовую фразу в динамики без блокировки UI."""
        try:
            import pythoncom
            pythoncom.CoInitialize()
        except Exception:
            pass

        try:
            if cls._preview_speaker is None:
                cls._preview_speaker = win32com.client.Dispatch("SAPI.SpVoice")

            cls._apply_voice(cls._preview_speaker, voice_name)
            cls._preview_speaker.Rate = max(-10, min(10, int(rate)))
            cls._preview_speaker.Volume = max(0, min(100, int(volume)))
            # 1 = SVSFlagsAsync, 2 = SVSFPurgeBeforeSpeak (прерывает предыдущую речь и синтезирует заново)
            cls._preview_speaker.Speak(text, 1 | 2)
        except Exception as e:
            print(f"Ошибка воспроизведения примера SAPI5: {e}")

    @classmethod
    def synthesize_to_file(
        cls,
        text: str,
        output_wav_path: str,
        voice_name: str = "",
        rate: int = 0,
        volume: int = 100
    ) -> bool:
        """Синтезирует речь напрямую в WAV-файл."""
        os.makedirs(os.path.dirname(os.path.abspath(output_wav_path)), exist_ok=True)
        try:
            import pythoncom
            pythoncom.CoInitialize()
        except Exception:
            pass

        try:
            speaker = win32com.client.Dispatch("SAPI.SpVoice")
            file_stream = win32com.client.Dispatch("SAPI.SpFileStream")

            cls._apply_voice(speaker, voice_name)
            speaker.Rate = max(-10, min(10, int(rate)))
            speaker.Volume = max(0, min(100, int(volume)))

            # 3 = SSFMCreateForWrite
            file_stream.Open(output_wav_path, 3)
            speaker.AudioOutputStream = file_stream
            speaker.Speak(text, 0)  # 0 = SVSFDefault (синхронно)
            file_stream.Close()

            return os.path.isfile(output_wav_path) and os.path.getsize(output_wav_path) > 0
        except Exception as e:
            print(f"Ошибка SAPI5 синтеза в файл {output_wav_path}: {e}")
            return False


class TTSService:
    """Сервис высокоуровневой озвучки комментариев с контролем хронометража."""

    def __init__(self, config_manager, gemini_client=None):
        self.config = config_manager
        self.gemini_client = gemini_client
        self.last_error = ''

    def adjust_audio_for_duration(
        self,
        comment: Dict[str, Any],
        project,
        max_speedup: Optional[float] = None
    ) -> bool:
        """
        Адаптирует скорость озвучки под измененную длительность комментария на основе
        нетронутого исходного мастер-файла (raw_audio_file).
        Исключает накопление искажений при многократной смене длительности.
        """
        comm_id = comment.get("id")
        if not comm_id or not project:
            return False

        # Определяем путь к исходному мастер-файлу (raw)
        raw_path = comment.get("raw_audio_file")
        if not raw_path or not os.path.isfile(raw_path):
            expected_raw = os.path.join(project.audio_dir, f"{comm_id}_raw.wav")
            if os.path.isfile(expected_raw):
                raw_path = expected_raw
                comment["raw_audio_file"] = raw_path

        final_path = comment.get("audio_file") or os.path.join(project.audio_dir, f"{comm_id}.wav")

        # Если исходный raw_path отсутствует, но есть готовый final_path, используем его как базу
        if (not raw_path or not os.path.isfile(raw_path)) and os.path.isfile(final_path):
            raw_path = os.path.join(project.audio_dir, f"{comm_id}_raw.wav")
            try:
                shutil.copy2(final_path, raw_path)
                comment["raw_audio_file"] = raw_path
            except Exception as e:
                print(f"Предупреждение при резервировании raw-аудио: {e}")
                raw_path = final_path

        if not raw_path or not os.path.isfile(raw_path):
            return False

        raw_dur = get_audio_duration_sec(raw_path, custom_ffprobe=self.config.ffprobe_path)
        if raw_dur <= 0.0:
            return False

        comment["raw_duration_sec"] = round(raw_dur, 3)
        st = float(comment.get("start_time", 0.0))
        et = float(comment.get("end_time", st + 2.0))
        allowed_duration = max(0.2, round(et - st, 3))

        target_factor = raw_dur / allowed_duration
        limit_speedup = max_speedup if max_speedup is not None else self.config.max_speedup

        stretch_ok, effective_factor = time_stretch_audio(
            input_wav=raw_path,
            output_wav=final_path,
            target_factor=target_factor,
            max_speedup=limit_speedup,
            custom_ffmpeg=self.config.ffmpeg_path
        )

        if stretch_ok and os.path.isfile(final_path):
            comment["audio_file"] = final_path
            comment["raw_audio_file"] = raw_path
            comment["speed_factor"] = round(effective_factor, 3)
            comment["audio_needs_rebuild"] = False

            # Реальная длительность полученного ускоренного аудиофайла
            actual_audio_dur = round(raw_dur / effective_factor, 3)
            # Если реальная длительность превышает отведенный интервал (из-за лимита max_speedup),
            # расширяем end_time, чтобы аудио звучало полностью без обрезания!
            if actual_audio_dur > allowed_duration:
                comment["end_time"] = round(st + actual_audio_dur, 3)
                comment["duration_sec"] = actual_audio_dur
            else:
                comment["duration_sec"] = round(float(comment.get("end_time", st + allowed_duration)) - st, 3)

            return True

        return False

    def synthesize_single_commentary(
        self,
        comment: Dict[str, Any],
        project,
        engine_type: str = "sapi5"
    ) -> bool:
        """
        Озвучивает отдельный комментарий, сохраняет исходный мастер-файл
        и адаптирует итоговую скорость под хронометраж.
        """
        comm_id = comment.get("id", f"comm_{int(time.time()*1000)}")
        text = comment.get("text", "").strip()
        if not text:
            return False

        raw_wav_path = os.path.join(project.audio_dir, f"{comm_id}_raw.wav")
        final_wav_path = os.path.join(project.audio_dir, f"{comm_id}.wav")

        success = False
        if engine_type == "sapi5":
            success = SAPI5Engine.synthesize_to_file(
                text=text,
                output_wav_path=raw_wav_path,
                voice_name=self.config.sapi5_voice,
                rate=self.config.sapi5_rate,
                volume=self.config.sapi5_volume
            )
        elif engine_type == "gemini":
            if not self.gemini_client:
                from core.gemini_client import GeminiClient
                self.gemini_client = GeminiClient(self.config.api_key)
            success = self.gemini_client.synthesize_speech(
                text=text,
                output_wav_path=raw_wav_path,
                voice_name=self.config.gemini_tts_voice,
                model_name=self.config.gemini_tts_model
            )
            if not success:
                self.last_error = (getattr(self.gemini_client, 'last_error', '')
                                   or 'Google Gemini не вернул аудиоданные (подробности в журнале).')

        if not success or not os.path.isfile(raw_wav_path):
            return False

        comment["raw_audio_file"] = raw_wav_path
        comment["tts_engine"] = engine_type
        comment["audio_file"] = final_wav_path

        return self.adjust_audio_for_duration(comment, project)

    @staticmethod
    def delete_commentary_audio(comment: Dict[str, Any], project=None) -> bool:
        """
        Удаляет аудиофайл тифлокомментария и исходный raw-файл с диска
        только при явном запросе пользователя на удаление озвучки.
        """
        audio_path = comment.get("audio_file")
        raw_path = comment.get("raw_audio_file")
        comm_id = comment.get("id", "")
        deleted = False

        paths_to_delete = []
        if audio_path:
            paths_to_delete.append(audio_path)
        if raw_path:
            paths_to_delete.append(raw_path)

        if project and comm_id:
            paths_to_delete.append(os.path.join(project.audio_dir, f"{comm_id}_raw.wav"))
            paths_to_delete.append(os.path.join(project.audio_dir, f"{comm_id}.wav"))

        for p in set(paths_to_delete):
            if p and os.path.isfile(p):
                for _ in range(3):
                    try:
                        os.remove(p)
                        deleted = True
                        break
                    except Exception:
                        time.sleep(0.06)

        comment["audio_file"] = None
        comment["raw_audio_file"] = None
        comment["tts_engine"] = None
        comment["speed_factor"] = None
        comment["raw_duration_sec"] = None
        comment["audio_needs_rebuild"] = True
        return deleted

    def synthesize_all(
        self,
        project,
        engine_type: str = "sapi5",
        comments_to_process: Optional[List[Dict[str, Any]]] = None,
        only_pending: bool = True,
        progress_callback: Optional[Callable[[int, int, str], None]] = None,
        cancel_check: Optional[Callable[[], bool]] = None
    ) -> int:
        """
        Озвучивает комментарии в проекте.
        Если only_pending=True, озвучиваются только комментарии без готового аудио или помеченные для пересборки.
        Возвращает количество успешно озвученных реплик.
        """
        all_comms = comments_to_process if comments_to_process is not None else project.commentaries
        if only_pending:
            targets = [
                c for c in all_comms
                if c.get("audio_needs_rebuild", False)
                or not c.get("audio_file")
                or not os.path.isfile(c.get("audio_file", ""))
            ]
        else:
            targets = list(all_comms)

        total = len(targets)
        if total == 0:
            return 0

        count = 0
        pause_sec = self.config.api_request_pause_sec if engine_type == "gemini" else 0

        for idx, comm in enumerate(targets, start=1):
            if cancel_check and cancel_check():
                return count

            if idx > 1 and pause_sec > 0:
                for rem in range(pause_sec, 0, -1):
                    if cancel_check and cancel_check():
                        return count
                    if progress_callback:
                        progress_callback(idx - 1, total, f"Соблюдение лимитов Gemini API: пауза {rem} сек... ({idx}/{total})")
                    for _ in range(10):
                        if cancel_check and cancel_check():
                            return count
                        time.sleep(0.1)

            if cancel_check and cancel_check():
                return count

            if progress_callback:
                progress_callback(idx, total, f"Озвучивание ({idx}/{total}): {comm.get('text', '')[:40]}...")
            ok = self.synthesize_single_commentary(comm, project, engine_type=engine_type)
            if ok:
                count += 1
            project.save()

            if cancel_check and cancel_check():
                return count

        return count

