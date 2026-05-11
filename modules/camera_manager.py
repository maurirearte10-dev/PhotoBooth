import cv2
import time
import threading
from typing import Callable, Optional
from PIL import Image


class CameraInfo:
    def __init__(self, index: int, nombre: str):
        self.index = index
        self.nombre = nombre

    def __str__(self):
        return self.nombre


class CameraManager:
    """Detecta cámaras disponibles y gestiona la captura de fotogramas."""

    MAX_CAMERAS_CHECK = 8

    def __init__(self):
        self._cap: Optional[cv2.VideoCapture] = None
        self._camara_index: int = 0
        self._activa: bool = False
        self._frame_lock = threading.Lock()
        self._ultimo_frame: Optional[Image.Image] = None
        self._hilo: Optional[threading.Thread] = None
        self._callback_frame: Optional[Callable[[Image.Image], None]] = None

    # ── Detección ──────────────────────────────────────────────────────────────

    # MSMF excluido: tiene COM marshaling que puede congelar threads en Windows
    _BACKENDS = [cv2.CAP_DSHOW, cv2.CAP_ANY]

    @classmethod
    def _abrir_camara(cls, index: int) -> cv2.VideoCapture | None:
        """Intenta abrir la cámara probando backends DSHOW y CAP_ANY."""
        for backend in cls._BACKENDS:
            try:
                cap = cv2.VideoCapture(index, backend)
                if cap.isOpened():
                    ok, _ = cap.read()
                    if ok:
                        return cap
                    cap.release()
            except Exception:
                pass
        return None

    @staticmethod
    def _nombres_camaras_windows() -> list[str]:
        """Devuelve nombres reales de cámaras vía PowerShell (sin wmic)."""
        try:
            import subprocess
            cmd = (
                "Get-PnpDevice -PresentOnly | "
                "Where-Object { $_.Class -eq 'Camera' -or $_.Class -eq 'Image' } | "
                "Select-Object -ExpandProperty FriendlyName"
            )
            r = subprocess.run(
                ["powershell", "-NoProfile", "-Command", cmd],
                capture_output=True, text=True, timeout=8,
            )
            return [n.strip() for n in r.stdout.splitlines() if n.strip()]
        except Exception:
            return []

    def detectar_camaras(self) -> list[CameraInfo]:
        nombres = self._nombres_camaras_windows()
        camaras = []
        for i in range(self.MAX_CAMERAS_CHECK):
            cap = self._abrir_camara(i)
            if cap is not None:
                idx = len(camaras)
                nombre = nombres[idx] if idx < len(nombres) else f"Cámara {i + 1}"
                camaras.append(CameraInfo(i, nombre))
                cap.release()
        return camaras

    # ── Preview en tiempo real ─────────────────────────────────────────────────

    def iniciar_preview(self, camara_index: int,
                        callback: Callable[[Image.Image], None] | None = None,
                        width: int = 1280, height: int = 720):
        self.detener_preview()
        self._camara_index = camara_index
        self._callback_frame = callback
        self._activa = True
        # Abrir en hilo principal (MSMF/DSHOW requieren COM del hilo principal en Windows)
        self._cap = self._abrir_camara(camara_index)
        if self._cap is None:
            self._cap = cv2.VideoCapture(camara_index)
        self._hilo = threading.Thread(target=self._loop_captura, daemon=True)
        self._hilo.start()

    def _loop_captura(self):
        # Descartar primeros frames: la cámara ajusta exposición al arrancar
        warmup = 20
        warmup_done = 0
        last_cb = 0.0
        min_interval = 1.0 / 25  # máx 25 fps para el callback
        fallos_consecutivos = 0
        MAX_FALLOS = 40  # ~1.6s sin frames → reconectar con DSHOW

        while self._activa:
            if not self._cap or not self._cap.isOpened():
                # Reconectar con DSHOW (más estable que MSMF para streams largos)
                time.sleep(0.5)
                if not self._activa:
                    break
                cap_nuevo = cv2.VideoCapture(self._camara_index, cv2.CAP_DSHOW)
                if cap_nuevo.isOpened():
                    if self._cap:
                        self._cap.release()
                    self._cap = cap_nuevo
                    fallos_consecutivos = 0
                    warmup_done = 0
                continue

            try:
                ok, frame = self._cap.read()
            except Exception:
                time.sleep(0.05)
                continue

            if not ok or frame is None:
                fallos_consecutivos += 1
                if fallos_consecutivos >= MAX_FALLOS:
                    # Stream perdido — reconectar con DSHOW
                    self._cap.release()
                    self._cap = None
                    fallos_consecutivos = 0
                else:
                    time.sleep(0.04)
                continue

            fallos_consecutivos = 0

            # Descartar frames de warm-up (exposición aún ajustando)
            if warmup_done < warmup:
                warmup_done += 1
                continue

            try:
                img = self._bgr_to_pil(frame)
            except Exception:
                continue
            with self._frame_lock:
                self._ultimo_frame = img
            now = time.monotonic()
            if self._callback_frame and (now - last_cb) >= min_interval:
                last_cb = now
                self._callback_frame(img)

    def detener_preview(self):
        self._activa = False
        if self._cap:
            self._cap.release()
            self._cap = None
        self._hilo = None

    # ── Captura de foto ────────────────────────────────────────────────────────

    def capturar_foto(self) -> Optional[Image.Image]:
        """Devuelve el frame actual como PIL Image. Espera hasta 3s si la cámara aún calienta."""
        deadline = time.monotonic() + 3.0
        while time.monotonic() < deadline:
            with self._frame_lock:
                if self._ultimo_frame:
                    return self._ultimo_frame.copy()
            time.sleep(0.05)
        return None

    def capturar_foto_directa(self, camara_index: int) -> Optional[Image.Image]:
        """Captura una foto sin preview activo."""
        cap = self._abrir_camara(camara_index)
        if not cap or not cap.isOpened():
            return None
        # Calentar la cámara (descartar primeros frames)
        for _ in range(5):
            cap.read()
        ok, frame = cap.read()
        cap.release()
        return self._bgr_to_pil(frame) if ok else None

    # ── Utilidades ─────────────────────────────────────────────────────────────

    @staticmethod
    def _bgr_to_pil(frame) -> Image.Image:
        rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
        return Image.fromarray(rgb)

    def camara_disponible(self, index: int) -> bool:
        cap = self._abrir_camara(index)
        if cap:
            cap.release()
            return True
        return False

    def __del__(self):
        self.detener_preview()
