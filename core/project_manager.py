# -*- coding: utf-8 -*-
"""
Модуль управления проектами тифлокомментирования.
Каждый проект хранится в отдельной подпапке в каталоге Projects/.
"""

import os
import json
import shutil
import time
import math
import glob
from typing import Dict, List, Any, Optional
from core.app_paths import get_projects_dir


def resolve_commentary_overlaps(commentaries: List[Dict[str, Any]], moved_comm_id: Optional[str] = None) -> bool:
    """
    Устраняет любые наложения комментариев во времени:
    Если следующий комментарий должен начаться до окончания предыдущего,
    он автоматически сдвигается сразу после окончания предыдущего.
    Никакое аудио не обрезается.
    moved_comm_id получает наивысший приоритет при совпадении начального времени.
    Возвращает True, если было произведено хотя бы одно смещение.
    """
    if not commentaries or len(commentaries) < 2:
        return False

    def sort_key(c):
        st = float(c.get("start_time", 0.0))
        is_moved = 0 if (moved_comm_id and c.get("id") == moved_comm_id) else 1
        return (st, is_moved)

    # Сортируем по времени начала с учетом приоритета перемещенного комментария
    commentaries.sort(key=sort_key)

    changed = False
    for i in range(len(commentaries) - 1):
        curr_comm = commentaries[i]
        next_comm = commentaries[i + 1]

        curr_end = float(curr_comm.get("end_time", 0.0))
        next_start = float(next_comm.get("start_time", 0.0))
        next_end = float(next_comm.get("end_time", next_start + 2.0))
        next_dur = max(0.2, round(next_end - next_start, 3))

        if next_start < curr_end:
            # Следующий комментарий перекрывается текущим — сдвигаем его встык
            new_next_start = round(curr_end, 3)
            new_next_end = round(new_next_start + next_dur, 3)
            next_comm["start_time"] = new_next_start
            next_comm["end_time"] = new_next_end
            next_comm["duration_sec"] = next_dur
            changed = True

    return changed


