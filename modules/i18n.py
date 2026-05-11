"""
WelcomeX - Sistema de Internacionalización (i18n)
Soporte para Español, English, Português
"""

import json
import os
import sys

SUPPORTED_LANGUAGES = ["es", "en", "pt"]
LANGUAGE_NAMES = {
    "es": "Español",
    "en": "English",
    "pt": "Português"
}
DEFAULT_LANGUAGE = "es"

_translations = {}
_current_lang = DEFAULT_LANGUAGE

# Detectar directorio correcto para locales (empaquetado vs desarrollo)
if getattr(sys, 'frozen', False) and hasattr(sys, '_MEIPASS'):
    # Empaquetado como .exe: recursos dentro del bundle
    _RESOURCE_DIR = sys._MEIPASS
else:
    # Desarrollo: directorio del proyecto
    _RESOURCE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

LOCALES_DIR = os.path.join(_RESOURCE_DIR, "locales")


def load_translations():
    """Carga todos los archivos de traducción"""
    global _translations
    for lang in SUPPORTED_LANGUAGES:
        filepath = os.path.join(LOCALES_DIR, f"{lang}.json")
        try:
            with open(filepath, 'r', encoding='utf-8') as f:
                _translations[lang] = json.load(f)
            print(f"[i18n] OK Cargado: {lang}.json")
        except FileNotFoundError:
            print(f"[i18n] WARN No encontrado: {filepath}")
            _translations[lang] = {}
        except Exception as e:
            print(f"[i18n] ERROR cargando {lang}: {e}")
            _translations[lang] = {}


def set_language(lang: str):
    """Cambia el idioma actual"""
    global _current_lang
    if lang in SUPPORTED_LANGUAGES:
        _current_lang = lang
        print(f"[i18n] Idioma cambiado a: {LANGUAGE_NAMES.get(lang, lang)}")


def get_language() -> str:
    """Retorna el idioma actual"""
    return _current_lang


def t(key: str, **kwargs) -> str:
    """
    Obtener texto traducido.

    Uso: t("login.title") -> "Iniciar Sesión" (es) / "Sign In" (en)

    Soporta variables: t("welcome", name="Juan") -> "Bienvenido, Juan"
    """
    keys = key.split(".")
    value = _translations.get(_current_lang, {})

    for k in keys:
        if isinstance(value, dict):
            value = value.get(k)
        else:
            value = None
            break

    if value is None:
        # Fallback a español
        value = _translations.get("es", {})
        for k in keys:
            if isinstance(value, dict):
                value = value.get(k)
            else:
                value = None
                break

    if value is None:
        # Si no existe ni en español, retornar la key
        return key

    # Reemplazar variables {name} si existen
    if kwargs and isinstance(value, str):
        try:
            value = value.format(**kwargs)
        except (KeyError, IndexError):
            pass

    return value


# Cargar traducciones al importar
load_translations()
