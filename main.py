import customtkinter as ctk
import threading
import tkinter as tk
import sys, os, logging

from config.settings import APP_NAME, APP_VERSION, PROGRAM_CODE, PAMPA_API_URL, COLORS, DATA_DIR

# Log a archivo para detectar errores en el ejecutable (sin consola)
_log_path = os.path.join(DATA_DIR, "photobooth.log")
os.makedirs(DATA_DIR, exist_ok=True)
logging.basicConfig(
    filename=_log_path, level=logging.ERROR,
    format="%(asctime)s %(levelname)s %(message)s"
)
def _log_exc(exc_type, exc_val, exc_tb):
    logging.error("Unhandled exception", exc_info=(exc_type, exc_val, exc_tb))
sys.excepthook = _log_exc
from modules.database import DatabaseManager
from modules.pampa_client import PampaClient
from modules.i18n import t

ctk.set_appearance_mode("dark")
ctk.set_default_color_theme("dark-blue")

C = COLORS


class PhotoBoothApp(ctk.CTk):
    def report_callback_exception(self, exc_type, exc_val, exc_tb):
        import traceback
        msg = "".join(traceback.format_exception(exc_type, exc_val, exc_tb))
        logging.error("Tkinter callback exception:\n%s", msg)
        from tkinter import messagebox
        messagebox.showerror("Error interno", str(exc_val))

    def __init__(self):
        super().__init__()
        self.title(APP_NAME)
        self.geometry("1200x760")
        self.minsize(960, 640)
        self.configure(fg_color=C["bg"])
        try:
            from config.settings import ASSETS_DIR
            import os
            ico = os.path.join(ASSETS_DIR, "photobooth.ico")
            if os.path.exists(ico):
                self.iconbitmap(ico)
        except Exception:
            pass

        self.db = DatabaseManager()
        self.pampa = PampaClient(PROGRAM_CODE, PAMPA_API_URL)
        self.usuario_actual: dict | None = None
        self._frame_actual: ctk.CTkFrame | None = None

        self._verificar_licencia()

    # ── Licencia ───────────────────────────────────────────────────────────────

    def _verificar_licencia(self):
        self._mostrar_loading("Iniciando PhotoBooth...")
        threading.Thread(target=self._check_lic_bg, daemon=True).start()

    def _check_lic_bg(self):
        license_key = self.db.get_config("license_key", "")
        try:
            resultado = self.pampa.validate_license(license_key) if license_key else None
        except Exception:
            resultado = None

        # Ping de instalación: genera/recupera install_id estable y notifica a PAMPA
        threading.Thread(target=self._ping_install, args=(license_key,), daemon=True).start()

        self.after(0, self._on_lic_result, resultado)

    def _ping_install(self, license_key: str):
        install_id = self.db.get_config("install_id", "")
        if not install_id:
            import hashlib, uuid as _uuid
            install_id = hashlib.sha256(
                (self.pampa.get_hardware_hash() + str(_uuid.uuid4())).encode()
            ).hexdigest()[:32]
            self.db.set_config("install_id", install_id)
        self.pampa.register_install(install_id, license_key=license_key)

    def _on_lic_result(self, resultado):
        if resultado and (resultado.get("valid") or resultado.get("offline_ok")):
            self.mostrar_login()
        elif resultado and resultado.get("status") == "hardware_mismatch":
            msg = resultado.get("message", "Esta licencia está activa en otro equipo. Solicitá la liberación desde Configuración.")
            self.mostrar_activacion(error=msg)
        elif resultado and resultado.get("status") in ("expired", "revoked", "suspended"):
            # Licencia guardada pero inválida → pantalla de activación con mensaje
            msg = resultado.get("message", "Licencia inválida")
            self.mostrar_activacion(error=msg)
        elif self.db.get_config("license_key", ""):
            # Hay clave guardada pero no se pudo validar (offline sin JWT) → activación
            self.mostrar_activacion(error="No se pudo validar la licencia. Verifica tu conexión.")
        else:
            # Sin licencia → pantalla de activación
            self.mostrar_activacion()

    # ── Navegación ─────────────────────────────────────────────────────────────

    def _set_frame(self, frame):
        if self._frame_actual:
            self._frame_actual.destroy()
        self._frame_actual = frame
        frame.pack(fill="both", expand=True)

    def _mostrar_loading(self, msg: str = ""):
        f = ctk.CTkFrame(self, fg_color=C["bg"])
        ctk.CTkLabel(f, text="📷",
                     font=ctk.CTkFont(size=64)).pack(pady=(140, 4))
        ctk.CTkLabel(f, text=APP_NAME,
                     font=ctk.CTkFont(size=30, weight="bold"),
                     text_color=C["primary"]).pack()
        ctk.CTkLabel(f, text=msg,
                     font=ctk.CTkFont(size=13),
                     text_color=C["text_muted"]).pack(pady=(12, 0))
        self._set_frame(f)

    def mostrar_activacion(self, error: str = ""):
        self._set_frame(ActivacionScreen(self, self.db, self.pampa,
                                         on_activado=self.mostrar_login,
                                         on_trial=lambda: self.mostrar_login(trial=True),
                                         error_inicial=error))

    def mostrar_login(self, trial: bool = False):
        self._set_frame(LoginScreen(self, self.db, self._on_login_ok, trial=trial))

    def _on_login_ok(self, usuario: dict):
        self.usuario_actual = usuario
        self.mostrar_dashboard()

    def mostrar_dashboard(self):
        self._set_frame(DashboardScreen(
            self, self.db, self.usuario_actual,
            on_nuevo_evento=lambda: self.mostrar_evento_screen(None),
            on_editar_evento=self.mostrar_evento_screen,
            on_iniciar_cabina=self.iniciar_cabina,
            on_plantillas=self.mostrar_plantillas,
            on_galeria=self.mostrar_galeria,
            on_configuracion=self.mostrar_configuracion,
            on_logout=self._logout,
        ))

    def mostrar_evento_screen(self, evento: dict | None):
        from screens.evento_screen import EventoScreen
        try:
            frame = EventoScreen(
                self, self.db, self.usuario_actual,
                evento=evento,
                on_guardar=self._on_evento_guardado,
                on_cancelar=self.mostrar_dashboard,
            )
            self._set_frame(frame)
        except Exception as e:
            import traceback
            from tkinter import messagebox
            traceback.print_exc()
            messagebox.showerror("Error al abrir evento", str(e))

    def _on_evento_guardado(self, evento: dict):
        self.mostrar_dashboard()

    def iniciar_cabina(self, evento: dict):
        from modules.capture_ui import CaptureUI
        ev = {**evento, "_usuario_rol": (self.usuario_actual or {}).get("rol", "")}
        cabina = CaptureUI(self, self.db, ev)
        cabina.grab_set()

    def mostrar_plantillas(self):
        from screens.plantillas_screen import PlantillasScreen
        self._set_frame(PlantillasScreen(
            self, self.db, self.usuario_actual,
            on_volver=self.mostrar_dashboard,
        ))

    def mostrar_galeria(self, evento: dict):
        from screens.galeria_screen import GaleriaScreen
        self._set_frame(GaleriaScreen(
            self, self.db, self.usuario_actual,
            evento=evento,
            on_volver=self.mostrar_dashboard,
        ))

    def mostrar_configuracion(self):
        from screens.configuracion_screen import ConfiguracionScreen
        self._set_frame(ConfiguracionScreen(
            self, self.db, self.usuario_actual,
            on_volver=self.mostrar_dashboard,
        ))

    def _logout(self):
        self.usuario_actual = None
        self.mostrar_login()


