"""
ConfiguracionScreen — ajustes generales de la aplicación.
Idioma, cámara predeterminada, impresora predeterminada, tiempo de inactividad y licencia.
"""
import threading
import customtkinter as ctk
from tkinter import messagebox

from config.settings import COLORS, APP_VERSION
from modules.database import DatabaseManager
from modules.i18n import t, set_language, get_language

C = COLORS

IDIOMAS = [("Español", "es"), ("English", "en"), ("Português", "pt")]


class ConfiguracionScreen(ctk.CTkFrame):
    def __init__(self, master, db: DatabaseManager, usuario: dict, on_volver):
        super().__init__(master, fg_color=C["bg"])
        self.db = db
        self.usuario = usuario
        self.on_volver = on_volver

        self._camaras: list = []
        self._impresoras: list[str] = []

        self._build_ui()
        self._cargar_valores()
        self._detectar_dispositivos()

    # ── UI ─────────────────────────────────────────────────────────────────────

    def _build_ui(self):
        hdr = ctk.CTkFrame(self, fg_color="transparent")
        hdr.pack(fill="x", padx=24, pady=(20, 0))

        ctk.CTkButton(hdr, text=t("comun.volver"), width=90,
                      fg_color="transparent", border_width=1,
                      border_color=C["border"], text_color=C["text_gray"],
                      command=self.on_volver).pack(side="left")

        ctk.CTkLabel(hdr, text=t("configuracion.titulo"),
                     font=ctk.CTkFont(size=22, weight="bold"),
                     text_color=C["text"]).pack(side="left", padx=20)

        ctk.CTkLabel(hdr, text=f"v{APP_VERSION}",
                     font=ctk.CTkFont(size=11),
                     text_color=C["text_muted"]).pack(side="right")

        scroll = ctk.CTkScrollableFrame(self, fg_color="transparent")
        scroll.pack(fill="both", expand=True, padx=24, pady=16)

        self._build_seccion_idioma(scroll)
        self._build_seccion_camara(scroll)
        self._build_seccion_impresora(scroll)
        self._build_seccion_idle(scroll)
        self._build_seccion_licencia(scroll)

        ctk.CTkButton(self, text=t("configuracion.btn_guardar"), height=46,
                      fg_color=C["primary"], text_color="#ffffff",
                      font=ctk.CTkFont(size=14, weight="bold"),
                      command=self._guardar).pack(padx=24, pady=(0, 20))

    def _seccion(self, parent, titulo: str) -> ctk.CTkFrame:
        box = ctk.CTkFrame(parent, fg_color=C["bg_card"],
                           corner_radius=14, border_width=1,
                           border_color=C["border"])
        box.pack(fill="x", pady=8)
        ctk.CTkLabel(box, text=titulo,
                     font=ctk.CTkFont(size=14, weight="bold"),
                     text_color=C["primary"]).pack(anchor="w", padx=20, pady=(16, 8))
        ctk.CTkFrame(box, height=1, fg_color=C["border"]).pack(fill="x", padx=20)
        return box

    def _fila(self, parent, label: str) -> ctk.CTkFrame:
        row = ctk.CTkFrame(parent, fg_color="transparent")
        row.pack(fill="x", padx=20, pady=8)
        ctk.CTkLabel(row, text=label, width=220, anchor="w",
                     font=ctk.CTkFont(size=13),
                     text_color=C["text_gray"]).pack(side="left")
        return row

    def _build_seccion_idioma(self, parent):
        box = self._seccion(parent, t("configuracion.sec_idioma"))
        row = self._fila(box, t("configuracion.label_idioma_interfaz"))
        self._seg_idioma = ctk.CTkSegmentedButton(
            row,
            values=[lbl for lbl, _ in IDIOMAS],
            width=300,
            command=self._on_idioma_click,
        )
        self._seg_idioma.pack(side="left")

    def _build_seccion_camara(self, parent):
        box = self._seccion(parent, t("configuracion.sec_camara"))
        row = self._fila(box, t("configuracion.label_camara_default"))
        self.combo_camara = ctk.CTkComboBox(
            row, values=[t("comun.detectando")], width=300, state="readonly")
        self.combo_camara.pack(side="left")
        ctk.CTkButton(row, text="🔄", width=36, height=32,
                      fg_color="transparent", border_width=1, border_color=C["border"],
                      text_color=C["primary"],
                      command=self._redetectar_camaras).pack(side="left", padx=(8, 0))
        self.lbl_camara_status = ctk.CTkLabel(
            box, text="", font=ctk.CTkFont(size=11), text_color=C["text_muted"])
        self.lbl_camara_status.pack(anchor="w", padx=20, pady=(0, 12))

    def _build_seccion_impresora(self, parent):
        box = self._seccion(parent, t("configuracion.sec_impresora"))
        row = self._fila(box, t("configuracion.label_impresora_default"))
        self.combo_impresora = ctk.CTkComboBox(
            row, values=[t("comun.detectando")], width=300, state="readonly")
        self.combo_impresora.pack(side="left")
        ctk.CTkButton(row, text="🔄", width=36, height=32,
                      fg_color="transparent", border_width=1, border_color=C["border"],
                      text_color=C["primary"],
                      command=self._redetectar_impresoras).pack(side="left", padx=(8, 0))
        self.lbl_imp_status = ctk.CTkLabel(
            box, text="", font=ctk.CTkFont(size=11), text_color=C["text_muted"])
        self.lbl_imp_status.pack(anchor="w", padx=20, pady=(0, 12))

    def _build_seccion_idle(self, parent):
        box = self._seccion(parent, t("configuracion.sec_reposo"))
        row = self._fila(box, t("configuracion.label_idle"))
        self.idle_var = ctk.StringVar(value="60")
        ctk.CTkEntry(row, textvariable=self.idle_var, width=100, height=36).pack(side="left")
        ctk.CTkLabel(row, text=t("configuracion.idle_hint"),
                     font=ctk.CTkFont(size=11),
                     text_color=C["text_muted"]).pack(side="left", padx=10)

    def _build_seccion_licencia(self, parent):
        box = self._seccion(parent, t("configuracion.sec_licencia"))
        row = self._fila(box, t("configuracion.label_licencia"))
        self.lic_var = ctk.StringVar()
        ctk.CTkEntry(row, textvariable=self.lic_var, width=340, height=36,
                     placeholder_text="XXXX-XXXX-XXXX-XXXX").pack(side="left")

        row2 = ctk.CTkFrame(box, fg_color="transparent")
        row2.pack(fill="x", padx=20, pady=(0, 8))
        ctk.CTkButton(row2, text=t("configuracion.btn_activar"), width=160, height=36,
                      fg_color=C["primary"], text_color="#ffffff",
                      font=ctk.CTkFont(size=12, weight="bold"),
                      command=self._activar_licencia).pack(side="left", padx=(0, 8))
        self.lbl_lic_status = ctk.CTkLabel(
            row2, text="", font=ctk.CTkFont(size=11), text_color=C["text_muted"])
        self.lbl_lic_status.pack(side="left")

        row3 = ctk.CTkFrame(box, fg_color="transparent")
        row3.pack(fill="x", padx=20, pady=(0, 16))
        ctk.CTkButton(row3, text="🔄  Solicitar liberación de licencia", width=260, height=32,
                      fg_color="transparent", border_width=1, border_color=C["border"],
                      text_color=C["text_gray"], font=ctk.CTkFont(size=12),
                      command=self._solicitar_liberacion).pack(side="left")

    # ── Carga de valores guardados ──────────────────────────────────────────────

    def _cargar_valores(self):
        lang = get_language()
        nombre = next((lbl for lbl, code in IDIOMAS if code == lang), IDIOMAS[0][0])
        self._seg_idioma.set(nombre)

        self.idle_var.set(self.db.get_config("idle_timeout", "60"))
        self.lic_var.set(self.db.get_config("license_key", ""))

    # ── Detección de dispositivos ──────────────────────────────────────────────

    def _detectar_dispositivos(self):
        threading.Thread(target=self._detect_camaras_bg, daemon=True).start()
        threading.Thread(target=self._detect_impresoras_bg, daemon=True).start()

    def _redetectar_camaras(self):
        self.combo_camara.configure(values=[t("comun.detectando")])
        self.combo_camara.set(t("comun.detectando"))
        self.lbl_camara_status.configure(text=t("comun.detectando"))
        threading.Thread(target=self._detect_camaras_bg, daemon=True).start()

    def _redetectar_impresoras(self):
        self.combo_impresora.configure(values=[t("comun.detectando")])
        self.combo_impresora.set(t("comun.detectando"))
        self.lbl_imp_status.configure(text=t("comun.detectando"))
        threading.Thread(target=self._detect_impresoras_bg, daemon=True).start()

    def _detect_camaras_bg(self):
        from modules.camera_manager import CameraManager
        camaras = CameraManager().detectar_camaras()
        self.after(0, self._on_camaras, camaras)

    def _on_camaras(self, camaras: list):
        self._camaras = camaras
        if not camaras:
            self.combo_camara.configure(values=[t("configuracion.sin_camaras")])
            self.combo_camara.set(t("configuracion.sin_camaras"))
            self.lbl_camara_status.configure(text=t("configuracion.sin_camaras_conectadas"))
            return
        saved_idx = self.db.get_config("camara_index", "0")
        nombres = [c.nombre for c in camaras]
        self.combo_camara.configure(values=nombres, state="normal")
        sel = next((c.nombre for c in camaras if str(c.index) == saved_idx), nombres[0])
        self.combo_camara.set(sel)
        self.lbl_camara_status.configure(
            text=t("configuracion.camaras_detectadas", n=len(camaras)))

    def _detect_impresoras_bg(self):
        from modules.printer_manager import PrinterManager
        impresoras = PrinterManager.listar_impresoras()
        self.after(0, self._on_impresoras, impresoras)

    def _on_impresoras(self, impresoras: list):
        self._impresoras = impresoras
        if not impresoras:
            self.combo_impresora.configure(values=[t("configuracion.sin_impresoras")])
            self.combo_impresora.set(t("configuracion.sin_impresoras"))
            self.lbl_imp_status.configure(
                text=t("configuracion.sin_impresoras_instaladas"))
            return
        saved = self.db.get_config("impresora_default", "")
        self.combo_impresora.configure(values=impresoras, state="normal")
        self.combo_impresora.set(saved if saved in impresoras else impresoras[0])
        self.lbl_imp_status.configure(
            text=t("configuracion.impresoras_detectadas", n=len(impresoras)))

    def _on_idioma_click(self, nombre_sel: str):
        codigo = next((c for lbl, c in IDIOMAS if lbl == nombre_sel), "es")
        set_language(codigo)
        self.db.set_config("idioma", codigo)
        # Reconstruir la pantalla de configuración con el nuevo idioma
        self.after(80, self.winfo_toplevel().mostrar_configuracion)

    # ── Guardar ────────────────────────────────────────────────────────────────

    def _guardar(self):
        nombre_sel = self._seg_idioma.get()
        codigo = next((c for lbl, c in IDIOMAS if lbl == nombre_sel), "es")
        set_language(codigo)
        self.db.set_config("idioma", codigo)

        if self._camaras:
            sel_txt = self.combo_camara.get()
            cam = next((c for c in self._camaras if c.nombre == sel_txt), None)
            if cam:
                self.db.set_config("camara_index", str(cam.index))

        if self._impresoras:
            imp = self.combo_impresora.get()
            if imp in self._impresoras:
                self.db.set_config("impresora_default", imp)

        try:
            idle = int(self.idle_var.get())
            self.db.set_config("idle_timeout", str(max(0, idle)))
        except ValueError:
            pass

        messagebox.showinfo(t("configuracion.titulo"), t("configuracion.guardado_ok"))
        # Volver reconstruye el dashboard con el nuevo idioma activo
        self.on_volver()

    # ── Licencia ───────────────────────────────────────────────────────────────

    def _activar_licencia(self):
        key = self.lic_var.get().strip()
        if not key:
            self.lbl_lic_status.configure(
                text=t("configuracion.lic_ingresa_clave"), text_color=C["warning"])
            return
        self.lbl_lic_status.configure(
            text=t("configuracion.lic_verificando"), text_color=C["text_muted"])
        threading.Thread(target=self._activar_bg, args=(key,), daemon=True).start()

    def _activar_bg(self, key: str):
        from modules.pampa_client import PampaClient
        from config.settings import PROGRAM_CODE, PAMPA_API_URL
        pampa = PampaClient(PROGRAM_CODE, PAMPA_API_URL)
        try:
            res = pampa.validate_license(key, force_online=True)
            if res and (res.get("valid") or res.get("offline_ok")):
                self.db.set_config("license_key", key)
                self.after(0, lambda: self.lbl_lic_status.configure(
                    text=t("configuracion.lic_activada"), text_color=C["success"]))
            else:
                msg = res.get("message", t("comun.error")) if res else t("comun.error")
                self.after(0, lambda m=msg: self.lbl_lic_status.configure(
                    text=f"✗ {m}", text_color=C["danger"]))
        except Exception as e:
            self.after(0, lambda m=str(e): self.lbl_lic_status.configure(
                text=f"✗ {m}", text_color=C["danger"]))

    def _solicitar_liberacion(self):
        key = self.db.get_config("license_key", "").strip()
        if not key:
            messagebox.showwarning("Sin licencia", "No hay una licencia activa para liberar.")
            return
        motivo = ""
        try:
            from tkinter.simpledialog import askstring
            motivo = askstring("Motivo", "¿Por qué necesitás liberar la licencia?\n(opcional, ayuda al soporte)", parent=self.winfo_toplevel()) or ""
        except Exception:
            pass
        if motivo is None:
            return  # usuario canceló
        threading.Thread(target=self._do_solicitar_liberacion, args=(key, motivo), daemon=True).start()

    def _do_solicitar_liberacion(self, key: str, motivo: str):
        try:
            from modules.pampa_client import PampaClient
            from config.settings import PROGRAM_CODE, PAMPA_API_URL
            import socket, requests as req_lib
            pampa = PampaClient(PROGRAM_CODE, PAMPA_API_URL)
            response = req_lib.post(
                f"{PAMPA_API_URL}/api/v1/license/request-release",
                json={
                    "license_key": key,
                    "hardware_id": pampa.get_hardware_hash(),
                    "machine_name": socket.gethostname(),
                    "reason": motivo or "Sin motivo indicado"
                },
                timeout=10
            )
            try:
                data = response.json()
            except Exception:
                data = {"success": False, "message": f"Error del servidor ({response.status_code})"}
            if data.get("success"):
                self.after(0, lambda: messagebox.showinfo(
                    "Solicitud enviada",
                    "Tu solicitud fue enviada al soporte.\nTe avisaremos cuando sea procesada y podrás activar la licencia en el nuevo equipo."))
            else:
                msg = data.get("message", "Error desconocido")
                self.after(0, lambda m=msg: messagebox.showwarning("No se pudo enviar", m))
        except Exception as e:
            self.after(0, lambda m=str(e): messagebox.showerror("Error", m))
