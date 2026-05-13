"""
PrintQueue — cola inteligente de impresión 2-up.

Lógica:
  - Cada tira 5×15 que se quiere imprimir pasa por aquí.
  - Si ya hay una tira esperando del mismo evento → se imprimen juntas (2-up mixto).
  - Si no hay ninguna → se guarda en cola y se devuelve "en_cola".
  - El operador puede vaciar la cola manualmente desde el dashboard
    (las tiras sueltas se imprimen como 2-up duplicado).

Resultado de agregar_y_imprimir():
  "impreso"  — trabajo enviado a la impresora.
  "en_cola"  — tira guardada, esperando pareja.
  "error"    — fallo al imprimir.
"""
import threading
from PIL import Image

from modules.database import DatabaseManager
from modules.printer_manager import PrinterManager
from config.formatos import get_formato

# Lock global por evento: garantiza que cola_pendiente + cola_agregar/eliminar
# sean atómicas entre sesiones concurrentes del mismo proceso.
_cola_locks: dict[int, threading.Lock] = {}
_cola_locks_meta = threading.Lock()


def _get_lock(evento_id: int) -> threading.Lock:
    """Devuelve (creando si hace falta) el lock del evento dado."""
    with _cola_locks_meta:
        if evento_id not in _cola_locks:
            _cola_locks[evento_id] = threading.Lock()
        return _cola_locks[evento_id]


