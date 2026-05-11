"""
CaptureUI — ventana fullscreen de la cabina de fotos.

Flujo:
  IDLE → COUNTDOWN → CAPTURA (x5) → SELECCION → PREVIEW_TIRA → IMPRESION → GRACIAS → IDLE
"""
import os
import time
import threading
import tkinter as tk
import customtkinter as ctk
from tkinter import messagebox
from PIL import Image, ImageTk

from config.settings import COLORS, FOTO_SESSION, PHOTOS_DIR
from config.formatos import get_formato
from modules.database import DatabaseManager
from modules.camera_manager import CameraManager
from modules.i18n import t

C = COLORS
FS = FOTO_SESSION


class CaptureUI(tk.Toplevel):
    ESTADOS = ("idle", "countdown", "capturando", "seleccion", "preview", "imprimiendo", "gracias")

    def __init__(self, parent, db: DatabaseManager, evento: dict):
        super().__init__(parent)
        self.db = db
        self.evento = evento
        self.parent_app = parent

        self.configure(bg=C["bg"])
        self.title("PhotoBooth — Cabina")
        self.attributes("-topmost", True)
        # Aplicar fullscreen diferido — en Windows debe ocurrir después del mapeo
        self.after(50, lambda: self.attributes("-fullscreen", True))

        fmt = get_formato(evento.get("formato", "tira_5x15"))
        self._n_elegir: int = fmt["n_fotos"]
        self._n_total: int = fmt["n_fotos"] + 2

        self.cam = CameraManager()
        self._camara_index: int = int(evento.get("camara_index") or db.get_config("camara_index", "0"))
        self._estado: str = "idle"
        self._fotos: list[Image.Image] = []          # PIL Images capturadas
        self._rutas_fotos: list[str] = []             # rutas guardadas en disco
        self._indices_elegidos: set[int] = set()
        self._sesion_id: int | None = None
        self._countdown_val: int = 0
        self._countdown_pausado: bool = False
        self._cd_after_id: str | None = None
        self._foto_actual: int = 0
        self._idle_timer: str | None = None
        self._slideshow_after_id: str | None = None
        self._cd_texto: str = ""        # texto del countdown a dibujar sobre la cámara
        self._cd_overlay_cache: dict = {}  # {(txt,w,h): imagen pre-renderizada}
        self._slide_tiras: list[str] = []
        self._slide_idx: int = 0
        self._slide_photo_ref = None   # evitar GC

        self._ctrl_hide_timer: str | None = None
        self._poll_after_id: str | None = None
        self._build_ui()
        # CTkToplevel en Windows necesita tiempo para renderizar antes de place()
        self.after(200, self._iniciar)

        self.bind("<Escape>", lambda _: self._cerrar())
        self.bind("<space>", lambda _: self._on_espacio())
        self.bind("<Motion>", self._on_mouse_move)
        self.bind("<Button-1>", self._on_click)
        self.bind("<F11>", lambda _: self._toggle_fullscreen())

    # ── UI ─────────────────────────────────────────────────────────────────────

    def _build_ui(self):
        self.columnconfigure(0, weight=1)
        self.rowconfigure(0, weight=1)

        # Feed de cámara — tk.Label nativo para compatibilidad con ImageTk.PhotoImage
        self.lbl_preview = tk.Label(self, bg="black", bd=0, highlightthickness=0)
        self.lbl_preview.grid(row=0, column=0, sticky="nsew")
        # Los overlays se colocan con place() directamente sobre self,
        # encima del feed. CTkFrame "transparent" NO es transparente en
        # CustomTkinter, por eso no usamos un frame intermedio.

        # Widgets de overlay (se muestran según estado)
        self._build_overlay_idle()
        self._build_overlay_countdown()
        self._build_overlay_flash()
        self._build_overlay_freeze()
        self._build_overlay_seleccion()
        self._build_overlay_reorden()
        self._build_overlay_preview_tira()
        self._build_overlay_gracias()
        self._build_barra_progreso()

        # Barra de controles — SE CREA AL FINAL para quedar siempre encima de overlays
        self._is_fullscreen = True
        self._ctrl_bar = ctk.CTkFrame(self, fg_color="#1a1a1a", corner_radius=22,
                                      border_width=1, border_color="#333")
        self._ctrl_bar.place(relx=1.0, rely=0.0, anchor="ne", x=-16, y=16)

        self._btn_fs = ctk.CTkButton(
            self._ctrl_bar, text="⛶", width=40, height=40, corner_radius=20,
            fg_color="transparent", text_color="#aaaaaa",
            hover_color="#2d2d2d", font=ctk.CTkFont(size=18),
            command=self._toggle_fullscreen,
        )
        self._btn_fs.pack(side="left", padx=(4, 0), pady=4)

        ctk.CTkButton(
            self._ctrl_bar, text="🖨", width=40, height=40, corner_radius=20,
            fg_color="transparent", text_color="#aaaaaa",
            hover_color="#2d2d2d", font=ctk.CTkFont(size=16),
            command=self._abrir_panel_cola,
        ).pack(side="left", padx=0, pady=4)

        ctk.CTkButton(
            self._ctrl_bar, text="✕", width=40, height=40, corner_radius=20,
            fg_color="transparent", text_color="#cc4444",
            hover_color="#2d1010", font=ctk.CTkFont(size=16, weight="bold"),
            command=self._cerrar,
        ).pack(side="left", padx=(0, 4), pady=4)

        self._ctrl_bar.place_forget()   # oculta hasta hover en esquina
        self._ocultar_todos()

    # ── Overlays ───────────────────────────────────────────────────────────────

    def _build_overlay_idle(self):
        self.frm_idle = ctk.CTkFrame(self, fg_color="#08050f", corner_radius=0)

        # ── Slideshow de tiras (panel derecho) ───────────────────────────────
        # Marco decorativo con borde primary; se muestra solo si hay tiras
        self._slide_card = ctk.CTkFrame(
            self.frm_idle,
            fg_color="#110d1a",
            corner_radius=20,
            border_width=2,
            border_color=C["primary"],
        )
        self.lbl_slide = ctk.CTkLabel(self._slide_card, text="", fg_color="transparent")
        self.lbl_slide.pack(padx=14, pady=(14, 6))

        self.lbl_slide_info = ctk.CTkLabel(
            self._slide_card, text="",
            font=ctk.CTkFont(size=11),
            text_color=C["text_muted"],
            fg_color="transparent",
        )
        self.lbl_slide_info.pack(pady=(0, 12))

        # ── Contenido central ────────────────────────────────────────────────
        ctk.CTkLabel(self.frm_idle, text="📸",
                     font=ctk.CTkFont(size=80),
                     text_color="#ffffff").place(relx=0.38, rely=0.30, anchor="center")

        ctk.CTkLabel(self.frm_idle, text=t("cabina.idle_titulo"),
                     font=ctk.CTkFont(size=58, weight="bold"),
                     text_color=C["primary"]).place(relx=0.38, rely=0.46, anchor="center")

        ctk.CTkLabel(self.frm_idle, text=t("cabina.idle_subtitulo"),
                     font=ctk.CTkFont(size=22),
                     text_color=C["text_gray"]).place(relx=0.38, rely=0.57, anchor="center")

        ctk.CTkButton(self.frm_idle, text="✦  Tocar para comenzar  ✦",
                      height=68, width=440,
                      font=ctk.CTkFont(size=20, weight="bold"),
                      fg_color=C["primary"], text_color="#ffffff",
                      hover_color=C["primary_dark"],
                      corner_radius=34,
                      command=self._on_espacio).place(relx=0.38, rely=0.72, anchor="center")

        ctk.CTkLabel(self.frm_idle, text="o presioná  ESPACIO",
                     font=ctk.CTkFont(size=13),
                     text_color=C["text_muted"]).place(relx=0.38, rely=0.82, anchor="center")

        self.frm_idle.bind("<Button-1>", lambda _: self._on_espacio())

    def _build_overlay_countdown(self):
        # Número flotante sobre la cámara — sin fondo oscuro para no tapar la pose
        # frm_countdown es un frame fantasma solo para agrupar los place_forget()
        self.frm_countdown = ctk.CTkFrame(self, fg_color="transparent",
                                           corner_radius=0, width=1, height=1)

        # Etiqueta "Foto X de Y" — banda semiopaca en la parte superior
        self._cd_topbar = ctk.CTkFrame(self, fg_color="#1a1228",
                                        corner_radius=0, height=48)

        self.lbl_foto_n = ctk.CTkLabel(
            self._cd_topbar, text="",
            font=ctk.CTkFont(size=15, weight="bold"),
            text_color=C["text_muted"],
            fg_color="transparent")
        self.lbl_foto_n.place(relx=0.5, rely=0.5, anchor="center")

        # Número grande directo sobre la cámara, fondo transparente
        self.lbl_countdown = ctk.CTkLabel(
            self, text="3",
            font=ctk.CTkFont(size=200, weight="bold"),
            text_color=C["primary"],
            fg_color="transparent")

        # "¡Sonreí!" — pastilla pequeña centrada abajo
        self._cd_smile = ctk.CTkLabel(
            self, text="¡Sonreí! 😄",
            font=ctk.CTkFont(size=22, weight="bold"),
            text_color="#ffffff",
            fg_color="#1a1228",
            corner_radius=16)

    def _build_overlay_flash(self):
        self.frm_flash = ctk.CTkFrame(self, fg_color="#ffffff", corner_radius=0)

    def _build_overlay_freeze(self):
        self.frm_freeze = ctk.CTkFrame(self, fg_color="#08050f", corner_radius=0)

        self.lbl_freeze_foto = ctk.CTkLabel(self.frm_freeze, text="",
                                             fg_color="transparent")
        self.lbl_freeze_foto.place(relx=0.5, rely=0.47, anchor="center")

        # Badge de éxito — esquina superior izquierda, sin tapar la foto
        self._badge_freeze = ctk.CTkFrame(self.frm_freeze, fg_color=C["success"],
                                           corner_radius=14, width=220, height=36)
        self._badge_freeze.place(x=20, y=20, anchor="nw")
        self.lbl_freeze_status = ctk.CTkLabel(
            self._badge_freeze, text="",
            font=ctk.CTkFont(size=13, weight="bold"),
            text_color="#ffffff",
            fg_color="transparent")
        self.lbl_freeze_status.place(relx=0.5, rely=0.5, anchor="center")

        # Barra inferior — texto dinámico (listo / toca para continuar)
        self._barra_freeze = ctk.CTkFrame(self.frm_freeze, fg_color=C["bg_card"],
                                           corner_radius=0, height=80)
        self._barra_freeze.place(relx=0, rely=1.0, relwidth=1.0, anchor="sw")
        self.lbl_barra_freeze_txt = ctk.CTkLabel(
            self._barra_freeze, text="",
            font=ctk.CTkFont(size=18, weight="bold"),
            text_color=C["primary"],
            fg_color="transparent")
        self.lbl_barra_freeze_txt.place(relx=0.5, rely=0.5, anchor="center")

    def _build_barra_progreso(self):
        # Barra superior fija durante toda la sesión
        self.frm_progreso = ctk.CTkFrame(self, fg_color=C["bg_card"],
                                          corner_radius=0, height=72,
                                          border_width=0)
        ctk.CTkLabel(self.frm_progreso, text="FOTOS",
                     font=ctk.CTkFont(size=10, weight="bold"),
                     text_color=C["text_muted"],
                     fg_color="transparent").place(relx=0.5, rely=0.22, anchor="center")
        self.lbl_dots = ctk.CTkLabel(self.frm_progreso, text="",
                                      font=ctk.CTkFont(size=32),
                                      text_color=C["primary"],
                                      fg_color="transparent")
        self.lbl_dots.place(relx=0.5, rely=0.65, anchor="center")

    def _build_overlay_seleccion(self):
        self.frm_seleccion = ctk.CTkFrame(self, fg_color=C["bg"], corner_radius=0)

        # Header con borde inferior sutil
        hdr = ctk.CTkFrame(self.frm_seleccion, fg_color=C["bg_card"],
                           corner_radius=0, height=88)
        hdr.pack(fill="x")
        hdr.pack_propagate(False)

        self.lbl_seleccion_titulo = ctk.CTkLabel(
            hdr, text="",
            font=ctk.CTkFont(size=28, weight="bold"),
            text_color=C["text"])
        self.lbl_seleccion_titulo.pack(side="left", padx=32, pady=(0, 4))

        ctk.CTkLabel(hdr, text=t("cabina.seleccion_sub"),
                     font=ctk.CTkFont(size=14),
                     text_color=C["text_muted"]).pack(side="left", padx=(0, 32))

        self.btn_confirmar_sel = ctk.CTkButton(
            hdr, text=t("cabina.btn_confirmar"),
            width=220, height=50,
            font=ctk.CTkFont(size=15, weight="bold"),
            fg_color=C["primary"], text_color="#ffffff",
            hover_color=C["primary_dark"],
            corner_radius=25,
            state="disabled", command=self._confirmar_seleccion,
        )
        self.btn_confirmar_sel.pack(side="right", padx=32)

        self.frm_grid_fotos = ctk.CTkFrame(self.frm_seleccion, fg_color="transparent")
        self.frm_grid_fotos.pack(pady=20, padx=40, fill="both", expand=True)

        self.frm_seleccion.place(relx=0, rely=0, relwidth=1, relheight=1)

    def _build_overlay_preview_tira(self):
        self.frm_preview = ctk.CTkFrame(self, fg_color=C["bg"], corner_radius=0)

        ctk.CTkLabel(self.frm_preview, text=t("cabina.preview_titulo"),
                     font=ctk.CTkFont(size=30, weight="bold"),
                     text_color=C["primary"]).pack(pady=(28, 4))
        ctk.CTkLabel(self.frm_preview, text="¿Te gusta como quedó?",
                     font=ctk.CTkFont(size=15),
                     text_color=C["text_muted"]).pack()

        self.lbl_tira = ctk.CTkLabel(self.frm_preview, text="")
        self.lbl_tira.pack(pady=12, expand=True)

        btns = ctk.CTkFrame(self.frm_preview, fg_color="transparent")
        btns.pack(pady=(8, 32))

        ctk.CTkButton(btns, text="Siguiente sesión  →",
                      width=240, height=58,
                      fg_color=C["primary"], text_color="#ffffff",
                      hover_color=C["primary_dark"],
                      corner_radius=29,
                      font=ctk.CTkFont(size=17, weight="bold"),
                      command=self._guardar_y_continuar).pack(side="left", padx=16)

        ctk.CTkButton(btns, text="↩  " + t("cabina.btn_repetir"),
                      width=200, height=58,
                      fg_color="transparent", border_width=2, border_color=C["border"],
                      text_color=C["text_gray"],
                      hover_color=C["bg_hover"],
                      corner_radius=29,
                      font=ctk.CTkFont(size=16),
                      command=self._repetir).pack(side="left", padx=16)

        self.frm_preview.place(relx=0, rely=0, relwidth=1, relheight=1)

    def _build_overlay_reorden(self):
        self.frm_reorden = ctk.CTkFrame(self, fg_color=C["bg"], corner_radius=0)
        ctk.CTkLabel(self.frm_reorden,
                     text=t("cabina.reorden_titulo"),
                     font=ctk.CTkFont(size=24, weight="bold"),
                     text_color=C["text"]).pack(pady=(28, 4))
        ctk.CTkLabel(self.frm_reorden,
                     text=t("cabina.reorden_sub"),
                     font=ctk.CTkFont(size=13), text_color=C["text_gray"]).pack()
        self.frm_reorden_grid = ctk.CTkFrame(self.frm_reorden, fg_color="transparent")
        self.frm_reorden_grid.pack(pady=16, padx=40, fill="both", expand=True)
        ctk.CTkButton(self.frm_reorden,
                      text=t("cabina.btn_confirmar_orden"),
                      height=48, font=ctk.CTkFont(size=15, weight="bold"),
                      fg_color=C["primary"], text_color="#ffffff",
                      command=self._confirmar_orden).pack(pady=(0, 28))
        self.frm_reorden.place(relx=0, rely=0, relwidth=1, relheight=1)

    def _build_overlay_gracias(self):
        self.frm_gracias = ctk.CTkFrame(self, fg_color="#08050f", corner_radius=0)

        ctk.CTkLabel(self.frm_gracias, text="🎉",
                     font=ctk.CTkFont(size=90),
                     fg_color="transparent").place(relx=0.5, rely=0.25, anchor="center")

        ctk.CTkLabel(self.frm_gracias, text=t("cabina.gracias"),
                     font=ctk.CTkFont(size=64, weight="bold"),
                     text_color=C["primary"],
                     fg_color="transparent").place(relx=0.5, rely=0.43, anchor="center")

        self.lbl_impresion_status = ctk.CTkLabel(
            self.frm_gracias, text=t("cabina.impresion_ok"),
            font=ctk.CTkFont(size=20),
            text_color=C["text_gray"],
            fg_color="transparent")
        self.lbl_impresion_status.place(relx=0.5, rely=0.56, anchor="center")

        ctk.CTkButton(self.frm_gracias, text=t("cabina.btn_nueva_sesion"),
                      width=280, height=60,
                      fg_color=C["primary"], text_color="#ffffff",
                      hover_color=C["primary_dark"],
                      corner_radius=30,
                      font=ctk.CTkFont(size=16, weight="bold"),
                      command=self._nueva_sesion).place(relx=0.5, rely=0.72, anchor="center")

    def _ocultar_todos(self):
        self._parar_slideshow()
        for f in (self.frm_idle, self.frm_countdown, self.frm_flash,
                  self.frm_freeze, self.frm_seleccion,
                  self.frm_reorden, self.frm_preview, self.frm_gracias):
            f.place_forget()
        self.frm_progreso.place_forget()
        self._cd_topbar.place_forget()
        self._cd_texto = ""
        # Eliminar frames de fotos que se colocan directamente en frm_seleccion
        if hasattr(self, '_btns_foto'):
            for f in self._btns_foto:
                try:
                    f.destroy()
                except Exception:
                    pass
            self._btns_foto = []

    # ── Inicialización diferida ────────────────────────────────────────────────

    def _iniciar(self):
        self._iniciar_preview()
        self._ir_idle()

    # ── Estados ────────────────────────────────────────────────────────────────

    def _ir_idle(self):
        self._estado = "idle"
        self._fotos.clear()
        self._rutas_fotos.clear()
        self._indices_elegidos.clear()
        self._foto_actual = 0
        self._sesion_id = None
        self._ocultar_todos()
        self.frm_idle.place(relx=0, rely=0, relwidth=1, relheight=1)
        self._reset_idle_timer()
        self._iniciar_slideshow()

    # ── Slideshow de tiras en idle ─────────────────────────────────────────────

    def _obtener_tiras(self) -> list[str]:
        """Devuelve rutas de tiras impresas/guardadas del evento, más recientes primero."""
        sesiones = self.db.listar_sesiones_evento(self.evento["id"])
        rutas = [s["ruta_tira"] for s in sesiones
                 if s.get("ruta_tira") and os.path.isfile(s["ruta_tira"])]
        return rutas

    def _iniciar_slideshow(self):
        self._slide_tiras = self._obtener_tiras()
        if not self._slide_tiras:
            self._slide_card.place_forget()
            return
        self._slide_idx = 0
        self._slide_card.place(relx=0.80, rely=0.50, anchor="center")
        self._tick_slideshow()

    def _cargar_slide_img(self, ruta: str) -> Image.Image:
        img = Image.open(ruta).convert("RGB")
        sh = max(self.winfo_height(), 600)
        target_h = min(int(sh * 0.70), 800)
        ratio = target_h / img.height
        target_w = int(img.width * ratio)
        return img.resize((target_w, target_h), Image.LANCZOS)

    def _tick_slideshow(self):
        if self._estado != "idle" or not self._slide_tiras:
            return
        ruta = self._slide_tiras[self._slide_idx % len(self._slide_tiras)]
        self._slide_idx += 1
        try:
            nueva = self._cargar_slide_img(ruta)
            anterior = getattr(self, "_slide_img_actual", None)

            n = len(self._slide_tiras)
            self.lbl_slide_info.configure(
                text=f"{n} {'sesión' if n == 1 else 'sesiones'} registradas"
            )

            if anterior is None:
                # Primera imagen: mostrar directamente
                photo = ImageTk.PhotoImage(nueva)
                self._slide_photo_ref = photo
                self.lbl_slide.configure(image=photo)
            else:
                # Asegurar mismo tamaño para blend
                if anterior.size != nueva.size:
                    anterior = anterior.resize(nueva.size, Image.LANCZOS)
                self._fade_slide(anterior, nueva, step=0)

            self._slide_img_actual = nueva
        except Exception:
            pass

        # Próximo ciclo: 4 s de espera + ~0.6 s de fade
        self._slideshow_after_id = self.after(4600, self._tick_slideshow)

    def _fade_slide(self, vieja: Image.Image, nueva: Image.Image,
                    step: int = 0, pasos: int = 15):
        if self._estado != "idle":
            return
        alpha = step / pasos
        frame = Image.blend(vieja, nueva, alpha)
        photo = ImageTk.PhotoImage(frame)
        self._slide_photo_ref = photo
        self.lbl_slide.configure(image=photo)
        if step < pasos:
            self.after(40, lambda: self._fade_slide(vieja, nueva, step + 1, pasos))

    def _parar_slideshow(self):
        if self._slideshow_after_id:
            self.after_cancel(self._slideshow_after_id)
            self._slideshow_after_id = None

    def _on_espacio(self):
        if self._estado == "idle":
            self._iniciar_sesion()
        elif self._estado == "capturando":
            pass  # captura automática

    def _es_licenciado(self) -> bool:
        """True si tiene licencia activa o es admin/super_admin."""
        if self.evento.get("_usuario_rol") in ("admin", "super_admin"):
            return True
        return bool(self.db.get_config("license_key", ""))

    def _iniciar_sesion(self):
        # Guard: evita crear dos sesiones si el botón y el frame disparan a la vez
        if self._estado != "idle":
            return
        if not self._es_licenciado():
            total = self.db.contar_sesiones_total()
            if total >= 10:
                from tkinter import messagebox
                messagebox.showwarning(
                    "Modo de prueba",
                    "Alcanzaste el límite de 10 sesiones en modo prueba.\n\n"
                    "Activá una licencia en Configuración para continuar."
                )
                return
        if not self.evento.get("id"):
            from tkinter import messagebox
            messagebox.showerror("Error", "Evento no configurado correctamente.")
            return
        self._estado = "sesion"
        self._sesion_id = self.db.crear_sesion(self.evento["id"])
        self._foto_actual = 0
        self._siguiente_foto()

    def _siguiente_foto(self):
        if self._foto_actual >= self._n_total:
            self._ir_seleccion()
            return
        self._estado = "countdown"
        self._ocultar_todos()
        self.lbl_foto_n.configure(
            text=t("cabina.foto_n", n=self._foto_actual + 1, total=self._n_total)
        )
        # Banda superior con número de foto
        self._cd_topbar.place(relx=0, rely=0, relwidth=1, anchor="nw", y=72)
        self._mostrar_progreso()
        self._countdown_val = FS["countdown_seg"]
        self._countdown_pausado = False
        self._tick_countdown()

    def _tick_countdown(self):
        if self._countdown_pausado:
            return  # espera hasta que _reanudar_countdown lo relame
        if self._countdown_val > 0:
            self._cd_texto = str(self._countdown_val)
            self._countdown_val -= 1
            self._cd_after_id = self.after(1000, self._tick_countdown)
        else:
            self._cd_texto = "📸"
            self._cd_after_id = self.after(300, self._limpiar_cd_y_capturar)

    def _on_click(self, event):
        """Click izquierdo: pausa/reanuda el countdown. Solo actúa durante countdown."""
        if self._estado != "countdown":
            return
        if self._countdown_pausado:
            self._countdown_pausado = False
            self._tick_countdown()
        else:
            self._countdown_pausado = True
            if self._cd_after_id:
                self.after_cancel(self._cd_after_id)
                self._cd_after_id = None
            self._cd_texto = "⏸"

    def _limpiar_cd_y_capturar(self):
        self._cd_texto = ""
        self._capturar()

    def _capturar(self):
        self._estado = "capturando"
        img = self.cam.capturar_foto()
        if img is None:
            img = self._foto_placeholder()

        self._fotos.append(img)
        indice = self._foto_actual + 1  # 1-based

        # Guardar en disco
        evento_dir = os.path.join(PHOTOS_DIR, str(self.evento["id"]))
        os.makedirs(evento_dir, exist_ok=True)
        ruta = os.path.join(evento_dir, f"sesion_{self._sesion_id}_foto_{indice}.jpg")
        try:
            img.save(ruta, "JPEG", quality=95)
            if self._sesion_id:
                self.db.registrar_foto(self._sesion_id, ruta, indice)
        except OSError as e:
            print(f"[PhotoBooth] Error guardando foto en disco: {e}")
            self.after(0, lambda: messagebox.showerror("Error de disco", f"No se pudo guardar la foto: {e}"))
            return  # No continuar si no se guardó
        except Exception as e:
            # BD falló después de guardar en disco — limpiar
            import os as _os
            if _os.path.exists(ruta):
                _os.unlink(ruta)
            self.after(0, lambda: messagebox.showerror("Error", "Error interno al registrar foto."))
            return
        self._rutas_fotos.append(ruta)

        self._foto_actual += 1
        self._disparar_flash(img)

    # ── Flash + Freeze ─────────────────────────────────────────────────────────

    def _disparar_flash(self, img: Image.Image):
        """Pantalla blanca de flash → freeze de la foto → siguiente."""
        self.frm_countdown.place_forget()
        self.frm_flash.place(relx=0, rely=0, relwidth=1, relheight=1)
        self.update_idletasks()
        self.after(130, lambda: self._mostrar_freeze(img))

    def _mostrar_freeze(self, img: Image.Image):
        self.frm_flash.place_forget()

        w = max(self.winfo_width(), 800)
        h = max(self.winfo_height() - 64 - 90, 400)   # descuenta barra progreso + barra estado

        foto = img.copy()
        foto.thumbnail((w, h), Image.LANCZOS)
        photo = ImageTk.PhotoImage(foto)
        self._freeze_photo = photo

        self.lbl_freeze_foto.configure(image=photo)
        self.lbl_freeze_status.configure(
            text=f"✓  Foto {self._foto_actual} de {self._n_total} capturada")
        self.lbl_barra_freeze_txt.configure(text="")

        self.frm_freeze.place(relx=0, rely=0, relwidth=1, relheight=1)
        self._mostrar_progreso()

        # Después de una pausa corta, invitar a tocar para continuar
        self.after(900, self._freeze_listo)

    def _freeze_listo(self):
        es_ultima = self._foto_actual >= self._n_total
        if es_ultima:
            msg = "✦  Elegí tus fotos  ✦"
        else:
            msg = "✦  Siguiente foto...  ✦"
        self.lbl_barra_freeze_txt.configure(text=msg)

        # Resetear flag de disparo único antes de armar los callbacks
        self._freeze_fired = False

        # Avance automático — click adelanta si el usuario quiere saltar la espera
        self._freeze_auto_id = self.after(3000, self._fin_freeze)
        self.frm_freeze.bind("<Button-1>", lambda _: self._fin_freeze())
        self.lbl_freeze_foto.bind("<Button-1>", lambda _: self._fin_freeze())
        self._barra_freeze.bind("<Button-1>", lambda _: self._fin_freeze())
        self.lbl_barra_freeze_txt.bind("<Button-1>", lambda _: self._fin_freeze())

    def _fin_freeze(self):
        # Guard: timer y click pueden llegar simultáneamente — solo procesar una vez
        if getattr(self, "_freeze_fired", False):
            return
        self._freeze_fired = True

        # Cancelar auto-avance si lo disparó el usuario
        if hasattr(self, "_freeze_auto_id") and self._freeze_auto_id:
            try:
                self.after_cancel(self._freeze_auto_id)
            except Exception:
                pass
            self._freeze_auto_id = None
        # Desligar los binds para evitar futuros disparos
        for w in (self.frm_freeze, self.lbl_freeze_foto,
                  self._barra_freeze, self.lbl_barra_freeze_txt):
            try:
                w.unbind("<Button-1>")
            except Exception:
                pass
        self.frm_freeze.place_forget()
        self._siguiente_foto()

    # ── Barra de progreso (dots) ───────────────────────────────────────────────

    def _mostrar_progreso(self):
        tomadas = self._foto_actual
        dots = "  ".join(
            "●" if i < tomadas else "○"
            for i in range(self._n_total)
        )
        self.lbl_dots.configure(text=dots)
        self.frm_progreso.place(relx=0, rely=0, relwidth=1, anchor="nw")

    # ── Selección ──────────────────────────────────────────────────────────────

    def _ir_seleccion(self):
        self._estado = "seleccion"
        self._ocultar_todos()
        self.lbl_seleccion_titulo.configure(
            text=t("cabina.seleccion_titulo", n=self._n_elegir))
        self.frm_seleccion.place(relx=0, rely=0, relwidth=1, relheight=1)
        self._indices_elegidos.clear()
        self._poblar_grid_seleccion()

    def _poblar_grid_seleccion(self):
        # Limpiar fotos anteriores (excepto header y botón)
        for w in self.frm_seleccion.place_slaves():
            if w not in (self.frm_grid_fotos,):
                w.destroy()
        # también limpiar frm_grid_fotos (no lo usamos más para las fotos)
        for w in self.frm_grid_fotos.winfo_children():
            w.destroy()

        n = len(self._fotos)
        self.update_idletasks()
        sw = max(self.winfo_width(), 1280)
        sh = max(self.winfo_height(), 720)
        gap = 14

        cols = 3 if n > 3 else n
        rows = 2 if n > 3 else 1
        cols_row2 = n - cols if rows == 2 else 0

        # Espacio bajo el header (88px)
        avail_w = sw
        avail_h = sh - 88

        # Tamaño uniforme: el mínimo de lo que entra por ancho y por alto
        tw_a = (avail_w - (cols + 1) * gap) // cols
        th_b = (avail_h - (rows + 1) * gap) // rows
        tw = min(tw_a, int(th_b * 4 / 3))
        th = int(tw * 3 / 4)

        # Posición inicial para centrar la grilla en la ventana
        grid_w = cols * tw + (cols - 1) * gap
        grid_h = rows * th + (rows - 1) * gap
        x0 = (sw - grid_w) // 2
        y0 = 88 + (avail_h - grid_h) // 2  # centrado vertical bajo el header

        # Offset para centrar la fila inferior
        row2_w = cols_row2 * tw + max(0, cols_row2 - 1) * gap
        row2_offset = (grid_w - row2_w) // 2 if cols_row2 > 0 else 0

        self._thumb_refs = []
        self._btns_foto = []

        for i, img in enumerate(self._fotos):
            r = 0 if i < cols else 1
            c = i if i < cols else i - cols

            x = x0 + c * (tw + gap) + (row2_offset if r == 1 else 0)
            y = y0 + r * (th + gap)

            thumb = img.copy().resize((tw, th), Image.LANCZOS)
            photo = ImageTk.PhotoImage(thumb)
            self._thumb_refs.append(photo)

            frm = tk.Frame(self.frm_seleccion,
                           bg=C["bg_card"],
                           width=tw, height=th,
                           highlightthickness=3,
                           highlightbackground=C["border"])
            frm.place(x=x, y=y)
            frm.pack_propagate(False)

            lbl = tk.Label(frm, image=photo, bg=C["bg_card"],
                           width=tw - 6, height=th - 6)
            lbl.place(relx=0.5, rely=0.5, anchor="center")

            badge = tk.Label(frm, text=f"  Foto {i + 1}  ",
                             font=("Helvetica", 11, "bold"),
                             fg="#ffffff", bg="#1a1228",
                             padx=4, pady=2)
            badge.place(x=8, y=8)

            frm.bind("<Button-1>", lambda e, idx=i, f=frm: self._toggle_foto(idx, f))
            lbl.bind("<Button-1>", lambda e, idx=i, f=frm: self._toggle_foto(idx, f))
            self._btns_foto.append(frm)

        self.btn_confirmar_sel.configure(state="disabled")

    def _toggle_foto(self, idx: int, frm):
        if idx in self._indices_elegidos:
            self._indices_elegidos.discard(idx)
            frm.config(highlightbackground=C["border"])
        else:
            if len(self._indices_elegidos) >= self._n_elegir:
                return
            self._indices_elegidos.add(idx)
            frm.config(highlightbackground=C["primary"])

        n_elegidas = len(self._indices_elegidos)
        if n_elegidas == self._n_elegir:
            self.btn_confirmar_sel.configure(state="normal")
        else:
            self.btn_confirmar_sel.configure(state="disabled")

    def _confirmar_seleccion(self):
        # Guard: doble tap en touchscreen no debe generar dos previews
        if self._estado != "seleccion":
            return
        self._estado = "preview"   # transición inmediata antes de cualquier I/O
        self._indices_elegidos_ord = sorted(self._indices_elegidos)
        indices_1based = [i + 1 for i in self._indices_elegidos_ord]
        if self._sesion_id:
            self.db.marcar_fotos_elegidas(self._sesion_id, indices_1based)
        self._ir_preview_tira(indices_1based)

    # ── Reordenamiento ─────────────────────────────────────────────────────────

    def _ir_reorden(self, indices_1based: list):
        self._orden_actual = list(indices_1based)  # orden mutable
        self._estado = "reorden"
        self._ocultar_todos()
        self.frm_reorden.place(relx=0, rely=0, relwidth=1, relheight=1)
        self._poblar_grid_reorden()

    def _poblar_grid_reorden(self):
        for w in self.frm_reorden_grid.winfo_children():
            w.destroy()

        n = len(self._orden_actual)
        sw = max(self.winfo_width(), 1280)
        sh = max(self.winfo_height(), 720)
        thumb_w = min((sw - 80) // n - 24, 480)
        thumb_h = min(int(thumb_w * 3 / 4), sh - 240)
        THUMB_W = max(220, thumb_w)
        THUMB_H = max(165, thumb_h)
        self._reorden_thumb_refs = []

        for pos, idx in enumerate(self._orden_actual):
            foto = self._fotos[idx - 1]

            col_frame = ctk.CTkFrame(self.frm_reorden_grid,
                                      fg_color=C["bg_card"],
                                      corner_radius=12,
                                      border_width=1, border_color=C["border"])
            col_frame.grid(row=0, column=pos, padx=10, pady=8)

            ctk.CTkLabel(col_frame,
                         text=t("cabina.posicion_n", n=pos + 1),
                         font=ctk.CTkFont(size=12, weight="bold"),
                         text_color=C["primary"]).pack(pady=(10, 4))

            thumb = foto.copy()
            thumb.thumbnail((THUMB_W, THUMB_H), Image.LANCZOS)
            photo = ImageTk.PhotoImage(thumb)
            self._reorden_thumb_refs.append(photo)
            ctk.CTkLabel(col_frame, image=photo, text="").pack(padx=8, pady=4)

            arr_row = ctk.CTkFrame(col_frame, fg_color="transparent")
            arr_row.pack(pady=(4, 10))
            if pos > 0:
                ctk.CTkButton(arr_row, text="◀", width=44, height=34,
                              fg_color=C["primary"], text_color="#ffffff",
                              font=ctk.CTkFont(size=14, weight="bold"),
                              command=lambda p=pos: self._swap_orden(p, p - 1)).pack(
                    side="left", padx=4)
            if pos < len(self._orden_actual) - 1:
                ctk.CTkButton(arr_row, text="▶", width=44, height=34,
                              fg_color=C["primary"], text_color="#ffffff",
                              font=ctk.CTkFont(size=14, weight="bold"),
                              command=lambda p=pos: self._swap_orden(p, p + 1)).pack(
                    side="left", padx=4)

    def _swap_orden(self, a: int, b: int):
        self._orden_actual[a], self._orden_actual[b] = \
            self._orden_actual[b], self._orden_actual[a]
        self._poblar_grid_reorden()

    def _confirmar_orden(self):
        self._ir_preview_tira(self._orden_actual)

    # ── Preview de tira ────────────────────────────────────────────────────────

    def _ir_preview_tira(self, orden: list):
        from modules.image_processor import ImageProcessor
        self._estado = "preview"
        self._ocultar_todos()

        # orden es lista de índices 1-based en el orden final
        fotos_elegidas = [self._fotos[i - 1] for i in orden]
        indices_1based = orden
        plantilla = self._cargar_plantilla()

        es_trial = not self._es_licenciado()
        tira = ImageProcessor.componer_tira(fotos_elegidas, plantilla, evento=self.evento, trial=es_trial)
        self._tira_img = tira

        # Guardar tira
        ruta_digital = self.evento.get("ruta_digital", "")
        if ruta_digital and os.path.isdir(ruta_digital):
            evento_dir = ruta_digital
        else:
            evento_dir = os.path.join(PHOTOS_DIR, str(self.evento["id"]))
        os.makedirs(evento_dir, exist_ok=True)
        ruta_tira = os.path.join(evento_dir, f"sesion_{self._sesion_id}_tira.jpg")
        try:
            tira.save(ruta_tira, "JPEG", quality=95)
            if self._sesion_id:
                self.db.marcar_fotos_elegidas(self._sesion_id, indices_1based, ruta_tira)
        except OSError as e:
            print(f"[PhotoBooth] Error guardando tira: {e}")
            self.after(0, lambda: messagebox.showerror("Error de disco", f"No se pudo guardar la tira: {e}"))
            return
        except Exception as e:
            # BD falló después de guardar en disco — limpiar
            import os as _os
            if _os.path.exists(ruta_tira):
                _os.unlink(ruta_tira)
            self.after(0, lambda: messagebox.showerror("Error", "Error interno al registrar la tira."))
            return
        self._ruta_tira_guardada = ruta_tira

        # Mostrar preview redimensionado
        preview = tira.copy()
        preview.thumbnail((360, 600), Image.LANCZOS)
        self._tira_photo = ImageTk.PhotoImage(preview)
        self.lbl_tira.configure(image=self._tira_photo)

        self.frm_preview.place(relx=0, rely=0, relwidth=1, relheight=1)

    def _cargar_plantilla(self) -> dict | None:
        pid = self.evento.get("plantilla_id")
        if pid:
            return self.db.obtener_plantilla(pid)
        return None

    # ── Acción final de sesión ────────────────────────────────────────────────

    def _guardar_y_continuar(self):
        """Modo digital: confirma guardado y pasa a siguiente sesión.
           Modo impresión: encola la tira y muestra el resultado."""
        # Guard contra doble tap: si ya estamos procesando, ignorar llamada extra
        if self._estado == "imprimiendo":
            return
        self._estado = "imprimiendo"
        self._ocultar_todos()
        self.frm_gracias.place(relx=0, rely=0, relwidth=1, relheight=1)
        if self.evento.get("modo_salida", "imprimir") == "digital":
            self.lbl_impresion_status.configure(text="✓  Sesión guardada")
            self.after(2500, self._nueva_sesion)
        else:
            self.lbl_impresion_status.configure(text="⏳  Enviando a cola...")
            threading.Thread(target=self._do_encolar_impresion, daemon=True).start()

    def _do_encolar_impresion(self):
        from modules.print_queue import PrintQueue
        ruta_tira = getattr(self, "_ruta_tira_guardada", None)
        if not ruta_tira:
            self.after(0, lambda: self.lbl_impresion_status.configure(
                text="✗  Error: tira no encontrada"))
            self.after(6000, self._nueva_sesion)
            return
        try:
            resultado = PrintQueue.agregar_y_imprimir(
                self.db, self.evento, self._sesion_id, ruta_tira)
        except Exception as e:
            print(f"[CaptureUI] Error en cola de impresión: {e}")
            resultado = "error"
        msgs  = {"en_cola": "⏳  En cola — se imprimirá con la próxima sesión",
                 "impreso": "✓  Impreso",
                 "error":   "✗  Error al imprimir"}
        delays = {"en_cola": 6000, "impreso": 5000, "error": 8000}
        msg   = msgs.get(resultado, "✗  Error al imprimir")
        delay = delays.get(resultado, 8000)
        self.after(0, lambda m=msg: self.lbl_impresion_status.configure(text=m))
        self.after(delay, self._nueva_sesion)

    # ── Panel de cola / estado de impresión ───────────────────────────────────

    def _abrir_panel_cola(self):
        """Abre un panel modal sobre la cabina mostrando cola e historial."""
        import tkinter as tk

        es_digital = self.evento.get("modo_salida") == "digital"
        titulo_panel = "💾  Estado digital" if es_digital else "🖨  Estado de impresión"

        win = tk.Toplevel(self)
        win.title(titulo_panel)
        win.configure(bg=C["bg"])
        win.geometry("820x580")
        win.grab_set()
        win.attributes("-topmost", True)

        # Header
        hdr = ctk.CTkFrame(win, fg_color=C["bg_card"], corner_radius=0, height=56)
        hdr.pack(fill="x")
        hdr.pack_propagate(False)
        ctk.CTkLabel(hdr, text=titulo_panel,
                     font=ctk.CTkFont(size=17, weight="bold"),
                     text_color=C["text"]).pack(side="left", padx=20, pady=12)
        ctk.CTkButton(hdr, text="✕  Cerrar", width=90, height=32,
                      fg_color="transparent", border_width=1,
                      border_color=C["border"], text_color=C["text_gray"],
                      command=win.destroy).pack(side="right", padx=16, pady=12)

        # ── Cola pendiente ───────────────────────────────────────────────────
        cola = self.db.cola_todos(self.evento["id"])
        sec_cola = ctk.CTkFrame(win, fg_color=C["bg_card"], corner_radius=12,
                                border_width=1, border_color=C["border"])
        sec_cola.pack(fill="x", padx=16, pady=(14, 6))

        accion_txt = "esperando pareja para guardar" if es_digital else "esperando pareja para imprimir"
        cola_titulo = f"En cola: {len(cola)} tira(s) {accion_txt}"
        cola_color  = C["warning"] if cola else C["success"]
        ctk.CTkLabel(sec_cola, text=cola_titulo,
                     font=ctk.CTkFont(size=13, weight="bold"),
                     text_color=cola_color).pack(anchor="w", padx=14, pady=(10, 4))

        if cola:
            for item in cola:
                row = ctk.CTkFrame(sec_cola, fg_color="transparent")
                row.pack(fill="x", padx=14, pady=3)
                ruta = item.get("ruta_tira", "")
                if ruta and os.path.exists(ruta):
                    try:
                        img = Image.open(ruta)
                        img.thumbnail((36, 60))
                        from PIL import ImageTk
                        ph = ImageTk.PhotoImage(img)
                        lbl_img = ctk.CTkLabel(row, image=ph, text="")
                        lbl_img.image = ph
                        lbl_img.pack(side="left", padx=(0, 8))
                    except Exception:
                        pass
                ts = item.get("creado_en", "")[:16].replace("T", "  ")
                ctk.CTkLabel(row,
                             text=f"Tira guardada el {ts}  —  {accion_txt}",
                             font=ctk.CTkFont(size=11),
                             text_color=C["text_gray"]).pack(side="left")

            btns_cola = ctk.CTkFrame(sec_cola, fg_color="transparent")
            btns_cola.pack(anchor="w", padx=14, pady=(4, 12))
            btn_vaciar_txt = "💾  Guardar como par" if es_digital else "🖨  Duplicar e imprimir"
            ctk.CTkButton(btns_cola, text=btn_vaciar_txt,
                          height=32, fg_color=C["primary"], text_color="#fff",
                          font=ctk.CTkFont(size=12, weight="bold"),
                          command=lambda: self._vaciar_cola_desde_panel(win)
                          ).pack(side="left", padx=(0, 8))
            if len(cola) == 1:
                ctk.CTkButton(btns_cola, text="👥  Elegir pareja",
                              height=32,
                              fg_color="transparent", border_width=1,
                              border_color=C["border"], text_color=C["text"],
                              font=ctk.CTkFont(size=12),
                              command=lambda: self._abrir_picker_pareja(win, cola[0])
                              ).pack(side="left")
        else:
            ctk.CTkLabel(sec_cola, text="No hay tiras pendientes.",
                         font=ctk.CTkFont(size=11),
                         text_color=C["text_muted"]).pack(anchor="w", padx=14, pady=(0, 10))

        # ── Historial de sesiones ────────────────────────────────────────────
        ctk.CTkLabel(win, text="Historial del evento",
                     font=ctk.CTkFont(size=13, weight="bold"),
                     text_color=C["text"]).pack(anchor="w", padx=16, pady=(8, 4))

        scroll = ctk.CTkScrollableFrame(win, fg_color="transparent")
        scroll.pack(fill="both", expand=True, padx=16, pady=(0, 16))

        sesiones = self.db.listar_sesiones_evento(self.evento["id"])
        if not sesiones:
            ctk.CTkLabel(scroll, text="Sin sesiones aún.",
                         text_color=C["text_muted"]).pack(pady=20)
        else:
            for s in sesiones:
                self._fila_sesion(scroll, s, cola)

    def _fila_sesion(self, parent, sesion: dict, cola: list):
        """Dibuja una fila de sesión en el historial."""
        es_digital = self.evento.get("modo_salida") == "digital"
        cola_ids = {c.get("sesion_id") for c in cola}
        en_cola  = sesion["id"] in cola_ids
        impresa  = sesion.get("impresa", 0)

        if impresa:
            estado_txt = "✓  Guardada" if es_digital else "✓  Impresa"
            estado_col = C["success"]
            bg = "#0d1f0d"
        elif en_cola:
            estado_txt = "⏳  En cola"
            estado_col = C["warning"]
            bg = "#1f1a0a"
        else:
            estado_txt = "○  Sin guardar" if es_digital else "○  Sin imprimir"
            estado_col = C["text_muted"]
            bg = C["bg_card"]

        row = ctk.CTkFrame(parent, fg_color=bg, corner_radius=10,
                           border_width=1, border_color=C["border"])
        row.pack(fill="x", pady=4)

        # Miniatura
        ruta = sesion.get("ruta_tira", "")
        if ruta and os.path.exists(ruta):
            try:
                img = Image.open(ruta)
                img.thumbnail((40, 66))
                ph = ImageTk.PhotoImage(img)
                lbl = ctk.CTkLabel(row, image=ph, text="")
                lbl.image = ph
                lbl.pack(side="left", padx=(10, 8), pady=8)
            except Exception:
                self._placeholder_mini(row)
        else:
            self._placeholder_mini(row)

        # Info
        info = ctk.CTkFrame(row, fg_color="transparent")
        info.pack(side="left", fill="x", expand=True, pady=8)

        ts = sesion.get("timestamp", "")[:16].replace("T", "  ")
        ctk.CTkLabel(info, text=f"Sesión #{sesion['id']}   —   {ts}",
                     font=ctk.CTkFont(size=12, weight="bold"),
                     text_color=C["text"]).pack(anchor="w")
        ctk.CTkLabel(info, text=f"{sesion.get('fotos_tomadas', 0)} fotos tomadas",
                     font=ctk.CTkFont(size=11),
                     text_color=C["text_muted"]).pack(anchor="w")

        # Estado
        ctk.CTkLabel(row, text=estado_txt,
                     font=ctk.CTkFont(size=12, weight="bold"),
                     text_color=estado_col,
                     width=130, anchor="e").pack(side="right", padx=14)

    def _placeholder_mini(self, parent):
        ph = ctk.CTkFrame(parent, fg_color=C["bg_hover"],
                          width=40, height=66, corner_radius=4)
        ph.pack(side="left", padx=(10, 8), pady=8)
        ph.pack_propagate(False)

    def _vaciar_cola_desde_panel(self, win):
        from modules.print_queue import PrintQueue
        from tkinter import messagebox
        win.destroy()
        def on_done(n, err):
            if err:
                self.after(0, lambda e=err: messagebox.showerror("Error", str(e)))
            else:
                self.after(0, self._nueva_sesion)
        if self.evento.get("modo_salida", "imprimir") == "digital":
            PrintQueue.vaciar_guardar(self.db, self.evento, on_done=on_done)
        else:
            PrintQueue.vaciar(self.db, self.evento, on_done=on_done)

    def _abrir_picker_pareja(self, panel_cola, item_cola: dict):
        """Muestra diálogo para elegir qué sesión imprimir junto a la pendiente."""
        from modules.print_queue import PrintQueue
        from config.formatos import get_formato

        picker = tk.Toplevel(panel_cola)
        picker.title("Elegir pareja para imprimir")
        picker.configure(bg=C["bg"])
        picker.geometry("1100x700")
        picker.grab_set()
        picker.attributes("-topmost", True)

        ctk.CTkLabel(picker,
                     text="Elegí una sesión para imprimir junto a la tira pendiente:",
                     font=ctk.CTkFont(size=15, weight="bold"),
                     text_color=C["text"]).pack(padx=24, pady=(20, 12), anchor="w")

        scroll = ctk.CTkScrollableFrame(picker, fg_color="transparent",
                                        orientation="horizontal")
        scroll.pack(fill="both", expand=True, padx=16, pady=(0, 12))

        sesiones = self.db.listar_sesiones_evento(self.evento["id"])
        sesiones_con_tira = [s for s in sesiones
                             if s.get("ruta_tira") and os.path.exists(s["ruta_tira"])
                             and s["id"] != item_cola.get("sesion_id")]

        _photo_refs = []

        if not sesiones_con_tira:
            ctk.CTkLabel(scroll, text="No hay otras sesiones disponibles.",
                         text_color=C["text_muted"],
                         font=ctk.CTkFont(size=14)).pack(pady=60, padx=40)
        else:
            for s in sesiones_con_tira:
                card = ctk.CTkFrame(scroll, fg_color=C["bg_card"], corner_radius=14,
                                    border_width=1, border_color=C["border"],
                                    width=200)
                card.pack(side="left", padx=10, pady=8, fill="y")
                card.pack_propagate(False)

                try:
                    img_t = Image.open(s["ruta_tira"]).convert("RGB")
                    # Escalar manteniendo proporción, alto fijo 400px
                    ratio = 400 / img_t.height
                    img_t = img_t.resize((int(img_t.width * ratio), 400), Image.LANCZOS)
                    ph = ImageTk.PhotoImage(img_t)
                    _photo_refs.append(ph)
                    lbl_ph = tk.Label(card, image=ph, bg=C["bg_card"], bd=0)
                    lbl_ph.image = ph
                    lbl_ph.pack(pady=(12, 6))
                except Exception:
                    ctk.CTkLabel(card, text="Sin preview",
                                 text_color=C["text_muted"]).pack(pady=40)

                ts = s.get("timestamp", "")[:16].replace("T", " ")
                ctk.CTkLabel(card, text=f"#{s['id']}  —  {ts}",
                             font=ctk.CTkFont(size=11, weight="bold"),
                             text_color=C["text"],
                             wraplength=180).pack(padx=8)

                impresa = "✓ Ya impresa" if s.get("impresa") else "○ Sin imprimir"
                ctk.CTkLabel(card, text=impresa,
                             font=ctk.CTkFont(size=11),
                             text_color=C["success"] if s.get("impresa") else C["text_muted"]
                             ).pack(pady=(2, 8))

                es_digital = self.evento.get("modo_salida", "imprimir") == "digital"

                def _accion(sesion=s):
                    picker.destroy()
                    panel_cola.destroy()
                    ruta_pendiente = item_cola["ruta_tira"]
                    ruta_pareja   = sesion["ruta_tira"]
                    fmt = get_formato(self.evento.get("formato", "tira_5x15"))
                    self.db.cola_eliminar(item_cola["id"])
                    def _run():
                        if es_digital:
                            ok = PrintQueue._guardar_par(ruta_pendiente, ruta_pareja,
                                                         self.evento, fmt)
                        else:
                            ok = PrintQueue._imprimir_par(ruta_pendiente, ruta_pareja,
                                                          self.evento, fmt)
                        if ok:
                            self.after(0, self._nueva_sesion)
                    import threading
                    threading.Thread(target=_run, daemon=True).start()

                btn_lbl = "💾 Guardar juntas →" if es_digital else "Imprimir juntas →"
                ctk.CTkButton(card, text=btn_lbl,
                              height=38, fg_color=C["primary"], text_color="#fff",
                              font=ctk.CTkFont(size=12, weight="bold"),
                              command=_accion).pack(padx=12, pady=(0, 14), fill="x")

        ctk.CTkButton(picker, text="Cancelar",
                      fg_color="transparent", border_width=1,
                      border_color=C["border"], text_color=C["text_gray"],
                      command=picker.destroy).pack(pady=(0, 14))

    def _repetir(self):
        self._ir_idle()

    def _nueva_sesion(self):
        self._ir_idle()

    # ── Preview de cámara ──────────────────────────────────────────────────────

    def _cd_get_overlay(self, txt: str, w: int, h: int) -> Image.Image:
        """Pre-renderiza el overlay del countdown y lo cachea por (txt, w, h)."""
        from PIL import ImageDraw, ImageFont, ImageFilter
        key = (txt, w, h)
        if key in self._cd_overlay_cache:
            return self._cd_overlay_cache[key]

        overlay = Image.new("RGBA", (w, h), (0, 0, 0, 0))
        draw = ImageDraw.Draw(overlay)

        es_emoji = not txt.strip().isdigit()
        font_size = int(h * 0.20) if es_emoji else int(h * 0.42)
        font = None
        for nombre in ("arialbd.ttf", "ariblk.ttf", "arial.ttf", "DejaVuSans-Bold.ttf"):
            try:
                font = ImageFont.truetype(nombre, font_size)
                break
            except Exception:
                pass
        if font is None:
            font = ImageFont.load_default()

        bbox = draw.textbbox((0, 0), txt, font=font)
        tw, th = bbox[2] - bbox[0], bbox[3] - bbox[1]
        x = (w - tw) // 2 - bbox[0]
        y = (h - th) // 2 - bbox[1] - int(h * 0.04)

        # Glow: capa separada con blur, pegada semitransparente
        glow = Image.new("RGBA", (w, h), (0, 0, 0, 0))
        gd = ImageDraw.Draw(glow)
        gd.text((x, y), txt, fill=(140, 30, 255, 200), font=font,
                stroke_width=font_size // 6, stroke_fill=(100, 0, 200, 180))
        glow = glow.filter(ImageFilter.GaussianBlur(radius=8 if es_emoji else 22))
        overlay = Image.alpha_composite(overlay, glow)
        draw = ImageDraw.Draw(overlay)

        # Stroke blanco + relleno violeta — usando stroke_width nativo (rápido)
        stroke = max(8, font_size // 16)
        draw.text((x, y), txt,
                  fill=(162, 50, 255, 255),
                  font=font,
                  stroke_width=stroke,
                  stroke_fill=(255, 255, 255, 255))

        # Reflejo interior sutil
        hi = max(2, stroke // 5)
        draw.text((x - hi, y - hi), txt, fill=(230, 200, 255, 120), font=font)

        # "¡Sonreí! 😄" con stroke oscuro
        sub = "¡Sonreí! 😄"
        sf_size = int(h * 0.048)
        sfont = None
        for nombre in ("arialbd.ttf", "arial.ttf", "DejaVuSans-Bold.ttf"):
            try:
                sfont = ImageFont.truetype(nombre, sf_size)
                break
            except Exception:
                pass
        if sfont is None:
            sfont = font
        sb = draw.textbbox((0, 0), sub, font=sfont)
        sx = (w - (sb[2] - sb[0])) // 2
        sy = int(h * 0.76)
        ss = max(3, sf_size // 12)
        draw.text((sx, sy), sub, fill=(255, 255, 255, 255), font=sfont,
                  stroke_width=ss, stroke_fill=(30, 0, 60, 220))

        # Guardar en cache (máx 6 entradas para no acumular)
        if len(self._cd_overlay_cache) > 6:
            self._cd_overlay_cache.clear()
        self._cd_overlay_cache[key] = overlay
        return overlay

    def _iniciar_preview(self):
        # Abrir cámara en thread para no congelar la UI; poll arranca ya (muestra negro hasta que haya frames)
        threading.Thread(
            target=self.cam.iniciar_preview,
            args=(self._camara_index,),
            kwargs={"callback": None},
            daemon=True,
        ).start()
        self._poll_camara()

    def _poll_camara(self):
        """Polling desde el hilo principal cada 40ms (~25fps). Evita problemas de threading con Tkinter."""
        if self._estado not in ("idle", "countdown", "capturando"):
            self._poll_after_id = self.after(40, self._poll_camara)
            return
        try:
            with self.cam._frame_lock:
                img = self.cam._ultimo_frame
            if img is None:
                self._poll_after_id = self.after(40, self._poll_camara)
                return
            w = max(self.winfo_width(), 640)
            h = max(self.winfo_height(), 480)
            cam_w, cam_h = img.size
            scale = min(w / cam_w, h / cam_h)
            new_w, new_h = int(cam_w * scale), int(cam_h * scale)
            resized = img.copy().resize((new_w, new_h), Image.BILINEAR)
            frame = Image.new("RGB", (w, h), (0, 0, 0))
            frame.paste(resized, ((w - new_w) // 2, (h - new_h) // 2))
            txt = self._cd_texto
            if txt:
                overlay = self._cd_get_overlay(txt, w, h)
                frame = Image.alpha_composite(frame.convert("RGBA"), overlay).convert("RGB")
            photo = ImageTk.PhotoImage(frame)
            self._last_photo = photo       # evitar GC
            self.lbl_preview.configure(image=photo)
            self.lbl_preview.image = photo # referencia extra anti-GC
        except Exception as e:
            import sys
            print(f"[POLL ERROR] {e}", file=sys.stderr)
        self._poll_after_id = self.after(40, self._poll_camara)

    # ── Idle timer ─────────────────────────────────────────────────────────────

    def _reset_idle_timer(self):
        if self._idle_timer:
            self.after_cancel(self._idle_timer)
        self._idle_timer = None

    # ── Utilidades ─────────────────────────────────────────────────────────────

    @staticmethod
    def _foto_placeholder() -> Image.Image:
        img = Image.new("RGB", (1280, 720), color=(30, 30, 30))
        return img

    def _on_mouse_move(self, event):
        w = self.winfo_width() or 1920
        zona = event.x > w - 120 and event.y < 80   # esquina superior derecha
        if zona:
            self._ctrl_bar.place(relx=1.0, rely=0.0, anchor="ne", x=-16, y=16)
            self._ctrl_bar.lift()
            if self._ctrl_hide_timer:
                self.after_cancel(self._ctrl_hide_timer)
                self._ctrl_hide_timer = None
        else:
            if not self._ctrl_hide_timer:
                self._ctrl_hide_timer = self.after(
                    1200, self._ocultar_ctrl_bar)

    def _ocultar_ctrl_bar(self):
        self._ctrl_hide_timer = None
        self._ctrl_bar.place_forget()

    def _toggle_fullscreen(self):
        self._is_fullscreen = not self._is_fullscreen
        if self._is_fullscreen:
            self.state("zoomed")
            self.attributes("-fullscreen", True)
        else:
            self.attributes("-fullscreen", False)
            self.state("zoomed")
        self._btn_fs.configure(text="⛶" if self._is_fullscreen else "⤢")

    def _cerrar(self):
        self._parar_slideshow()
        if self._poll_after_id:
            self.after_cancel(self._poll_after_id)
            self._poll_after_id = None
        self.cam.detener_preview()
        self.destroy()
