"""
PrinterManager — impresión nativa en Windows.

Soporta cualquier impresora instalada vía win32print.
Optimizado para Kodak 305 (tira 2×6" y foto 4×6").
"""
import os
import tempfile
from PIL import Image
from typing import Optional

try:
    import win32print
    import win32ui
    from PIL import ImageWin
    _WIN32_AVAILABLE = True
except ImportError:
    _WIN32_AVAILABLE = False


class PrinterManager:

    def __init__(self, nombre_impresora: str | None = None):
        self.nombre = nombre_impresora or self.impresora_predeterminada()

    # ── Detección ──────────────────────────────────────────────────────────────

    @staticmethod
    def listar_impresoras() -> list[str]:
        # Intentar con win32print primero
        if _WIN32_AVAILABLE:
            try:
                impresoras = win32print.EnumPrinters(
                    win32print.PRINTER_ENUM_LOCAL | win32print.PRINTER_ENUM_CONNECTIONS
                )
                nombres = [p[2] for p in impresoras if p[2]]
                if nombres:
                    return nombres
            except Exception:
                pass
        # Fallback: PowerShell (detecta impresoras locales y de red)
        try:
            import subprocess
            r = subprocess.run(
                ["powershell", "-NoProfile", "-Command",
                 "Get-Printer | Select-Object -ExpandProperty Name"],
                capture_output=True, text=True, timeout=8
            )
            if r.returncode == 0:
                nombres = [n.strip() for n in r.stdout.splitlines() if n.strip()]
                if nombres:
                    return nombres
        except Exception:
            pass
        # Fallback 2: wmic
        try:
            import subprocess
            r = subprocess.run(
                ["wmic", "printer", "get", "name", "/format:list"],
                capture_output=True, text=True, timeout=8
            )
            nombres = []
            for line in r.stdout.splitlines():
                if line.startswith("Name="):
                    nombre = line[5:].strip()
                    if nombre:
                        nombres.append(nombre)
            if nombres:
                return nombres
        except Exception:
            pass
        return []

    @staticmethod
    def impresora_predeterminada() -> str:
        if not _WIN32_AVAILABLE:
            return ""
        try:
            return win32print.GetDefaultPrinter()
        except Exception:
            return ""

    @staticmethod
    def es_kodak_305(nombre: str) -> bool:
        return "kodak" in nombre.lower() and "305" in nombre.lower()

    # ── Preparación del trabajo de impresión ──────────────────────────────────

    @staticmethod
    def preparar_para_impresion(img: Image.Image, formato: str) -> Image.Image:
        """
        Ajusta la imagen al trabajo de impresión físico.

        tira_5x15 → 2-up: dos tiras lado a lado en canvas 10×15 cm.
                    Así se aprovecha toda la hoja y no queda media hoja vacía.
        foto_10x15 → sin cambio, ya ocupa la hoja entera.
        """
        from config.formatos import get_formato
        fmt = get_formato(formato)
        if not fmt.get("print_2up"):
            return img

        tw, th = img.size
        pw, ph = fmt["print_w"], fmt["print_h"]

        # Canvas blanco del tamaño del papel de impresión
        canvas = Image.new("RGB", (pw, ph), color="#ffffff")

        # Escalar la tira si no coincide exactamente (tolerancia de 2px)
        if abs(tw - pw // 2) > 2 or abs(th - ph) > 2:
            img = img.resize((pw // 2, ph), Image.LANCZOS)
            tw, th = img.size

        # Pegar dos copias lado a lado
        canvas.paste(img, (0, 0))
        canvas.paste(img, (tw, 0))
        return canvas

    # ── Impresión ──────────────────────────────────────────────────────────────

    # Tamaños de papel en mm → se usa para informar al driver
    PAPEL_MM = {
        "A4":    (210, 297),
        "carta": (216, 279),
        "10x15": (100, 150),
        "15x21": (150, 210),
    }

    def imprimir_imagen(self, img: Image.Image, dpi: int = 300,
                        target_w_mm: float = 0, target_h_mm: float = 0,
                        papel_size: str = "10x15", escala: str = "exacto",
                        color_modo: str = "color", copias: int = 1) -> bool:
        """
        Envía la imagen a la impresora.
        papel_size: clave del papel cargado ("A4", "carta", "10x15", "15x21")
        escala: "exacto" (tamaño físico real centrado) | "llenar" (escala al papel)
        color_modo: "color" | "byn"
        copias: número de copias que gestiona el driver (1 trabajo, N copias)
        """
        if color_modo == "byn":
            img = img.convert("L").convert("RGB")

        try:
            return self._imprimir_powershell(
                img, target_w_mm, target_h_mm,
                papel_size, escala, copias)
        except Exception as e:
            print(f"[PrinterManager] powershell error: {e}")
        return self._imprimir_startfile(img)

    def _imprimir_win32(self, img: Image.Image, dpi: int) -> bool:
        hprinter = win32print.OpenPrinter(self.nombre)
        try:
            hdc = win32ui.CreateDC()
            hdc.CreatePrinterDC(self.nombre)

            # Dimensiones del papel en píxeles de impresora
            pw = hdc.GetDeviceCaps(8)   # HORZRES
            ph = hdc.GetDeviceCaps(10)  # VERTRES

            # Escalar imagen para llenar el papel manteniendo aspect ratio
            img_w, img_h = img.size
            ratio = min(pw / img_w, ph / img_h)
            new_w = int(img_w * ratio)
            new_h = int(img_h * ratio)
            img_resized = img.resize((new_w, new_h), Image.LANCZOS)

            hdc.StartDoc("PhotoBooth Print")
            hdc.StartPage()

            dib = ImageWin.Dib(img_resized)
            x = (pw - new_w) // 2
            y = (ph - new_h) // 2
            dib.draw(hdc.GetHandleOutput(), (x, y, x + new_w, y + new_h))

            hdc.EndPage()
            hdc.EndDoc()
            hdc.DeleteDC()
            return True
        finally:
            win32print.ClosePrinter(hprinter)

    def _imprimir_powershell(self, img: Image.Image,
                              target_w_mm: float = 0,
                              target_h_mm: float = 0,
                              papel_size: str = "10x15",
                              escala: str = "exacto",
                              copias: int = 1) -> bool:
        """
        Imprime usando PowerShell + System.Drawing.
        Coordenadas en unidades Display (1/100 pulgada) — coincide con MarginBounds.
        """
        import subprocess
        tmp = tempfile.NamedTemporaryFile(suffix=".jpg", delete=False)
        tmp.close()
        try:
            img.convert("RGB").save(tmp.name, "JPEG", quality=95)

            # Tamaño del papel en unidades Display (1/100 pulgada)
            pw_mm, ph_mm = self.PAPEL_MM.get(papel_size, (100, 150))
            pw_u = int(pw_mm / 25.4 * 100)
            ph_u = int(ph_mm / 25.4 * 100)

            if escala == "exacto" and target_w_mm > 0 and target_h_mm > 0:
                # Tamaño físico exacto de la imagen, centrado en la hoja
                draw_block = f"""
    $e.Graphics.InterpolationMode = [System.Drawing.Drawing2D.InterpolationMode]::HighQualityBicubic
    $pu_w  = [int]({target_w_mm} / 25.4 * 100)
    $pu_h  = [int]({target_h_mm} / 25.4 * 100)
    $rect  = $e.MarginBounds
    $x     = [int]($rect.Left + ($rect.Width  - $pu_w) / 2)
    $y     = [int]($rect.Top  + ($rect.Height - $pu_h) / 2)
    $e.Graphics.DrawImage($bmp, $x, $y, $pu_w, $pu_h)"""
            else:
                # Llenar hoja: escalar para ocupar toda el área imprimible
                draw_block = """
    $e.Graphics.InterpolationMode = [System.Drawing.Drawing2D.InterpolationMode]::HighQualityBicubic
    $rect  = $e.MarginBounds
    $ratio = [Math]::Min([double]$rect.Width / $bmp.Width, [double]$rect.Height / $bmp.Height)
    $w = [int]($bmp.Width  * $ratio)
    $h = [int]($bmp.Height * $ratio)
    $x = [int]($rect.Left + ($rect.Width  - $w) / 2)
    $y = [int]($rect.Top  + ($rect.Height - $h) / 2)
    $e.Graphics.DrawImage($bmp, $x, $y, $w, $h)"""

            # Printer name and path passed via env vars — never embedded in script string
            ps = f"""
Add-Type -AssemblyName System.Drawing
$bmp = [System.Drawing.Bitmap]::new($env:PS_FILE_PATH)
$pd  = New-Object System.Drawing.Printing.PrintDocument
$pd.PrinterSettings.PrinterName = $env:PS_PRINTER_NAME
$pd.PrinterSettings.Copies     = {max(1, int(copias))}
$paperSize = New-Object System.Drawing.Printing.PaperSize('Custom', {pw_u}, {ph_u})
$pd.DefaultPageSettings.PaperSize = $paperSize
$pd.DefaultPageSettings.Landscape = ($bmp.Width -gt $bmp.Height)
$pd.add_PrintPage({{
    param($s, $e){draw_block}
}})
$pd.Print()
$bmp.Dispose()
"""
            ps_env = os.environ.copy()
            ps_env["PS_PRINTER_NAME"] = self.nombre or ""
            ps_env["PS_FILE_PATH"] = tmp.name
            try:
                r = subprocess.run(
                    ["powershell", "-NoProfile", "-NonInteractive", "-Command", ps],
                    timeout=60, capture_output=True, text=True, env=ps_env
                )
            except subprocess.TimeoutExpired:
                print("[PrinterManager] PowerShell tardó más de 60s — trabajo cancelado")
                return False
            if r.returncode != 0:
                print(f"[PrinterManager] PS stderr: {r.stderr.strip()}")
            return r.returncode == 0
        finally:
            try:
                os.unlink(tmp.name)
            except Exception:
                pass

    def _imprimir_startfile(self, img: Image.Image) -> bool:
        """Último recurso: abre el archivo con el visor de impresión del sistema."""
        tmp_path = None
        try:
            tmp = tempfile.NamedTemporaryFile(suffix=".jpg", delete=False)
            tmp_path = tmp.name
            tmp.close()
            img.convert("RGB").save(tmp_path, "JPEG", quality=95)
            os.startfile(tmp_path, "print")
            # El visor de Windows necesita el archivo mientras imprime;
            # lo eliminamos con un pequeño retraso en un hilo daemon para no
            # bloquear y no dejar archivos huérfanos en %TEMP%.
            import threading, time
            def _cleanup(path: str):
                time.sleep(30)
                try:
                    os.unlink(path)
                except Exception:
                    pass
            threading.Thread(target=_cleanup, args=(tmp_path,), daemon=True).start()
            return True
        except Exception as e:
            print(f"[PrinterManager] startfile error: {e}")
            if tmp_path:
                try:
                    os.unlink(tmp_path)
                except Exception:
                    pass
            return False

    # ── Configuración Kodak 305 ───────────────────────────────────────────────

    @staticmethod
    def dimensiones_optimas_kodak305(modo: str = "strip_2x6") -> tuple[int, int]:
        """Devuelve (ancho, alto) en píxeles a 300 dpi para el Kodak 305."""
        if modo == "strip_2x6":
            return (600, 1800)   # 2" × 6" a 300 dpi
        elif modo == "foto_4x6":
            return (1200, 1800)  # 4" × 6" a 300 dpi
        return (600, 1800)
