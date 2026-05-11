"""
PlantillasScreen — listado y gestión de plantillas.
"""
import json
import os
import threading
import customtkinter as ctk
from tkinter import messagebox
from PIL import Image, ImageTk

from config.settings import COLORS
from modules.database import DatabaseManager
from modules.image_processor import ImageProcessor
from modules.i18n import t

C = COLORS


class PlantillasScreen(ctk.CTkFrame):
    def __init__(self, master, db: DatabaseManager, usuario: dict, on_volver):
        super().__init__(master, fg_color=C["bg"])
        self.db = db
        self.usuario = usuario
        self.on_volver = on_volver
        self._thumb_refs: list = []

        self._build_ui()
        self._cargar()

    def _build_ui(self):
        # Header
        hdr = ctk.CTkFrame(self, fg_color="transparent")
        hdr.pack(fill="x", padx=24, pady=(20, 0))
        ctk.CTkButton(hdr, text="← Volver", width=90, fg_color="transparent",
                      border_width=1, border_color=C["border"], text_color=C["text_gray"],
                      command=self.on_volver).pack(side="left")
        ctk.CTkLabel(hdr, text=t("plantillas.titulo"),
                     font=ctk.CTkFont(size=20, weight="bold"),
                     text_color=C["text"]).pack(side="left", padx=20)

        ctk.CTkButton(hdr, text=f"＋  {t('plantillas.btn_nueva')}",
                      fg_color=C["primary"], text_color="#ffffff",
                      font=ctk.CTkFont(weight="bold"),
                      command=self._nueva_plantilla).pack(side="right")

        # Grid de plantillas
        self.scroll = ctk.CTkScrollableFrame(self, fg_color="transparent")
        self.scroll.pack(fill="both", expand=True, padx=24, pady=16)

    def _cargar(self):
        for w in self.scroll.winfo_children():
            w.destroy()
        self._thumb_refs.clear()

        plantillas = self.db.listar_plantillas(self.usuario["id"])
        if not plantillas:
            ctk.CTkLabel(self.scroll, text=t("plantillas.sin_plantillas"),
                         text_color=C["text_muted"],
                         font=ctk.CTkFont(size=14)).pack(pady=60)
            return

        # Grid 4 columnas
        grid = ctk.CTkFrame(self.scroll, fg_color="transparent")
        grid.pack(fill="both", expand=True)
        for i, p in enumerate(plantillas):
            self._card(grid, p, i % 4, i // 4)

    def _card(self, parent, p: dict, col: int, row: int):
        frm = ctk.CTkFrame(parent, fg_color=C["bg_card"], corner_radius=14,
                            border_width=1, border_color=C["border"])
        frm.grid(row=row, column=col, padx=10, pady=10, sticky="n")

        # Preview
        try:
            if p.get("ruta_json") and os.path.exists(p["ruta_json"]):
                with open(p["ruta_json"], encoding="utf-8") as f:
                    cfg = json.load(f)
            else:
                cfg = {"fondo_color": "#1a1a1a"}
            thumb = ImageProcessor.preview_plantilla(cfg, size=(130, 190))
        except Exception:
            thumb = Image.new("RGB", (130, 190), "#1a1a1a")

        photo = ImageTk.PhotoImage(thumb)
        self._thumb_refs.append(photo)

        ctk.CTkLabel(frm, image=photo, text="").pack(padx=10, pady=(10, 4))
        ctk.CTkLabel(frm, text=p["nombre"],
                     font=ctk.CTkFont(size=13, weight="bold"),
                     text_color=C["text"]).pack()

        tag = "Predefinida" if p.get("es_predefinida") else "Personalizada"
        ctk.CTkLabel(frm, text=tag, font=ctk.CTkFont(size=10),
                     text_color=C["text_muted"]).pack(pady=(0, 6))

        btn_row = ctk.CTkFrame(frm, fg_color="transparent")
        btn_row.pack(pady=(0, 10))
        ctk.CTkButton(btn_row, text="Editar", width=80, height=28,
                      fg_color="transparent", border_width=1, border_color=C["border"],
                      text_color=C["text_gray"], font=ctk.CTkFont(size=12),
                      command=lambda pid=p["id"]: self._editar(pid)).pack(side="left", padx=4)
        if not p.get("es_predefinida"):
            ctk.CTkButton(btn_row, text="Eliminar", width=80, height=28,
                          fg_color="transparent", border_width=1, border_color="#3d1010",
                          text_color=C["danger"], font=ctk.CTkFont(size=12),
                          command=lambda pid=p["id"]: self._eliminar(pid)).pack(side="left", padx=4)

    def _nueva_plantilla(self):
        from modules.template_designer import TemplateDesigner
        TemplateDesigner(self.winfo_toplevel(), self.db, self.usuario["id"],
                         on_guardar=lambda _: self._cargar())

    def _editar(self, plantilla_id: int):
        from modules.template_designer import TemplateDesigner
        p = self.db.obtener_plantilla(plantilla_id)
        TemplateDesigner(self.winfo_toplevel(), self.db, self.usuario["id"],
                         plantilla=p, on_guardar=lambda _: self._cargar())

    def _eliminar(self, plantilla_id: int):
        if messagebox.askyesno("Eliminar plantilla", "¿Confirmás eliminar esta plantilla?"):
            p = self.db.obtener_plantilla(plantilla_id)
            if p:
                for ruta in (p.get("ruta_json"), p.get("preview_png")):
                    if ruta and os.path.exists(ruta):
                        try:
                            os.remove(ruta)
                        except Exception:
                            pass
            # Marcar como inactiva (no hay campo activo en plantillas, la borramos directo)
            with self.db._conn() as conn:
                conn.execute("DELETE FROM plantillas WHERE id = ?", (plantilla_id,))
            self._cargar()
