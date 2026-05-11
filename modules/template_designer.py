"""
TemplateDesigner — editor visual de plantillas.

Soporta:
  - Slots de FOTO y slots de TEXTO (panel de branding)
  - Reordenamiento de slots via botones ↑↓
  - Preview en tiempo real con fotos de muestra de colores
  - Formatos: tira_5x15 (3 fotos, imprime 2-up en hoja 10×15) y foto_10x15 (4 fotos 2×2)
  - El panel de texto ocupa el espacio de una foto extra
"""
import json
import os
import re
import time
import customtkinter as ctk
import tkinter as tk
from tkinter import colorchooser, filedialog
from PIL import Image, ImageTk, ImageDraw, ImageFont

from config.settings import COLORS, TEMPLATES_DIR
from config.formatos import FORMATOS, get_formato
from modules.image_processor import ImageProcessor, _font, FONT_FAMILIES

C = COLORS

# Colores de muestra para las fotos placeholder
SAMPLE_COLORS = [
    ("#1a3a5c", "#4a9eff"),  # azul
    ("#1a3a2a", "#4aff9e"),  # verde
    ("#3a1a2a", "#ff4a9e"),  # rosa
    ("#3a2a1a", "#ffaa4a"),  # naranja
    ("#2a1a3a", "#aa4aff"),  # violeta
    ("#1a3a3a", "#4affee"),  # cyan
]

LAYOUT_PRESETS = [
    {"key": "simetrico",    "label": "Simétrico",          "desc": "Fotos del mismo tamaño, una columna"},
    {"key": "con_texto",    "label": "Fotos + Panel texto", "desc": "3 fotos + 1 panel de branding al final"},
    {"key": "dos_columnas", "label": "Dos columnas",        "desc": "Grilla 2×N (para 10×15 cm)"},
]


