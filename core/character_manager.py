# -*- coding: utf-8 -*-
"""
Модуль управления карточками героев (персонажей фильма) и их скриншотами.
Обеспечивает полный CRUD для персонажей, захват кадров из видео,
удаление и добавление скриншотов, а также экспорт и импорт базы персонажей.
"""

import os
import json
import shutil
import zipfile
import time
from typing import Dict, List, Any, Optional, Tuple
from core.video_splitter import extract_frame_screenshot


class CharacterManager:
    """Управляет карточками персонажей проекта, скриншотами, экспортом и импортом."""

    def __init__(self, project):
        self.project = project

    def get_character_by_id(self, char_id: str) -> Optional[Dict[str, Any]]:
        """Ищет персонажа в проекте по его идентификатору."""
        for c in self.project.characters:
            if c.get("id") == char_id:
                return c
        return None

    def add_character(
        self,
        name: str,
        role: str = "",
        description: str = "",
        images: Optional[List[str]] = None
    ) -> Dict[str, Any]:
        """Создает нового персонажа с уникальным ID и сохраняет проект."""
        existing_ids = {c.get("id") for c in self.project.characters if c.get("id")}
        idx = len(self.project.characters) + 1
        new_id = f"char_{idx:03d}"
        while new_id in existing_ids:
            idx += 1
            new_id = f"char_{idx:03d}"

        new_char = {
            "id": new_id,
            "name": str(name or "").strip() or "Новый персонаж",
            "role": str(role or "").strip(),
            "description": str(description or "").strip(),
            "images": list(images) if images else []
        }

        self.project.data.setdefault("characters", []).append(new_char)
        self.project.save()
        return new_char

    def update_character(
        self,
        char_id: str,
        name: Optional[str] = None,
        role: Optional[str] = None,
        description: Optional[str] = None
    ) -> bool:
        """Обновляет имя, роль или описание персонажа."""
        char = self.get_character_by_id(char_id)
        if not char:
            return False

        if name is not None:
            char["name"] = str(name).strip()
        if role is not None:
            char["role"] = str(role).strip()
        if description is not None:
            char["description"] = str(description).strip()

        self.project.save()
        return True

    def delete_character(self, char_id: str, delete_images: bool = True) -> bool:
        """Удаляет персонажа из проекта и при необходимости удаляет его файлы скриншотов."""
        char = self.get_character_by_id(char_id)
        if not char:
            return False

        if delete_images:
            for img_name in char.get("images", []):
                full_path = os.path.join(self.project.characters_dir, img_name)
                if os.path.isfile(full_path):
                    try:
                        os.remove(full_path)
                    except Exception as e:
                        print(f"Ошибка удаления скриншота {full_path}: {e}")

        self.project.data["characters"] = [
            c for c in self.project.characters if c.get("id") != char_id
        ]
        self.project.save()
        return True

    def process_detected_characters(
        self,
        characters_data: List[Dict[str, Any]],
        chunk_video_path: str,
        chunk_start_abs_sec: float
    ):
        """
        Обрабатывает персонажей, возвращенных Gemini, извлекает скриншоты и обновляет базу.
        """
        for char in characters_data:
            char_id = char.get("id") or char.get("character_id")
            if not char_id:
                char_id = f"char_{len(self.project.characters) + 1:03d}"
                char["id"] = char_id

            raw_ts = char.get("frame_timestamp_sec", char.get("frame_timestamp", char.get("best_frame_timestamp", 0.0)))
            from core.gemini_client import parse_time_to_seconds
            frame_sec = parse_time_to_seconds(raw_ts)
            char["frame_timestamp_sec"] = frame_sec

            # Формируем имя файла скриншота
            existing_char = next((c for c in self.project.characters if c.get("id") == char_id), None)
            img_index = len(existing_char.get("images", [])) + 1 if existing_char else 1
            img_filename = f"{char_id}_{img_index:02d}.jpg"
            img_filepath = os.path.join(self.project.characters_dir, img_filename)

            # Извлекаем скриншот из текущего видеофайла части
            if os.path.exists(chunk_video_path) and frame_sec >= 0:
                success = extract_frame_screenshot(chunk_video_path, frame_sec, img_filepath)
                if success:
                    if "images" not in char:
                        char["images"] = []
                    if img_filename not in char["images"]:
                        char["images"].append(img_filename)

            # Обновляем или добавляем персонажа
            self.project.add_or_update_character(char)

        self.project.save()

    def add_screenshot_from_video(
        self,
        char_id: str,
        timestamp_sec: float,
        video_path: Optional[str] = None
    ) -> Optional[str]:
        """
        Извлекает кадр из исходного видео на указанной секунде и прикрепляет к персонажу.
        Возвращает абсолютный путь к сохраненному скриншоту в случае успеха.
        """
        char = self.get_character_by_id(char_id)
        if not char:
            return None

        v_path = video_path or self.project.video_path
        if not v_path or not os.path.isfile(v_path):
            print(f"Видеофайл для извлечения кадра не найден: {v_path}")
            return None

        os.makedirs(self.project.characters_dir, exist_ok=True)

        current_images = char.get("images", [])
        img_index = len(current_images) + 1
        img_filename = f"{char_id}_{img_index:02d}.jpg"
        img_filepath = os.path.join(self.project.characters_dir, img_filename)

        while os.path.exists(img_filepath):
            img_index += 1
            img_filename = f"{char_id}_{img_index:02d}.jpg"
            img_filepath = os.path.join(self.project.characters_dir, img_filename)

        success = extract_frame_screenshot(v_path, max(0.0, timestamp_sec), img_filepath)
        if success and os.path.isfile(img_filepath) and os.path.getsize(img_filepath) > 0:
            if "images" not in char:
                char["images"] = []
            if img_filename not in char["images"]:
                char["images"].append(img_filename)
            self.project.save()
            return img_filepath

        return None

    def add_screenshot_from_file(self, char_id: str, source_file_path: str) -> Optional[str]:
        """Копирует изображение из внешнего файла в галерею персонажа."""
        char = self.get_character_by_id(char_id)
        if not char or not source_file_path or not os.path.isfile(source_file_path):
            return None

        os.makedirs(self.project.characters_dir, exist_ok=True)

        ext = os.path.splitext(source_file_path)[1].lower()
        if ext not in (".jpg", ".jpeg", ".png", ".webp", ".bmp"):
            ext = ".jpg"

        current_images = char.get("images", [])
        img_index = len(current_images) + 1
        img_filename = f"{char_id}_{img_index:02d}{ext}"
        img_filepath = os.path.join(self.project.characters_dir, img_filename)

        while os.path.exists(img_filepath):
            img_index += 1
            img_filename = f"{char_id}_{img_index:02d}{ext}"
            img_filepath = os.path.join(self.project.characters_dir, img_filename)

        try:
            shutil.copy2(source_file_path, img_filepath)
            if "images" not in char:
                char["images"] = []
            if img_filename not in char["images"]:
                char["images"].append(img_filename)
            self.project.save()
            return img_filepath
        except Exception as e:
            print(f"Ошибка копирования скриншота: {e}")
            return None

    def delete_screenshot(self, char_id: str, image_filename_or_path: str) -> bool:
        """Удаляет конкретный скриншот у персонажа и удаляет соответствующий файл."""
        char = self.get_character_by_id(char_id)
        if not char:
            return False

        filename = os.path.basename(image_filename_or_path)
        images = char.get("images", [])
        if filename in images:
            images.remove(filename)
            char["images"] = images

            full_path = os.path.join(self.project.characters_dir, filename)
            if os.path.isfile(full_path):
                try:
                    os.remove(full_path)
                except Exception as e:
                    print(f"Ошибка удаления файла кадра {full_path}: {e}")

            self.project.save()
            return True

        return False

    def get_character_images(self, character: Dict[str, Any]) -> List[str]:
        """Возвращает полные пути к существующим скриншотам персонажа."""
        images = []
        for img_name in character.get("images", []):
            full_path = os.path.join(self.project.characters_dir, img_name)
            if os.path.isfile(full_path):
                images.append(full_path)
        return images

    def export_characters_package(self, target_path: str) -> bool:
        """
        Экспортирует базу персонажей:
        - В ZIP-пакет (*.zip, *.tiflochars) со всеми файлами скриншотов.
        - В JSON-файл (*.json) с метаданными.
        """
        if not target_path:
            return False

        try:
            os.makedirs(os.path.dirname(os.path.abspath(target_path)), exist_ok=True)
            export_payload = {
                "format": "tiflocommentator_characters_package",
                "version": "1.0",
                "exported_at": time.time(),
                "project_name": self.project.name,
                "characters": self.project.characters
            }

            if target_path.lower().endswith(".json"):
                with open(target_path, "w", encoding="utf-8") as f:
                    json.dump(export_payload, f, ensure_ascii=False, indent=2)
                return True

            with zipfile.ZipFile(target_path, "w", zipfile.ZIP_DEFLATED) as zf:
                json_bytes = json.dumps(export_payload, ensure_ascii=False, indent=2).encode("utf-8")
                zf.writestr("characters.json", json_bytes)

                for char in self.project.characters:
                    for img_name in char.get("images", []):
                        img_full = os.path.join(self.project.characters_dir, img_name)
                        if os.path.isfile(img_full):
                            zf.write(img_full, arcname=f"images/{img_name}")

            return os.path.isfile(target_path) and os.path.getsize(target_path) > 0
        except Exception as e:
            print(f"Ошибка при экспорте персонажей в {target_path}: {e}")
            return False

    def import_characters_package(self, source_path: str) -> Tuple[int, int]:
        """
        Импортирует персонажей из ZIP-пакета или JSON-файла.
        СУЩЕСТВУЮЩИЙ СПИСОК ДОПОЛНЯЕТСЯ И ОБОГАЩАЕТСЯ (НЕ ПЕРЕЗАПИСЫВАЕТСЯ).
        Возвращает кортеж (число_добавленных_новых, число_дополненных_существующих).
        """
        if not source_path or not os.path.isfile(source_path):
            return 0, 0

        added_count = 0
        updated_count = 0
        imported_chars: List[Dict[str, Any]] = []

        try:
            os.makedirs(self.project.characters_dir, exist_ok=True)

            if zipfile.is_zipfile(source_path):
                with zipfile.ZipFile(source_path, "r") as zf:
                    manifest_name = next(
                        (n for n in zf.namelist() if n.lower().endswith("characters.json")),
                        None
                    )
                    if manifest_name:
                        content = zf.read(manifest_name).decode("utf-8", errors="replace")
                        parsed = json.loads(content)
                        if isinstance(parsed, dict) and "characters" in parsed:
                            imported_chars = parsed["characters"]
                        elif isinstance(parsed, list):
                            imported_chars = parsed

                    for name in zf.namelist():
                        if name.startswith("images/") and not name.endswith("/"):
                            fn = os.path.basename(name)
                            if fn:
                                target_img_path = os.path.join(self.project.characters_dir, fn)
                                if not os.path.exists(target_img_path):
                                    with open(target_img_path, "wb") as f_out:
                                        f_out.write(zf.read(name))
            else:
                with open(source_path, "r", encoding="utf-8") as f:
                    parsed = json.load(f)
                    if isinstance(parsed, dict) and "characters" in parsed:
                        imported_chars = parsed["characters"]
                    elif isinstance(parsed, list):
                        imported_chars = parsed

            if not imported_chars:
                return 0, 0

            for imp_char in imported_chars:
                imp_id = imp_char.get("id") or imp_char.get("character_id")
                imp_name = (imp_char.get("name") or "").strip()
                imp_role = (imp_char.get("role") or "").strip()
                imp_desc = (imp_char.get("description") or "").strip()
                imp_imgs = imp_char.get("images", [])

                if not imp_name and not imp_id:
                    continue

                existing = None
                if imp_name:
                    existing = next(
                        (c for c in self.project.characters if (c.get("name") or "").strip().lower() == imp_name.lower()),
                        None
                    )
                if not existing and imp_id:
                    existing = self.get_character_by_id(imp_id)

                if existing:
                    if imp_role and not existing.get("role"):
                        existing["role"] = imp_role
                    if imp_desc and not existing.get("description"):
                        existing["description"] = imp_desc
                    elif imp_desc and existing.get("description") and imp_desc not in existing.get("description"):
                        existing["description"] = f"{existing['description']}\n\n[Доп. из импорта]: {imp_desc}".strip()

                    cur_imgs = existing.get("images", [])
                    for img in imp_imgs:
                        if img not in cur_imgs:
                            cur_imgs.append(img)
                    existing["images"] = cur_imgs

                    updated_count += 1
                else:
                    self.add_character(
                        name=imp_name or "Импортированный персонаж",
                        role=imp_role,
                        description=imp_desc,
                        images=imp_imgs
                    )
                    added_count += 1

            self.project.save()
            return added_count, updated_count

        except Exception as e:
            print(f"Ошибка при импорте персонажей из {source_path}: {e}")
            return added_count, updated_count