class PrintQueue:

    # ── API pública ────────────────────────────────────────────────────────────

    @staticmethod
    def agregar_y_imprimir(
        db: DatabaseManager,
        evento: dict,
        sesion_id: int | None,
        ruta_tira: str,
    ) -> str:
        """
        Intenta emparejar con la tira pendiente más antigua del mismo evento.
        Devuelve "impreso" | "en_cola" | "error".

        El lock por evento garantiza que cola_pendiente() y cola_agregar/eliminar()
        sean atómicas: dos sesiones que terminen simultáneamente no pueden ambas ver
        la cola vacía y encolarse sin emparejarse.
        """
        formato = evento.get("formato", "tira_5x15")
        fmt = get_formato(formato)

        with _get_lock(evento["id"]):
            pendiente = db.cola_pendiente(evento["id"])

            if pendiente:
                # Tenemos par — eliminar de cola antes de imprimir para que
                # otra sesión concurrente no lo vea como candidato
                db.cola_eliminar(pendiente["id"])

            if not pendiente:
                # Sin pareja — encolar
                db.cola_agregar(evento["id"], sesion_id, ruta_tira)
                return "en_cola"

        # Imprimir fuera del lock: puede tardar segundos sin bloquear otras sesiones
        ok = PrintQueue._imprimir_par(pendiente["ruta_tira"], ruta_tira, evento, fmt)
        if not ok:
            # Re-encolar la tira pendiente original si la impresión falló
            db.cola_agregar(evento["id"], pendiente.get("sesion_id"), pendiente["ruta_tira"])
        return "impreso" if ok else "error"

    @staticmethod
    def vaciar(db: DatabaseManager, evento: dict, on_done=None):
        """
        Imprime todas las tiras pendientes del evento como 2-up duplicado.
        Ejecuta en hilo para no bloquear la UI.
        on_done(n_impresas, error_msg) se llama al terminar.
        """
        def _run():
            pendientes = db.cola_todos(evento["id"])
            fmt = get_formato(evento.get("formato", "tira_5x15"))
            impresora = evento.get("impresora", "") or PrinterManager.impresora_predeterminada()
            pm = PrinterManager(impresora)
            n = 0
            error_msg = ""
            kw = PrintQueue._params_impresion(evento, fmt)
            for p in pendientes:
                try:
                    img = Image.open(p["ruta_tira"])
                    img_print = PrinterManager.preparar_para_impresion(
                        img, evento.get("formato", "tira_5x15"))
                    if pm.imprimir_imagen(img_print, **kw):
                        db.cola_eliminar(p["id"])
                        n += 1
                    else:
                        error_msg = "La impresora rechazó un trabajo."
                except FileNotFoundError:
                    db.cola_eliminar(p["id"])
                    error_msg = f"Archivo no encontrado: {p['ruta_tira']}"
                except Exception as e:
                    error_msg = str(e)
            if on_done:
                on_done(n, error_msg)

        threading.Thread(target=_run, daemon=True).start()

    @staticmethod
    def agregar_y_guardar(
        db: DatabaseManager,
        evento: dict,
        sesion_id: int | None,
        ruta_tira: str,
    ) -> str:
        """
        Igual que agregar_y_imprimir pero guarda el par en disco en vez de imprimir.
        Devuelve "guardado" | "en_cola" | "error".
        """
        formato = evento.get("formato", "tira_5x15")
        fmt = get_formato(formato)

        with _get_lock(evento["id"]):
            pendiente = db.cola_pendiente(evento["id"])
            if pendiente:
                db.cola_eliminar(pendiente["id"])

        if not pendiente:
            db.cola_agregar(evento["id"], sesion_id, ruta_tira)
            return "en_cola"

        ok = PrintQueue._guardar_par(pendiente["ruta_tira"], ruta_tira, evento, fmt)
        if not ok:
            db.cola_agregar(evento["id"], pendiente.get("sesion_id"), pendiente["ruta_tira"])
        return "guardado" if ok else "error"

    @staticmethod
    def vaciar_guardar(db: DatabaseManager, evento: dict, on_done=None):
        """
        Guarda todas las tiras pendientes como 2-up duplicado (sin imprimir).
        on_done(n_guardadas, error_msg) se llama al terminar.
        """
        def _run():
            pendientes = db.cola_todos(evento["id"])
            fmt = get_formato(evento.get("formato", "tira_5x15"))
            n = 0
            error_msg = ""
            for p in pendientes:
                try:
                    ok = PrintQueue._guardar_par(p["ruta_tira"], p["ruta_tira"], evento, fmt)
                    if ok:
                        db.cola_eliminar(p["id"])
                        n += 1
                    else:
                        error_msg = "Error al guardar un par."
                except Exception as e:
                    error_msg = str(e)
            if on_done:
                on_done(n, error_msg)
        threading.Thread(target=_run, daemon=True).start()

    @staticmethod
    def count(db: DatabaseManager, evento_id: int) -> int:
        return db.cola_count(evento_id)

    # ── Impresión / guardado interno ───────────────────────────────────────────

    @staticmethod
    def _params_impresion(evento: dict, fmt: dict) -> dict:
        escala = evento.get("escala_impresion", "exacto")
        return dict(
            target_w_mm = fmt.get("print_w_mm", 0) if escala == "exacto" else 0,
            target_h_mm = fmt.get("print_h_mm", 0) if escala == "exacto" else 0,
            papel_size  = evento.get("papel_size", "10x15"),
            escala      = escala,
            color_modo  = evento.get("color_modo", "color"),
            copias      = evento.get("copias", 1),
        )

    @staticmethod
    def _imprimir_par(ruta1: str, ruta2: str, evento: dict, fmt: dict) -> bool:
        impresora = evento.get("impresora", "") or PrinterManager.impresora_predeterminada()
        pm = PrinterManager(impresora)
        kw = PrintQueue._params_impresion(evento, fmt)

        if fmt.get("print_2up"):
            pw, ph = fmt["print_w"], fmt["print_h"]
            canvas = Image.new("RGB", (pw, ph), "#ffffff")
            mitad = pw // 2
            for img_path, x_off in [(ruta1, 0), (ruta2, mitad)]:
                try:
                    img = Image.open(img_path).convert("RGB")
                    img = img.resize((mitad, ph), Image.LANCZOS)
                    canvas.paste(img, (x_off, 0))
                except Exception as e:
                    print(f"[PrintQueue] Imagen no disponible: {img_path} — {e}")
                    return False
            return pm.imprimir_imagen(canvas, **kw)
        else:
            ok = True
            for ruta in (ruta1, ruta2):
                try:
                    img = Image.open(ruta).convert("RGB")
                    if not pm.imprimir_imagen(img, **kw):
                        ok = False
                except Exception:
                    ok = False
            return ok

    @staticmethod
    def _guardar_par(ruta1: str, ruta2: str, evento: dict, fmt: dict) -> bool:
        """Compone el par (igual que _imprimir_par) y lo guarda en disco."""
        import os, time
        from config.settings import PHOTOS_DIR
        evento_dir = os.path.realpath(evento.get("ruta_digital", "") or "")
        if not (evento_dir and os.path.isdir(evento_dir)):
            evento_dir = os.path.join(PHOTOS_DIR, str(evento["id"]))
        try:
            os.makedirs(evento_dir, exist_ok=True)
        except OSError as _e:
            print(f"[PrintQueue] No se pudo crear directorio {evento_dir}: {_e}")
            return False
        ruta_out = os.path.join(evento_dir, f"pareja_{int(time.time())}.jpg")
        try:
            if fmt.get("print_2up"):
                pw, ph = fmt["print_w"], fmt["print_h"]
                canvas = Image.new("RGB", (pw, ph), "#ffffff")
                mitad = pw // 2
                for img_path, x_off in [(ruta1, 0), (ruta2, mitad)]:
                    img = Image.open(img_path).convert("RGB")
                    img = img.resize((mitad, ph), Image.LANCZOS)
                    canvas.paste(img, (x_off, 0))
                canvas.save(ruta_out, "JPEG", quality=95)
            else:
                # Para formatos no-2up, guardar las dos tiras lado a lado
                img1 = Image.open(ruta1).convert("RGB")
                img2 = Image.open(ruta2).convert("RGB")
                h = max(img1.height, img2.height)
                w1 = int(img1.width * h / img1.height)
                w2 = int(img2.width * h / img2.height)
                img1 = img1.resize((w1, h), Image.LANCZOS)
                img2 = img2.resize((w2, h), Image.LANCZOS)
                canvas = Image.new("RGB", (w1 + w2, h), "#ffffff")
                canvas.paste(img1, (0, 0))
                canvas.paste(img2, (w1, 0))
                canvas.save(ruta_out, "JPEG", quality=95)
            return True
        except Exception:
            return False