class Project:
    """Класс, инкапсулирующий структуру и данные отдельного проекта."""

    def __init__(self, name: str, folder_path: str, data: Dict[str, Any] = None):
        self.name = name
        self.folder_path = folder_path
        self.parts_dir = os.path.join(folder_path, "parts")
        self.characters_dir = os.path.join(folder_path, "characters")
        self.audio_dir = os.path.join(folder_path, "audio")
        self.output_dir = os.path.join(folder_path, "output")
        self.project_file = os.path.join(folder_path, "project.json")

        self.data: Dict[str, Any] = data or {
            "name": name,
            "created_at": time.time(),
            "updated_at": time.time(),
            "src_video_path": "",
            "source_video_rel": "",
            "total_duration_sec": 0.0,
            "chunk_duration_minutes": 50,
            "status": "created",
            "current_chunk_index": 0,
            "user_prompt": "",
            "chunks": [],
            "characters": [],
            "commentaries": []
        }

    def save(self):
        """Сохраняет состояние проекта в project.json."""
        self.data["updated_at"] = time.time()
        os.makedirs(self.folder_path, exist_ok=True)
        os.makedirs(self.parts_dir, exist_ok=True)
        os.makedirs(self.characters_dir, exist_ok=True)
        os.makedirs(self.audio_dir, exist_ok=True)
        os.makedirs(self.output_dir, exist_ok=True)

        with open(self.project_file, "w", encoding="utf-8") as f:
            json.dump(self.data, f, ensure_ascii=False, indent=2)

    @classmethod
    def load(cls, project_folder: str) -> Optional['Project']:
        """Загружает проект из указанной папки с нормализацией путей."""
        project_file = os.path.join(project_folder, "project.json")
        if not os.path.isfile(project_file):
            return None
        try:
            with open(project_file, "r", encoding="utf-8") as f:
                data = json.load(f)
            name = data.get("name", os.path.basename(project_folder))
            proj = cls(name, project_folder, data)
            needs_save = False

            # Нормализация пути к исходному видеофайлу
            src_video = proj.data.get("src_video_path", "")
            rel_video = proj.data.get("source_video_rel", "")
            if rel_video:
                expected_src = os.path.join(project_folder, rel_video)
                if os.path.isfile(expected_src) and (not src_video or not os.path.isfile(src_video) or src_video != expected_src):
                    proj.data["src_video_path"] = expected_src
                    needs_save = True
            elif not src_video or not os.path.isfile(src_video):
                # Поиск локального source_video.* в папке проекта
                potential = glob.glob(os.path.join(project_folder, "source_video.*"))
                if potential and os.path.isfile(potential[0]):
                    proj.data["src_video_path"] = potential[0]
                    proj.data["source_video_rel"] = os.path.basename(potential[0])
                    needs_save = True

            # Автонормализация медиаконтейнера в эталонный MP4 (H.264 / AAC / FastStart)
            cur_video = proj.data.get("src_video_path", "")
            if cur_video and os.path.isfile(cur_video):
                cur_ext = os.path.splitext(cur_video)[1].lower()
                target_mp4 = os.path.join(project_folder, "source_video.mp4")
                if cur_ext != ".mp4" and cur_video != target_mp4:
                    try:
                        from core.video_splitter import normalize_video_container, analyze_media
                        norm_ok = True
                        if not (os.path.isfile(target_mp4) and os.path.getsize(target_mp4) > 0):
                            norm_ok = normalize_video_container(cur_video, target_mp4)
                        if norm_ok and os.path.isfile(target_mp4):
                            proj.data["src_video_path"] = target_mp4
                            proj.data["source_video_rel"] = "source_video.mp4"
                            needs_save = True
                            media_info = analyze_media(target_mp4)
                            if media_info.duration > 0:
                                proj.data["total_duration_sec"] = round(media_info.duration, 3)
                    except Exception as e:
                        print(f"Предупреждение при автонормализации видео проекта {name}: {e}")

            # Нормализация путей нарезанных частей
            for chunk in proj.data.get("chunks", []):
                fn = chunk.get("filename")
                if fn:
                    expected_chunk = os.path.join(proj.parts_dir, fn)
                    if os.path.isfile(expected_chunk) and chunk.get("filepath") != expected_chunk:
                        chunk["filepath"] = expected_chunk
                        needs_save = True

            # Нормализация путей аудиофайлов на случай переноса каталога проекта
            for c in proj.commentaries:
                cid = c.get("id")
                if not cid:
                    continue
                expected_af = os.path.join(proj.audio_dir, f"{cid}.wav")
                af = c.get("audio_file")
                if (not af or not os.path.isfile(af)) and os.path.isfile(expected_af):
                    c["audio_file"] = expected_af
                    needs_save = True

                expected_rf = os.path.join(proj.audio_dir, f"{cid}_raw.wav")
                rf = c.get("raw_audio_file")
                if (not rf or not os.path.isfile(rf)) and os.path.isfile(expected_rf):
                    c["raw_audio_file"] = expected_rf
                    needs_save = True

            if needs_save:
                proj.save()

            return proj
        except Exception as e:
            print(f"Ошибка загрузки проекта {project_folder}: {e}")
            return None

    @property
    def commentaries(self) -> List[Dict[str, Any]]:
        return self.data.get("commentaries", [])

    @property
    def characters(self) -> List[Dict[str, Any]]:
        return self.data.get("characters", [])

    @property
    def chunks(self) -> List[Dict[str, Any]]:
        return self.data.get("chunks", [])

    @property
    def user_prompt(self) -> str:
        return self.data.get("user_prompt", "")

    @user_prompt.setter
    def user_prompt(self, value: str):
        self.data["user_prompt"] = str(value or "").strip()


    @property
    def video_path(self) -> str:
        """Возвращает актуальный абсолютный путь к видеофайлу проекта."""
        src_path = self.data.get("src_video_path", "")
        if src_path and os.path.isfile(src_path):
            return src_path
        target_mp4 = os.path.join(self.folder_path, "source_video.mp4")
        if os.path.isfile(target_mp4):
            return target_mp4
        if self.data.get("source_video_rel"):
            rel_path = os.path.join(self.folder_path, self.data["source_video_rel"])
            if os.path.isfile(rel_path):
                return rel_path
        return ""

    def add_or_update_character(self, char_dict: Dict[str, Any]):
        """Добавляет или обновляет карточку персонажа с сохранением существующих изображений."""
        char_id = char_dict.get("id") or char_dict.get("character_id")
        name = (char_dict.get("name") or "").strip().lower()
        existing = next(
            (c for c in self.data["characters"] if (
                (char_id and c.get("id") == char_id) or
                (name and (c.get("name") or "").strip().lower() == name)
            )),
            None
        )
        if existing:
            # Бережно объединяем изображения без перезаписи
            merged_images = list(existing.get("images", []))
            for img in char_dict.get("images", []):
                if img not in merged_images:
                    merged_images.append(img)

            existing.update(char_dict)
            existing["images"] = merged_images
            if "character_id" in existing and "id" not in existing:
                existing["id"] = existing["character_id"]
        else:
            if "id" not in char_dict and "character_id" in char_dict:
                char_dict["id"] = char_dict["character_id"]
            if "id" not in char_dict or not char_dict["id"]:
                char_dict["id"] = f"char_{len(self.data['characters']) + 1:03d}"
            if "images" not in char_dict:
                char_dict["images"] = []
            self.data["characters"].append(char_dict)

    def resolve_overlaps(self, moved_comm_id: Optional[str] = None) -> bool:
        """Устраняет временные наложения между комментариями проекта."""
        comms = self.data.get("commentaries", [])
        changed = resolve_commentary_overlaps(comms, moved_comm_id=moved_comm_id)
        if changed:
            self.save()
        return changed

    def add_commentaries(self, new_comments: List[Dict[str, Any]]):
        """Добавляет новые комментарии в хронологическом порядке и устраняет наложения."""
        self.data.setdefault("commentaries", [])
        existing_ids = {c.get("id") for c in self.data["commentaries"] if c.get("id")}
        idx = len(self.data["commentaries"]) + 1

        for comm in new_comments:
            # Убедимся, что у комментария есть уникальный id
            if "id" not in comm or not comm["id"] or comm["id"] in existing_ids:
                new_id = f"comm_{idx:04d}"
                while new_id in existing_ids:
                    idx += 1
                    new_id = f"comm_{idx:04d}"
                comm["id"] = new_id
                idx += 1
            existing_ids.add(comm["id"])

            # Проверяем нет ли дубликата
            if not any(c.get("id") == comm["id"] for c in self.data["commentaries"]):
                self.data["commentaries"].append(comm)

        self.resolve_overlaps()
        self.save()

    def replace_commentaries(self, new_comments: List[Dict[str, Any]]):
        """Заменяет все комментарии проекта на новый список с генерацией уникальных ID."""
        self.data["commentaries"] = []
        for idx, comm in enumerate(new_comments, start=1):
            if "id" not in comm or not comm["id"]:
                comm["id"] = f"comm_{idx:04d}"
            self.data["commentaries"].append(comm)
        self.resolve_overlaps()
        self.save()

    def update_commentary(self, comm_id: str, new_text: Optional[str] = None, start_time: Optional[float] = None, end_time: Optional[float] = None):
        """Обновляет текст или таймкоды конкретного комментария."""
        for comm in self.data["commentaries"]:
            if comm.get("id") == comm_id:
                if new_text is not None and new_text != comm.get("text"):
                    comm["text"] = new_text
                    comm["audio_needs_rebuild"] = True
                    for key in ("audio_file", "raw_audio_file"):
                        p = comm.get(key)
                        if p and os.path.isfile(p):
                            try:
                                os.remove(p)
                            except Exception:
                                pass
                        comm[key] = None
                if start_time is not None:
                    comm["start_time"] = round(start_time, 3)
                if end_time is not None:
                    comm["end_time"] = round(end_time, 3)
                st = float(comm.get("start_time", 0.0))
                et = float(comm.get("end_time", st + 2.0))
                comm["duration_sec"] = round(et - st, 3)
                break
        self.resolve_overlaps()
        self.save()

    def reset_for_full_regeneration(self):
        """
        Полностью очищает все существующие тифлокомментарии и сбрасывает статус частей видео
        для повторной генерации с первой части.
        Карточки персонажей и пожелания пользователя сохраняются.
        """
        # Удаляем аудиофайлы комментариев
        for comm in self.data.get("commentaries", []):
            for key in ("audio_file", "raw_audio_file"):
                audio_path = comm.get(key)
                if audio_path and os.path.isfile(audio_path):
                    try:
                        os.remove(audio_path)
                    except Exception:
                        pass

        # Удаляем мастер-аудио, если существует
        master_audio = os.path.join(self.output_dir, "preview_master_audio.wav")
        if os.path.isfile(master_audio):
            try:
                os.remove(master_audio)
            except Exception:
                pass

        # Очищаем комментарии
        self.data["commentaries"] = []

        # Сбрасываем обработку частей видео
        for chunk in self.data.get("chunks", []):
            chunk["processed"] = False

        self.data["current_chunk_index"] = 0
        self.data["status"] = "created"
        self.save()



