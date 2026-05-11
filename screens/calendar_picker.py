"""
CalendarPicker — selector de fecha con interfaz visual.
Usa tk.Toplevel en lugar de CTkToplevel para evitar bugs de render en Windows.
No permite seleccionar fechas pasadas. Callback recibe "dd/mm/yyyy".
"""
import calendar
import tkinter as tk
from datetime import date
from config.settings import COLORS

C = COLORS

DIAS_SEMANA = ["Lu", "Ma", "Mi", "Ju", "Vi", "Sa", "Do"]
MESES = [
    "", "Enero", "Febrero", "Marzo", "Abril", "Mayo", "Junio",
    "Julio", "Agosto", "Septiembre", "Octubre", "Noviembre", "Diciembre",
]

BG       = "#1a1a1a"
BG_HDR   = "#222222"
BG_HOV   = "#2a2a2a"
FG_TXT   = "#e0e0e0"
FG_MUTED = "#666666"
FG_PRI   = C.get("primary", "#f5a623")
FG_PRI_D = "#c8841a"


class CalendarPicker(tk.Toplevel):
    def __init__(self, parent, callback, min_date: date | None = None):
        super().__init__(parent)
        self.callback  = callback
        self.min_date  = min_date or date.today()
        self._hoy      = date.today()
        self._año      = self._hoy.year
        self._mes      = self._hoy.month

        self.title("Seleccionar fecha")
        self.resizable(False, False)
        self.configure(bg=BG)
        self.transient(parent)
        self.grab_set()

        self._build()
        self._render_mes()
        self._centrar(parent)
        self.lift()
        self.focus_force()

    # ── Layout ─────────────────────────────────────────────────────────────────

    def _build(self):
        # ── Header mes/año ──
        hdr = tk.Frame(self, bg=BG_HDR)
        hdr.pack(fill="x")

        self._btn_prev = tk.Button(hdr, text="◀", bg=BG_HDR, fg=FG_PRI,
                                   bd=0, relief="flat", cursor="hand2",
                                   font=("Arial", 14, "bold"),
                                   activebackground=BG_HOV, activeforeground=FG_PRI,
                                   command=self._mes_anterior)
        self._btn_prev.pack(side="left", padx=8, pady=8)

        self.lbl_mes = tk.Label(hdr, text="", bg=BG_HDR, fg=FG_TXT,
                                font=("Arial", 13, "bold"), width=18, anchor="center")
        self.lbl_mes.pack(side="left", expand=True)

        self._btn_next = tk.Button(hdr, text="▶", bg=BG_HDR, fg=FG_PRI,
                                   bd=0, relief="flat", cursor="hand2",
                                   font=("Arial", 14, "bold"),
                                   activebackground=BG_HOV, activeforeground=FG_PRI,
                                   command=self._mes_siguiente)
        self._btn_next.pack(side="right", padx=8, pady=8)

        # ── Separador ──
        tk.Frame(self, bg="#333", height=1).pack(fill="x")

        # ── Días de la semana ──
        dias_hdr = tk.Frame(self, bg=BG_HDR)
        dias_hdr.pack(fill="x")
        for d in DIAS_SEMANA:
            tk.Label(dias_hdr, text=d, width=4, bg=BG_HDR, fg=FG_MUTED,
                     font=("Arial", 10, "bold")).pack(side="left", padx=2, pady=4)

        # ── Grid de días ──
        self.grid_frame = tk.Frame(self, bg=BG)
        self.grid_frame.pack(padx=6, pady=4)

        # ── Separador ──
        tk.Frame(self, bg="#333", height=1).pack(fill="x")

        # ── Pie: botón Hoy ──
        pie = tk.Frame(self, bg=BG_HDR)
        pie.pack(fill="x")
        tk.Button(pie, text="Hoy", bg=BG_HDR, fg=FG_PRI, bd=0, relief="flat",
                  cursor="hand2", font=("Arial", 11),
                  activebackground=BG_HOV, activeforeground=FG_PRI,
                  command=self._ir_hoy).pack(pady=8)

    def _render_mes(self):
        for w in self.grid_frame.winfo_children():
            w.destroy()

        self.lbl_mes.configure(text=f"{MESES[self._mes]}  {self._año}")

        cal = calendar.monthcalendar(self._año, self._mes)

        for semana in cal:
            fila = tk.Frame(self.grid_frame, bg=BG)
            fila.pack(side="top")
            for dia in semana:
                if dia == 0:
                    tk.Label(fila, text="", width=4, height=2, bg=BG).pack(
                        side="left", padx=2, pady=2)
                    continue

                d = date(self._año, self._mes, dia)
                es_pasado = d < self.min_date
                es_hoy    = d == self._hoy

                if es_hoy:
                    bg_b, fg_b = FG_PRI, "#000000"
                    bg_act     = FG_PRI_D
                elif es_pasado:
                    bg_b, fg_b = BG, FG_MUTED
                    bg_act     = BG
                else:
                    bg_b, fg_b = BG, FG_TXT
                    bg_act     = BG_HOV

                btn = tk.Button(
                    fila,
                    text=str(dia),
                    width=3, height=1,
                    bg=bg_b, fg=fg_b,
                    activebackground=bg_act,
                    activeforeground=fg_b,
                    bd=0, relief="flat",
                    font=("Arial", 11),
                    cursor="hand2" if not es_pasado else "arrow",
                    state="disabled" if es_pasado else "normal",
                    command=(lambda _d=d: self._seleccionar(_d)) if not es_pasado else None,
                )
                btn.pack(side="left", padx=2, pady=2)

    # ── Acciones ───────────────────────────────────────────────────────────────

    def _seleccionar(self, d: date):
        self.callback(d.strftime("%d/%m/%Y"))
        self.destroy()

    def _mes_anterior(self):
        if self._mes == 1:
            self._mes, self._año = 12, self._año - 1
        else:
            self._mes -= 1
        self._render_mes()

    def _mes_siguiente(self):
        if self._mes == 12:
            self._mes, self._año = 1, self._año + 1
        else:
            self._mes += 1
        self._render_mes()

    def _ir_hoy(self):
        self._año, self._mes = self._hoy.year, self._hoy.month
        self._render_mes()

    def _centrar(self, parent):
        self.update_idletasks()
        w = self.winfo_width()
        h = self.winfo_height()
        px = parent.winfo_rootx() + (parent.winfo_width()  - w) // 2
        py = parent.winfo_rooty() + (parent.winfo_height() - h) // 2
        self.geometry(f"+{px}+{py}")