# ── Activación Screen ─────────────────────────────────────────────────────────

class ActivacionScreen(tk.Canvas):
    """Pantalla de activación de licencia. Se muestra cuando no hay licencia válida."""

    def __init__(self, master, db: DatabaseManager, pampa, on_activado, on_trial,
                 error_inicial: str = ""):
        super().__init__(master, bd=0, highlightthickness=0, bg="#1c0439")
        self.db       = db
        self.pampa    = pampa
        self.on_activado = on_activado
        self.on_trial    = on_trial
        self._bg_ref  = None
        self._bg_id   = None
        self._card_id = None

        self.key_var   = ctk.StringVar()
        self.error_var = ctk.StringVar(value=error_inicial)

        # ── Tarjeta ───────────────────────────────────────────────────────────
        rim  = ctk.CTkFrame(self, fg_color="#7c50d0", corner_radius=28)
        glow = ctk.CTkFrame(rim,  fg_color="#2a1060", corner_radius=26)
        glow.pack(padx=2, pady=2)
        card = ctk.CTkFrame(glow, fg_color="#0e0820", corner_radius=22)
        card.pack(padx=3, pady=3)

        ctk.CTkLabel(card, text="📷",
                     font=ctk.CTkFont(size=52)).pack(pady=(32, 4))
        ctk.CTkLabel(card, text=APP_NAME,
                     font=ctk.CTkFont(size=24, weight="bold"),
                     text_color=C["primary"]).pack()
        ctk.CTkLabel(card, text="Activar licencia",
                     font=ctk.CTkFont(size=13),
                     text_color=C["text_muted"]).pack(pady=(4, 0))

        ctk.CTkFrame(card, fg_color="#2a1a4a", height=1,
                     corner_radius=0).pack(fill="x", padx=32, pady=(16, 20))

        ctk.CTkLabel(card,
                     text="Ingresá tu clave de licencia para activar PhotoBooth.",
                     font=ctk.CTkFont(size=12),
                     text_color=C["text_gray"],
                     wraplength=300).pack(padx=32)

        ctk.CTkEntry(card, textvariable=self.key_var,
                     placeholder_text="PB-XXXX-XXXX-XXXX-XXXX",
                     width=300, height=42,
                     font=ctk.CTkFont(size=13)).pack(pady=(14, 6), padx=32)

        ctk.CTkLabel(card, textvariable=self.error_var,
                     text_color=C["danger"],
                     font=ctk.CTkFont(size=11),
                     wraplength=300).pack()

        self.btn_activar = ctk.CTkButton(
            card, text="Activar licencia", width=300, height=42,
            fg_color=C["primary"], text_color="#ffffff",
            font=ctk.CTkFont(size=14, weight="bold"),
            command=self._activar)
        self.btn_activar.pack(pady=(10, 6), padx=32)

        ctk.CTkButton(card, text="Continuar sin licencia  →",
                      fg_color="transparent", text_color=C["text_muted"],
                      hover_color="#1a0a30", font=ctk.CTkFont(size=12),
                      width=300, height=32,
                      command=self.on_trial).pack(pady=(0, 28))

        self._card_id = self.create_window(0, 0, window=rim, anchor="center")
        self.bind("<Configure>", self._on_canvas_resize)
        self.winfo_toplevel().bind("<Configure>", self._on_tl_resize, add="+")
        self.after(150, self._render_bg)
        master.bind("<Return>", lambda _: self._activar())

    def _activar(self):
        key = self.key_var.get().strip().upper()
        if not key:
            self.error_var.set("Ingresá una clave de licencia.")
            return
        self.btn_activar.configure(state="disabled", text="Verificando...")
        self.error_var.set("")
        threading.Thread(target=self._do_activar, args=(key,), daemon=True).start()

    def _do_activar(self, key: str):
        try:
            res = self.pampa.validate_license(key, force_online=True)
        except Exception as e:
            res = {"valid": False, "message": str(e)}

        if not self.winfo_exists():
            return
        if res and (res.get("valid") or res.get("offline_ok")):
            self.db.set_config("license_key", key)
            self.after(0, self.on_activado)
        else:
            raw = res.get("message", "") if res else ""
            if not res or "connect" in raw.lower() or "timeout" in raw.lower():
                msg = "No se pudo conectar con el servidor. Verificá tu conexión."
            elif "already" in raw.lower() or "activ" in raw.lower():
                msg = "Esta licencia ya está activada en otro equipo.\nLiberála desde tu panel en pampaguazu.com.ar antes de activarla acá."
            elif "invalid" in raw.lower() or "inválid" in raw.lower() or not raw:
                msg = "Clave de licencia incorrecta. Verificá que la copiaste bien."
            elif "expired" in raw.lower() or "venc" in raw.lower():
                msg = "Esta licencia está vencida. Renovála desde pampaguazu.com.ar."
            elif "revoked" in raw.lower():
                msg = "Esta licencia fue revocada. Contactá a soporte."
            else:
                msg = raw or "No se pudo activar la licencia."
            self.after(0, lambda m=msg: self._mostrar_error(m))

    def _mostrar_error(self, msg: str):
        self.error_var.set(msg)
        self.btn_activar.configure(state="normal", text="Activar licencia")

    # ── Fondo (mismo sistema que LoginScreen) ─────────────────────────────────
    def _center_card(self):
        w, h = self.winfo_width(), self.winfo_height()
        if w > 10 and self._card_id:
            self.coords(self._card_id, w // 2, h // 2)

    def _render_bg(self, w=None, h=None):
        from PIL import Image, ImageFilter, ImageTk
        from config.settings import ASSETS_DIR
        import os
        tl = self.winfo_toplevel()
        w = w or tl.winfo_width()
        h = h or tl.winfo_height()
        if w < 100 or h < 100:
            self.after(120, self._render_bg)
            return
        path = os.path.join(ASSETS_DIR, "photobooth_icon.png")
        if not os.path.exists(path):
            return
        icon = Image.open(path).convert("RGBA")
        scale = max(w / icon.width, h / icon.height) * 2.5
        nw, nh = int(icon.width * scale), int(icon.height * scale)
        icon = icon.resize((nw, nh), Image.LANCZOS)
        bg = Image.new("RGBA", (w, h), (28, 4, 58, 255))
        bg.paste(icon, ((w - nw) // 2, (h - nh) // 2), icon)
        bg = bg.filter(ImageFilter.GaussianBlur(radius=28))
        overlay = Image.new("RGBA", (w, h), (18, 2, 42, 90))
        bg = Image.alpha_composite(bg, overlay)
        self._bg_ref = ImageTk.PhotoImage(bg.convert("RGB"))
        if self._bg_id:
            self.itemconfig(self._bg_id, image=self._bg_ref)
            self.coords(self._bg_id, 0, 0)
        else:
            self._bg_id = self.create_image(0, 0, anchor="nw", image=self._bg_ref)
            self.tag_lower(self._bg_id)
        self._center_card()

    def _on_canvas_resize(self, event):
        if not self.winfo_exists(): return
        if event.width > 100:
            self._render_bg(event.width, event.height)

    def _on_tl_resize(self, event):
        if not self.winfo_exists(): return
        tl = self.winfo_toplevel()
        if event.widget is tl and event.width > 100:
            self._render_bg(event.width, event.height)


# ── Login Screen ───────────────────────────────────────────────────────────────

class LoginScreen(tk.Canvas):
    def __init__(self, master, db: DatabaseManager, on_ok, trial=False):
        super().__init__(master, bd=0, highlightthickness=0, bg="#1c0439")
        self.db = db
        self.on_ok = on_ok
        self._bg_ref  = None
        self._bg_id   = None
        self._card_id = None

        self.email_var    = ctk.StringVar()
        self.pass_var     = ctk.StringVar()
        self.error_var    = ctk.StringVar()
        self.remember_var = ctk.BooleanVar()

        saved_email = db.get_config("remember_email", "")
        if saved_email:
            self.email_var.set(saved_email)
            self.remember_var.set(True)

        # ── Tarjeta centrada ──────────────────────────────────────────────────
        rim = ctk.CTkFrame(self, fg_color="#7c50d0", corner_radius=28, border_width=0)

        glow = ctk.CTkFrame(rim, fg_color="#2a1060", corner_radius=26, border_width=0)
        glow.pack(padx=2, pady=2)

        card = ctk.CTkFrame(glow, fg_color="#0e0820", corner_radius=22, border_width=0)
        card.pack(padx=3, pady=3)

        # Ícono + nombre
        ctk.CTkLabel(card, text="📷",
                     font=ctk.CTkFont(size=52)).pack(pady=(32, 4))
        ctk.CTkLabel(card, text=APP_NAME,
                     font=ctk.CTkFont(size=26, weight="bold"),
                     text_color=C["primary"]).pack()
        ctk.CTkLabel(card, text=f"v{APP_VERSION}",
                     font=ctk.CTkFont(size=11),
                     text_color=C["text_muted"]).pack(pady=(0, 6))

        if trial:
            ctk.CTkLabel(card, text=t("login.trial_aviso"),
                         font=ctk.CTkFont(size=12),
                         text_color=C["warning"]).pack(pady=(0, 6))

        ctk.CTkFrame(card, fg_color="#2a1a4a", height=1,
                     corner_radius=0).pack(fill="x", padx=32, pady=(4, 20))

        ctk.CTkLabel(card, text="Iniciar sesión",
                     font=ctk.CTkFont(size=14, weight="bold"),
                     text_color=C["text"]).pack(pady=(0, 14))

        # Email
        ctk.CTkEntry(card, textvariable=self.email_var,
                     placeholder_text="Correo electrónico",
                     width=300, height=42).pack(pady=(0, 8), padx=32)

        # Contraseña
        pass_cont = ctk.CTkFrame(card, fg_color="#1d1535",
                                 corner_radius=8, border_width=1,
                                 border_color="#3a2a5a", width=300, height=42)
        pass_cont.pack(pady=(0, 8), padx=32)
        pass_cont.pack_propagate(False)

        self._pass_visible = False
        self.pass_entry = ctk.CTkEntry(pass_cont, textvariable=self.pass_var,
                                       placeholder_text="Contraseña",
                                       show="•", border_width=0,
                                       fg_color="transparent",
                                       width=254, height=38)
        self.pass_entry.pack(side="left", padx=(6, 0))
        ctk.CTkButton(pass_cont, text="👁", width=36, height=34,
                      fg_color="transparent", text_color=C["text_gray"],
                      hover_color="#2a1a4a",
                      command=self._toggle_pass).pack(side="right", padx=(0, 3))

        ctk.CTkCheckBox(card, text="Recordarme",
                        variable=self.remember_var,
                        font=ctk.CTkFont(size=12),
                        text_color=C["text_gray"],
                        checkmark_color="#ffffff",
                        fg_color=C["primary"],
                        hover_color=C["primary_dark"],
                        ).pack(pady=(2, 2), padx=32, anchor="w")

        ctk.CTkLabel(card, textvariable=self.error_var,
                     text_color=C["danger"],
                     font=ctk.CTkFont(size=12)).pack(pady=(2, 0))

        self.btn = ctk.CTkButton(
            card, text="Ingresar", width=300, height=42,
            fg_color=C["primary"], text_color="#ffffff",
            font=ctk.CTkFont(size=14, weight="bold"),
            command=self._login,
        )
        self.btn.pack(pady=(6, 32))

        # Colocar tarjeta en el canvas (centrada)
        self._card_id = self.create_window(0, 0, window=rim, anchor="center")

        # Fondo y resize
        self.bind("<Configure>", self._on_canvas_resize)
        self.winfo_toplevel().bind("<Configure>", self._on_tl_resize, add="+")
        self.after(150, self._render_bg)

        master.bind("<Return>", lambda _: self._login())

    def _center_card(self):
        w, h = self.winfo_width(), self.winfo_height()
        if w > 10 and self._card_id:
            self.coords(self._card_id, w // 2, h // 2)

    def _render_bg(self, w=None, h=None):
        from PIL import Image, ImageFilter, ImageTk
        from config.settings import ASSETS_DIR
        import os
        tl = self.winfo_toplevel()
        w = w or tl.winfo_width()
        h = h or tl.winfo_height()
        if w < 100 or h < 100:
            self.after(120, self._render_bg)
            return
        path = os.path.join(ASSETS_DIR, "photobooth_icon.png")
        if not os.path.exists(path):
            return
        icon = Image.open(path).convert("RGBA")
        scale = max(w / icon.width, h / icon.height) * 2.5
        nw, nh = int(icon.width * scale), int(icon.height * scale)
        icon = icon.resize((nw, nh), Image.LANCZOS)
        bg = Image.new("RGBA", (w, h), (28, 4, 58, 255))
        bg.paste(icon, ((w - nw) // 2, (h - nh) // 2), icon)
        bg = bg.filter(ImageFilter.GaussianBlur(radius=28))
        overlay = Image.new("RGBA", (w, h), (18, 2, 42, 90))
        bg = Image.alpha_composite(bg, overlay)
        self._bg_ref = ImageTk.PhotoImage(bg.convert("RGB"))
        if self._bg_id:
            self.itemconfig(self._bg_id, image=self._bg_ref)
            self.coords(self._bg_id, 0, 0)
        else:
            self._bg_id = self.create_image(0, 0, anchor="nw", image=self._bg_ref)
            self.tag_lower(self._bg_id)  # imagen siempre debajo de la tarjeta
        self._center_card()

    def _on_canvas_resize(self, event):
        if not self.winfo_exists(): return
        if event.width > 100:
            self._render_bg(event.width, event.height)

    def _on_tl_resize(self, event):
        if not self.winfo_exists(): return
        tl = self.winfo_toplevel()
        if event.widget is tl and event.width > 100:
            self._render_bg(event.width, event.height)

    def _toggle_pass(self):
        self._pass_visible = not self._pass_visible
        self.pass_entry.configure(show="" if self._pass_visible else "•")

    def _login(self):
        email = self.email_var.get().strip()
        pwd   = self.pass_var.get()
        if not email or not pwd:
            return
        self.btn.configure(state="disabled", text="Verificando...")
        self.after(50, lambda: self._do_login(email, pwd))

    def _do_login(self, email, pwd):
        usuario = self.db.autenticar_usuario(email, pwd)
        if usuario:
            if self.remember_var.get():
                self.db.set_config("remember_email", email)
            else:
                self.db.set_config("remember_email", "")
            self.winfo_toplevel().unbind("<Return>")
            self.on_ok(usuario)
        else:
            self.error_var.set("Correo o contraseña incorrectos")
            self.btn.configure(state="normal", text="Ingresar")


# ── Dashboard Screen ────────────────────────────────────────────────────────────

class DashboardScreen(ctk.CTkFrame):
    def __init__(self, master, db: DatabaseManager, usuario: dict,
                 on_nuevo_evento, on_editar_evento, on_iniciar_cabina,
                 on_plantillas, on_galeria, on_configuracion, on_logout):
        super().__init__(master, fg_color=C["bg"])
        self.db = db
        self.usuario = usuario
        self.on_editar_evento = on_editar_evento
        self.on_iniciar_cabina = on_iniciar_cabina
        self.on_galeria = on_galeria

        # ── Sidebar ──────────────────────────────────────────────────────────
        sidebar = ctk.CTkFrame(self, fg_color=C["sidebar"], width=230, corner_radius=0)
        sidebar.pack(side="left", fill="y")
        sidebar.pack_propagate(False)

        ctk.CTkLabel(sidebar, text="📷",
                     font=ctk.CTkFont(size=38)).pack(pady=(36, 4))
        ctk.CTkLabel(sidebar, text=APP_NAME,
                     font=ctk.CTkFont(size=17, weight="bold"),
                     text_color=C["primary"]).pack()
        ctk.CTkLabel(sidebar, text=usuario.get("nombre", ""),
                     font=ctk.CTkFont(size=12),
                     text_color=C["text_gray"]).pack(pady=(2, 0))

        ctk.CTkFrame(sidebar, height=1,
                     fg_color=C["border"]).pack(fill="x", padx=16, pady=20)

        def nav(txt, cmd, danger=False):
            ctk.CTkButton(
                sidebar, text=txt, anchor="w",
                fg_color="transparent",
                hover_color=C["bg_hover"] if not danger else "#1a0000",
                text_color=C["danger"] if danger else C["text_gray"],
                font=ctk.CTkFont(size=13), height=40,
                command=cmd,
            ).pack(fill="x", padx=10, pady=2)

        nav("➕  Nuevo evento", on_nuevo_evento)
        nav("🖼  Plantillas", on_plantillas)
        nav("⚙  Configuración", on_configuracion)
        nav("⬅  Cerrar sesión", on_logout, danger=True)

        ctk.CTkLabel(sidebar, text=f"v{APP_VERSION}",
                     font=ctk.CTkFont(size=10),
                     text_color=C["text_muted"]).pack(side="bottom", pady=12)

        # ── Área principal ────────────────────────────────────────────────────
        main = ctk.CTkFrame(self, fg_color=C["bg"], corner_radius=0)
        main.pack(side="left", fill="both", expand=True)

        hdr = ctk.CTkFrame(main, fg_color="transparent")
        hdr.pack(fill="x", padx=28, pady=(28, 0))
        ctk.CTkLabel(hdr, text="Mis eventos",
                     font=ctk.CTkFont(size=24, weight="bold"),
                     text_color=C["text"]).pack(side="left")

        self.scroll = ctk.CTkScrollableFrame(main, fg_color="transparent")
        self.scroll.pack(fill="both", expand=True, padx=28, pady=16)
        self._cargar()

    def _cargar(self):
        for w in self.scroll.winfo_children():
            w.destroy()

        eventos = self.db.listar_eventos(self.usuario["id"])
        if not eventos:
            ctk.CTkLabel(self.scroll,
                         text="No hay eventos. Creá uno con el botón ➕",
                         text_color=C["text_muted"],
                         font=ctk.CTkFont(size=15)).pack(pady=80)
            return

        for ev in eventos:
            self._card(ev)

    def _card(self, ev: dict):
        from modules.print_queue import PrintQueue
        stats  = self.db.stats_evento(ev["id"])
        n_cola = PrintQueue.count(self.db, ev["id"])

        card = ctk.CTkFrame(self.scroll, fg_color=C["bg_card"],
                            corner_radius=14, border_width=1,
                            border_color=C["border"])
        card.pack(fill="x", pady=6)

        # ── Info ──────────────────────────────────────────────────────────────
        info = ctk.CTkFrame(card, fg_color="transparent")
        info.pack(side="left", fill="both", expand=True, padx=20, pady=16)

        ctk.CTkLabel(info, text=ev["nombre"],
                     font=ctk.CTkFont(size=16, weight="bold"),
                     text_color=C["text"]).pack(anchor="w")

        from config.formatos import get_formato
        fmt_obj  = get_formato(ev.get("formato", ""))
        fmt_str  = fmt_obj["label"] if fmt_obj else ev.get("formato", "")
        meta_parts = []
        if ev.get("fecha_evento"): meta_parts.append(ev["fecha_evento"])
        if fmt_str:               meta_parts.append(fmt_str)
        if ev.get("impresora"):   meta_parts.append(ev["impresora"][:28])
        meta_parts.append(f"{stats['sesiones']} sesiones · {stats['impresas']} impresas")
        ctk.CTkLabel(info, text="  ·  ".join(meta_parts),
                     font=ctk.CTkFont(size=12),
                     text_color=C["text_gray"]).pack(anchor="w", pady=(3, 0))

        if n_cola > 0:
            cola_info = ctk.CTkFrame(info, fg_color="transparent")
            cola_info.pack(anchor="w", pady=(4, 0))
            ctk.CTkLabel(cola_info,
                         text=f"⏳ {n_cola} tira{'s' if n_cola > 1 else ''} en cola de impresión",
                         font=ctk.CTkFont(size=11), text_color=C["warning"]).pack(side="left")

        # ── Botones ───────────────────────────────────────────────────────────
        btns = ctk.CTkFrame(card, fg_color="transparent")
        btns.pack(side="right", padx=16, pady=16)

        ctk.CTkButton(
            btns, text="▶  Iniciar cabina",
            width=170, height=40,
            fg_color=C["primary"], text_color="#ffffff",
            font=ctk.CTkFont(size=13, weight="bold"),
            command=lambda e=ev: self.on_iniciar_cabina(e),
        ).pack(pady=(0, 6))

        row2 = ctk.CTkFrame(btns, fg_color="transparent")
        row2.pack(fill="x")

        ctk.CTkButton(row2, text="Editar", width=60, height=32,
                      fg_color="transparent", border_width=1, border_color=C["border"],
                      text_color=C["text_gray"],
                      command=lambda e=ev: self.on_editar_evento(e),
                      ).pack(side="left", padx=(0, 4))

        ctk.CTkButton(row2, text="Galería", width=72, height=32,
                      fg_color="transparent", border_width=1, border_color=C["border"],
                      text_color=C["text_gray"],
                      command=lambda e=ev: self.on_galeria(e),
                      ).pack(side="left", padx=(0, 4))

        ctk.CTkButton(row2, text="Vista previa", width=90, height=32,
                      fg_color="transparent", border_width=1, border_color=C["border"],
                      text_color=C["primary"],
                      command=lambda e=ev: self._vista_previa_impresion(e),
                      ).pack(side="left", padx=(0, 4))

        ctk.CTkButton(row2, text="🗑", width=34, height=32,
                      fg_color="transparent", border_width=1, border_color="#3d1010",
                      text_color=C["danger"],
                      command=lambda e=ev: self._confirmar_eliminar(e),
                      ).pack(side="left")

        cola_label = (f"🖨 Imprimir cola ({n_cola})" if n_cola > 0
                      else "🖨 Imprimir cola")
        ctk.CTkButton(btns, text=cola_label,
                      height=28, width=170,
                      fg_color="transparent",
                      border_width=1,
                      border_color=C["warning"] if n_cola > 0 else C["border"],
                      text_color=C["warning"] if n_cola > 0 else C["text_muted"],
                      font=ctk.CTkFont(size=11),
                      command=lambda e=ev: self._vaciar_cola(e),
                      ).pack(pady=(6, 0))

    # ── Eliminar evento ───────────────────────────────────────────────────────

    def _confirmar_eliminar(self, ev: dict):
        from tkinter import messagebox
        ok = messagebox.askyesno(
            "Eliminar evento",
            f"¿Eliminar el evento \"{ev['nombre']}\"?\n\n"
            "Las sesiones y fotos guardadas no se borran del disco.",
            icon="warning")
        if ok:
            self.db.eliminar_evento(ev["id"])
            self._cargar()

    # ── Vista previa de impresión ─────────────────────────────────────────────

    def _vista_previa_impresion(self, ev: dict):
        import tkinter as tk
        from PIL import Image, ImageTk
        from modules.image_processor import ImageProcessor
        from modules.printer_manager import PrinterManager
        from config.formatos import get_formato

        fmt = get_formato(ev.get("formato", "tira_5x15"))

        # Componer la tira con fotos de muestra
        plantilla_dict = None
        if ev.get("plantilla_id"):
            plantilla_dict = self.db.obtener_plantilla(ev["plantilla_id"])

        tira = ImageProcessor.preview_plantilla(
            ImageProcessor._config_default(evento=ev),
            size=(fmt["w"], fmt["h"]))

        # Armar el canvas de impresión (2-up o directo)
        img_print = PrinterManager.preparar_para_impresion(tira, fmt["key"])

        # Representar el papel (fondo blanco) con la imagen centrada
        PAPER_PREVIEW_H = 520
        ratio = PAPER_PREVIEW_H / img_print.height
        pw = int(img_print.width * ratio)
        ph = PAPER_PREVIEW_H
        img_scaled = img_print.resize((pw, ph), Image.LANCZOS)

        # Ventana modal
        win = tk.Toplevel(self.winfo_toplevel())
        win.title(f"Vista previa — {ev['nombre']}")
        win.configure(bg=C["bg"])
        win.resizable(False, False)
        win.grab_set()

        # Encabezado
        ctk.CTkLabel(win, text="Vista previa de impresión",
                     font=ctk.CTkFont(size=18, weight="bold"),
                     text_color=C["text"]).pack(pady=(20, 4))

        imp_str = ev.get("impresora") or "Impresora predeterminada"
        ctk.CTkLabel(win,
                     text=f"{fmt['label']}   ·   {fmt['print_w_mm']}×{fmt['print_h_mm']} mm   ·   {imp_str[:40]}",
                     font=ctk.CTkFont(size=12), text_color=C["text_muted"]).pack()

        # Canvas con sombra
        outer = ctk.CTkFrame(win, fg_color=C["bg_hover"], corner_radius=12)
        outer.pack(padx=32, pady=16)

        photo = ImageTk.PhotoImage(img_scaled)
        lbl = tk.Label(outer, image=photo, bg=C["bg_hover"], relief="flat")
        lbl.image = photo
        lbl.pack(padx=16, pady=16)

        ctk.CTkLabel(win,
                     text="Fotos de muestra — la tira real usará las fotos de la sesión",
                     font=ctk.CTkFont(size=10), text_color=C["text_muted"]).pack(pady=(0, 8))

        ctk.CTkButton(win, text="Cerrar", width=120, height=36,
                      fg_color=C["primary"], text_color="#ffffff",
                      command=win.destroy).pack(pady=(0, 20))

    # ── Cola ─────────────────────────────────────────────────────────────────

    def _vaciar_cola(self, ev: dict):
        from modules.print_queue import PrintQueue
        from tkinter import messagebox
        n_cola = PrintQueue.count(self.db, ev["id"])
        if n_cola == 0:
            messagebox.showinfo("Cola vacía",
                                "No hay tiras pendientes en la cola de este evento.")
            return
        def on_done(n, err):
            self.after(0, self._cargar)
            if err:
                self.after(0, lambda: messagebox.showerror("Error de impresión", err))
            elif n > 0:
                self.after(0, lambda: messagebox.showinfo(
                    "Listo", f"Se imprimieron {n} tira{'s' if n > 1 else ''}."))
        PrintQueue.vaciar(self.db, ev, on_done=on_done)


# ── Registrar screens en sys.modules ──────────────────────────────────────────
import sys, types

def _reg(mod_name, cls_name, cls):
    m = types.ModuleType(mod_name)
    setattr(m, cls_name, cls)
    sys.modules[mod_name] = m

_reg("screens.dashboard_screen", "DashboardScreen", DashboardScreen)

# ── Entry point ────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    import ctypes
    try:
        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID("PampaGuazu.PhotoBooth")
    except Exception:
        pass
    app = PhotoBoothApp()
    app.mainloop()
