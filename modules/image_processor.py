"""
ImageProcessor — composición final de tiras con slots de foto y texto.
"""
import os
from PIL import Image, ImageDraw, ImageFont
from config.settings import ASSETS_DIR

# Tamaños por defecto (5×15 cm a 300 dpi)
DEFAULT_STRIP_W, DEFAULT_STRIP_H = 591, 1772


def _scan_system_fonts() -> dict[str, str]:
    """Devuelve {nombre_display: ruta_absoluta} de todas las fuentes instaladas."""
    from PIL.ImageFont import FreeTypeFont
    wins_dir = os.environ.get("WINDIR", "C:/Windows")
    fonts_dir = os.path.join(wins_dir, "Fonts")
    result: dict[str, str] = {}
    if not os.path.isdir(fonts_dir):
        return result
    for fname in sorted(os.listdir(fonts_dir)):
        if not fname.lower().endswith((".ttf", ".otf")):
            continue
        path = os.path.join(fonts_dir, fname)
        try:
            ft = FreeTypeFont(path, size=12)
            name = ft.getname()[0]   # (family, style) — tomamos family
            if name and name not in result:
                result[name] = path
        except Exception:
            continue
    return result


# Mapa nombre → ruta, construido una sola vez al importar el módulo
_SYSTEM_FONTS: dict[str, str] = _scan_system_fonts()
FONT_FAMILIES: list[str] = sorted(_SYSTEM_FONTS.keys()) or ["Arial"]


def _font(size: int, family: str = "Arial", bold: bool = True):
    # Intentar con la fuente pedida
    path = _SYSTEM_FONTS.get(family)
    if path and os.path.exists(path):
        try:
            return ImageFont.truetype(path, size)
        except Exception:
            pass
    # Fallback: Arial del sistema
    wins_dir = os.environ.get("WINDIR", "C:/Windows")
    for fallback in ("arialbd.ttf", "arial.ttf"):
        fb_path = os.path.join(wins_dir, "Fonts", fallback)
        if os.path.exists(fb_path):
            try:
                return ImageFont.truetype(fb_path, size)
            except Exception:
                pass
    return ImageFont.load_default()


