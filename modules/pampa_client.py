"""
PAMPA Client - Módulo de validación de licencias con JWT
Para integrar en WelcomeX, Tauro360, Clickear, etc.
"""
import requests
import platform
import uuid
import subprocess
import hashlib
import json
import socket
import jwt
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional, Dict

# Límite offline en horas (debe coincidir con el servidor)
OFFLINE_LIMIT_HOURS = 48


class PampaClient:
    """Cliente para validar licencias con PAMPA usando tokens JWT"""

    def __init__(self, program_code: str, api_url: str = "https://pampaguazu.com.ar"):
        self.program_code = program_code
        self.api_url = api_url.rstrip('/')

        # Token JWT local
        self.token_file = Path.home() / ".pampa" / f"{program_code}_token.jwt"
        self.token_file.parent.mkdir(exist_ok=True)

        # Cache viejo (para migración)
        self.old_cache_file = Path.home() / ".pampa" / f"{program_code}_license.json"

        # Archivo de timestamp para detección de manipulación de reloj
        self.timestamp_file = Path.home() / ".pampa" / f"{program_code}_lasttime.dat"

    # ==============================================
    # HARDWARE FINGERPRINT
    # ==============================================

    @staticmethod
    def _ps(cmd: str) -> str:
        """Ejecuta un comando PowerShell y devuelve la salida limpia."""
        try:
            r = subprocess.run(
                ["powershell", "-NoProfile", "-NonInteractive", "-Command", cmd],
                capture_output=True, text=True, timeout=8,
                creationflags=subprocess.CREATE_NO_WINDOW
            )
            return r.stdout.strip()
        except Exception:
            return ""

    def get_cpu_id(self) -> str:
        try:
            if platform.system() == "Windows":
                out = self._ps("(Get-CimInstance Win32_Processor | Select-Object -First 1).ProcessorId")
                return out if out else "CPU_UNKNOWN"
            return str(uuid.getnode())
        except:
            return "CPU_UNKNOWN"

    def get_motherboard_serial(self) -> str:
        try:
            if platform.system() == "Windows":
                out = self._ps("(Get-CimInstance Win32_BaseBoard).SerialNumber")
                return out if out else "MB_UNKNOWN"
            return "MB_UNKNOWN"
        except:
            return "MB_UNKNOWN"

    def get_disk_serial(self) -> str:
        try:
            if platform.system() == "Windows":
                out = self._ps("(Get-CimInstance Win32_DiskDrive | Select-Object -First 1).SerialNumber")
                return out if out else "DISK_UNKNOWN"
            return "DISK_UNKNOWN"
        except:
            return "DISK_UNKNOWN"

    def get_mac_address(self) -> str:
        try:
            mac = ':'.join(['{:02x}'.format((uuid.getnode() >> elements) & 0xff)
                           for elements in range(0, 2*6, 2)][::-1])
            return mac
        except:
            return "MAC_UNKNOWN"

    def get_system_uuid(self) -> str:
        try:
            if platform.system() == "Windows":
                out = self._ps("(Get-CimInstance Win32_ComputerSystemProduct).UUID")
                invalid = {"", "FFFFFFFF-FFFF-FFFF-FFFF-FFFFFFFFFFFF", "03000200-0400-0500-0006-000700080009"}
                return out if out and out not in invalid else str(uuid.uuid4())
            return str(uuid.uuid4())
        except:
            return str(uuid.uuid4())

    def get_hardware_fingerprint(self) -> Dict[str, str]:
        return {
            "cpu_id": self.get_cpu_id(),
            "motherboard_serial": self.get_motherboard_serial(),
            "disk_serial": self.get_disk_serial(),
            "mac_address": self.get_mac_address(),
            "system_uuid": self.get_system_uuid()
        }

    def get_hardware_hash(self) -> str:
        """Genera hash SHA256 del hardware (debe coincidir con el servidor)"""
        hw = self.get_hardware_fingerprint()
        data = f"{hw['cpu_id']}|{hw['motherboard_serial']}|{hw['disk_serial']}|{hw['mac_address']}|{hw['system_uuid']}"
        return hashlib.sha256(data.encode()).hexdigest()

    def get_machine_name(self) -> str:
        try:
            return socket.gethostname()
        except:
            return "Desconocido"

    # ==============================================
    # TOKEN JWT LOCAL
    # ==============================================

    def save_token(self, token_str: str):
        """Guarda el JWT en archivo local"""
        with open(self.token_file, 'w') as f:
            f.write(token_str)
        # Eliminar cache viejo si existe (migración)
        if self.old_cache_file.exists():
            try:
                self.old_cache_file.unlink()
                print("[PAMPA] Cache viejo eliminado (migración a JWT)")
            except:
                pass

    def load_token_raw(self) -> Optional[str]:
        """Carga el JWT raw (string) del archivo"""
        if not self.token_file.exists():
            return None
        try:
            with open(self.token_file, 'r') as f:
                return f.read().strip()
        except:
            return None

    def load_token(self) -> Optional[dict]:
        """
        Carga y decodifica el token JWT local (sin verificar firma).
        Retorna el payload como dict o None si no existe/es inválido.
        """
        raw = self.load_token_raw()
        if not raw:
            return None

        try:
            payload = jwt.decode(raw, options={"verify_signature": False})
            return payload
        except Exception as e:
            print(f"[PAMPA] Error decodificando token: {e}")
            return None

    def clear_token(self):
        """Elimina el token local"""
        if self.token_file.exists():
            self.token_file.unlink()

    def _has_old_cache(self) -> bool:
        """Verifica si existe cache viejo (pre-JWT) para forzar migración"""
        return self.old_cache_file.exists()

    # ==============================================
    # PROTECCIÓN ANTI-MANIPULACIÓN DE RELOJ
    # ==============================================

    def save_last_seen_time(self):
        """Guarda el timestamp actual como última hora conocida (nunca retrocede)"""
        try:
            now = datetime.now()
            current = self.load_last_seen_time()
            time_to_save = max(now, current) if current else now
            with open(self.timestamp_file, 'w') as f:
                f.write(time_to_save.isoformat())
        except:
            pass

    def load_last_seen_time(self) -> Optional[datetime]:
        """Carga la última hora conocida del sistema"""
        if not self.timestamp_file.exists():
            return None
        try:
            with open(self.timestamp_file, 'r') as f:
                return datetime.fromisoformat(f.read().strip())
        except:
            return None

    def get_effective_now(self) -> tuple:
        """
        Retorna la hora efectiva actual, protegida contra manipulación de reloj.
        Si el reloj retrocedió, usa la última hora conocida para evitar bypass del límite offline.

        Returns: (effective_time: datetime, clock_warning: str|None)
        """
        now = datetime.now()
        last_seen = self.load_last_seen_time()
        clock_warning = None

        if last_seen and now < (last_seen - timedelta(minutes=5)):
            diff_minutes = int((last_seen - now).total_seconds() / 60)
            clock_warning = (
                f"Se detectó que el reloj del sistema retrocedió {diff_minutes} minutos "
                f"respecto al último uso registrado."
            )
            print(f"[PAMPA] ⚠️ Clock tampering detectado: reloj retrocedió {diff_minutes} min")
            return last_seen, clock_warning

        return now, clock_warning

    def check_time_integrity(self) -> dict:
        """
        Verificación completa de integridad del reloj.
        Compara con hora local guardada y con servidor si hay conexión.

        Returns: {ok: bool, warning: str|None, type: str|None}
        """
        result = {"ok": True, "warning": None, "type": None}

        effective_now, clock_warning = self.get_effective_now()
        if clock_warning:
            result["ok"] = False
            result["warning"] = clock_warning
            result["type"] = "clock_backwards"

        # Comparar con hora del servidor si hay conexión
        try:
            from email.utils import parsedate_to_datetime
            response = requests.head(f"{self.api_url}/", timeout=5)
            server_date = response.headers.get('Date')
            if server_date:
                server_time = parsedate_to_datetime(server_date)
                # Comparar ambos en UTC para evitar desfasaje por timezone
                from datetime import timezone as tz
                now_utc = datetime.now(tz.utc)
                server_utc = server_time if server_time.tzinfo else server_time.replace(tzinfo=tz.utc)
                diff_seconds = abs((now_utc - server_utc).total_seconds())
                if diff_seconds > 300:  # 5 minutos
                    result["ok"] = False
                    result["warning"] = (
                        f"El reloj del sistema difiere del servidor por "
                        f"{int(diff_seconds/60)} minutos."
                    )
                    result["type"] = "clock_drift"
        except:
            pass

        # Guardar hora actual (monotónica)
        self.save_last_seen_time()

        return result

    # ==============================================
    # VALIDACIÓN CON JWT
    # ==============================================

    def validate_license(self, license_key: str, force_online: bool = False, app_version: str = None) -> dict:
        """
        Valida una licencia usando JWT.

        - Si hay token local válido (< 48h): permite uso offline
        - Si no hay token o expiró: valida online y recibe nuevo JWT
        - Si hardware_id no coincide: bloquea (token copiado)
        """
        _offline_limit_ctx = None  # Set if offline limit exceeded, used as fallback in exception handlers

        # Forzar online si hay cache viejo (migración)
        if self._has_old_cache():
            print("[PAMPA] Detectado cache viejo, forzando validación online para migrar a JWT")
            force_online = True

        # Intentar usar token local
        if not force_online:
            token_data = self.load_token()
            if token_data and token_data.get('license_key') == license_key:
                last_validation_str = token_data.get('last_validation')
                if last_validation_str:
                    try:
                        last_validation = datetime.fromisoformat(last_validation_str)

                        # Usar hora efectiva (protegida contra manipulación de reloj)
                        effective_now, clock_warning = self.get_effective_now()
                        hours_since = (effective_now - last_validation).total_seconds() / 3600

                        # Si hours_since es negativo pese a la protección, forzar a 0
                        if hours_since < 0:
                            hours_since = 0

                        # Verificar hardware_id
                        current_hw_hash = self.get_hardware_hash()
                        if token_data.get('hardware_id') != current_hw_hash:
                            # Token de otra PC o reinstalación — borrar y revalidar online
                            print("[PAMPA] Hardware ID del token no coincide — borrando token y revalidando online")
                            self.clear_token()
                            return self.validate_license(license_key, force_online=True, app_version=app_version)

                        # Verificar expiración de licencia
                        expires_at_str = token_data.get('expires_at')
                        if expires_at_str:
                            expires_at = datetime.fromisoformat(expires_at_str)
                            if expires_at < effective_now:
                                return {
                                    "valid": False,
                                    "status": "expired",
                                    "message": "La licencia ha vencido.",
                                    "used_cache": True
                                }

                        # Verificar límite offline
                        offline_limit = token_data.get('offline_limit_hours', OFFLINE_LIMIT_HOURS)
                        if hours_since <= offline_limit:
                            print(f"[PAMPA] Token válido (offline {hours_since:.1f}h / {offline_limit}h)")
                            days_remaining = None
                            if expires_at_str:
                                days_remaining = max(0, (datetime.fromisoformat(expires_at_str) - effective_now).days)

                            # Guardar timestamp (monotónico)
                            self.save_last_seen_time()

                            return {
                                "valid": True,
                                "status": "active",
                                "message": "Licencia válida (modo offline)",
                                "expires_at": expires_at_str,
                                "days_remaining": days_remaining,
                                "used_cache": True,
                                "hours_offline": round(hours_since, 1),
                                "hours_remaining": round(offline_limit - hours_since, 1),
                                "clock_warning": clock_warning
                            }
                        else:
                            print(f"[PAMPA] Límite offline superado ({hours_since:.1f}h > {offline_limit}h) — intentando validación online...")
                            _offline_limit_ctx = {
                                "limit": offline_limit,
                                "hours": hours_since,
                                "clock_warning": clock_warning
                            }
                            # No return — caer en validación online
                    except Exception as e:
                        print(f"[PAMPA] Error procesando token: {e}")

        # Validación online
        print("[PAMPA] Validando licencia online...")

        # Verificar integridad del reloj antes de validar
        _, clock_warning_online = self.get_effective_now()

        try:
            hardware = self.get_hardware_fingerprint()

            response = requests.post(
                f"{self.api_url}/api/v1/validate",
                json={
                    "program_code": self.program_code,
                    "license_key": license_key,
                    "hardware": hardware,
                    "machine_name": self.get_machine_name(),
                    "app_version": app_version,
                    "clock_tampered": clock_warning_online is not None
                },
                timeout=15
            )

            if response.status_code == 200:
                result = response.json()
                result['used_cache'] = False

                # Guardar token JWT si viene en la respuesta
                token = result.get('token')
                if token:
                    self.save_token(token)
                    self.save_last_seen_time()
                    print("[PAMPA] Token JWT guardado")

                return result
            else:
                try:
                    detail = response.json().get("detail", "")
                except Exception:
                    detail = response.text[:200]
                msg = f"Error del servidor: {response.status_code}"
                if detail:
                    msg += f"\n{detail}"
                return {
                    "valid": False,
                    "status": "connection_error",
                    "message": msg,
                    "used_cache": False
                }

        except requests.exceptions.Timeout:
            if _offline_limit_ctx:
                return {
                    "valid": False,
                    "status": "offline_limit",
                    "message": f"Se superó el límite de {_offline_limit_ctx['limit']} horas sin conexión. Conéctate a internet para continuar.",
                    "used_cache": True,
                    "clock_warning": _offline_limit_ctx.get("clock_warning")
                }
            return {
                "valid": False,
                "status": "connection_error",
                "message": "Timeout al conectar con PAMPA. Verifica tu conexión a internet.",
                "used_cache": False
            }

        except requests.exceptions.ConnectionError:
            if _offline_limit_ctx:
                return {
                    "valid": False,
                    "status": "offline_limit",
                    "message": f"Se superó el límite de {_offline_limit_ctx['limit']} horas sin conexión. Conéctate a internet para continuar.",
                    "used_cache": True,
                    "clock_warning": _offline_limit_ctx.get("clock_warning")
                }
            return {
                "valid": False,
                "status": "connection_error",
                "message": "No se pudo conectar con PAMPA. Verifica tu conexión a internet.",
                "used_cache": False
            }

        except Exception as e:
            if _offline_limit_ctx:
                return {
                    "valid": False,
                    "status": "offline_limit",
                    "message": f"Se superó el límite de {_offline_limit_ctx['limit']} horas sin conexión. Conéctate a internet para continuar.",
                    "used_cache": True,
                    "clock_warning": _offline_limit_ctx.get("clock_warning")
                }
            return {
                "valid": False,
                "status": "error",
                "message": f"Error inesperado: {str(e)}",
                "used_cache": False
            }

    # ==============================================
    # VALIDACIÓN SILENCIOSA (cada 6h)
    # ==============================================

    def silent_refresh(self, license_key: str) -> dict:
        """
        Refresca el token JWT silenciosamente.
        Se usa cada 6 horas para verificar que la licencia sigue activa
        y que no fue activada en otra PC.
        """
        raw_token = self.load_token_raw()
        if not raw_token:
            return {"valid": False, "status": "no_token", "message": "No hay token local"}

        hw_hash = self.get_hardware_hash()

        try:
            response = requests.post(
                f"{self.api_url}/api/v1/token/refresh",
                json={
                    "token": raw_token,
                    "hardware_id": hw_hash
                },
                timeout=10
            )

            if response.status_code == 200:
                result = response.json()

                if result.get('valid') and result.get('token'):
                    self.save_token(result['token'])
                    self.save_last_seen_time()
                    print("[PAMPA] Token renovado silenciosamente")

                return result
            else:
                return {"valid": False, "status": "server_error",
                        "message": f"Error del servidor: {response.status_code}"}

        except (requests.exceptions.ConnectionError, requests.exceptions.Timeout):
            print("[PAMPA] Sin conexión para refresh silencioso (se usará token local)")
            return {"valid": True, "status": "offline",
                    "message": "Sin conexión, usando token local"}

        except Exception as e:
            print(f"[PAMPA] Error en refresh silencioso: {e}")
            return {"valid": True, "status": "refresh_error",
                    "message": f"Error: {str(e)}"}

    # ==============================================
    # REGISTRO DE INSTALACIÓN
    # ==============================================

    def register_install(self, install_id: str, license_key: str = "",
                         app_version: str = None) -> bool:
        """
        Envía un ping a PAMPA con datos del equipo para registrar la instalación.
        Fire-and-forget: devuelve True si OK, False si falla (no bloquea el inicio).
        """
        from config.settings import APP_VERSION
        try:
            response = requests.post(
                f"{self.api_url}/api/v1/install",
                json={
                    "install_id":    install_id,
                    "program_code":  self.program_code,
                    "machine_name":  self.get_machine_name(),
                    "hardware_hash": self.get_hardware_hash(),
                    "app_version":   app_version or APP_VERSION,
                    "license_key":   license_key or None,
                },
                timeout=10,
            )
            return response.status_code == 200
        except Exception:
            return False

    # ==============================================
    # AUTOLIBERACIÓN
    # ==============================================

    def release_license(self, license_key: str, app_version: str = None) -> dict:
        """
        Libera la licencia de este equipo para poder usarla en otro.
        Requiere conexión a internet.
        """
        try:
            hardware = self.get_hardware_fingerprint()

            response = requests.post(
                f"{self.api_url}/api/v1/license/release",
                json={
                    "license_key": license_key,
                    "hardware": hardware,
                    "machine_name": self.get_machine_name(),
                    "app_version": app_version
                },
                timeout=15
            )

            if response.status_code == 200:
                result = response.json()

                if result.get('success'):
                    self.clear_token()
                    print("[PAMPA] Licencia liberada, token local eliminado")

                return result
            else:
                return {"success": False, "message": f"Error del servidor: {response.status_code}"}

        except requests.exceptions.ConnectionError:
            return {"success": False, "message": "Se necesita conexión a internet para liberar la licencia."}
        except requests.exceptions.Timeout:
            return {"success": False, "message": "Timeout al conectar. Intenta nuevamente."}
        except Exception as e:
            return {"success": False, "message": f"Error: {str(e)}"}

    # ==============================================
    # CONSULTAS
    # ==============================================

    def get_license_status(self, license_key: str) -> Optional[dict]:
        """Obtiene el estado de una licencia (sin validar hardware)"""
        try:
            response = requests.get(
                f"{self.api_url}/api/v1/license/{license_key}/status",
                timeout=10
            )
            if response.status_code == 200:
                return response.json()
            else:
                return None
        except Exception as e:
            print(f"[PAMPA] Error obteniendo estado: {e}")
            return None

    def check_expiration_alerts(self, license_key: str) -> Optional[str]:
        """Verifica si la licencia está por vencer"""
        token_data = self.load_token()
        if not token_data or token_data.get('license_key') != license_key:
            return None

        expires_at_str = token_data.get('expires_at')
        if not expires_at_str:
            return None

        try:
            expires_at = datetime.fromisoformat(expires_at_str)
            effective_now, _ = self.get_effective_now()
            days_remaining = max(0, (expires_at - effective_now).days)
        except:
            return None

        if days_remaining <= 1:
            return f"⚠️ Tu licencia vence en {days_remaining} día(s). Renueva ahora para evitar interrupciones."
        elif days_remaining <= 3:
            return f"⚠️ Tu licencia vence en {days_remaining} días."
        elif days_remaining <= 7:
            return f"ℹ️ Tu licencia vence en {days_remaining} días."

        return None

    def get_validation_info(self) -> Dict:
        """Obtiene información sobre el estado de validación"""
        token_data = self.load_token()

        if not token_data:
            return {
                "last_validation": None,
                "hours_since_validation": None,
                "hours_until_required": 0,
                "requires_connection": True
            }

        try:
            last_validation = datetime.fromisoformat(token_data['last_validation'])
            effective_now, _ = self.get_effective_now()
            hours_since = (effective_now - last_validation).total_seconds() / 3600
            if hours_since < 0:
                hours_since = 0
            offline_limit = token_data.get('offline_limit_hours', OFFLINE_LIMIT_HOURS)
            hours_until = max(0, offline_limit - hours_since)

            return {
                "last_validation": last_validation,
                "hours_since_validation": round(hours_since, 1),
                "hours_until_required": round(hours_until, 1),
                "requires_connection": hours_since >= offline_limit
            }
        except:
            return {
                "last_validation": None,
                "hours_since_validation": None,
                "hours_until_required": 0,
                "requires_connection": True
            }

    def is_cache_expired(self) -> bool:
        """Verifica si el token local ha expirado (>48h offline)"""
        info = self.get_validation_info()
        return info.get("requires_connection", True)

    # ==============================================
    # AUTENTICACIÓN DE USUARIOS
    # ==============================================

    def login(self, email: str, password: str) -> dict:
        """Autenticar usuario contra PAMPA"""
        print("[PAMPA] Autenticando usuario online...")

        try:
            response = requests.post(
                f"{self.api_url}/api/v1/auth/login",
                json={"email": email, "password": password},
                timeout=15
            )

            if response.status_code == 200:
                result = response.json()
                if result.get('success'):
                    print(f"[PAMPA] Usuario autenticado: {result['usuario']['email']}")
                else:
                    print(f"[PAMPA] Error: {result.get('error')}")
                return result
            else:
                return {"success": False, "error": f"Error del servidor: {response.status_code}"}

        except requests.exceptions.Timeout:
            return {"success": False, "error": "Timeout al conectar. Verifica tu conexión a internet."}
        except requests.exceptions.ConnectionError:
            return {"success": False, "error": "No se pudo conectar con el servidor. Verifica tu conexión."}
        except Exception as e:
            return {"success": False, "error": f"Error inesperado: {str(e)}"}

    def register(self, email: str, password: str, nombre: str, apellido: str = "", telefono: str = "") -> dict:
        """Registrar usuario en PAMPA"""
        print("[PAMPA] Registrando usuario online...")

        try:
            response = requests.post(
                f"{self.api_url}/api/v1/auth/register",
                json={
                    "email": email, "password": password,
                    "nombre": nombre, "apellido": apellido,
                    "telefono": telefono
                },
                timeout=15
            )

            if response.status_code == 200:
                result = response.json()
                if result.get('success'):
                    print(f"[PAMPA] Usuario registrado: {email}")
                else:
                    print(f"[PAMPA] Error: {result.get('error')}")
                return result
            else:
                return {"success": False, "error": f"Error del servidor: {response.status_code}"}

        except requests.exceptions.Timeout:
            return {"success": False, "error": "Timeout al conectar. Verifica tu conexión a internet."}
        except requests.exceptions.ConnectionError:
            return {"success": False, "error": "No se pudo conectar con el servidor. Verifica tu conexión."}
        except Exception as e:
            return {"success": False, "error": f"Error inesperado: {str(e)}"}

    # ==============================================
    # VERIFICACIÓN DE ACTUALIZACIONES
    # ==============================================

    def check_for_updates(self, current_version: str) -> Optional[Dict]:
        """Consulta al servidor si hay una versión más nueva."""
        try:
            response = requests.get(
                f"{self.api_url}/api/v1/version/{self.program_code}",
                timeout=5
            )
            if response.status_code == 200:
                data = response.json()
                latest = data.get("latest_version", current_version)
                if self._version_is_newer(latest, current_version):
                    return {
                        "latest_version": latest,
                        "download_url": data.get("download_url", ""),
                        "changelog": data.get("changelog", {})
                    }
            return None
        except:
            return None

    def download_update(self, download_url: str, dest_path: str, progress_callback=None) -> bool:
        """Descarga el instalador de actualización con progreso."""
        try:
            response = requests.get(download_url, stream=True, timeout=30)
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
            print(f"[WelcomeX] Error descargando update: {e}")
            return False

    def _version_is_newer(self, latest: str, current: str) -> bool:
        """Compara versiones semánticas (1.2.3 > 1.2.0)"""
        try:
            latest_parts = [int(x) for x in latest.split(".")]
            current_parts = [int(x) for x in current.split(".")]
            return latest_parts > current_parts
        except:
            return False
