"""
PAMPA Client — PhotoBooth
Validación de licencias siempre en línea con gracia de 48h si no hay internet.
"""
import requests
import platform
import uuid
import subprocess
import hashlib
import hmac
import socket
import json
from pathlib import Path
from datetime import datetime
from typing import Optional, Dict

OFFLINE_LIMIT_HOURS = 48


class PampaClient:
    def __init__(self, program_code: str, api_url: str = "https://pampaguazu.com.ar"):
        self.program_code = program_code
        self.api_url = api_url.rstrip("/")

    # ── Caché de última validación exitosa (gracia 48h offline) ──────────────

    def _cache_path(self) -> Path:
        p = Path.home() / ".pampa"
        p.mkdir(exist_ok=True)
        return p / f"{self.program_code}_lastvalid.json"

    def _hmac_key(self) -> bytes:
        """Clave HMAC derivada del hardware — única por máquina."""
        return self.get_hardware_hash().encode()

    def _sign(self, payload: dict) -> str:
        body = json.dumps(payload, sort_keys=True).encode()
        return hmac.new(self._hmac_key(), body, hashlib.sha256).hexdigest()

    def save_last_valid(self, license_key: str) -> None:
        try:
            payload = {"license_key": license_key, "timestamp": datetime.now().isoformat()}
            payload["sig"] = self._sign({k: v for k, v in payload.items()})
            with open(self._cache_path(), "w") as f:
                json.dump(payload, f)
        except Exception:
            pass

    def hours_since_last_valid(self, license_key: str) -> Optional[float]:
        try:
            with open(self._cache_path()) as f:
                data = json.load(f)
            # Verificar integridad HMAC
            sig = data.pop("sig", None)
            expected = self._sign(data)
            if not sig or not hmac.compare_digest(sig, expected):
                return None  # Archivo manipulado o de otra máquina
            if data.get("license_key") != license_key:
                return None
            last = datetime.fromisoformat(data["timestamp"])
            return max(0.0, (datetime.now() - last).total_seconds() / 3600)
        except Exception:
            return None

    # ── Hardware ──────────────────────────────────────────────────────────────

    @staticmethod
    def _ps(cmd: str) -> str:
        try:
            r = subprocess.run(
                ["powershell", "-NoProfile", "-NonInteractive", "-Command", cmd],
                capture_output=True, text=True, timeout=8,
                creationflags=subprocess.CREATE_NO_WINDOW
            )
            return r.stdout.strip()
        except Exception:
            return ""

    def get_hardware_fingerprint(self) -> Dict[str, str]:
        cpu_id = "CPU_UNKNOWN"
        mb_serial = "MB_UNKNOWN"
        disk_serial = "DISK_UNKNOWN"
        sys_uuid = str(uuid.uuid4())

        if platform.system() == "Windows":
            try:
                cpu_id = self._ps("(Get-CimInstance Win32_Processor | Select-Object -First 1).ProcessorId") or "CPU_UNKNOWN"
            except Exception:
                pass
            try:
                mb_serial = self._ps("(Get-CimInstance Win32_BaseBoard).SerialNumber") or "MB_UNKNOWN"
            except Exception:
                pass
            try:
                disk_serial = self._ps("(Get-CimInstance Win32_DiskDrive | Select-Object -First 1).SerialNumber") or "DISK_UNKNOWN"
            except Exception:
                pass
            try:
                raw_uuid = self._ps("(Get-CimInstance Win32_ComputerSystemProduct).UUID")
                invalid = {"", "FFFFFFFF-FFFF-FFFF-FFFF-FFFFFFFFFFFF", "03000200-0400-0500-0006-000700080009"}
                if raw_uuid and raw_uuid not in invalid:
                    sys_uuid = raw_uuid
            except Exception:
                pass

        try:
            mac = ":".join(["{:02x}".format((uuid.getnode() >> e) & 0xff) for e in range(0, 48, 8)][::-1])
        except Exception:
            mac = "MAC_UNKNOWN"

        return {
            "cpu_id": cpu_id,
            "motherboard_serial": mb_serial,
            "disk_serial": disk_serial,
            "mac_address": mac,
            "system_uuid": sys_uuid,
        }

    def get_hardware_hash(self) -> str:
        hw = self.get_hardware_fingerprint()
        data = f"{hw['cpu_id']}|{hw['motherboard_serial']}|{hw['disk_serial']}|{hw['mac_address']}|{hw['system_uuid']}"
        return hashlib.sha256(data.encode()).hexdigest()

    def get_machine_name(self) -> str:
        try:
            return socket.gethostname()
        except Exception:
            return "Desconocido"

    # ── Validación ────────────────────────────────────────────────────────────

    def validate_license(self, license_key: str, force_online: bool = True, app_version: str = None, explicit_activation: bool = False) -> dict:
        """
        Valida la licencia contra PAMPA.
        - Online: siempre intenta primero. Si OK, guarda timestamp de última validación.
        - Offline: si no hay internet y la última validación fue hace menos de 48h, permite continuar.
        """
        from config.settings import APP_VERSION
        try:
            response = requests.post(
                f"{self.api_url}/api/v1/validate",
                json={
                    "program_code": self.program_code,
                    "license_key": license_key,
                    "hardware": self.get_hardware_fingerprint(),
                    "machine_name": self.get_machine_name(),
                    "app_version": app_version or APP_VERSION,
                    "clock_tampered": False,
                    "explicit_activation": explicit_activation,
                },
                timeout=30,
            )
            if response.status_code == 200:
                result = response.json()
                if result.get("valid"):
                    self.save_last_valid(license_key)
                return result
            else:
                try:
                    detail = response.json().get("detail", response.text[:200])
                except Exception:
                    detail = response.text[:200]
                return {
                    "valid": False,
                    "status": "server_error",
                    "message": f"Error del servidor ({response.status_code}): {detail}",
                }
        except (requests.exceptions.ConnectionError, requests.exceptions.Timeout) as exc:
            # Sin internet → intentar gracia offline
            hours = self.hours_since_last_valid(license_key)
            if hours is not None and hours <= OFFLINE_LIMIT_HOURS:
                remaining = round(OFFLINE_LIMIT_HOURS - hours, 1)
                return {
                    "valid": True,
                    "status": "offline_grace",
                    "message": f"Sin conexión. Modo offline activo ({remaining}h restantes).",
                    "hours_offline": round(hours, 1),
                    "hours_remaining": remaining,
                }
            # Gracia vencida o primer uso sin validación previa
            is_timeout = isinstance(exc, requests.exceptions.Timeout)
            return {
                "valid": False,
                "status": "sin_conexion",
                "message": (
                    "El servidor tardó demasiado en responder. Verificá tu conexión."
                    if is_timeout else
                    "Sin conexión a internet. PhotoBooth requiere conexión para validar la licencia."
                ),
            }
        except Exception as e:
            return {
                "valid": False,
                "status": "error",
                "message": f"Error al conectar con el servidor: {str(e)}",
            }

    # ── Autenticación ─────────────────────────────────────────────────────────

    def login(self, email: str, password: str) -> dict:
        try:
            response = requests.post(
                f"{self.api_url}/api/v1/auth/login",
                json={"email": email, "password": password},
                timeout=15,
            )
            if response.status_code == 200:
                return response.json()
            return {"success": False, "error": f"Error del servidor: {response.status_code}"}
        except requests.exceptions.Timeout:
            return {"success": False, "error": "Timeout al conectar. Verificá tu conexión."}
        except requests.exceptions.ConnectionError:
            return {"success": False, "error": "Sin conexión a internet."}
        except Exception as e:
            return {"success": False, "error": str(e)}

    def register(self, email: str, password: str, nombre: str, apellido: str = "", telefono: str = "") -> dict:
        try:
            response = requests.post(
                f"{self.api_url}/api/v1/auth/register",
                json={"email": email, "password": password, "nombre": nombre,
                      "apellido": apellido, "telefono": telefono},
                timeout=15,
            )
            if response.status_code == 200:
                return response.json()
            return {"success": False, "error": f"Error del servidor: {response.status_code}"}
        except requests.exceptions.Timeout:
            return {"success": False, "error": "Timeout al conectar. Verificá tu conexión."}
        except requests.exceptions.ConnectionError:
            return {"success": False, "error": "Sin conexión a internet."}
        except Exception as e:
            return {"success": False, "error": str(e)}

    # ── Registro de instalación ────────────────────────────────────────────────

    def register_install(self, install_id: str, license_key: str = "", app_version: str = None) -> bool:
        from config.settings import APP_VERSION
        try:
            response = requests.post(
                f"{self.api_url}/api/v1/install",
                json={
                    "install_id": install_id,
                    "program_code": self.program_code,
                    "machine_name": self.get_machine_name(),
                    "hardware_hash": self.get_hardware_hash(),
                    "app_version": app_version or APP_VERSION,
                    "license_key": license_key or None,
                },
                timeout=10,
            )
            return response.status_code == 200
        except Exception:
            return False

    # ── Actualizaciones ───────────────────────────────────────────────────────

    def check_for_updates(self, current_version: str) -> Optional[Dict]:
        try:
            response = requests.get(
                f"{self.api_url}/api/v1/version/{self.program_code}",
                timeout=5,
            )
            if response.status_code == 200:
                data = response.json()
                latest = data.get("latest_version", current_version)
                if self._version_is_newer(latest, current_version):
                    return {
                        "latest_version": latest,
                        "download_url": data.get("download_url", ""),
                        "changelog": data.get("changelog", {}),
                    }
            return None
        except Exception:
            return None

    def download_update(self, download_url: str, dest_path: str, progress_callback=None) -> bool:
        try:
            response = requests.get(download_url, stream=True, timeout=60)
            response.raise_for_status()
            total = int(response.headers.get("content-length", 0))
            downloaded = 0
            with open(dest_path, "wb") as f:
                for chunk in response.iter_content(chunk_size=8192):
                    f.write(chunk)
                    downloaded += len(chunk)
                    if progress_callback and total > 0:
                        progress_callback(downloaded / total, downloaded, total)
            return True
        except Exception as e:
            return False

    def _version_is_newer(self, latest: str, current: str) -> bool:
        try:
            return [int(x) for x in latest.split(".")] > [int(x) for x in current.split(".")]
        except Exception:
            return False
