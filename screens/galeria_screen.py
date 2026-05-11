"""
GaleriaScreen — historial de sesiones de un evento.
Muestra miniaturas de cada tira, permite reimprimir y ver fotos individuales.
"""
import os
import threading
import customtkinter as ctk
from tkinter import messagebox
from PIL import Image, ImageTk

from config.settings import COLORS
from modules.database import DatabaseManager
from modules.i18n import t

C = COLORS


class GaleriaScreen(ctk.CTkFrame):
    def __init__(self, master, db: DatabaseManager, usuario: dict,
                 evento: dict, on_volver):
        super().__init__(master, fg_color=C["bg"])
        self.db = db
        self.usuario = usuario
        self.evento = evento
        self.on_volver = on_volver
        self._thumb_refs: list = []

        self._build_ui()
        self._cargar()

    def _build_ui(self):
        hdr = ctk.CTkFrame(self, fg_color="transparent")
        hdr.pack(fill="x", padx=24, pady=(20, 0))

        ctk.CTkButton(hdr, text=t("comun.volver"), width=90,
                      fg_color="transparent", border_width=1,
                      border_color=C["border"], text_color=C["text_gray"],
                      command=self.on_volver).pack(side="left")

        ctk.CTkLabel(hdr,
                     text=t("galeria.titulo", evento=self.evento.get("nombre", "")),
                     font=ctk.CTkFont(size=20, weight="bold"),
                     text_color=C["text"]).pack(side="left", padx=20)

        stats = self.db.stats_evento(self.evento["id"]) or {"sesiones": 0, "impresas": 0}
        ctk.CTkLabel(hdr,
                     text=t("galeria.estadisticas",
                             sesiones=stats["sesiones"],
                             impresas=stats["impresas"]),
                     font=ctk.CTkFont(size=12),
                     text_color=C["text_gray"]).pack(side="right")

        self.scroll = ctk.CTkScrollableFrame(self, fg_color="transparent")
        self.scroll.pack(fill="both", expand=True, padx=24, pady=16)

    def _cargar(self):
        for w in self.scroll.winfo_children():
            w.destroy()
        self._thumb_refs.clear()

        sesiones = self.db.listar_sesiones_evento(self.evento["id"])
        if not sesiones:
            ctk.CTkLabel(self.scroll,
                         text=t("galeria.sin_sesiones"),
                         text_color=C["text_muted"],
                         font=ctk.CTkFont(size=14)).pack(pady=80)
            return

        cola = self.db.cola_todos(self.evento["id"])
        cola_map = {c["sesion_id"]: c for c in cola if c.get("sesion_id")}

        grid = ctk.CTkFrame(self.scroll, fg_color="transparent")
        grid.pack(fill="both", expand=True)
        for col in range(4):
            grid.columnconfigure(col, weight=1)

        for i, sesion in enumerate(sesiones):
            self._card(grid, sesion, i % 4, i // 4, cola_map, sesiones)

    def _card(self, parent, sesion: dict, col: int, row: int,
              cola_map: dict, todas_sesiones: list):
        en_cola = sesion["id"] in cola_map
        item_cola = cola_map.get(sesion["id"])

        border_col = C["warning"] if en_cola else C["border"]
        card = ctk.CTkFrame(parent, fg_color=C["bg_card"],
                            corner_radius=14, border_width=2 if en_cola else 1,
                            border_color=border_col)
        card.grid(row=row, column=col, padx=10, pady=10, sticky="nsew")

        ruta_tira = sesion.get("ruta_tira")
        if ruta_tira and os.path.exists(ruta_tira):
            try:
                img = Image.open(ruta_tira)
                img.thumbnail((180, 300), Image.LANCZOS)
                photo = ImageTk.PhotoImage(img)
                self._thumb_refs.append(photo)
                ctk.CTkLabel(card, image=photo, text="").pack(padx=10, pady=(10, 4))
            except Exception:
                self._placeholder_thumb(card)
        else:
            self._placeholder_thumb(card)

        ts = sesion.get("timestamp", "")[:16].replace("T", "  ")
        ctk.CTkLabel(card, text=ts,
                     font=ctk.CTkFont(size=10),
                     text_color=C["text_muted"]).pack()

        if en_cola:
            estado_txt = "⏳  En cola — sin pareja"
            estado_col = C["warning"]
        elif sesion.get("impresa", 0):
            estado_txt = t("galeria.estado_impresa")
            estado_col = C["success"]
        else:
            estado_txt = t("galeria.estado_sin_imprimir")
            estado_col = C["text_muted"]

        ctk.CTkLabel(card, text=estado_txt,
                     font=ctk.CTkFont(size=11, weight="bold"),
                     text_color=estado_col).pack(pady=(2, 6))

        btns = ctk.CTkFrame(card, fg_color="transparent")
        btns.pack(pady=(0, 10))

        es_digital = self.evento.get("modo_salida") == "digital"

        # Acción principal: imprimir individual o exportar individual
        btn_accion = "💾  Exportar" if es_digital else t("galeria.btn_reimprimir")
        cmd_accion = (lambda s=sesion: self._abrir_opciones_exportar(s, todas_sesiones)) if es_digital \
                     else (lambda s=sesion: self._reimprimir(s))
        ctk.CTkButton(btns, text=btn_accion,
                      width=100, height=30,
                      fg_color=C["primary"], text_color="#ffffff",
                      font=ctk.CTkFont(size=11, weight="bold"),
                      command=cmd_accion).pack(side="left", padx=3)

        # Combinar (imprimir par o exportar par) — siempre disponible
        btn_comb = "🔗  Combinar" if es_digital else "🖨  Imprimir par"
        cmd_comb = (lambda s=sesion: self._combinar_sesion(s, todas_sesiones)) if es_digital \
                   else (lambda s=sesion, ic=item_cola: self._elegir_pareja(s, ic or {}, todas_sesiones))
        ctk.CTkButton(btns, text=btn_comb,
                      width=110, height=30,
                      fg_color=C["bg_hover"], text_color=C["text"],
                      border_width=1, border_color=C["border"],
                      font=ctk.CTkFont(size=11),
                      command=cmd_comb).pack(side="left", padx=3)

        ctk.CTkButton(btns, text=t("galeria.btn_ver_fotos"),
                      width=90, height=30,
                      fg_color="transparent",
                      border_width=1, border_color=C["border"],
                      text_color=C["text_gray"],
                      font=ctk.CTkFont(size=11),
                      command=lambda s=sesion: self._ver_fotos(s)).pack(
            side="left", padx=3)

        ctk.CTkButton(btns, text="🗑",
                      width=34, height=30,
                      fg_color="transparent",
                      border_width=1, border_color="#552222",
                      text_color="#cc4444",
                      font=ctk.CTkFont(size=14),
                      command=lambda s=sesion: self._eliminar_sesion(s)).pack(
            side="left", padx=3)

    def _placeholder_thumb(self, parent):
        ph = ctk.CTkFrame(parent, fg_color=C["bg_hover"],
                          width=180, height=300, corner_radius=8)
        ph.pack(padx=10, pady=(10, 4))
        ph.pack_propagate(False)
        ctk.CTkLabel(ph, text=t("comun.sin_foto"),
                     font=ctk.CTkFont(size=28)).place(relx=0.5, rely=0.5, anchor="center")

    def _reimprimir(self, sesion: dict):
        ruta = sesion.get("ruta_tira")
        if not ruta or not os.path.exists(ruta):
            messagebox.showwarning(t("comun.error"), t("galeria.sin_imagen"))
            return
        impresora = self.evento.get("impresora", "")
        copias = self.evento.get("copias", 1)

        def do():
            try:
                from modules.printer_manager import PrinterManager
                from config.formatos import get_formato
                fmt = get_formato(self.evento.get("formato", "tira_5x15"))
                escala = self.evento.get("escala_impresion", "exacto")
                pm = PrinterManager(impresora)
                img = Image.open(ruta)
                img_print = PrinterManager.preparar_para_impresion(img, fmt["key"])
                pm.imprimir_imagen(
                    img_print,
                    target_w_mm = fmt.get("print_w_mm", 0) if escala == "exacto" else 0,
                    target_h_mm = fmt.get("print_h_mm", 0) if escala == "exacto" else 0,
                    papel_size  = self.evento.get("papel_size", "10x15"),
                    escala      = escala,
                    color_modo  = self.evento.get("color_modo", "color"),
                    copias      = copias,
                )
                iid = self.db.registrar_impresion(sesion["id"], impresora, copias)
                self.db.actualizar_estado_impresion(iid, "ok")
                self.after(0, lambda: messagebox.showinfo(
                    t("comun.exito"), t("galeria.reimprimir_ok")))
                self.after(0, self._cargar)
            except Exception as e:
                self.after(0, lambda: messagebox.showerror(t("comun.error"), str(e)))

        threading.Thread(target=do, daemon=True).start()

    def _eliminar_sesion(self, sesion: dict):
        if not messagebox.askyesno("Eliminar sesión",
                                   "¿Eliminar esta sesión y sus fotos? Esta acción no se puede deshacer."):
            return
        self.db.eliminar_sesion(sesion["id"])
        self._cargar()

    def _abrir_opciones_exportar(self, sesion: dict, todas_sesiones: list):
        """Modo digital: abre el Explorador con la tira seleccionada."""
        ruta = sesion.get("ruta_tira")
        if not ruta or not os.path.exists(ruta):
            messagebox.showwarning("Sin imagen", "Esta sesión no tiene tira generada.")
            return
        import subprocess
        subprocess.Popen(["explorer", f"/select,{ruta}"])

    def _combinar_sesion(self, sesion_base: dict, todas_sesiones: list):
        """Modo digital: abre picker para combinar esta sesión con otra y exportar la 10×15."""
        import tkinter as tk
        from modules.print_queue import PrintQueue
        from config.formatos import get_formato

        ruta_base = sesion_base.get("ruta_tira")
        if not ruta_base or not os.path.exists(ruta_base):
            messagebox.showwarning("Sin imagen", "Esta sesión no tiene tira generada.")
            return

        win = ctk.CTkToplevel(self)
        win.title("Combinar sesiones")
        win.geometry("1100x720")
        win.configure(fg_color=C["bg"])
        win.grab_set()

        ctk.CTkLabel(win,
                     text=f"Sesión #{sesion_base['id']} — elegí con cuál combinar:",
                     font=ctk.CTkFont(size=15, weight="bold"),
                     text_color=C["text"]).pack(padx=24, pady=(20, 4), anchor="w")
        ctk.CTkLabel(win,
                     text="Se guardará una imagen 10×15 combinada en la carpeta destino.",
                     font=ctk.CTkFont(size=12),
                     text_color=C["text_muted"]).pack(padx=24, pady=(0, 14), anchor="w")

        scroll = ctk.CTkScrollableFrame(win, fg_color="transparent", orientation="horizontal")
        scroll.pack(fill="both", expand=True, padx=16, pady=(0, 8))

        candidatas = [s for s in todas_sesiones
                      if s.get("ruta_tira") and os.path.exists(s["ruta_tira"])
                      and s["id"] != sesion_base["id"]]

        _photo_refs = []

        def _hacer_par(pareja: dict):
            win.destroy()
            fmt = get_formato(self.evento.get("formato", "tira_5x15"))
            def _run():
                ok = PrintQueue._guardar_par(ruta_base, pareja["ruta_tira"], self.evento, fmt)
                msg = "💾  Par exportado correctamente." if ok else "✗  Error al exportar."
                self.after(0, lambda: messagebox.showinfo("Exportar", msg))
                self.after(0, self._cargar)
            threading.Thread(target=_run, daemon=True).start()

        if not candidatas:
            ctk.CTkLabel(scroll, text="No hay otras sesiones con tira disponible.",
                         text_color=C["text_muted"],
                         font=ctk.CTkFont(size=14)).pack(pady=60, padx=40)
        else:
            # Opción: duplicar (misma sesión x2)
            dup_card = ctk.CTkFrame(scroll, fg_color=C["bg_card"], corner_radius=14,
                                    border_width=1, border_color=C["border"], width=210)
            dup_card.pack(side="left", padx=10, pady=8, fill="y")
            dup_card.pack_propagate(False)
            ctk.CTkLabel(dup_card, text="🔁",
                         font=ctk.CTkFont(size=48)).pack(pady=(30, 8))
            ctk.CTkLabel(dup_card, text="Duplicar\n(misma tira × 2)",
                         font=ctk.CTkFont(size=13, weight="bold"),
                         text_color=C["text"], justify="center").pack(padx=8)
            ctk.CTkButton(dup_card, text="Exportar duplicado →",
                          height=40, fg_color=C["bg_hover"], text_color=C["text"],
                          border_width=1, border_color=C["border"],
                          font=ctk.CTkFont(size=12),
                          command=lambda: _hacer_par(sesion_base)
                          ).pack(padx=12, pady=(16, 14), fill="x")

            for s in candidatas:
                card = ctk.CTkFrame(scroll, fg_color=C["bg_card"], corner_radius=14,
                                    border_width=1, border_color=C["border"], width=210)
                card.pack(side="left", padx=10, pady=8, fill="y")
                card.pack_propagate(False)
                try:
                    img_t = Image.open(s["ruta_tira"]).convert("RGB")
                    ratio = 420 / img_t.height
                    img_t = img_t.resize((int(img_t.width * ratio), 420), Image.LANCZOS)
                    ph = ImageTk.PhotoImage(img_t)
                    _photo_refs.append(ph)
                    lbl_ph = tk.Label(card, image=ph, bg=C["bg_card"], bd=0)
                    lbl_ph.image = ph
                    lbl_ph.pack(pady=(12, 6))
                except Exception:
                    ctk.CTkLabel(card, text="Sin preview",
                                 text_color=C["text_muted"]).pack(pady=60)
                ts = s.get("timestamp", "")[:16].replace("T", " ")
                ctk.CTkLabel(card, text=f"#{s['id']}  —  {ts}",
                             font=ctk.CTkFont(size=11, weight="bold"),
                             text_color=C["text"], wraplength=190).pack(padx=8, pady=(2, 8))
                ctk.CTkButton(card, text="Combinar →",
                              height=40, fg_color=C["primary"], text_color="#fff",
                              font=ctk.CTkFont(size=12, weight="bold"),
                              command=lambda p=s: _hacer_par(p)
                              ).pack(padx=12, pady=(0, 14), fill="x")

        ctk.CTkButton(win, text="Cancelar",
                      fg_color="transparent", border_width=1,
                      border_color=C["border"], text_color=C["text_gray"],
                      command=win.destroy).pack(pady=(0, 14))

    def _elegir_pareja(self, sesion_cola: dict, item_cola: dict, todas_sesiones: list):
        """Diálogo para elegir con qué tira imprimir la sesión pendiente."""
        import tkinter as tk
        from modules.print_queue import PrintQueue
        from modules.printer_manager import PrinterManager
        from config.formatos import get_formato

        win = ctk.CTkToplevel(self)
        win.title("Elegir pareja para imprimir")
        win.geometry("1100x720")
        win.configure(fg_color=C["bg"])
        win.grab_set()

        ctk.CTkLabel(win,
                     text=f"Sesión #{sesion_cola['id']} en cola — elegí con cuál imprimirla:",
                     font=ctk.CTkFont(size=15, weight="bold"),
                     text_color=C["text"]).pack(padx=24, pady=(20, 4), anchor="w")
        ctk.CTkLabel(win,
                     text="Podés elegir cualquier sesión del evento, incluso una ya impresa.",
                     font=ctk.CTkFont(size=12),
                     text_color=C["text_muted"]).pack(padx=24, pady=(0, 14), anchor="w")

        scroll = ctk.CTkScrollableFrame(win, fg_color="transparent",
                                        orientation="horizontal")
        scroll.pack(fill="both", expand=True, padx=16, pady=(0, 8))

        candidatas = [s for s in todas_sesiones
                      if s.get("ruta_tira") and os.path.exists(s["ruta_tira"])]

        _photo_refs = []

        def _imprimir_con(pareja: dict, win=win):
            win.destroy()
            ruta_pendiente = sesion_cola.get("ruta_tira") or item_cola.get("ruta_tira", "")
            ruta_pareja    = pareja["ruta_tira"]
            fmt = get_formato(self.evento.get("formato", "tira_5x15"))
            if item_cola.get("id"):
                self.db.cola_eliminar(item_cola["id"])
            def _run():
                PrintQueue._imprimir_par(ruta_pendiente, ruta_pareja, self.evento, fmt)
                self.after(0, self._cargar)
            threading.Thread(target=_run, daemon=True).start()

        def _card(parent, sesion, label_extra=""):
            card = ctk.CTkFrame(parent, fg_color=C["bg_card"], corner_radius=14,
                                border_width=1, border_color=C["border"], width=210)
            card.pack(side="left", padx=10, pady=8, fill="y")
            card.pack_propagate(False)
            try:
                img_t = Image.open(sesion["ruta_tira"]).convert("RGB")
                ratio = 420 / img_t.height
                img_t = img_t.resize((int(img_t.width * ratio), 420), Image.LANCZOS)
                ph = ImageTk.PhotoImage(img_t)
                _photo_refs.append(ph)
                import tkinter as tk
                lbl_ph = tk.Label(card, image=ph, bg=C["bg_card"], bd=0)
                lbl_ph.image = ph
                lbl_ph.pack(pady=(12, 6))
            except Exception:
                ctk.CTkLabel(card, text="Sin preview",
                             text_color=C["text_muted"]).pack(pady=60)
            if label_extra:
                ctk.CTkLabel(card, text=label_extra,
                             font=ctk.CTkFont(size=11, weight="bold"),
                             text_color=C["primary"]).pack(padx=8)
            ts = sesion.get("timestamp", "")[:16].replace("T", " ")
            ctk.CTkLabel(card, text=f"#{sesion['id']}  —  {ts}",
                         font=ctk.CTkFont(size=11, weight="bold"),
                         text_color=C["text"], wraplength=190).pack(padx=8, pady=(2, 2))
            badge = "✓ Ya impresa" if sesion.get("impresa") else "○ Sin imprimir"
            ctk.CTkLabel(card, text=badge, font=ctk.CTkFont(size=11),
                         text_color=C["success"] if sesion.get("impresa") else C["text_muted"]
                         ).pack(pady=(0, 8))
            ctk.CTkButton(card, text="Imprimir juntas →",
                          height=40, fg_color=C["primary"], text_color="#fff",
                          font=ctk.CTkFont(size=12, weight="bold"),
                          command=lambda s=sesion: _imprimir_con(s)
                          ).pack(padx=12, pady=(0, 14), fill="x")
            return card

        # Opción duplicar
        _card(scroll, sesion_cola, label_extra="🔁 Duplicar (misma tira x2)")

        # Separador vertical
        sep = ctk.CTkFrame(scroll, fg_color=C["border"], width=2)
        sep.pack(side="left", fill="y", padx=8, pady=20)

        # Resto de sesiones
        for s in candidatas:
            if s["id"] == sesion_cola["id"]:
                continue
            _card(scroll, s)

        ctk.CTkButton(win, text="Cancelar",
                      fg_color="transparent", border_width=1,
                      border_color=C["border"], text_color=C["text_gray"],
                      command=win.destroy).pack(pady=(0, 14))

    def _ver_fotos(self, sesion: dict):
        fotos = self.db.obtener_fotos_sesion(sesion["id"])
        if not fotos:
            messagebox.showinfo(t("comun.ok"), t("galeria.sin_sesiones"))
            return
        VisorFotos(self.winfo_toplevel(), fotos, sesion)


class VisorFotos(ctk.CTkToplevel):
    def __init__(self, parent, fotos: list, sesion: dict):
        super().__init__(parent)
        self.title(t("galeria.visor_titulo", id=sesion["id"]))
        self.geometry("900x560")
        self.configure(fg_color=C["bg"])
        self.grab_set()

        self._refs: list = []

        ts = sesion.get("timestamp", "")[:16].replace("T", "  ")
        ctk.CTkLabel(self,
                     text=t("galeria.visor_sesion", fecha=ts),
                     font=ctk.CTkFont(size=16, weight="bold"),
                     text_color=C["text"]).pack(pady=(20, 12))

        scroll = ctk.CTkScrollableFrame(self, fg_color="transparent",
                                        orientation="horizontal")
        scroll.pack(fill="both", expand=True, padx=20)

        for foto in fotos:
            ruta = foto.get("ruta", "")
            elegida = foto.get("elegida", 0)
            orden = foto.get("indice", "?")

            frm = ctk.CTkFrame(scroll, fg_color=C["bg_card"],
                               corner_radius=12, border_width=2,
                               border_color=C["primary"] if elegida else C["border"])
            frm.pack(side="left", padx=8, pady=8)

            if ruta and os.path.exists(ruta):
                try:
                    img = Image.open(ruta)
                    img.thumbnail((160, 220), Image.LANCZOS)
                    photo = ImageTk.PhotoImage(img)
                    self._refs.append(photo)
                    ctk.CTkLabel(frm, image=photo, text="").pack(padx=8, pady=(8, 4))
                except Exception:
                    ctk.CTkLabel(frm, text=t("comun.sin_foto"),
                                 font=ctk.CTkFont(size=40)).pack(pady=40, padx=20)
            else:
                ctk.CTkLabel(frm, text=t("comun.sin_foto"),
                             font=ctk.CTkFont(size=40)).pack(pady=40, padx=20)

            ctk.CTkLabel(frm, text=t("galeria.foto_n", n=orden),
                         font=ctk.CTkFont(size=11),
                         text_color=C["text_gray"]).pack()

            if elegida:
                ctk.CTkLabel(frm, text=t("galeria.foto_elegida"),
                             font=ctk.CTkFont(size=10, weight="bold"),
                             text_color=C["primary"]).pack(pady=(0, 8))
            else:
                ctk.CTkLabel(frm, text="",
                             font=ctk.CTkFont(size=10)).pack(pady=(0, 8))

        ctk.CTkButton(self, text=t("comun.cerrar"), width=120,
                      fg_color="transparent",
                      border_width=1, border_color=C["border"],
                      text_color=C["text_gray"],
                      command=self.destroy).pack(pady=16)
