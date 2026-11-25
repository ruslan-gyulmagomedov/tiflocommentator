# -*- coding: utf-8 -*-
"""
Модуль управления сетевыми прокси-настройками.
Обеспечивает автоматическое извлечение настроек системного прокси-сервера Windows
из реестра WinINet и применение их к сетевым библиотекам Python.
"""

import logging
import os
import sys
import urllib.request
from typing import Dict, Optional

if sys.platform == "win32":
    import winreg


def get_windows_system_proxy_info() -> Dict[str, Optional[str]]:
    """Извлекает подробные сведения о системном прокси-сервере Windows."""
    info = {
        "enabled": False,
        "server": None,
        "override": None,
        "http": None,
        "https": None
    }

    if sys.platform != "win32":
        proxies = urllib.request.getproxies_environment()
        if proxies:
            info["enabled"] = True
            info["http"] = proxies.get("http")
            info["https"] = proxies.get("https")
            info["server"] = info["https"] or info["http"]
        return info

    logging.info('Прокси: чтение реестра Windows')
    try:
        with winreg.OpenKey(
            winreg.HKEY_CURRENT_USER,
            r"Software\Microsoft\Windows\CurrentVersion\Internet Settings"
        ) as key:
            try:
                enabled, _ = winreg.QueryValueEx(key, "ProxyEnable")
                info["enabled"] = bool(enabled)
            except OSError:
                info["enabled"] = False

            if info["enabled"]:
                try:
                    server, _ = winreg.QueryValueEx(key, "ProxyServer")
                    info["server"] = str(server).strip() if server else None
                except OSError:
                    info["server"] = None

                try:
                    override, _ = winreg.QueryValueEx(key, "ProxyOverride")
                    info["override"] = str(override).strip() if override else None
                except OSError:
                    info["override"] = None
    except Exception as e:
        print(f"Предупреждение при чтении настроек прокси из реестра Windows: {e}")

    try:
        logging.info('Прокси: urllib getproxies_registry')
        reg_proxies = urllib.request.getproxies_registry()
        logging.info('Прокси: urllib getproxies_registry готово')
        if reg_proxies:
            info["http"] = reg_proxies.get("http")
            info["https"] = reg_proxies.get("https")
            if not info["server"]:
                info["server"] = info["https"] or info["http"]
            if not info["enabled"] and (info["http"] or info["https"]):
                info["enabled"] = True
    except Exception:
        pass

    if info["server"] and not info["http"] and not info["https"]:
        srv = info["server"]
        if "=" in srv:
            for part in srv.split(";"):
                part = part.strip()
                if part.startswith("http="):
                    val = part[5:]
                    if not val.startswith(("http://", "https://", "socks5://", "socks5h://")):
                        val = f"http://{val}"
                    info["http"] = val
                elif part.startswith("https="):
                    val = part[6:]
                    if not val.startswith(("http://", "https://", "socks5://", "socks5h://")):
                        val = f"http://{val}"
                    info["https"] = val
        else:
            val = srv
            if not val.startswith(("http://", "https://", "socks5://", "socks5h://")):
                val = f"http://{val}"
            info["http"] = val
            info["https"] = val

    return info


def format_proxy_url(proxy_str: str) -> str:
    """Нормализует адрес прокси, добавляя схему http:// при необходимости."""
    proxy_str = proxy_str.strip()
    if not proxy_str:
        return ""
    if not proxy_str.startswith(("http://", "https://", "socks5://", "socks5h://", "socks4://")):
        proxy_str = f"http://{proxy_str}"
    return proxy_str


def clear_proxy_env():
    """Удаляет все переменные окружения, относящиеся к прокси, и сбрасывает кэш urllib."""
    proxy_keys = [
        "HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY", "GRPC_PROXY",
        "http_proxy", "https_proxy", "all_proxy", "grpc_proxy",
        "NO_PROXY", "no_proxy"
    ]
    for k in proxy_keys:
        if k in os.environ:
            del os.environ[k]

    try:
        urllib.request.install_opener(None)
    except Exception:
        pass