class ProjectManager:
    """Класс для управления каталогом всех проектов."""

    def __init__(self, projects_dir: str = None):
        self.projects_dir = projects_dir or get_projects_dir()
        os.makedirs(self.projects_dir, exist_ok=True)

    def list_projects(self) -> List[Dict[str, Any]]:
        """Возвращает список всех доступных проектов."""
        projects = []
        if not os.path.exists(self.projects_dir):
            return projects

        for item in os.listdir(self.projects_dir):
            folder = os.path.join(self.projects_dir, item)
            if os.path.isdir(folder):
                proj_json = os.path.join(folder, "project.json")
                if os.path.isfile(proj_json):
                    try:
                        with open(proj_json, "r", encoding="utf-8") as f:
                            data = json.load(f)

                        chunks_list = data.get("chunks", [])
                        total_dur = float(data.get("total_duration_sec", 0.0))
                        chunk_min = float(data.get("chunk_duration_minutes", 50))

                        if chunks_list:
                            total_chunks = max(1, len(chunks_list))
                            completed_chunks = sum(1 for c in chunks_list if c.get("processed"))
                        else:
                            if total_dur > 0 and chunk_min > 0:
                                total_chunks = max(1, math.ceil(total_dur / (chunk_min * 60.0)))
                            else:
                                total_chunks = 1
                            completed_chunks = 0

                        projects.append({
                            "name": data.get("name", item),
                            "folder": folder,
                            "created_at": data.get("created_at", 0),
                            "updated_at": data.get("updated_at", 0),
                            "status": data.get("status", "created"),
                            "commentaries_count": len(data.get("commentaries", [])),
                            "characters_count": len(data.get("characters", [])),
                            "total_chunks": total_chunks,
                            "completed_chunks": completed_chunks
                        })
                    except Exception as e:
                        print(f"Ошибка чтения проекта {item}: {e}")
        # Сортировка по времени последнего обновления
        projects.sort(key=lambda x: x.get("updated_at", 0), reverse=True)
        return projects

    def create_project(
        self,
        project_name: str,
        src_video_path: str,
        chunk_duration_min: int = 50,
        custom_ffprobe: str = "",
        custom_ffmpeg: str = ""
    ) -> Project:
        """
        Создает новый проект с чистой структурой папок.
        Переупаковывает/нормализует исходный видеофайл в современный MKV без перекодировки видеодорожки
        и нормализует звук в AAC 48кГц для предотвращения любых проблем с рассинхронизацией.
        """
        # Очищаем имя от недопустимых символов
        safe_name = "".join(c for c in project_name if c.isalnum() or c in (' ', '_', '-', '.')).strip()
        if not safe_name:
            safe_name = f"Project_{int(time.time())}"

        folder_path = os.path.join(self.projects_dir, safe_name)
        # Если папка существует, добавляем суффикс
        if os.path.exists(folder_path):
            folder_path = os.path.join(self.projects_dir, f"{safe_name}_{int(time.time())}")

        os.makedirs(folder_path, exist_ok=True)
        proj = Project(project_name, folder_path)
        proj.data["chunk_duration_minutes"] = chunk_duration_min

        # Нормализация исходного видеофайла в папку проекта (MP4, H.264/AAC/FastStart)
        if src_video_path and os.path.isfile(src_video_path):
            dest_video_name = "source_video.mp4"
            dest_video_path = os.path.join(folder_path, dest_video_name)

            norm_ok = False
            try:
                from core.video_splitter import normalize_video_container
                norm_ok = normalize_video_container(
                    input_path=src_video_path,
                    output_path=dest_video_path,
                    custom_ffmpeg=custom_ffmpeg,
                    custom_ffprobe=custom_ffprobe
                )
            except Exception as e:
                print(f"Предупреждение при нормализации видео {src_video_path}: {e}")

            if not norm_ok or not os.path.isfile(dest_video_path):
                # Fallback: прямое копирование если FFmpeg не сработал
                ext = os.path.splitext(src_video_path)[1]
                if not ext:
                    ext = ".mp4"
                dest_video_name = f"source_video{ext}"
                dest_video_path = os.path.join(folder_path, dest_video_name)
                if os.path.abspath(src_video_path) != os.path.abspath(dest_video_path):
                    shutil.copy2(src_video_path, dest_video_path)

            proj.data["src_video_path"] = dest_video_path
            proj.data["source_video_rel"] = dest_video_name
            proj.data["original_src_path"] = src_video_path

            # Сразу определяем длительность видео
            try:
                from core.video_splitter import analyze_media
                media_info = analyze_media(dest_video_path, custom_ffprobe)
                if media_info.duration > 0:
                    proj.data["total_duration_sec"] = round(media_info.duration, 3)
            except Exception as e:
                print(f"Ошибка предварительного анализа видео: {e}")
        else:
            proj.data["src_video_path"] = src_video_path

        proj.save()
        return proj

    def open_project(self, project_name_or_folder: str) -> Optional[Project]:
        """Открывает проект по имени или пути."""
        if os.path.isdir(project_name_or_folder):
            return Project.load(project_name_or_folder)

        folder_path = os.path.join(self.projects_dir, project_name_or_folder)
        if os.path.isdir(folder_path):
            return Project.load(folder_path)
        return None

    def delete_project(self, project_name_or_folder: str) -> bool:
        """Удаляет проект и все его файлы."""
        folder_path = project_name_or_folder
        if not os.path.isabs(folder_path):
            folder_path = os.path.join(self.projects_dir, project_name_or_folder)

        if os.path.exists(folder_path):
            import gc
            import time
            gc.collect()

            last_err = None
            for attempt in range(5):
                try:
                    shutil.rmtree(folder_path)
                    return True
                except Exception as e:
                    last_err = e
                    gc.collect()
                    time.sleep(0.15)

            print(f"Ошибка удаления проекта {folder_path}: {last_err}")
            return False
        return False