def _foto_muestra(w: int, h: int, idx: int, label: str = "") -> Image.Image:
    """Genera imagen de muestra con gradiente para simular una foto."""
    bg, accent = SAMPLE_COLORS[idx % len(SAMPLE_COLORS)]
    img = Image.new("RGB", (w, h), color=bg)
    draw = ImageDraw.Draw(img)
    # Marco interior
    draw.rectangle([4, 4, w - 5, h - 5], outline=accent, width=2)
    # Ícono cámara simplificado
    cx, cy = w // 2, h // 2
    r = min(w, h) // 5
    draw.ellipse([cx - r, cy - r, cx + r, cy + r], outline=accent, width=2)
    draw.ellipse([cx - r // 2, cy - r // 2, cx + r // 2, cy + r // 2], fill=accent)
    # Label
    if label:
        try:
            fnt = _font(max(10, min(22, h // 8)))
            bbox = draw.textbbox((0, 0), label, font=fnt)
            tw, th = bbox[2] - bbox[0], bbox[3] - bbox[1]
            draw.text((cx - tw // 2, h - th - 8), label, fill=accent, font=fnt)
        except Exception:
            pass
    return img


class TemplateDesigner(ctk.CTkToplevel):
    PREVIEW_SCALE = 0.18   # fracción del tamaño real para el panel de preview
    _ZOOM_STEPS = [0.10, 0.15, 0.18, 0.25, 0.35, 0.50, 0.70, 1.0]

    def __init__(self, parent, db, usuario_id: int,
                 plantilla: dict | None = None,
                 formato_key: str = "tira_5x15",
                 on_guardar=None):
        super().__init__(parent)
        self.db = db
        self.usuario_id = usuario_id
        self.on_guardar = on_guardar
        self._preview_photo: ImageTk.PhotoImage | None = None
        self._zoom_idx: int = 2   # índice en _ZOOM_STEPS (0.18 por defecto)

        self.title("Editor de plantilla")
        self.geometry("940x700")
        self.minsize(820, 580)
        self.configure(fg_color=C["bg"])
        self.grab_set()

        self._config = self._config_inicial(plantilla, formato_key)
        self._build_ui()
        self._refresh_all()

    # ── Config inicial ─────────────────────────────────────────────────────────

    def _config_inicial(self, p: dict | None, formato_key: str) -> dict:
        fmt = get_formato(formato_key)
        base = {
            "nombre":      "Nueva plantilla",
            "formato":     fmt["key"],
            "ancho":       fmt["w"],
            "alto":        fmt["h"],
            "n_fotos":     fmt["n_fotos"],
            "cols":        fmt["cols"],
            "fondo_color": "#111111",
            "fondo_imagen": None,
            "layout":      "simetrico",
            "padding":     24,
            "gap":         14,
            "slots":       [],   # se generan en _recalcular_slots
        }
        if p and p.get("ruta_json") and os.path.exists(p["ruta_json"]):
            try:
                with open(p["ruta_json"], encoding="utf-8") as f:
                    saved = json.load(f)
                base.update(saved)
                return base
            except Exception:
                pass
        # Generar slots por defecto
        base["slots"] = self._slots_para_layout(
            base["layout"], base["ancho"], base["alto"],
            base["n_fotos"], base["cols"], base["padding"], base["gap"])
        return base

    # ── Generación de slots ────────────────────────────────────────────────────

    def _slots_para_layout(self, layout: str, W: int, H: int,
                           n_fotos: int, cols: int,
                           padding: int, gap: int) -> list[dict]:
        if layout == "dos_columnas" and cols == 2:
            return self._slots_dos_columnas(W, H, n_fotos, padding, gap)
        elif layout == "con_texto":
            return self._slots_con_texto(W, H, n_fotos, padding, gap)
        else:
            return self._slots_simetrico(W, H, n_fotos, padding, gap)

    @staticmethod
    def _slots_simetrico(W, H, n, padding, gap) -> list[dict]:
        foto_w = W - padding * 2
        total_h = H - padding * 2 - gap * (n - 1)
        foto_h = max(20, total_h // n)
        return [
            {"type": "foto", "orden": i + 1,
             "x": padding, "y": padding + i * (foto_h + gap),
             "w": foto_w, "h": foto_h}
            for i in range(n)
        ]

    @staticmethod
    def _slots_dos_columnas(W, H, n, padding, gap) -> list[dict]:
        filas = (n + 1) // 2
        foto_w = (W - padding * 2 - gap) // 2
        foto_h = (H - padding * 2 - gap * (filas - 1)) // filas
        slots = []
        for i in range(n):
            col = i % 2
            fila = i // 2
            x = padding + col * (foto_w + gap)
            y = padding + fila * (foto_h + gap)
            slots.append({"type": "foto", "orden": i + 1, "x": x, "y": y,
                          "w": foto_w, "h": foto_h})
        return slots

    @staticmethod
    def _slots_con_texto(W, H, n, padding, gap, branding_h: int | None = None) -> list[dict]:
        # Panel de branding ~22% del área útil, pero mínimo 160px
        util_h = H - padding * 2
        if branding_h is None:
            branding_h = max(160, int(util_h * 0.22))

        available = util_h - branding_h - gap * n
        foto_h = max(20, available // n)
        foto_w = W - padding * 2

        slots = []
        for i in range(n):
            slots.append({"type": "foto", "orden": i + 1,
                          "x": padding, "y": padding + i * (foto_h + gap),
                          "w": foto_w, "h": foto_h})
        y_texto = padding + n * (foto_h + gap)
        slots.append({
            "type": "texto",
            "orden": n + 1,
            "x": padding, "y": y_texto,
            "w": foto_w, "h": branding_h,
            "texto_principal": "",
            "texto_sub": "",
            "bg_color": "#0d0d0d",
            "color": "#ffffff",
            "color_sub": "#888888",
            "font_size": 32,
            "font_size_sub": 18,
            "font_family": "Arial",
            "bold_principal": True,
            "bold_sub": False,
            "logo": None,
        })
        return slots

    def _recalcular_slots(self):
        cfg = self._config
        nuevos = self._slots_para_layout(
            cfg["layout"], cfg["ancho"], cfg["alto"],
            cfg["n_fotos"], cfg["cols"],
            cfg["padding"], cfg["gap"])
        # Preservar config de texto si existía
        textos_viejos = {s["orden"]: s for s in cfg.get("slots", [])
                         if s.get("type") == "texto"}
        for s in nuevos:
            if s.get("type") == "texto" and s["orden"] in textos_viejos:
                viejo = textos_viejos[s["orden"]]
                for k in ("texto_principal", "texto_sub", "bg_color",
                           "color", "color_sub", "font_size", "font_size_sub", "logo"):
                    s[k] = viejo.get(k, s.get(k, ""))
        cfg["slots"] = nuevos

    # ── UI ─────────────────────────────────────────────────────────────────────

    def _build_ui(self):
        # Panel izquierdo: controles
        left = ctk.CTkScrollableFrame(self, fg_color=C["bg_card"],
                                       corner_radius=0, width=400)
        left.pack(side="left", fill="y")

        self._S(left, "Editor de plantilla", big=True)

        # Nombre
        self._sec(left, "Nombre")
        self.nombre_var = ctk.StringVar(value=self._config["nombre"])
        self.nombre_var.trace_add("write", lambda *_: self._on_change())
        ctk.CTkEntry(left, textvariable=self.nombre_var, height=38).pack(
            padx=16, fill="x", pady=(0, 10))

        # Formato
        self._sec(left, "Formato")
        self.fmt_var = ctk.StringVar(value=self._config["formato"])
        fmt_f = ctk.CTkFrame(left, fg_color=C["bg_hover"], corner_radius=10,
                              border_width=1, border_color=C["border"])
        fmt_f.pack(padx=16, fill="x", pady=(0, 10))
        for fmt in FORMATOS:
            ctk.CTkRadioButton(fmt_f, text=fmt["label"],
                               variable=self.fmt_var, value=fmt["key"],
                               fg_color=C["primary"], text_color=C["text"],
                               command=self._on_formato_change).pack(
                anchor="w", padx=12, pady=5)

        # Layout / disposición
        self._sec(left, "Disposición de fotos")
        self.layout_var = ctk.StringVar(value=self._config.get("layout", "simetrico"))
        lay_f = ctk.CTkFrame(left, fg_color=C["bg_hover"], corner_radius=10,
                              border_width=1, border_color=C["border"])
        lay_f.pack(padx=16, fill="x", pady=(0, 10))
        for lay in LAYOUT_PRESETS:
            row = ctk.CTkFrame(lay_f, fg_color="transparent")
            row.pack(fill="x", padx=8, pady=4)
            ctk.CTkRadioButton(row, text=lay["label"],
                               variable=self.layout_var, value=lay["key"],
                               fg_color=C["primary"], text_color=C["text"],
                               command=self._on_layout_change).pack(side="left")
            ctk.CTkLabel(row, text=lay["desc"], font=ctk.CTkFont(size=10),
                         text_color=C["text_muted"]).pack(side="left", padx=(8, 0))

        # Espaciado
        self._sec(left, "Espaciado")
        self._slider_row(left, "Margen exterior:", self._config.get("padding", 24),
                         0, 80, 16, "padding_var")
        self._slider_row(left, "Gap entre fotos:", self._config.get("gap", 14),
                         0, 50, 8, "gap_var")

        # Fondo
        self._sec(left, "Fondo")
        f_row = ctk.CTkFrame(left, fg_color="transparent")
        f_row.pack(padx=16, fill="x", pady=(0, 4))
        self.lbl_fondo_color = ctk.CTkLabel(f_row, text="",
                                             width=30, height=30, corner_radius=6,
                                             fg_color=self._config.get("fondo_color", "#111"))
        self.lbl_fondo_color.pack(side="left", padx=(0, 8))
        ctk.CTkButton(f_row, text="Color", width=90, height=32,
                      fg_color="transparent", border_width=1, border_color=C["border"],
                      text_color=C["text_gray"],
                      command=self._elegir_fondo_color).pack(side="left", padx=(0, 6))
        ctk.CTkButton(f_row, text="Imagen", width=90, height=32,
                      fg_color="transparent", border_width=1, border_color=C["border"],
                      text_color=C["text_gray"],
                      command=self._elegir_fondo_imagen).pack(side="left")
        self.lbl_fondo_path = ctk.CTkLabel(left, text="",
                                            font=ctk.CTkFont(size=10),
                                            text_color=C["text_muted"])
        self.lbl_fondo_path.pack(padx=16, anchor="w", pady=(0, 10))

        # Panel de texto (solo si layout == con_texto)
        self.frm_texto_panel = ctk.CTkFrame(left, fg_color="transparent")
        self.frm_texto_panel.pack(padx=0, fill="x")
        self._build_texto_panel()

        # Orden de slots (foto slots)
        self.frm_orden = ctk.CTkFrame(left, fg_color="transparent")
        self.frm_orden.pack(padx=0, fill="x")
        self._build_orden_ui()

        # Botones guardar/cancelar
        btns = ctk.CTkFrame(left, fg_color="transparent")
        btns.pack(padx=16, pady=12, fill="x")
        ctk.CTkButton(btns, text="Guardar plantilla", height=46,
                      fg_color=C["primary"], text_color="#ffffff",
                      font=ctk.CTkFont(size=14, weight="bold"),
                      command=self._guardar).pack(fill="x", pady=(0, 8))
        ctk.CTkButton(btns, text="Cancelar", height=36,
                      fg_color="transparent", border_width=1, border_color=C["border"],
                      text_color=C["text_gray"],
                      command=self.destroy).pack(fill="x")

        # Panel derecho: preview con zoom
        right = ctk.CTkFrame(self, fg_color="transparent")
        right.pack(side="left", fill="both", expand=True)

        hdr_right = ctk.CTkFrame(right, fg_color="transparent")
        hdr_right.pack(fill="x", padx=16, pady=(20, 4))
        ctk.CTkLabel(hdr_right, text="Vista previa con fotos de muestra",
                     font=ctk.CTkFont(size=13, weight="bold"),
                     text_color=C["text_gray"]).pack(side="left")

        # Controles de zoom
        zoom_row = ctk.CTkFrame(hdr_right, fg_color="transparent")
        zoom_row.pack(side="right")
        ctk.CTkButton(zoom_row, text="−", width=32, height=28,
                      fg_color="transparent", border_width=1, border_color=C["border"],
                      text_color=C["text_gray"],
                      command=self._zoom_out).pack(side="left", padx=2)
        self.lbl_zoom = ctk.CTkLabel(zoom_row, text="18%", width=44,
                                      font=ctk.CTkFont(size=11),
                                      text_color=C["text_gray"])
        self.lbl_zoom.pack(side="left")
        ctk.CTkButton(zoom_row, text="+", width=32, height=28,
                      fg_color="transparent", border_width=1, border_color=C["border"],
                      text_color=C["text_gray"],
                      command=self._zoom_in).pack(side="left", padx=2)
        ctk.CTkButton(zoom_row, text="⊙", width=32, height=28,
                      fg_color="transparent", border_width=1, border_color=C["border"],
                      text_color=C["primary"],
                      command=self._zoom_fit).pack(side="left", padx=(6, 0))

        # Canvas scrollable para el preview
        canvas_frame = tk.Frame(right, bg=C["bg_card"],
                                highlightthickness=1,
                                highlightbackground=C["border"])
        canvas_frame.pack(fill="both", expand=True, padx=16, pady=(0, 4))

        self.prev_canvas = tk.Canvas(canvas_frame, bg=C["bg_card"],
                                      highlightthickness=0)
        vsb = tk.Scrollbar(canvas_frame, orient="vertical",
                            command=self.prev_canvas.yview)
        hsb = tk.Scrollbar(canvas_frame, orient="horizontal",
                            command=self.prev_canvas.xview)
        self.prev_canvas.configure(yscrollcommand=vsb.set,
                                    xscrollcommand=hsb.set)
        vsb.pack(side="right", fill="y")
        hsb.pack(side="bottom", fill="x")
        self.prev_canvas.pack(fill="both", expand=True)

        self.prev_canvas.bind("<MouseWheel>", self._on_mousewheel)
        self.prev_canvas.bind("<Button-4>", self._on_mousewheel)
        self.prev_canvas.bind("<Button-5>", self._on_mousewheel)

        self.lbl_dims = ctk.CTkLabel(right, text="",
                                      font=ctk.CTkFont(size=11),
                                      text_color=C["text_muted"])
        self.lbl_dims.pack(pady=(2, 8))

    # ── Sub-secciones UI ───────────────────────────────────────────────────────

    def _build_texto_panel(self):
        for w in self.frm_texto_panel.winfo_children():
            w.destroy()

        slot_texto = next((s for s in self._config.get("slots", [])
                           if s.get("type") == "texto"), None)
        if not slot_texto:
            return

        self._sec(self.frm_texto_panel, "Panel de texto (branding)")
        inner = ctk.CTkFrame(self.frm_texto_panel, fg_color=C["bg_hover"],
                              corner_radius=10, border_width=1, border_color=C["border"])
        inner.pack(padx=16, fill="x", pady=(0, 10))

        # ── Textos ────────────────────────────────────────────────────────────
        ctk.CTkLabel(inner, text="Texto principal:",
                     font=ctk.CTkFont(size=11), text_color=C["text_gray"]).pack(
            padx=12, anchor="w", pady=(8, 2))
        self.tp_principal_var = ctk.StringVar(
            value=slot_texto.get("texto_principal", ""))
        self.tp_principal_var.trace_add("write", lambda *_: self._on_texto_panel_change())
        ctk.CTkEntry(inner, textvariable=self.tp_principal_var,
                     placeholder_text="Ej: Mis 15 Juanita",
                     height=36).pack(padx=12, fill="x", pady=(0, 6))

        ctk.CTkLabel(inner, text="Subtítulo:",
                     font=ctk.CTkFont(size=11), text_color=C["text_gray"]).pack(
            padx=12, anchor="w", pady=(0, 2))
        self.tp_sub_var = ctk.StringVar(value=slot_texto.get("texto_sub", ""))
        self.tp_sub_var.trace_add("write", lambda *_: self._on_texto_panel_change())
        ctk.CTkEntry(inner, textvariable=self.tp_sub_var,
                     placeholder_text="Ej: 15 de marzo 2025",
                     height=36).pack(padx=12, fill="x", pady=(0, 6))

        # ── Tipografía ────────────────────────────────────────────────────────
        ctk.CTkFrame(inner, height=1, fg_color=C["border"]).pack(fill="x", padx=12, pady=(4, 8))
        ctk.CTkLabel(inner, text="Tipografía",
                     font=ctk.CTkFont(size=11, weight="bold"),
                     text_color=C["text_gray"]).pack(padx=12, anchor="w")

        font_row = ctk.CTkFrame(inner, fg_color="transparent")
        font_row.pack(padx=12, fill="x", pady=(4, 6))
        ctk.CTkLabel(font_row, text="Fuente:", width=70,
                     font=ctk.CTkFont(size=11), text_color=C["text_gray"]).pack(side="left")
        self.tp_font_var = ctk.StringVar(
            value=slot_texto.get("font_family", "Arial"))
        self.tp_font_var.trace_add("write", lambda *_: self._on_texto_panel_change())
        ctk.CTkComboBox(font_row, variable=self.tp_font_var,
                        values=FONT_FAMILIES, width=200,
                        command=lambda _: self._on_texto_panel_change()).pack(side="left")

        # Tamaño principal
        sz_row = ctk.CTkFrame(inner, fg_color="transparent")
        sz_row.pack(padx=12, fill="x", pady=(0, 4))
        ctk.CTkLabel(sz_row, text="Tam. principal:", width=110,
                     font=ctk.CTkFont(size=11), text_color=C["text_gray"]).pack(side="left")
        self.tp_size_var = ctk.IntVar(value=slot_texto.get("font_size", 28))
        ctk.CTkSlider(sz_row, from_=8, to=120, number_of_steps=56,
                      variable=self.tp_size_var, width=110,
                      button_color=C["primary"],
                      command=lambda _: self._on_texto_panel_change()).pack(side="left", padx=4)
        ctk.CTkLabel(sz_row, textvariable=self.tp_size_var,
                     text_color=C["text"], width=30).pack(side="left")
        self.tp_bold_var = ctk.BooleanVar(value=slot_texto.get("bold_principal", True))
        ctk.CTkCheckBox(sz_row, text="Bold", variable=self.tp_bold_var,
                        fg_color=C["primary"], width=60,
                        command=self._on_texto_panel_change).pack(side="left", padx=(6, 0))

        # Tamaño subtítulo
        sz_row2 = ctk.CTkFrame(inner, fg_color="transparent")
        sz_row2.pack(padx=12, fill="x", pady=(0, 8))
        ctk.CTkLabel(sz_row2, text="Tam. subtítulo:", width=110,
                     font=ctk.CTkFont(size=11), text_color=C["text_gray"]).pack(side="left")
        self.tp_size_sub_var = ctk.IntVar(value=slot_texto.get("font_size_sub", 16))
        ctk.CTkSlider(sz_row2, from_=8, to=80, number_of_steps=36,
                      variable=self.tp_size_sub_var, width=110,
                      button_color=C["primary"],
                      command=lambda _: self._on_texto_panel_change()).pack(side="left", padx=4)
        ctk.CTkLabel(sz_row2, textvariable=self.tp_size_sub_var,
                     text_color=C["text"], width=30).pack(side="left")
        self.tp_bold_sub_var = ctk.BooleanVar(value=slot_texto.get("bold_sub", False))
        ctk.CTkCheckBox(sz_row2, text="Bold", variable=self.tp_bold_sub_var,
                        fg_color=C["primary"], width=60,
                        command=self._on_texto_panel_change).pack(side="left", padx=(6, 0))

        # ── Posición y tamaño ─────────────────────────────────────────────────
        ctk.CTkFrame(inner, height=1, fg_color=C["border"]).pack(fill="x", padx=12, pady=(4, 8))
        ctk.CTkLabel(inner, text="Posición y tamaño",
                     font=ctk.CTkFont(size=11, weight="bold"),
                     text_color=C["text_gray"]).pack(padx=12, anchor="w")

        W = self._config["ancho"]
        H = self._config["alto"]

        for lbl, attr, mn, mx, default_key in [
            ("X:",  "tp_x_var",  0, W, "x"),
            ("Y:",  "tp_y_var",  0, H, "y"),
            ("Ancho:", "tp_w_var", 50, W, "w"),
            ("Alto:",  "tp_h_var", 20, H // 2, "h"),
        ]:
            r = ctk.CTkFrame(inner, fg_color="transparent")
            r.pack(padx=12, fill="x", pady=2)
            ctk.CTkLabel(r, text=lbl, width=55,
                         font=ctk.CTkFont(size=11), text_color=C["text_gray"]).pack(side="left")
            var = ctk.IntVar(value=slot_texto.get(default_key, 0))
            setattr(self, attr, var)
            steps = max(1, (mx - mn) // 4)
            ctk.CTkSlider(r, from_=mn, to=mx, number_of_steps=steps,
                          variable=var, width=130,
                          button_color=C["primary"],
                          command=lambda _: self._on_texto_panel_change()).pack(side="left", padx=4)
            ctk.CTkLabel(r, textvariable=var,
                         text_color=C["text"], width=40).pack(side="left")

        ctk.CTkFrame(inner, height=1, fg_color=C["border"]).pack(fill="x", padx=12, pady=(8, 6))

        # ── Colores ───────────────────────────────────────────────────────────
        col_row = ctk.CTkFrame(inner, fg_color="transparent")
        col_row.pack(padx=12, pady=(0, 8), fill="x")
        ctk.CTkLabel(col_row, text="Fondo panel:",
                     font=ctk.CTkFont(size=11), text_color=C["text_gray"],
                     width=90).pack(side="left")
        self.tp_bg_lbl = ctk.CTkLabel(col_row, text="",
                                       width=28, height=28, corner_radius=6,
                                       fg_color=slot_texto.get("bg_color", "#1a1a1a"))
        self.tp_bg_lbl.pack(side="left", padx=(0, 8))
        ctk.CTkButton(col_row, text="Cambiar", width=80, height=28,
                      fg_color="transparent", border_width=1, border_color=C["border"],
                      text_color=C["text_gray"],
                      command=self._elegir_color_panel).pack(side="left")

        col_row2 = ctk.CTkFrame(inner, fg_color="transparent")
        col_row2.pack(padx=12, pady=(0, 10), fill="x")
        ctk.CTkLabel(col_row2, text="Color texto:",
                     font=ctk.CTkFont(size=11), text_color=C["text_gray"],
                     width=90).pack(side="left")
        self.tp_color_lbl = ctk.CTkLabel(col_row2, text="",
                                          width=28, height=28, corner_radius=6,
                                          fg_color=slot_texto.get("color", "#ffffff"))
        self.tp_color_lbl.pack(side="left", padx=(0, 8))
        ctk.CTkButton(col_row2, text="Cambiar", width=80, height=28,
                      fg_color="transparent", border_width=1, border_color=C["border"],
                      text_color=C["text_gray"],
                      command=self._elegir_color_texto_panel).pack(side="left")

    def _build_orden_ui(self):
        for w in self.frm_orden.winfo_children():
            w.destroy()

        foto_slots = [s for s in self._config.get("slots", [])
                      if s.get("type") == "foto"]
        if len(foto_slots) <= 1:
            return

        self._sec(self.frm_orden, "Orden de las fotos")
        ctk.CTkLabel(self.frm_orden,
                     text="Cambiá el orden en que se muestran las fotos en la tira.",
                     font=ctk.CTkFont(size=11), text_color=C["text_muted"],
                     wraplength=340).pack(padx=16, anchor="w", pady=(0, 6))

        for i, slot in enumerate(foto_slots):
            row = ctk.CTkFrame(self.frm_orden, fg_color=C["bg_hover"],
                                corner_radius=8, border_width=1, border_color=C["border"])
            row.pack(padx=16, fill="x", pady=2)
            ctk.CTkLabel(row, text=f"Posición {i + 1}  →  Foto {slot['orden']}",
                         font=ctk.CTkFont(size=12), text_color=C["text"]).pack(
                side="left", padx=12, pady=8)
            if i > 0:
                ctk.CTkButton(row, text="↑", width=32, height=28,
                              fg_color="transparent", text_color=C["primary"],
                              command=lambda idx=i: self._mover_slot(idx, -1)).pack(
                    side="right", padx=2, pady=4)
            if i < len(foto_slots) - 1:
                ctk.CTkButton(row, text="↓", width=32, height=28,
                              fg_color="transparent", text_color=C["primary"],
                              command=lambda idx=i: self._mover_slot(idx, 1)).pack(
                    side="right", padx=2, pady=4)

    # ── Helpers UI ─────────────────────────────────────────────────────────────

    def _S(self, parent, texto: str, big: bool = False):
        ctk.CTkLabel(parent, text=texto,
                     font=ctk.CTkFont(size=17 if big else 12,
                                      weight="bold"),
                     text_color=C["text"] if big else C["text_gray"]).pack(
            padx=16, anchor="w", pady=(16 if big else 10, 3))

    def _sec(self, parent, texto: str):
        ctk.CTkLabel(parent, text=texto,
                     font=ctk.CTkFont(size=12, weight="bold"),
                     text_color=C["text_gray"]).pack(padx=16, anchor="w", pady=(10, 3))

    def _slider_row(self, parent, label: str, val: int, mn: int, mx: int,
                    steps: int, attr: str):
        row = ctk.CTkFrame(parent, fg_color="transparent")
        row.pack(padx=16, fill="x", pady=(0, 6))
        ctk.CTkLabel(row, text=label, text_color=C["text_gray"],
                     font=ctk.CTkFont(size=12), width=120).pack(side="left")
        var = ctk.IntVar(value=val)
        setattr(self, attr, var)
        ctk.CTkSlider(row, from_=mn, to=mx, number_of_steps=steps,
                      variable=var, width=110,
                      button_color=C["primary"],
                      command=lambda _: self._on_change()).pack(side="left", padx=4)
        ctk.CTkLabel(row, textvariable=var,
                     text_color=C["text"], width=30).pack(side="left")

    # ── Acciones ───────────────────────────────────────────────────────────────

    def _on_formato_change(self):
        fmt = get_formato(self.fmt_var.get())
        self._config.update({
            "formato":  fmt["key"],
            "ancho":    fmt["w"],
            "alto":     fmt["h"],
            "n_fotos":  fmt["n_fotos"],
            "cols":     fmt["cols"],
        })
        self._recalcular_slots()
        self._refresh_all()

    def _on_layout_change(self):
        self._config["layout"] = self.layout_var.get()
        self._recalcular_slots()
        self._refresh_all()

    def _on_change(self):
        self._config["padding"] = self.padding_var.get()
        self._config["gap"]     = self.gap_var.get()
        self._recalcular_slots()
        self.after(80, self._refresh_preview)

    def _on_texto_panel_change(self):
        slot_texto = next((s for s in self._config.get("slots", [])
                           if s.get("type") == "texto"), None)
        if slot_texto:
            slot_texto["texto_principal"] = self.tp_principal_var.get()
            slot_texto["texto_sub"]       = self.tp_sub_var.get()
            slot_texto["font_family"]     = self.tp_font_var.get()
            slot_texto["font_size"]       = self.tp_size_var.get()
            slot_texto["font_size_sub"]   = self.tp_size_sub_var.get()
            slot_texto["bold_principal"]  = self.tp_bold_var.get()
            slot_texto["bold_sub"]        = self.tp_bold_sub_var.get()
            slot_texto["x"] = self.tp_x_var.get()
            slot_texto["y"] = self.tp_y_var.get()
            slot_texto["w"] = self.tp_w_var.get()
            slot_texto["h"] = self.tp_h_var.get()
        self.after(80, self._refresh_preview)

    def _mover_slot(self, idx: int, delta: int):
        foto_slots = [s for s in self._config["slots"] if s.get("type") == "foto"]
        j = idx + delta
        if 0 <= j < len(foto_slots):
            # Swap orden
            foto_slots[idx]["orden"], foto_slots[j]["orden"] = \
                foto_slots[j]["orden"], foto_slots[idx]["orden"]
        self._build_orden_ui()
        self._refresh_preview()

    def _elegir_fondo_color(self):
        c = colorchooser.askcolor(
            color=self._config.get("fondo_color", "#111"), title="Color de fondo")[1]
        if c:
            self._config["fondo_color"] = c
            self._config["fondo_imagen"] = None
            self.lbl_fondo_color.configure(fg_color=c)
            self.lbl_fondo_path.configure(text=c)
            self._refresh_preview()

    def _elegir_fondo_imagen(self):
        path = filedialog.askopenfilename(
            title="Imagen de fondo",
            filetypes=[("Imágenes", "*.png *.jpg *.jpeg *.bmp"), ("Todos", "*.*")])
        if path:
            self._config["fondo_imagen"] = path
            self.lbl_fondo_path.configure(text=os.path.basename(path))
            self._refresh_preview()

    def _elegir_color_panel(self):
        slot_texto = next((s for s in self._config.get("slots", [])
                           if s.get("type") == "texto"), None)
        if not slot_texto:
            return
        c = colorchooser.askcolor(
            color=slot_texto.get("bg_color", "#1a1a1a"), title="Color fondo panel")[1]
        if c:
            slot_texto["bg_color"] = c
            self.tp_bg_lbl.configure(fg_color=c)
            self._refresh_preview()

    def _elegir_color_texto_panel(self):
        slot_texto = next((s for s in self._config.get("slots", [])
                           if s.get("type") == "texto"), None)
        if not slot_texto:
            return
        c = colorchooser.askcolor(
            color=slot_texto.get("color", "#ffffff"), title="Color texto panel")[1]
        if c:
            slot_texto["color"] = c
            self.tp_color_lbl.configure(fg_color=c)
            self._refresh_preview()

    def _refresh_all(self):
        self._build_texto_panel()
        self._build_orden_ui()
        self._refresh_preview()

    # ── Zoom ───────────────────────────────────────────────────────────────────

    def _zoom_in(self):
        if self._zoom_idx < len(self._ZOOM_STEPS) - 1:
            self._zoom_idx += 1
            self._refresh_preview()

    def _zoom_out(self):
        if self._zoom_idx > 0:
            self._zoom_idx -= 1
            self._refresh_preview()

    def _zoom_fit(self):
        self._zoom_idx = 2   # volver a escala por defecto 0.18
        self._refresh_preview()

    def _on_mousewheel(self, event):
        if event.num == 4 or event.delta > 0:
            self._zoom_in()
        else:
            self._zoom_out()

    # ── Preview ────────────────────────────────────────────────────────────────

    def _refresh_preview(self):
        W = self._config["ancho"]
        H = self._config["alto"]
        scale = self._ZOOM_STEPS[self._zoom_idx]
        pw = max(80, int(W * scale))
        ph = max(120, int(H * scale))

        img = self._render_preview(W, H)
        img = img.resize((pw, ph), Image.LANCZOS)

        self._preview_photo = ImageTk.PhotoImage(img)
        self.prev_canvas.delete("all")
        self.prev_canvas.create_image(pw // 2, ph // 2, anchor="center",
                                       image=self._preview_photo)
        self.prev_canvas.configure(scrollregion=(0, 0, pw, ph))

        pct = int(scale * 100)
        self.lbl_zoom.configure(text=f"{pct}%")

        n_fotos = sum(1 for s in self._config.get("slots", []) if s["type"] == "foto")
        self.lbl_dims.configure(
            text=f"{W} × {H} px  ·  {n_fotos} fotos  ·  "
                 f"{W/300*2.54:.1f} × {H/300*2.54:.1f} cm")

    def _render_preview(self, W: int, H: int) -> Image.Image:
        # Fondo
        fi = self._config.get("fondo_imagen")
        if fi and os.path.exists(fi):
            canvas = Image.open(fi).convert("RGB").resize((W, H), Image.LANCZOS)
        else:
            canvas = Image.new("RGB", (W, H),
                               color=self._config.get("fondo_color", "#111111"))

        draw = ImageDraw.Draw(canvas)
        foto_idx = 0

        for slot in sorted(self._config.get("slots", []),
                           key=lambda s: s.get("orden", 0)):
            x, y, sw, sh = slot["x"], slot["y"], slot["w"], slot["h"]

            if slot["type"] == "foto":
                # Foto de muestra con color y etiqueta
                orden = slot.get("orden", foto_idx + 1)
                muestra = _foto_muestra(sw, sh, foto_idx, f"Foto {orden}")
                canvas.paste(muestra, (x, y))
                foto_idx += 1

            elif slot["type"] == "texto":
                # Panel de texto
                bg = slot.get("bg_color", "#1a1a1a")
                color_txt = slot.get("color", "#ffffff")
                color_sub = slot.get("color_sub", "#aaaaaa")
                draw.rectangle([x, y, x + sw, y + sh], fill=bg)

                txt_p = slot.get("texto_principal", "")
                txt_s = slot.get("texto_sub", "")

                family  = slot.get("font_family", "Arial")
                bold_p  = slot.get("bold_principal", True)
                bold_s  = slot.get("bold_sub", False)
                cy = y + sh // 2
                if txt_p:
                    fnt_p = _font(slot.get("font_size", 28), family=family, bold=bold_p)
                    bbox = draw.textbbox((0, 0), txt_p, font=fnt_p)
                    tw = bbox[2] - bbox[0]
                    th = bbox[3] - bbox[1]
                    offset = -(th // 2 + 4) if txt_s else 0
                    draw.text((x + (sw - tw) // 2, cy - th // 2 + offset),
                              txt_p, fill=color_txt, font=fnt_p)
                if txt_s:
                    fnt_s = _font(slot.get("font_size_sub", 16), family=family, bold=bold_s)
                    bbox = draw.textbbox((0, 0), txt_s, font=fnt_s)
                    tw = bbox[2] - bbox[0]
                    y_sub = cy + (bbox[3] - bbox[1]) // 2 + 6
                    draw.text((x + (sw - tw) // 2, y_sub),
                              txt_s, fill=color_sub, font=fnt_s)

        # Logo global
        logo = self._config.get("logo")
        if logo and logo.get("path") and os.path.exists(logo["path"]):
            try:
                lg = Image.open(logo["path"]).convert("RGBA")
                lg = lg.resize((logo.get("w", 100), logo.get("h", 60)), Image.LANCZOS)
                canvas.paste(lg, (logo.get("x", 10), logo.get("y", 10)), lg)
            except Exception:
                pass

        return canvas

    # ── Guardar ────────────────────────────────────────────────────────────────

    def _guardar(self):
        self._config["nombre"] = self.nombre_var.get().strip() or "Plantilla"
        self._on_change()

        os.makedirs(TEMPLATES_DIR, exist_ok=True)
        slug = re.sub(r"[^a-z0-9_]", "_",
                      self._config["nombre"].lower()) + f"_{int(time.time())}"
        ruta_json    = os.path.join(TEMPLATES_DIR, f"{slug}.json")
        ruta_preview = os.path.join(TEMPLATES_DIR, f"{slug}_preview.png")

        with open(ruta_json, "w", encoding="utf-8") as f:
            json.dump(self._config, f, ensure_ascii=False, indent=2)

        preview = self._render_preview(self._config["ancho"], self._config["alto"])
        preview.thumbnail((200, 340), Image.LANCZOS)
        preview.save(ruta_preview)

        pid = self.db.crear_plantilla(
            self.usuario_id, self._config["nombre"],
            ruta_json, ruta_preview)

        if self.on_guardar:
            self.on_guardar(pid)
        self.destroy()