def apply_proxy_settings(mode: str = "system", custom_proxy: str = "") -> Dict[str, Optional[str]]:
    """
    Применяет настройки прокси-сервера ко всем сетевым компонентам текущего процесса Python
    (requests, urllib, urllib3, httplib2, PySocks, gRPC).

    Параметры:
    - mode: "system" (системный Windows), "custom" (пользовательский URL), "direct" (без прокси).
    - custom_proxy: строка адреса прокси (для режима "custom").

    Возвращает словарь с фактически примененными прокси.
    """
    logging.info('Прокси: старт apply_proxy_settings, режим %s', mode)
    clear_proxy_env()
    logging.info('Прокси: переменные очищены')

    # Привязываем httplib2 к модулю socks (PySocks)
    try:
        import socks
        logging.info('Прокси: socks импортирован')
        import httplib2
        logging.info('Прокси: httplib2 импортирован')
        httplib2.socks = socks
    except Exception:
        pass
    logging.info('Прокси: модули подготовлены')

    applied = {"http": None, "https": None, "mode": mode}

    if mode == "direct":
        return applied

    if mode == "custom":
        url = format_proxy_url(custom_proxy)
        if url:
            os.environ["HTTP_PROXY"] = url
            os.environ["HTTPS_PROXY"] = url
            os.environ["ALL_PROXY"] = url
            os.environ["GRPC_PROXY"] = url
            os.environ["http_proxy"] = url
            os.environ["https_proxy"] = url
            os.environ["all_proxy"] = url
            os.environ["grpc_proxy"] = url
            applied["http"] = url
            applied["https"] = url
        return applied

    # mode == "system" (по умолчанию)
    info = get_windows_system_proxy_info()
    logging.info('Прокси: системные настройки получены: %s', info)
    if info.get("enabled"):
        http_url = info.get("http") or format_proxy_url(info.get("server") or "")
        https_url = info.get("https") or http_url

        if http_url:
            os.environ["HTTP_PROXY"] = http_url
            os.environ["http_proxy"] = http_url
            applied["http"] = http_url

        if https_url:
            os.environ["HTTPS_PROXY"] = https_url
            os.environ["https_proxy"] = https_url
            os.environ["ALL_PROXY"] = https_url
            os.environ["all_proxy"] = https_url
            os.environ["grpc_proxy"] = https_url
            os.environ["GRPC_PROXY"] = https_url
            applied["https"] = https_url

        override = info.get("override")
        if override:
            bypass_list = [p.strip() for p in override.replace(";", ",").split(",") if p.strip()]
            bypass_clean = [p for p in bypass_list if p.lower() != "<local>"]
            if "<local>" in [p.lower() for p in bypass_list]:
                bypass_clean.extend(["localhost", "127.0.0.1", "::1"])
            no_proxy_val = ",".join(bypass_clean)
            if no_proxy_val:
                os.environ["NO_PROXY"] = no_proxy_val
                os.environ["no_proxy"] = no_proxy_val

    return applied


def ensure_proxy_configured():
    """Считывает настройки из Settings.ini и гарантированно применяет их к процессу."""
    try:
        from core.config_manager import ConfigManager
        cfg = ConfigManager()
        apply_proxy_settings(mode=cfg.proxy_mode, custom_proxy=cfg.custom_proxy)
    except Exception as e:
        print(f"Предупреждение при применении настроек прокси: {e}")
        apply_proxy_settings(mode="system")


def get_proxy_status_description() -> str:
    """Возвращает понятное текстовое описание статуса системного прокси для интерфейса и скринридеров."""
    info = get_windows_system_proxy_info()
    if info.get("enabled") and (info.get("server") or info.get("http") or info.get("https")):
        addr = info.get("server") or info.get("https") or info.get("http")
        return f"Системный прокси Windows активен: {addr}"
    return "Системный прокси Windows выключен или не настроен."

