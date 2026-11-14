# -*- coding: utf-8 -*-
"""
Модуль для управления настройками приложения (Settings.ini).
"""

import os
import math
import configparser
from core.app_paths import get_settings_path


class ConfigManager:
    """Класс для чтения и сохранения настроек в Settings.ini."""

    DEFAULT_CONFIG = {
        "Gemini": {
            "api_key": "",
            "model": "gemini-2.5-flash",
            "tts_model": "gemini-3.1-flash-tts-preview",
            "tts_voice": "Puck",
            "chunk_duration_minutes": "50",
            "api_request_pause_sec": "20",
        },
        "SAPI5": {
            "voice": "",
            "rate": "0",
            "volume": "100",
        },
        "Audio": {
            "movie_volume_db": "0.0",
            "commentary_volume_db": "0.0",
            "movie_muted": "false",
            "commentary_muted": "false",
            "auto_ducking": "true",
            "ducking_level_db": "-12.0",
            "ducking_attack_ms": "50",
            "ducking_release_ms": "200",
            "max_speedup": "3.0",
            "compressor_threshold_db": "-2.0",
            "compressor_lookahead_ms": "5.0",
            "compressor_release_ms": "120.0",
        },
        "System": {
            "ffmpeg_path": "",
            "last_project": "",
        },
        "Proxy": {
            "proxy_mode": "system",
            "custom_proxy": "",
        },
        "TokenUsage": {
            "stats": "{}",
            "prices": "{}",
        }
    }

    def __init__(self, filepath: str = None):
        self.filepath = filepath or get_settings_path()
        self.config = configparser.ConfigParser()
        self.load()

    def load(self):
        """Загружает настройки из файла или создает файл по умолчанию."""
        if not os.path.exists(self.filepath):
            self.config.read_dict(self.DEFAULT_CONFIG)
            self.save()
        else:
            self.config.read(self.filepath, encoding="utf-8")
            modified = False
            for section, options in self.DEFAULT_CONFIG.items():
                if not self.config.has_section(section):
                    self.config.add_section(section)
                    modified = True
                for option, default_val in options.items():
                    if not self.config.has_option(section, option):
                        self.config.set(section, option, default_val)
                        modified = True
            if modified:
                self.save()

    def save(self):
        """Сохраняет текущую конфигурацию в Settings.ini с защитой динамических секций (TokenUsage)."""
        os.makedirs(os.path.dirname(os.path.abspath(self.filepath)), exist_ok=True)
        # Если файл на диске существует, подтягиваем актуальные значения TokenUsage перед сохранением
        if os.path.isfile(self.filepath):
            try:
                disk_cfg = configparser.ConfigParser()
                disk_cfg.read(self.filepath, encoding="utf-8")
                if disk_cfg.has_section("TokenUsage"):
                    if not self.config.has_section("TokenUsage"):
                        self.config.add_section("TokenUsage")
                    
                    import json
                    # Сливаем stats
                    mem_stats_str = self.config.get("TokenUsage", "stats", fallback="{}")
                    disk_stats_str = disk_cfg.get("TokenUsage", "stats", fallback="{}")
                    try:
                        mem_stats = json.loads(mem_stats_str)
                    except Exception:
                        mem_stats = {}
                    try:
                        disk_stats = json.loads(disk_stats_str)
                    except Exception:
                        disk_stats = {}
                    
                    # Объединяем модели и токены
                    merged_stats = dict(disk_stats)
                    for m_name, m_val in mem_stats.items():
                        if m_name not in merged_stats:
                            merged_stats[m_name] = m_val
                        else:
                            merged_stats[m_name]["input_tokens"] = max(
                                merged_stats[m_name].get("input_tokens", 0),
                                m_val.get("input_tokens", 0)
                            )
                            merged_stats[m_name]["output_tokens"] = max(
                                merged_stats[m_name].get("output_tokens", 0),
                                m_val.get("output_tokens", 0)
                            )
                    self.config.set("TokenUsage", "stats", json.dumps(merged_stats, ensure_ascii=False))

                    # Сливаем prices
                    mem_prices_str = self.config.get("TokenUsage", "prices", fallback="{}")
                    disk_prices_str = disk_cfg.get("TokenUsage", "prices", fallback="{}")
                    try:
                        mem_prices = json.loads(mem_prices_str)
                    except Exception:
                        mem_prices = {}
                    try:
                        disk_prices = json.loads(disk_prices_str)
                    except Exception:
                        disk_prices = {}
                    merged_prices = dict(disk_prices)
                    merged_prices.update(mem_prices)
                    self.config.set("TokenUsage", "prices", json.dumps(merged_prices, ensure_ascii=False))
            except Exception:
                pass

        with open(self.filepath, "w", encoding="utf-8") as f:
            self.config.write(f)

    # Gemini
    @property
    def api_key(self) -> str:
        return self.config.get("Gemini", "api_key", fallback="")

    @api_key.setter
    def api_key(self, value: str):
        self.config.set("Gemini", "api_key", str(value).strip())

    @property
    def gemini_model(self) -> str:
        return self.config.get("Gemini", "model", fallback="gemini-2.5-flash")

    @gemini_model.setter
    def gemini_model(self, value: str):
        self.config.set("Gemini", "model", str(value).strip())

    @property
    def gemini_tts_model(self) -> str:
        return self.config.get("Gemini", "tts_model", fallback="gemini-3.1-flash-tts-preview")

    @gemini_tts_model.setter
    def gemini_tts_model(self, value: str):
        self.config.set("Gemini", "tts_model", str(value).strip())

    @property
    def gemini_tts_voice(self) -> str:
        return self.config.get("Gemini", "tts_voice", fallback="Puck")

    @gemini_tts_voice.setter
    def gemini_tts_voice(self, value: str):
        self.config.set("Gemini", "tts_voice", str(value).strip())

    @property
    def chunk_duration_minutes(self) -> int:
        return self.config.getint("Gemini", "chunk_duration_minutes", fallback=50)

    @chunk_duration_minutes.setter
    def chunk_duration_minutes(self, value: int):
        self.config.set("Gemini", "chunk_duration_minutes", str(max(1, int(value))))

    @property
    def api_request_pause_sec(self) -> int:
        return self.config.getint("Gemini", "api_request_pause_sec", fallback=20)

    @api_request_pause_sec.setter
    def api_request_pause_sec(self, value: int):
        self.config.set("Gemini", "api_request_pause_sec", str(max(0, int(value))))

    # SAPI5
    @property
    def sapi5_voice(self) -> str:
        return self.config.get("SAPI5", "voice", fallback="")

    @sapi5_voice.setter
    def sapi5_voice(self, value: str):
        self.config.set("SAPI5", "voice", str(value).strip())

    @property
    def sapi5_rate(self) -> int:
        return self.config.getint("SAPI5", "rate", fallback=0)

    @sapi5_rate.setter
    def sapi5_rate(self, value: int):
        self.config.set("SAPI5", "rate", str(int(value)))

    @property
    def sapi5_volume(self) -> int:
        return self.config.getint("SAPI5", "volume", fallback=100)

    @sapi5_volume.setter
    def sapi5_volume(self, value: int):
        self.config.set("SAPI5", "volume", str(max(0, min(100, int(value)))))

    # Audio & DSP
    @property
    def movie_volume_db(self) -> float:
        if self.config.has_option("Audio", "movie_volume_db"):
            val = self.config.getfloat("Audio", "movie_volume_db", fallback=0.0)
            return max(-15.0, min(20.0, float(val)))
        if self.config.has_option("Audio", "movie_volume"):
            raw = self.config.getfloat("Audio", "movie_volume", fallback=100.0)
            if raw > 20.0:  # Старое процентное значение (100% -> 0.0 dB)
                val = 20.0 * math.log10(max(0.1, raw / 100.0))
            else:
                val = raw
            return max(-15.0, min(20.0, round(val, 1)))
        return 0.0

    @movie_volume_db.setter
    def movie_volume_db(self, value: float):
        clamped = max(-15.0, min(20.0, float(value)))
        self.config.set("Audio", "movie_volume_db", f"{clamped:.1f}")
        self.config.set("Audio", "movie_volume", f"{clamped:.1f}")

    @property
    def movie_volume(self) -> float:
        return self.movie_volume_db

    @movie_volume.setter
    def movie_volume(self, value: float):
        self.movie_volume_db = value

    @property
    def commentary_volume_db(self) -> float:
        if self.config.has_option("Audio", "commentary_volume_db"):
            val = self.config.getfloat("Audio", "commentary_volume_db", fallback=0.0)
            return max(-15.0, min(20.0, float(val)))
        if self.config.has_option("Audio", "commentary_volume"):
            raw = self.config.getfloat("Audio", "commentary_volume", fallback=100.0)
            if raw > 20.0:  # Старое процентное значение (100% -> 0.0 dB)
                val = 20.0 * math.log10(max(0.1, raw / 100.0))
            else:
                val = raw
            return max(-15.0, min(20.0, round(val, 1)))
        return 0.0

    @commentary_volume_db.setter
    def commentary_volume_db(self, value: float):
        clamped = max(-15.0, min(20.0, float(value)))
        self.config.set("Audio", "commentary_volume_db", f"{clamped:.1f}")
        self.config.set("Audio", "commentary_volume", f"{clamped:.1f}")

    @property
    def commentary_volume(self) -> float:
        return self.commentary_volume_db

    @commentary_volume.setter
    def commentary_volume(self, value: float):
        self.commentary_volume_db = value

    @property
    def movie_muted(self) -> bool:
        return self.config.getboolean("Audio", "movie_muted", fallback=False)

    @movie_muted.setter
    def movie_muted(self, value: bool):
        self.config.set("Audio", "movie_muted", "true" if value else "false")

    @property
    def commentary_muted(self) -> bool:
        return self.config.getboolean("Audio", "commentary_muted", fallback=False)

    @commentary_muted.setter
    def commentary_muted(self, value: bool):
        self.config.set("Audio", "commentary_muted", "true" if value else "false")

    @property
    def auto_ducking(self) -> bool:
        return self.config.getboolean("Audio", "auto_ducking", fallback=True)

    @auto_ducking.setter
    def auto_ducking(self, value: bool):
        self.config.set("Audio", "auto_ducking", "true" if value else "false")

    @property
    def ducking_level_db(self) -> float:
        return self.config.getfloat("Audio", "ducking_level_db", fallback=-12.0)

    @ducking_level_db.setter
    def ducking_level_db(self, value: float):
        self.config.set("Audio", "ducking_level_db", str(float(value)))

    @property
    def ducking_attack_ms(self) -> float:
        return self.config.getfloat("Audio", "ducking_attack_ms", fallback=50.0)

    @ducking_attack_ms.setter
    def ducking_attack_ms(self, value: float):
        self.config.set("Audio", "ducking_attack_ms", str(float(value)))

    @property
    def ducking_release_ms(self) -> float:
        return self.config.getfloat("Audio", "ducking_release_ms", fallback=200.0)

    @ducking_release_ms.setter
    def ducking_release_ms(self, value: float):
        self.config.set("Audio", "ducking_release_ms", str(float(value)))


    @property
    def max_speedup(self) -> float:
        return self.config.getfloat("Audio", "max_speedup", fallback=3.0)

    @max_speedup.setter
    def max_speedup(self, value: float):
        self.config.set("Audio", "max_speedup", str(max(1.0, float(value))))

    @property
    def compressor_threshold_db(self) -> float:
        return self.config.getfloat("Audio", "compressor_threshold_db", fallback=-2.0)

    @compressor_threshold_db.setter
    def compressor_threshold_db(self, value: float):
        self.config.set("Audio", "compressor_threshold_db", str(float(value)))

    @property
    def compressor_lookahead_ms(self) -> float:
        return self.config.getfloat("Audio", "compressor_lookahead_ms", fallback=5.0)

    @compressor_lookahead_ms.setter
    def compressor_lookahead_ms(self, value: float):
        self.config.set("Audio", "compressor_lookahead_ms", str(float(value)))

    @property
    def compressor_release_ms(self) -> float:
        return self.config.getfloat("Audio", "compressor_release_ms", fallback=120.0)

    @compressor_release_ms.setter
    def compressor_release_ms(self, value: float):
        self.config.set("Audio", "compressor_release_ms", str(float(value)))

    # System
    @property
    def ffmpeg_path(self) -> str:
        return self.config.get("System", "ffmpeg_path", fallback="")

    @ffmpeg_path.setter
    def ffmpeg_path(self, value: str):
        self.config.set("System", "ffmpeg_path", str(value).strip())

    @property
    def ffprobe_path(self) -> str:
        return self.config.get("System", "ffprobe_path", fallback="")

    @ffprobe_path.setter
    def ffprobe_path(self, value: str):
        self.config.set("System", "ffprobe_path", str(value).strip())

    @property
    def last_project(self) -> str:
        return self.config.get("System", "last_project", fallback="")

    @last_project.setter
    def last_project(self, value: str):
        self.config.set("System", "last_project", str(value).strip())


    # Proxy
    @property
    def proxy_mode(self) -> str:
        return self.config.get("Proxy", "proxy_mode", fallback="system")

    @proxy_mode.setter
    def proxy_mode(self, value: str):
        self.config.set("Proxy", "proxy_mode", str(value).strip())

    @property
    def custom_proxy(self) -> str:
        return self.config.get("Proxy", "custom_proxy", fallback="")

    @custom_proxy.setter
    def custom_proxy(self, value: str):
        self.config.set("Proxy", "custom_proxy", str(value).strip())

