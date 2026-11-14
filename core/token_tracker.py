# -*- coding: utf-8 -*-
"""
Модуль для учета расхода входящих и исходящих токенов по каждой используемой модели (Google Gemini / TTS).
Сохраняет статистику и пользовательские цены в Settings.ini.
"""

import os
import json
import threading
import configparser
from typing import Dict, Any, List, Optional
from core.app_paths import get_settings_path

_tracker_lock = threading.Lock()


class TokenTracker:
    """Управляет учетом расхода токенов и расчетом стоимости по моделям."""

    SECTION_NAME = "TokenUsage"

    @classmethod
    def _get_config(cls, settings_path: Optional[str] = None) -> tuple[configparser.ConfigParser, str]:
        path = settings_path or get_settings_path()
        cfg = configparser.ConfigParser()
        if os.path.isfile(path):
            cfg.read(path, encoding="utf-8")
        if not cfg.has_section(cls.SECTION_NAME):
            cfg.add_section(cls.SECTION_NAME)
        return cfg, path

    @classmethod
    def _save_config(cls, cfg: configparser.ConfigParser, path: str):
        os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
        with open(path, "w", encoding="utf-8") as f:
            cfg.write(f)

    @classmethod
    def clean_model_name(cls, model_name: str) -> str:
        name = str(model_name).strip()
        if name.startswith("models/"):
            name = name[len("models/"):]
        return name

    @classmethod
    def record_usage(
        cls,
        model_name: str,
        input_tokens: int = 0,
        output_tokens: int = 0,
        settings_path: Optional[str] = None
    ):
        """
        Фиксирует факт использования модели и добавляет токены.
        Модель добавляется в статистику в момент начала использования.
        """
        clean_name = cls.clean_model_name(model_name)
        if not clean_name:
            return

        with _tracker_lock:
            cfg, path = cls._get_config(settings_path)
            raw_stats = cfg.get(cls.SECTION_NAME, "stats", fallback="{}")
            try:
                stats = json.loads(raw_stats)
            except Exception:
                stats = {}

            if clean_name not in stats:
                stats[clean_name] = {"input_tokens": 0, "output_tokens": 0}

            in_val = max(0, int(input_tokens))
            out_val = max(0, int(output_tokens))
            stats[clean_name]["input_tokens"] = stats[clean_name].get("input_tokens", 0) + in_val
            stats[clean_name]["output_tokens"] = stats[clean_name].get("output_tokens", 0) + out_val

            cfg.set(cls.SECTION_NAME, "stats", json.dumps(stats, ensure_ascii=False))
            cls._save_config(cfg, path)

    @classmethod
    def get_tracked_usage(cls, settings_path: Optional[str] = None) -> Dict[str, Dict[str, Any]]:
        """Возвращает данные о моделях, использовавшихся с последнего сброса."""
        with _tracker_lock:
            cfg, _ = cls._get_config(settings_path)
            raw_stats = cfg.get(cls.SECTION_NAME, "stats", fallback="{}")
            raw_prices = cfg.get(cls.SECTION_NAME, "prices", fallback="{}")
            try:
                stats = json.loads(raw_stats)
            except Exception:
                stats = {}
            try:
                prices = json.loads(raw_prices)
            except Exception:
                prices = {}

            result = {}
            for model_name, usage in stats.items():
                m_prices = prices.get(model_name, {})
                price_in = m_prices.get("price_input")
                price_out = m_prices.get("price_output")
                unit = m_prices.get("unit", 1000000)

                result[model_name] = {
                    "input_tokens": int(usage.get("input_tokens", 0)),
                    "output_tokens": int(usage.get("output_tokens", 0)),
                    "price_input": float(price_in) if price_in is not None and str(price_in).strip() != "" else None,
                    "price_output": float(price_out) if price_out is not None and str(price_out).strip() != "" else None,
                    "unit": int(unit) if unit else 1000000
                }
            return result

    @classmethod
    def set_model_prices(
        cls,
        model_name: str,
        price_input: Optional[float],
        price_output: Optional[float],
        unit: int = 1000000,
        settings_path: Optional[str] = None
    ):
        """Сохраняет цены токенов для конкретной модели в Settings.ini."""
        clean_name = cls.clean_model_name(model_name)
        if not clean_name:
            return

        with _tracker_lock:
            cfg, path = cls._get_config(settings_path)
            raw_prices = cfg.get(cls.SECTION_NAME, "prices", fallback="{}")
            try:
                prices = json.loads(raw_prices)
            except Exception:
                prices = {}

            prices[clean_name] = {
                "price_input": price_input if price_input is not None else None,
                "price_output": price_output if price_output is not None else None,
                "unit": int(unit) if unit else 1000000
            }

            cfg.set(cls.SECTION_NAME, "prices", json.dumps(prices, ensure_ascii=False))
            cls._save_config(cfg, path)

    @classmethod
    def reset_usage(cls, settings_path: Optional[str] = None):
        """Очищает статистику расхода токенов для всех моделей."""
        with _tracker_lock:
            cfg, path = cls._get_config(settings_path)
            cfg.set(cls.SECTION_NAME, "stats", "{}")
            cls._save_config(cfg, path)
