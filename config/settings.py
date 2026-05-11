import os
import sys


APP_NAME = "PhotoBooth"
APP_VERSION = "1.0.1"
PROGRAM_CODE = "PHOTO_BOOTH"
PAMPA_API_URL = "https://pampaguazu.com.ar"

# ── Rutas ─────────────────────────────────────────────────────────────────────

def get_base_dir() -> str:
    if getattr(sys, 'frozen', False):
        return os.path.dirname(sys.executable)
    return os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

def get_resource_dir() -> str:
    if getattr(sys, 'frozen', False):
        return sys._MEIPASS  # type: ignore
    return get_base_dir()

BASE_DIR      = get_base_dir()
RESOURCE_DIR  = get_resource_dir()
DATA_DIR      = os.path.join(BASE_DIR, "data")
DATABASE_PATH = os.path.join(DATA_DIR, "photobooth.db")
PHOTOS_DIR    = os.path.join(DATA_DIR, "fotos")
ASSETS_DIR    = os.path.join(RESOURCE_DIR, "assets")
TEMPLATES_DIR = os.path.join(ASSETS_DIR, "templates")
LOCALES_DIR   = os.path.join(RESOURCE_DIR, "locales")

# Crear directorios en runtime si no existen
for _d in (DATA_DIR, PHOTOS_DIR):
    os.makedirs(_d, exist_ok=True)

# ── Colores (tema oscuro) ──────────────────────────────────────────────────────

COLORS = {
    "bg":           "#08050f",   # negro con tinte violeta
    "bg_card":      "#110d1e",   # card violeta muy oscuro
    "bg_hover":     "#1c1530",   # hover violeta oscuro
    "sidebar":      "#0c0818",   # sidebar negro violáceo
    "primary":      "#9333ea",   # violeta principal
    "primary_dark": "#7e22ce",   # violeta oscuro (hover)
    "primary_fg":   "#ffffff",   # texto sobre botones primarios
    "primary_bg":   "#1e0a3c",   # fondo tintado violeta
    "success":      "#10b981",
    "warning":      "#f59e0b",
    "danger":       "#ef4444",
    "text":         "#f3f0ff",   # blanco con leve tinte violeta
    "text_gray":    "#a89cc8",   # gris violáceo
    "text_muted":   "#4b3f6b",   # muted violáceo
    "border":       "#2d1b4e",   # borde violeta oscuro
    "border_amber": "#4c1d95",   # acento borde (renombrar eventual)
}

# ── Roles y permisos ──────────────────────────────────────────────────────────

ROLES = ["super_admin", "admin", "operario"]

PERMISOS = {
    "super_admin": ["todo"],
    "admin": [
        "crear_evento", "editar_evento", "eliminar_evento",
        "iniciar_cabina", "ver_galeria",
        "editar_plantillas", "configurar_impresora",
        "ver_usuarios", "crear_operario",
    ],
    "operario": [
        "iniciar_cabina", "ver_galeria",
    ],
}

# ── Configuración Kodak 305 ───────────────────────────────────────────────────

KODAK_305 = {
    "nombre": "Kodak 305",
    # Tamaño tira 2×6" a 300 dpi
    "strip_2x6_px": (600, 1800),
    # Tamaño 4×6" a 300 dpi
    "foto_4x6_px":  (1200, 1800),
    "dpi":          300,
}

# ── Sesión de fotos ───────────────────────────────────────────────────────────

FOTO_SESSION = {
    "total_fotos":    5,      # cuántas fotos se toman
    "fotos_a_elegir": 3,      # cuántas elige el usuario
    "countdown_seg":  3,      # segundos antes de cada disparo
    "preview_seg":    2,      # segundos que se muestra preview post-captura
    "idle_timeout_seg": 30,   # segundos sin actividad para volver a idle
}

# ── Super admin por defecto ────────────────────────────────────────────────────

SUPER_ADMIN_EMAIL  = "mrearte21@hotmail.com"
SUPER_ADMIN_NOMBRE = "Mauricio Rearte"
