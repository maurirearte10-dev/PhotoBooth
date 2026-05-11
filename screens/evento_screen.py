"""
EventoScreen — creación y edición de eventos.
Pide: nombre, fecha, formato, cámara (+ test), impresora (+ test), modo salida, plantilla.
"""
import threading
import tkinter as tk
import customtkinter as ctk
from tkinter import messagebox
from PIL import Image, ImageTk

from config.settings import COLORS
from config.formatos import FORMATOS, get_formato
from modules.database import DatabaseManager
from modules.i18n import t

C = COLORS


class EventoScreen(ctk.CTkFrame):
    def __init__(self, master, db: DatabaseManager, usuario: dict,
                 evento: dict | None, on_guardar, on_cancelar):
        super().__init__(master, fg_color=C["bg"])
        self.db = db
        self.usuario = usuario
        self.evento = evento
        self.on_guardar = on_guardar
        self.on_cancelar = on_cancelar

        self._camaras: list = []
        self._impresoras: list = []
        self._plantillas: list = []
        self._plantilla_sel: int | None = evento.get("plantilla_id") if evento else None
        self._thumb_refs: list = []
        self._cam_preview_win = None

        self._build_ui()
        self._cargar_datos()

    # ── UI ─────────────────────────────────────────────────────────────────────

    def _build_ui(self):
        hdr = ctk.CTkFrame(self, fg_color="transparent")
        hdr.pack(fill="x", padx=24, pady=(20, 0))
        ctk.CTkButton(hdr, text="← Volver", width=90, fg_color="transparent",
                      border_width=1, border_color=C["border"],
                      text_color=C["text_gray"],
                      command=self.on_cancelar).pack(side="left")
        titulo = t("evento.titulo_editar") if self.evento else t("evento.titulo_nuevo")
        ctk.CTkLabel(hdr, text=titulo,
                     font=ctk.CTkFont(size=20, weight="bold"),
                     text_color=C["text"]).pack(side="left", padx=20)
        ctk.CTkButton(hdr, text="Guardar evento", width=160, height=38,
                      fg_color=C["primary"], text_color="#ffffff",
                      font=ctk.CTkFont(size=13, weight="bold"),
                      command=self._guardar).pack(side="right")

        body = ctk.CTkScrollableFrame(self, fg_color="transparent")
        body.pack(fill="both", expand=True, padx=24, pady=16)
        body.columnconfigure(0, weight=1)
        body.columnconfigure(1, weight=1)

        row = 0

        # ── Nombre ────────────────────────────────────────────────────────────
        self._lbl(body, t("evento.label_nombre"), row, 0, span=2); row += 1
        self.nombre_var = ctk.StringVar(
            value=self.evento.get("nombre", "") if self.evento else "")
        ctk.CTkEntry(body, textvariable=self.nombre_var,
                     placeholder_text=t("evento.placeholder_nombre"),
                     height=44, font=ctk.CTkFont(size=14)).grid(
            row=row, column=0, columnspan=2, sticky="ew", pady=(0, 16))
        row += 1

        # ── Fecha ─────────────────────────────────────────────────────────────
        self._lbl(body, t("evento.label_fecha"), row, 0, span=2); row += 1
        fecha_row = ctk.CTkFrame(body, fg_color="transparent")
        fecha_row.grid(row=row, column=0, columnspan=2, sticky="ew", pady=(0, 16))
        row += 1

        self.fecha_var = ctk.StringVar(
            value=self.evento.get("fecha_evento", "") if self.evento else "")
        ctk.CTkLabel(fecha_row, textvariable=self.fecha_var,
                     text_color=C["text"], font=ctk.CTkFont(size=14),
                     fg_color=C["bg_card"], corner_radius=10,
                     width=200, height=44).pack(side="left", padx=(0, 10))
        ctk.CTkButton(fecha_row, text="📅  Elegir fecha",
                      height=44, fg_color="transparent",
                      border_width=1, border_color=C["border"],
                      text_color=C["primary"],
                      command=self._abrir_calendario).pack(side="left")

        # ── Formato ───────────────────────────────────────────────────────────
        self._lbl(body, t("evento.label_formato"), row, 0, span=2); row += 1
        fmt_frame = ctk.CTkFrame(body, fg_color=C["bg_card"], corner_radius=12,
                                  border_width=1, border_color=C["border"])
        fmt_frame.grid(row=row, column=0, columnspan=2, sticky="ew", pady=(0, 16))
        row += 1

        self.formato_var = ctk.StringVar(
            value=self.evento.get("formato", "tira_5x15") if self.evento else "tira_5x15")
        for fmt in FORMATOS:
            rb_frame = ctk.CTkFrame(fmt_frame, fg_color="transparent")
            rb_frame.pack(fill="x", padx=12, pady=6)
            ctk.CTkRadioButton(
                rb_frame, text=fmt["label"],
                variable=self.formato_var, value=fmt["key"],
                fg_color=C["primary"], border_color=C["border"],
                text_color=C["text"], font=ctk.CTkFont(size=13, weight="bold"),
                command=self._on_formato_change,
            ).pack(side="left")
            ctk.CTkLabel(rb_frame, text=fmt["desc"],
                         font=ctk.CTkFont(size=11),
                         text_color=C["text_muted"]).pack(side="left", padx=(12, 0))

        # ── Cámara ────────────────────────────────────────────────────────────
        self._lbl(body, t("evento.label_camara"), row, 0); row_hw = row; row += 1
        cam_frame = ctk.CTkFrame(body, fg_color=C["bg_card"], corner_radius=12,
                                  border_width=1, border_color=C["border"])
        cam_frame.grid(row=row_hw, column=0, sticky="nsew", padx=(0, 8), pady=(0, 16))

        self.lbl_cam_status = ctk.CTkLabel(cam_frame, text="Detectando...",
                                            text_color=C["text_muted"],
                                            font=ctk.CTkFont(size=11))
        self.lbl_cam_status.pack(padx=14, pady=(10, 4), anchor="w")

        self.cam_var = ctk.StringVar(value="0")
        self.cam_menu = ctk.CTkOptionMenu(cam_frame, variable=self.cam_var,
                                           values=["Detectando..."],
                                           fg_color=C["bg_hover"],
                                           button_color=C["primary"],
                                           text_color=C["text"])
        self.cam_menu.pack(padx=14, pady=(0, 8), fill="x")

        ctk.CTkButton(cam_frame, text="🎥  Probar cámara",
                      height=34, fg_color="transparent",
                      border_width=1, border_color=C["border"],
                      text_color=C["primary"], font=ctk.CTkFont(size=12),
                      command=self._probar_camara).pack(padx=14, pady=(0, 14), fill="x")

        # ── Impresora ─────────────────────────────────────────────────────────
        self._lbl(body, t("evento.label_impresora"), row_hw, 1)
        imp_frame = ctk.CTkFrame(body, fg_color=C["bg_card"], corner_radius=12,
                                  border_width=1, border_color=C["border"])
        imp_frame.grid(row=row_hw, column=1, sticky="nsew", padx=(8, 0), pady=(0, 16))

        self.lbl_imp_status = ctk.CTkLabel(imp_frame, text="Detectando...",
                                            text_color=C["text_muted"],
                                            font=ctk.CTkFont(size=11))
        self.lbl_imp_status.pack(padx=14, pady=(10, 4), anchor="w")

        self.imp_var = ctk.StringVar(
            value=self.evento.get("impresora", "") if self.evento else "")
        self.imp_menu = ctk.CTkOptionMenu(imp_frame, variable=self.imp_var,
                                           values=["Detectando..."],
                                           fg_color=C["bg_hover"],
                                           button_color=C["primary"],
                                           text_color=C["text"])
        self.imp_menu.pack(padx=14, pady=(0, 8), fill="x")

        copias_row = ctk.CTkFrame(imp_frame, fg_color="transparent")
        copias_row.pack(padx=14, pady=(0, 8), fill="x")
        ctk.CTkLabel(copias_row, text="Copias:",
                     text_color=C["text_gray"],
                     font=ctk.CTkFont(size=12)).pack(side="left")
        self.copias_var = ctk.DoubleVar(
            value=float(self.evento.get("copias", 1) if self.evento else 1))
        ctk.CTkSlider(copias_row, from_=1, to=5, number_of_steps=4,
                      variable=self.copias_var, width=100,
                      button_color=C["primary"]).pack(side="left", padx=8)
        self._copias_display_var = ctk.StringVar(value="1")
        self.copias_var.trace_add("write",
            lambda *_: self._copias_display_var.set(str(int(self.copias_var.get()))))
        ctk.CTkLabel(copias_row, textvariable=self._copias_display_var,
                     text_color=C["text"]).pack(side="left")

        btn_row_imp = ctk.CTkFrame(imp_frame, fg_color="transparent")
        btn_row_imp.pack(padx=14, pady=(0, 14), fill="x")

        ctk.CTkButton(btn_row_imp, text="🖨  Probar impresora",
                      height=34, fg_color="transparent",
                      border_width=1, border_color=C["border"],
                      text_color=C["primary"], font=ctk.CTkFont(size=12),
                      command=self._probar_impresora).pack(side="left", expand=True, fill="x", padx=(0, 6))

        ctk.CTkButton(btn_row_imp, text="⚙  Preferencias",
                      height=34, fg_color="transparent",
                      border_width=1, border_color=C["border"],
                      text_color=C["text_gray"], font=ctk.CTkFont(size=12),
                      command=self._abrir_preferencias_impresora).pack(side="left", expand=True, fill="x")

        # ── Configuración de impresión ────────────────────────────────────────
        self._lbl(body, "Configuración de impresión", row, 0, span=2); row += 1
        prop_frame = ctk.CTkFrame(body, fg_color=C["bg_card"], corner_radius=12,
                                  border_width=1, border_color=C["border"])
        prop_frame.grid(row=row, column=0, columnspan=2, sticky="ew", pady=(0, 16))
        row += 1

        # Variables
        self.papel_var      = ctk.StringVar(value=self.evento.get("papel_size", "10x15") if self.evento else "10x15")
        self.escala_var     = ctk.StringVar(value=self.evento.get("escala_impresion", "exacto") if self.evento else "exacto")
        self.color_modo_var = ctk.StringVar(value=self.evento.get("color_modo", "color") if self.evento else "color")

        # ── Fila 1: ¿Qué papel tenés cargado? ────────────────────────────────
        ctk.CTkLabel(prop_frame, text="¿Qué papel tenés cargado?",
                     font=ctk.CTkFont(size=13, weight="bold"),
                     text_color=C["text"]).pack(anchor="w", padx=16, pady=(14, 8))

        papel_cards = ctk.CTkFrame(prop_frame, fg_color="transparent")
        papel_cards.pack(fill="x", padx=16, pady=(0, 4))

        PAPEL_DEFS = [
            ("10x15", "10×15 cm", "Foto estándar\n(imprime la tira exacta)"),
            ("A4",    "A4",       "210×297 mm\n(papel de oficina)"),
            ("carta", "Carta",    "216×279 mm\n(carta US)"),
            ("15x21", "15×21 cm", "Cuarto de pliego\n(formato intermedio)"),
        ]
        self._papel_btns = {}

        def _seleccionar_papel(key):
            self.papel_var.set(key)
            for k, btn in self._papel_btns.items():
                btn.configure(
                    fg_color=C["primary"] if k == key else C["bg_hover"],
                    border_color=C["primary"] if k == key else C["border"],
                    text_color="#ffffff" if k == key else C["text"],
                )
            # Mostrar/ocultar escala según si el papel es más grande que la tira
            if key == "10x15":
                self.frm_escala.pack_forget()
            else:
                self.frm_escala.pack(fill="x", padx=16, pady=(0, 4),
                                     before=self.frm_color)

        for key, titulo, desc in PAPEL_DEFS:
            sel = self.papel_var.get() == key
            btn = ctk.CTkButton(
                papel_cards, text=f"{titulo}\n{desc}",
                width=130, height=72, corner_radius=10,
                fg_color=C["primary"] if sel else C["bg_hover"],
                border_width=2,
                border_color=C["primary"] if sel else C["border"],
                text_color="#ffffff" if sel else C["text"],
                font=ctk.CTkFont(size=11),
                hover_color=C["primary_dark"],
                command=lambda k=key: _seleccionar_papel(k),
            )
            btn.pack(side="left", padx=(0, 8))
            self._papel_btns[key] = btn

        # ── Fila 2: ¿Cómo querés imprimir? (solo visible si papel > tira) ───
        self.frm_escala = ctk.CTkFrame(prop_frame, fg_color="transparent")
        ctk.CTkLabel(self.frm_escala, text="¿Cómo querés imprimir?",
                     font=ctk.CTkFont(size=13, weight="bold"),
                     text_color=C["text"]).pack(anchor="w", pady=(6, 6))
        for val, ico, titulo, desc in [
            ("exacto", "⬜", "Centrado en la hoja",
             "La tira se imprime a su tamaño real. El resto de la hoja queda en blanco."),
            ("llenar", "▪️", "Llenar la hoja",
             "La imagen se agranda para ocupar todo el papel."),
        ]:
            rb_row = ctk.CTkFrame(self.frm_escala, fg_color="transparent")
            rb_row.pack(fill="x", pady=2)
            ctk.CTkRadioButton(rb_row, text=f"{ico}  {titulo}",
                               variable=self.escala_var, value=val,
                               fg_color=C["primary"], border_color=C["border"],
                               text_color=C["text"],
                               font=ctk.CTkFont(size=12, weight="bold")).pack(side="left")
            ctk.CTkLabel(rb_row, text=f"  —  {desc}",
                         font=ctk.CTkFont(size=11),
                         text_color=C["text_muted"]).pack(side="left")

        # Mostrar escala solo si el papel actual no es 10x15
        if self.papel_var.get() != "10x15":
            self.frm_escala.pack(fill="x", padx=16, pady=(0, 4))

        # ── Fila 3: Color / B&N ───────────────────────────────────────────────
        self.frm_color = ctk.CTkFrame(prop_frame, fg_color="transparent")
        self.frm_color.pack(fill="x", padx=16, pady=(8, 14))

        ctk.CTkLabel(self.frm_color, text="Modo de color:",
                     font=ctk.CTkFont(size=13, weight="bold"),
                     text_color=C["text"]).pack(side="left", padx=(0, 16))
        for val, ico, txt in [("color", "🎨", "Color"), ("byn", "⬛", "Blanco y Negro")]:
            ctk.CTkRadioButton(self.frm_color, text=f"{ico}  {txt}",
                               variable=self.color_modo_var, value=val,
                               fg_color=C["primary"], border_color=C["border"],
                               text_color=C["text"],
                               font=ctk.CTkFont(size=12)).pack(side="left", padx=(0, 20))

        # ── Modo de salida ────────────────────────────────────────────────────
        self._lbl(body, "Modo de salida", row, 0, span=2); row += 1
        modo_frame = ctk.CTkFrame(body, fg_color=C["bg_card"], corner_radius=12,
                                   border_width=1, border_color=C["border"])
        modo_frame.grid(row=row, column=0, columnspan=2, sticky="ew", pady=(0, 16))
        row += 1

        self.modo_var = ctk.StringVar(
            value=self.evento.get("modo_salida", "imprimir") if self.evento else "imprimir")

        modos = [
            ("imprimir", "🖨  Imprimir al instante",
             "Cada sesión se envía a la impresora automáticamente."),
            ("digital",  "💾  Solo guardar digital",
             "Las fotos se guardan en disco pero no se imprimen."),
        ]
        for val, lbl, desc in modos:
            rb_row = ctk.CTkFrame(modo_frame, fg_color="transparent")
            rb_row.pack(fill="x", padx=14, pady=8)
            ctk.CTkRadioButton(
                rb_row, text=lbl, variable=self.modo_var, value=val,
                fg_color=C["primary"], border_color=C["border"],
                text_color=C["text"], font=ctk.CTkFont(size=13, weight="bold"),
                command=self._toggle_digital_ui,
            ).pack(side="left")
            ctk.CTkLabel(rb_row, text=desc,
                         font=ctk.CTkFont(size=11),
                         text_color=C["text_muted"]).pack(side="left", padx=(12, 0))

        # Fila carpeta digital (solo visible cuando modo == digital)
        self.frm_digital = ctk.CTkFrame(modo_frame, fg_color="transparent")
        self.frm_digital.pack(fill="x", padx=14, pady=(0, 10))

        ctk.CTkLabel(self.frm_digital, text="Carpeta de destino:",
                     font=ctk.CTkFont(size=12), text_color=C["text_gray"]).pack(
            side="left", padx=(0, 8))

        self.ruta_digital_var = ctk.StringVar(
            value=self.evento.get("ruta_digital", "") if self.evento else "")
        self.lbl_ruta_digital = ctk.CTkLabel(
            self.frm_digital,
            textvariable=self.ruta_digital_var,
            text_color=C["text"], font=ctk.CTkFont(size=11),
            fg_color=C["bg_hover"], corner_radius=8,
            width=200, height=32)
        self.lbl_ruta_digital.pack(side="left", padx=(0, 8))

        ctk.CTkButton(self.frm_digital, text="📁  Elegir carpeta",
                      height=32, fg_color="transparent",
                      border_width=1, border_color=C["border"],
                      text_color=C["primary"], font=ctk.CTkFont(size=12),
                      command=self._elegir_carpeta_digital).pack(side="left")

        self._toggle_digital_ui()

        # ── Branding (logo o texto del panel inferior) ────────────────────────
        self._lbl(body, "Panel de branding (última sección de la tira)", row, 0, span=2); row += 1
        brand_frame = ctk.CTkFrame(body, fg_color=C["bg_card"], corner_radius=12,
                                    border_width=1, border_color=C["border"])
        brand_frame.grid(row=row, column=0, columnspan=2, sticky="ew", pady=(0, 16))
        row += 1

        ctk.CTkLabel(brand_frame,
                     text="Si elegís un logo, se muestra centrado en el panel. "
                          "Si no, se muestra el nombre y fecha del evento.",
                     font=ctk.CTkFont(size=11), text_color=C["text_muted"],
                     wraplength=580).pack(anchor="w", padx=14, pady=(10, 6))

        brand_row = ctk.CTkFrame(brand_frame, fg_color="transparent")
        brand_row.pack(fill="x", padx=14, pady=(0, 12))

        self.logo_branding_var = ctk.StringVar(
            value=self.evento.get("logo_branding", "") if self.evento else "")
        self.lbl_logo_branding = ctk.CTkLabel(
            brand_row, textvariable=self.logo_branding_var,
            text_color=C["text"], font=ctk.CTkFont(size=11),
            fg_color=C["bg_hover"], corner_radius=8,
            width=280, height=32)
        self.lbl_logo_branding.pack(side="left", padx=(0, 8))

        ctk.CTkButton(brand_row, text="🖼  Elegir logo",
                      height=32, fg_color="transparent",
                      border_width=1, border_color=C["border"],
                      text_color=C["primary"], font=ctk.CTkFont(size=12),
                      command=self._elegir_logo_branding).pack(side="left", padx=(0, 6))
        ctk.CTkButton(brand_row, text="Quitar",
                      height=32, fg_color="transparent",
                      border_width=1, border_color="#3d1010",
                      text_color=C["danger"], font=ctk.CTkFont(size=12),
                      command=lambda: self.logo_branding_var.set("")).pack(side="left")

        # ── Plantilla ─────────────────────────────────────────────────────────
        self._lbl(body, "Plantilla", row, 0, span=2); row += 1
        self.frm_plantillas = ctk.CTkFrame(body, fg_color=C["bg_card"],
                                            corner_radius=12,
                                            border_width=1, border_color=C["border"])
        self.frm_plantillas.grid(row=row, column=0, columnspan=2,
                                  sticky="ew", pady=(0, 16))
        row += 1
        ctk.CTkLabel(self.frm_plantillas, text="Cargando plantillas...",
                     text_color=C["text_muted"]).pack(pady=16)

        # ── Guardar ───────────────────────────────────────────────────────────
        ctk.CTkButton(body, text="Guardar evento", height=50,
                      fg_color=C["primary"], text_color="#ffffff",
                      font=ctk.CTkFont(size=15, weight="bold"),
                      command=self._guardar).grid(
            row=row, column=0, columnspan=2, sticky="ew", pady=(8, 24))

    def _lbl(self, parent, texto, row, col, span=1):
        ctk.CTkLabel(parent, text=texto,
                     font=ctk.CTkFont(size=12, weight="bold"),
                     text_color=C["text_gray"]).grid(
            row=row, column=col, columnspan=span, sticky="w", pady=(10, 2))

    def _toggle_digital_ui(self):
        if self.modo_var.get() == "digital":
            self.frm_digital.pack(fill="x", padx=14, pady=(0, 10))
        else:
            self.frm_digital.pack_forget()

    def _elegir_carpeta_digital(self):
        from tkinter import filedialog
        ruta = filedialog.askdirectory(title="Elegir carpeta para guardar fotos digitales")
        if ruta:
            self.ruta_digital_var.set(ruta)

    def _elegir_logo_branding(self):
        from tkinter import filedialog
        ruta = filedialog.askopenfilename(
            title="Elegir logo para el panel de branding",
            filetypes=[("Imágenes", "*.png *.jpg *.jpeg *.webp *.bmp"), ("Todos", "*.*")])
        if ruta:
            self.logo_branding_var.set(ruta)

    # ── Calendario ─────────────────────────────────────────────────────────────

    def _abrir_calendario(self):
        from screens.calendar_picker import CalendarPicker
        CalendarPicker(self.winfo_toplevel(), callback=self._on_fecha)

    def _on_fecha(self, fecha_str: str):
        self.fecha_var.set(fecha_str)

    # ── Test de cámara ─────────────────────────────────────────────────────────

    def _probar_camara(self):
        if self._cam_preview_win and self._cam_preview_win.winfo_exists():
            self._cam_preview_win.lift()
            return

        cam_nombre = self.cam_var.get()
        cam_index  = next((c.index for c in self._camaras
                           if c.nombre == cam_nombre), 0)

        win = tk.Toplevel(self.winfo_toplevel())
        win.title(f"Vista previa — {cam_nombre}")
        win.configure(bg="#111")
        win.resizable(False, False)
        win.transient(self.winfo_toplevel())
        self._cam_preview_win = win

        lbl_img = tk.Label(win, bg="#111")
        lbl_img.pack(padx=16, pady=(16, 8))

        status_var = tk.StringVar(value="Iniciando cámara...")
        tk.Label(win, textvariable=status_var, bg="#111", fg="#aaa",
                 font=("Arial", 11)).pack()

        btn_captura = tk.Button(win, text="📸  Capturar foto",
                                bg=C["primary"], fg="#000",
                                font=("Arial", 12, "bold"),
                                relief="flat", cursor="hand2", bd=0,
                                padx=20, pady=8,
                                command=lambda: self._captura_test(cam, lbl_img, status_var))
        btn_captura.pack(pady=8)

        tk.Button(win, text="Cerrar", bg="#222", fg="#aaa",
                  font=("Arial", 11), relief="flat", cursor="hand2",
                  padx=16, pady=6,
                  command=lambda: self._cerrar_cam_preview(cam, win)).pack(pady=(0, 16))

        from modules.camera_manager import CameraManager
        cam = CameraManager()

        def start_preview():
            cam.iniciar_preview(cam_index,
                                lambda img: self._on_cam_frame(img, lbl_img, status_var, win),
                                width=640, height=480)

        threading.Thread(target=start_preview, daemon=True).start()

        win.protocol("WM_DELETE_WINDOW", lambda: self._cerrar_cam_preview(cam, win))

    def _on_cam_frame(self, img: Image.Image, lbl, status_var, win):
        if not win.winfo_exists():
            return
        preview = img.copy()
        preview.thumbnail((480, 360), Image.BILINEAR)
        photo = ImageTk.PhotoImage(preview)
        lbl._photo = photo
        try:
            win.after(0, lambda: lbl.configure(image=photo))
            win.after(0, lambda: status_var.set("✓ Cámara activa"))
        except Exception:
            pass

    def _captura_test(self, cam: CameraManager, lbl, status_var):
        img = cam.capturar_foto()
        if img:
            status_var.set("✓ Foto capturada correctamente")
        else:
            status_var.set("⚠  No se pudo capturar foto")

    def _cerrar_cam_preview(self, cam: CameraManager, win):
        cam.detener_preview()
        if win.winfo_exists():
            win.destroy()
        self._cam_preview_win = None

    # ── Test de impresora ──────────────────────────────────────────────────────

    def _abrir_preferencias_impresora(self):
        imp = self.imp_var.get()
        if not imp or imp in ("Detectando...", "Sin impresoras"):
            messagebox.showwarning("Sin impresora", "Seleccioná una impresora primero.")
            return
        import subprocess
        # Abre el diálogo nativo de preferencias de impresora de Windows
        # (tamaño de papel, tipo de papel, calidad, etc.)
        subprocess.Popen(
            ["rundll32", "printui.dll,PrintUIEntry", "/p", f"/n{imp}"],
            shell=False
        )

    def _probar_impresora(self):
        imp = self.imp_var.get()
        if not imp or imp in ("Detectando...", "Sin impresoras"):
            messagebox.showwarning("Sin impresora", "Seleccioná una impresora primero.")
            return
        threading.Thread(target=self._do_test_impresora, args=(imp,), daemon=True).start()

    def _do_test_impresora(self, imp: str):
        try:
            from modules.printer_manager import PrinterManager
            from PIL import Image, ImageDraw, ImageFont
            import os

            W, H = 591, 400
            img = Image.new("RGB", (W, H), "#111111")
            draw = ImageDraw.Draw(img)

            font_path = os.path.join(os.environ.get("WINDIR", "C:/Windows"),
                                     "Fonts", "arialbd.ttf")
            try:
                fnt_big = ImageFont.truetype(font_path, 42)
                fnt_med = ImageFont.truetype(font_path, 22)
                fnt_sml = ImageFont.truetype(font_path, 16)
            except Exception:
                fnt_big = fnt_med = fnt_sml = ImageFont.load_default()

            draw.rectangle([0, 0, W, H], outline="#f5a623", width=6)

            txt = "PhotoBooth"
            bb = draw.textbbox((0, 0), txt, font=fnt_big)
            draw.text(((W - (bb[2]-bb[0])) // 2, 60), txt,
                      fill="#f5a623", font=fnt_big)

            txt2 = "Prueba de impresora"
            bb2 = draw.textbbox((0, 0), txt2, font=fnt_med)
            draw.text(((W - (bb2[2]-bb2[0])) // 2, 130), txt2,
                      fill="#ffffff", font=fnt_med)

            txt3 = imp[:60]
            bb3 = draw.textbbox((0, 0), txt3, font=fnt_sml)
            draw.text(((W - (bb3[2]-bb3[0])) // 2, 180), txt3,
                      fill="#aaaaaa", font=fnt_sml)

            from datetime import datetime
            fecha = datetime.now().strftime("%d/%m/%Y  %H:%M")
            bb4 = draw.textbbox((0, 0), fecha, font=fnt_sml)
            draw.text(((W - (bb4[2]-bb4[0])) // 2, 310), fecha,
                      fill="#888888", font=fnt_sml)

            pm = PrinterManager(imp)
            pm.imprimir_imagen(img)
            self.after(0, lambda: messagebox.showinfo(
                "Impresora", f"Página de prueba enviada a:\n{imp}"))
        except Exception as e:
            self.after(0, lambda err=str(e): messagebox.showerror(
                "Error de impresora", err))

    # ── Detección de hardware ──────────────────────────────────────────────────

    def _cargar_datos(self):
        threading.Thread(target=self._detectar_camaras_bg, daemon=True).start()
        threading.Thread(target=self._detectar_impresoras_bg, daemon=True).start()
        threading.Thread(target=self._cargar_plantillas_bg, daemon=True).start()

    def _detectar_camaras_bg(self):
        try:
            from modules.camera_manager import CameraManager
            self._camaras = CameraManager().detectar_camaras()
        except Exception:
            self._camaras = []
        self.after(0, self._actualizar_camaras_ui)

    def _actualizar_camaras_ui(self):
        if self._camaras:
            nombres = [c.nombre for c in self._camaras]
            self.cam_menu.configure(values=nombres)
            saved = int(self.evento.get("camara_index", 0) if self.evento else 0)
            self.cam_var.set(nombres[saved] if saved < len(nombres) else nombres[0])
            self.lbl_cam_status.configure(
                text=f"✓  {len(self._camaras)} cámara(s) encontrada(s)")
        else:
            self.cam_menu.configure(values=["Sin cámaras"])
            self.cam_var.set("Sin cámaras")
            self.lbl_cam_status.configure(text="⚠  Sin cámaras detectadas")

    def _detectar_impresoras_bg(self):
        try:
            from modules.printer_manager import PrinterManager
            self._impresoras = PrinterManager.listar_impresoras()
        except Exception:
            self._impresoras = []
        self.after(0, self._actualizar_impresoras_ui)

    def _actualizar_impresoras_ui(self):
        if self._impresoras:
            from modules.printer_manager import PrinterManager
            self.imp_menu.configure(values=self._impresoras)
            saved   = self.evento.get("impresora", "") if self.evento else ""
            default = PrinterManager.impresora_predeterminada()
            val = saved if saved in self._impresoras else (
                default if default in self._impresoras else self._impresoras[0])
            self.imp_var.set(val)
            self.lbl_imp_status.configure(
                text=f"✓  {len(self._impresoras)} impresora(s)")
        else:
            self.imp_menu.configure(values=["Sin impresoras"])
            self.imp_var.set("Sin impresoras")
            self.lbl_imp_status.configure(text="⚠  Sin impresoras")

    def _cargar_plantillas_bg(self):
        self._plantillas = self.db.listar_plantillas(self.usuario["id"])
        self.after(0, self._mostrar_plantillas_ui)

    # ── Plantillas ─────────────────────────────────────────────────────────────

    def _on_formato_change(self):
        self._mostrar_plantillas_ui()

    def _mostrar_plantillas_ui(self):
        for w in self.frm_plantillas.winfo_children():
            w.destroy()

        scroll = ctk.CTkScrollableFrame(self.frm_plantillas, fg_color="transparent",
                                         orientation="horizontal", height=200)
        scroll.pack(fill="x", padx=8, pady=8)

        self._thumb_refs.clear()
        fmt = get_formato(self.formato_var.get())

        for p in self._plantillas:
            self._card_plantilla(scroll, p, fmt)

        btn_f = ctk.CTkFrame(scroll, fg_color=C["bg_hover"], corner_radius=12,
                              border_width=1, border_color=C["border"],
                              width=120, height=180)
        btn_f.pack(side="left", padx=6, pady=4)
        btn_f.pack_propagate(False)
        ctk.CTkLabel(btn_f, text="＋", font=ctk.CTkFont(size=32),
                     text_color=C["primary"]).place(relx=0.5, rely=0.38, anchor="center")
        ctk.CTkLabel(btn_f, text="Nueva\nplantilla",
                     font=ctk.CTkFont(size=11), text_color=C["text_gray"],
                     justify="center").place(relx=0.5, rely=0.68, anchor="center")
        for w in [btn_f] + btn_f.winfo_children():
            w.bind("<Button-1>", lambda _: self._abrir_designer())

    def _card_plantilla(self, parent, p: dict, fmt: dict):
        import json, os
        activa = self._plantilla_sel == p["id"]
        frm = ctk.CTkFrame(parent, fg_color=C["bg_card"], corner_radius=12,
                            border_width=2,
                            border_color=C["primary"] if activa else C["border"],
                            width=120, height=180)
        frm.pack(side="left", padx=6, pady=4)
        frm.pack_propagate(False)

        try:
            if p.get("ruta_json") and os.path.exists(p["ruta_json"]):
                with open(p["ruta_json"], encoding="utf-8") as f:
                    cfg = json.load(f)
            else:
                cfg = {"fondo_color": "#1a1a1a", "ancho": fmt["w"], "alto": fmt["h"]}
            from modules.image_processor import ImageProcessor
            thumb = ImageProcessor.preview_plantilla(cfg, size=(100, 145))
        except Exception:
            thumb = Image.new("RGB", (100, 145), "#1a1a1a")

        photo = ImageTk.PhotoImage(thumb)
        self._thumb_refs.append(photo)

        lbl_img = ctk.CTkLabel(frm, image=photo, text="")
        lbl_img.place(relx=0.5, rely=0.44, anchor="center")
        lbl_nom = ctk.CTkLabel(frm, text=p["nombre"][:14],
                               font=ctk.CTkFont(size=10),
                               text_color=C["primary"] if activa else C["text_gray"])
        lbl_nom.place(relx=0.5, rely=0.90, anchor="center")

        def sel(pid=p["id"]):
            self._plantilla_sel = pid
            self._mostrar_plantillas_ui()

        for w in (frm, lbl_img, lbl_nom):
            w.bind("<Button-1>", lambda _e, fn=sel: fn())

    def _abrir_designer(self):
        from modules.template_designer import TemplateDesigner
        TemplateDesigner(self.winfo_toplevel(), self.db, self.usuario["id"],
                         formato_key=self.formato_var.get(),
                         on_guardar=self._on_plantilla_guardada)

    def _on_plantilla_guardada(self, plantilla_id: int):
        self._plantilla_sel = plantilla_id
        threading.Thread(target=self._cargar_plantillas_bg, daemon=True).start()

    # ── Guardar ────────────────────────────────────────────────────────────────

    def _guardar(self):
        try:
            self._guardar_impl()
        except Exception as e:
            import traceback
            traceback.print_exc()
            messagebox.showerror("Error al guardar", str(e))

    def _guardar_impl(self):
        nombre = self.nombre_var.get().strip()
        if not nombre:
            messagebox.showwarning("Falta nombre", "Ingresá un nombre para el evento.")
            return

        cam_nombre = self.cam_var.get()
        cam_index  = next((c.index for c in self._camaras
                           if c.nombre == cam_nombre), 0)

        datos = {
            "nombre":            nombre,
            "fecha_evento":      self.fecha_var.get().strip(),
            "formato":           self.formato_var.get(),
            "camara_index":      cam_index,
            "impresora":         self.imp_var.get(),
            "copias":            int(self.copias_var.get()),
            "plantilla_id":      self._plantilla_sel,
            "modo_salida":       self.modo_var.get(),
            "ruta_digital":      self.ruta_digital_var.get().strip(),
            "logo_branding":     self.logo_branding_var.get().strip(),
            "papel_size":        self.papel_var.get(),
            "escala_impresion":  self.escala_var.get(),
            "color_modo":        self.color_modo_var.get(),
        }

        if self.evento:
            self.db.actualizar_evento(self.evento["id"], **datos)
            evento = {**self.evento, **datos}
        else:
            eid = self.db.crear_evento(self.usuario["id"], nombre,
                                        datos["fecha_evento"])
            self.db.actualizar_evento(eid, **{k: v for k, v in datos.items()
                                               if k != "nombre"})
            evento = {"id": eid, **datos}

        self.db.set_config("camara_index", str(cam_index))
        self.db.set_config("formato", datos["formato"])
        self.on_guardar(evento)