class ImageProcessor:

    # ── Composición final ──────────────────────────────────────────────────────

    @staticmethod
    def componer_tira(fotos: list[Image.Image],
                      plantilla: dict | None = None,
                      evento: dict | None = None,
                      trial: bool = False) -> Image.Image:
        """
        fotos: lista de PIL Images YA en el orden que eligió el usuario.
        plantilla: dict con ruta_json o None → usa layout con branding por defecto.
        evento: dict del evento (nombre, fecha_evento, logo_branding) para llenar
                el panel de branding automáticamente.
        """
        import json

        if plantilla and plantilla.get("ruta_json") and \
                os.path.exists(plantilla["ruta_json"]):
            try:
                with open(plantilla["ruta_json"], encoding="utf-8") as f:
                    config = json.load(f)
            except Exception:
                config = ImageProcessor._config_default(evento)
        else:
            config = ImageProcessor._config_default(evento)

        W = config.get("ancho", DEFAULT_STRIP_W)
        H = config.get("alto", DEFAULT_STRIP_H)

        canvas = ImageProcessor._fondo(W, H, config)
        draw = ImageDraw.Draw(canvas)

        slots = sorted(config.get("slots", []), key=lambda s: s.get("orden", 0))
        foto_idx = 0

        for slot in slots:
            x, y, sw, sh = slot["x"], slot["y"], slot["w"], slot["h"]

            if slot.get("type", "foto") == "foto":
                if foto_idx < len(fotos):
                    pegada = ImageProcessor._fit_crop(fotos[foto_idx], sw, sh)
                    canvas.paste(pegada, (x, y))
                    foto_idx += 1
                else:
                    draw.rectangle([x, y, x + sw, y + sh],
                                   fill="#1a1a1a", outline="#333")

            elif slot.get("type") == "texto":
                ImageProcessor._render_texto_slot(
                    canvas, draw, slot, x, y, sw, sh, evento=evento)

        if trial:
            ImageProcessor._aplicar_marca_agua(canvas)

        return canvas

    @staticmethod
    def _aplicar_marca_agua(img: Image.Image):
        """Dibuja marca de agua diagonal PAMPA GUAZÚ repetida sobre la imagen."""
        from PIL import ImageDraw, ImageFont
        import math
        w, h = img.size
        overlay = Image.new("RGBA", (w, h), (0, 0, 0, 0))
        draw = ImageDraw.Draw(overlay)
        texto = "PAMPA GUAZÚ"
        font_size = max(36, w // 12)
        try:
            font = ImageFont.truetype(
                "C:/Windows/Fonts/arialbd.ttf", font_size)
        except Exception:
            font = ImageFont.load_default()
        bbox = draw.textbbox((0, 0), texto, font=font)
        tw = bbox[2] - bbox[0]
        th = bbox[3] - bbox[1]
        # Repetir en diagonal cada ~200px
        paso_x = tw + 80
        paso_y = th + 80
        for yi in range(-h, h * 2, paso_y):
            for xi in range(-w, w * 2, paso_x):
                # rotación 45° con imagen temporal
                tmp = Image.new("RGBA", (tw + 20, th + 20), (0, 0, 0, 0))
                td = ImageDraw.Draw(tmp)
                td.text((10, 10), texto, font=font, fill=(255, 255, 255, 80))
                tmp_rot = tmp.rotate(40, expand=True)
                overlay.paste(tmp_rot, (xi, yi), tmp_rot)
        img.paste(Image.alpha_composite(img.convert("RGBA"), overlay).convert("RGB"))

    @staticmethod
    def _render_texto_slot(canvas, draw, slot, x, y, sw, sh, evento=None):
        bg = slot.get("bg_color", "#111111")
        draw.rectangle([x, y, x + sw, y + sh], fill=bg)

        color   = slot.get("color", "#ffffff")
        color_s = slot.get("color_sub", "#aaaaaa")

        # Si el slot no tiene texto propio, usa los datos del evento
        txt_p = slot.get("texto_principal", "")
        txt_s = slot.get("texto_sub", "")
        if not txt_p and evento:
            txt_p = evento.get("nombre", "")
        if not txt_s and evento:
            txt_s = evento.get("fecha_evento", "")

        # Logo del branding: prioridad slot.logo > evento.logo_branding
        slot_logo = slot.get("logo")
        if not slot_logo and evento and evento.get("logo_branding"):
            slot_logo = {"path": evento["logo_branding"], "w": 180, "h": 90}

        cy = y + sh // 2

        # Logo del panel (slot_logo ya unifica slot.logo + evento.logo_branding)
        if slot_logo and slot_logo.get("path") and os.path.exists(slot_logo["path"]):
            try:
                lg = Image.open(slot_logo["path"]).convert("RGBA")
                lw, lh = slot_logo.get("w", 180), slot_logo.get("h", 90)
                # Escalar manteniendo proporción si no cabe
                ratio = min(lw / lg.width, lh / lg.height)
                lw2, lh2 = int(lg.width * ratio), int(lg.height * ratio)
                lg = lg.resize((lw2, lh2), Image.LANCZOS)
                lx = x + (sw - lw2) // 2
                canvas.paste(lg, (lx, y + (sh - lh2) // 2), lg)
                # Con logo: texto debajo del logo
                cy = y + (sh - lh2) // 2 + lh2 + 8
            except Exception:
                pass

        family   = slot.get("font_family", "Arial")
        bold_p   = slot.get("bold_principal", True)
        bold_s   = slot.get("bold_sub", False)
        if txt_p:
            fnt = _font(slot.get("font_size", 28), family=family, bold=bold_p)
            bbox = draw.textbbox((0, 0), txt_p, font=fnt)
            tw, th = bbox[2] - bbox[0], bbox[3] - bbox[1]
            dy = -(th // 2 + 6) if txt_s else 0
            draw.text((x + (sw - tw) // 2, cy - th // 2 + dy),
                      txt_p, fill=color, font=fnt)
        if txt_s:
            fnt_s = _font(slot.get("font_size_sub", 16), family=family, bold=bold_s)
            bbox  = draw.textbbox((0, 0), txt_s, font=fnt_s)
            tw_s, th_s = bbox[2] - bbox[0], bbox[3] - bbox[1]
            fnt_p = _font(slot.get("font_size", 28), family=family, bold=bold_p)
            bbox_p = draw.textbbox((0, 0), txt_p or " ", font=fnt_p)
            th_p = (bbox_p[3] - bbox_p[1]) if txt_p else 0
            y_sub = cy + th_p // 2 + 8
            draw.text((x + (sw - tw_s) // 2, y_sub),
                      txt_s, fill=color_s, font=fnt_s)

    # ── Helpers ────────────────────────────────────────────────────────────────

    @staticmethod
    def _fondo(W: int, H: int, config: dict) -> Image.Image:
        fi = config.get("fondo_imagen")
        if fi and os.path.exists(fi):
            return Image.open(fi).convert("RGB").resize((W, H), Image.LANCZOS)
        return Image.new("RGB", (W, H),
                         color=config.get("fondo_color", "#111111"))

    @staticmethod
    def _fit_crop(img: Image.Image, tw: int, th: int) -> Image.Image:
        sw, sh = img.size
        ratio = max(tw / sw, th / sh)
        nw, nh = int(sw * ratio), int(sh * ratio)
        resized = img.resize((nw, nh), Image.LANCZOS)
        left = (nw - tw) // 2
        top  = (nh - th) // 2
        return resized.crop((left, top, left + tw, top + th))

    @staticmethod
    def _config_default(evento: dict | None = None) -> dict:
        from modules.template_designer import TemplateDesigner as TD
        slots = TD._slots_con_texto(DEFAULT_STRIP_W, DEFAULT_STRIP_H, 3, 24, 14)
        return {
            "ancho": DEFAULT_STRIP_W,
            "alto":  DEFAULT_STRIP_H,
            "fondo_color": "#111111",
            "slots": slots,
        }

    # ── Preview de plantilla ────────────────────────────────────────────────────

    @staticmethod
    def preview_plantilla(config: dict,
                          size: tuple[int, int] = (160, 240)) -> Image.Image:
        """Preview rápido para grillas y thumbnails."""
        from modules.template_designer import _foto_muestra
        W = config.get("ancho", DEFAULT_STRIP_W)
        H = config.get("alto", DEFAULT_STRIP_H)

        canvas = ImageProcessor._fondo(W, H, config)
        draw = ImageDraw.Draw(canvas)
        foto_idx = 0

        for slot in sorted(config.get("slots", []),
                           key=lambda s: s.get("orden", 0)):
            x, y, sw, sh = slot["x"], slot["y"], slot["w"], slot["h"]
            if slot.get("type", "foto") == "foto":
                muestra = _foto_muestra(sw, sh, foto_idx)
                canvas.paste(muestra, (x, y))
                foto_idx += 1
            else:
                bg = slot.get("bg_color", "#1a1a1a")
                draw.rectangle([x, y, x + sw, y + sh], fill=bg)
                txt = slot.get("texto_principal", "")
                if txt:
                    fnt = _font(max(10, min(slot.get("font_size", 22),
                                           int(sw * 0.07))))
                    bbox = draw.textbbox((0, 0), txt, font=fnt)
                    tw = bbox[2] - bbox[0]
                    cy = y + sh // 2 - (bbox[3] - bbox[1]) // 2
                    draw.text((x + (sw - tw) // 2, cy),
                              txt, fill=slot.get("color", "#fff"), font=fnt)

        canvas.thumbnail(size, Image.LANCZOS)
        return canvas

    # ── Filtros ────────────────────────────────────────────────────────────────

    @staticmethod
    def aplicar_filtro(img: Image.Image, filtro: str) -> Image.Image:
        if filtro == "bn":
            return img.convert("L").convert("RGB")
        if filtro == "vintage":
            r, g, b = img.split()
            return Image.merge("RGB", [
                r.point(lambda x: min(255, int(x * 1.1))),
                g,
                b.point(lambda x: int(x * 0.85)),
            ])
        if filtro == "sepia":
            gray = img.convert("L")
            return Image.merge("RGB", [
                gray.point(lambda x: min(255, int(x * 1.08))),
                gray.point(lambda x: int(x * 0.86)),
                gray.point(lambda x: int(x * 0.67)),
            ])
        return img

    # ── Default slots (para compatibilidad con código viejo) ──────────────────

    @staticmethod
    def _slots_default(W: int, H: int, n: int,
                       padding: int = 24, gap: int = 14) -> list[dict]:
        foto_w = W - padding * 2
        total_h = H - padding * 2 - gap * (n - 1)
        foto_h = max(20, total_h // n)
        return [
            {"type": "foto", "orden": i + 1,
             "x": padding, "y": padding + i * (foto_h + gap),
             "w": foto_w, "h": foto_h}
            for i in range(n)
        ]
