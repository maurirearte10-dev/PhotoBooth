import sqlite3
import hashlib
import secrets
import uuid
from datetime import datetime
from typing import Optional
from config.settings import DATABASE_PATH, SUPER_ADMIN_EMAIL, SUPER_ADMIN_NOMBRE


def _hash(password: str) -> str:
    return hashlib.sha256(password.encode()).hexdigest()


class DatabaseManager:
    def __init__(self):
        self.db_path = DATABASE_PATH
        self._crear_tablas()
        self._migrar()
        self._crear_super_admin()

    def _conn(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON")
        return conn

    # ── Migración ─────────────────────────────────────────────────────────────

    def _migrar(self):
        migraciones = [
            ("eventos", "formato",           "TEXT NOT NULL DEFAULT 'strip_2x6'"),
            ("eventos", "camara_index",      "INTEGER NOT NULL DEFAULT 0"),
            ("eventos", "modo_salida",       "TEXT NOT NULL DEFAULT 'imprimir'"),
            ("eventos", "ruta_digital",      "TEXT NOT NULL DEFAULT ''"),
            ("eventos", "logo_branding",     "TEXT NOT NULL DEFAULT ''"),
            ("eventos", "papel_size",        "TEXT NOT NULL DEFAULT '10x15'"),
            ("eventos", "escala_impresion",  "TEXT NOT NULL DEFAULT 'exacto'"),
            ("eventos", "color_modo",        "TEXT NOT NULL DEFAULT 'color'"),
        ]
        # Cada ALTER TABLE se ejecuta en su propio SAVEPOINT para que un cierre
        # abrupto a mitad de la migración no deje el schema en estado inconsistente:
        # las columnas ya aplicadas quedan commiteadas y las pendientes se reintentarán
        # en el próximo arranque.
        conn = self._conn()
        try:
            for tabla, col, definicion in migraciones:
                cols = [r[1] for r in conn.execute(f"PRAGMA table_info({tabla})").fetchall()]
                if col not in cols:
                    sp = f"sp_mig_{tabla}_{col}"
                    conn.execute(f"SAVEPOINT {sp}")
                    try:
                        conn.execute(f"ALTER TABLE {tabla} ADD COLUMN {col} {definicion}")
                        conn.execute(f"RELEASE {sp}")
                    except Exception:
                        conn.execute(f"ROLLBACK TO {sp}")
                        conn.execute(f"RELEASE {sp}")
                        raise
        finally:
            conn.close()

    # ── Creación de tablas ────────────────────────────────────────────────────

    def _crear_tablas(self):
        with self._conn() as conn:
            conn.executescript("""
                CREATE TABLE IF NOT EXISTS usuarios (
                    id              INTEGER PRIMARY KEY AUTOINCREMENT,
                    uuid            TEXT UNIQUE NOT NULL,
                    email           TEXT UNIQUE NOT NULL,
                    password_hash   TEXT NOT NULL,
                    nombre          TEXT NOT NULL,
                    rol             TEXT NOT NULL DEFAULT 'operario',
                    admin_id        INTEGER REFERENCES usuarios(id),
                    activo          INTEGER NOT NULL DEFAULT 1,
                    creado_en       TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS eventos (
                    id              INTEGER PRIMARY KEY AUTOINCREMENT,
                    usuario_id      INTEGER NOT NULL REFERENCES usuarios(id),
                    nombre          TEXT NOT NULL,
                    fecha_evento    TEXT,
                    formato         TEXT NOT NULL DEFAULT 'strip_2x6',
                    camara_index    INTEGER NOT NULL DEFAULT 0,
                    plantilla_id    INTEGER REFERENCES plantillas(id),
                    impresora       TEXT,
                    copias          INTEGER NOT NULL DEFAULT 1,
                    activo          INTEGER NOT NULL DEFAULT 1,
                    creado_en       TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS plantillas (
                    id              INTEGER PRIMARY KEY AUTOINCREMENT,
                    usuario_id      INTEGER REFERENCES usuarios(id),
                    nombre          TEXT NOT NULL,
                    ruta_json       TEXT NOT NULL,
                    preview_png     TEXT,
                    es_predefinida  INTEGER NOT NULL DEFAULT 0,
                    creado_en       TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS sesiones_foto (
                    id              INTEGER PRIMARY KEY AUTOINCREMENT,
                    evento_id       INTEGER NOT NULL REFERENCES eventos(id),
                    timestamp       TEXT NOT NULL,
                    fotos_tomadas   INTEGER NOT NULL DEFAULT 0,
                    fotos_elegidas  TEXT,
                    impresa         INTEGER NOT NULL DEFAULT 0,
                    ruta_tira       TEXT
                );

                CREATE TABLE IF NOT EXISTS fotos (
                    id              INTEGER PRIMARY KEY AUTOINCREMENT,
                    sesion_id       INTEGER NOT NULL REFERENCES sesiones_foto(id),
                    ruta            TEXT NOT NULL,
                    indice          INTEGER NOT NULL,
                    elegida         INTEGER NOT NULL DEFAULT 0
                );

                CREATE TABLE IF NOT EXISTS impresiones (
                    id              INTEGER PRIMARY KEY AUTOINCREMENT,
                    sesion_id       INTEGER NOT NULL REFERENCES sesiones_foto(id),
                    timestamp       TEXT NOT NULL,
                    impresora       TEXT,
                    copias          INTEGER NOT NULL DEFAULT 1,
                    estado          TEXT NOT NULL DEFAULT 'pendiente'
                );

                CREATE TABLE IF NOT EXISTS configuracion (
                    clave           TEXT PRIMARY KEY,
                    valor           TEXT
                );

                CREATE TABLE IF NOT EXISTS cola_impresion (
                    id          INTEGER PRIMARY KEY AUTOINCREMENT,
                    evento_id   INTEGER NOT NULL REFERENCES eventos(id),
                    sesion_id   INTEGER,
                    ruta_tira   TEXT NOT NULL,
                    creado_en   TEXT NOT NULL
                );

                CREATE INDEX IF NOT EXISTS idx_eventos_usuario ON eventos(usuario_id);
                CREATE INDEX IF NOT EXISTS idx_sesiones_evento ON sesiones_foto(evento_id);
                CREATE INDEX IF NOT EXISTS idx_fotos_sesion ON fotos(sesion_id);
                CREATE INDEX IF NOT EXISTS idx_cola_evento ON cola_impresion(evento_id);
            """)

    # ── Super admin ────────────────────────────────────────────────────────────

    def _crear_super_admin(self):
        with self._conn() as conn:
            exists = conn.execute(
                "SELECT id FROM usuarios WHERE email = ?", (SUPER_ADMIN_EMAIL,)
            ).fetchone()
            if not exists:
                temp_password = secrets.token_urlsafe(16)
                conn.execute(
                    "INSERT INTO usuarios (uuid, email, password_hash, nombre, rol, creado_en) VALUES (?,?,?,?,?,?)",
                    (str(uuid.uuid4()), SUPER_ADMIN_EMAIL, _hash(temp_password),
                     SUPER_ADMIN_NOMBRE, "super_admin", datetime.now().isoformat()),
                )
                import os
                print("=" * 60)
                print("✅ Super Admin creado — GUARDÁ ESTA CONTRASEÑA")
                print(f"   Email   : {SUPER_ADMIN_EMAIL}")
                print(f"   Password: {temp_password}")
                print("=" * 60)
                # Guardar en archivo de primer arranque junto a la DB
                try:
                    first_run = os.path.join(os.path.dirname(DATABASE_PATH), "PRIMERA_VEZ.txt")
                    with open(first_run, "w", encoding="utf-8") as f:
                        f.write(f"PhotoBooth - Credenciales iniciales\n")
                        f.write(f"Email   : {SUPER_ADMIN_EMAIL}\n")
                        f.write(f"Password: {temp_password}\n")
                        f.write(f"\nEliminá este archivo después de cambiar la contraseña.\n")
                except Exception:
                    pass

    # ── Usuarios ───────────────────────────────────────────────────────────────

    def autenticar_usuario(self, email: str, password: str) -> Optional[dict]:
        with self._conn() as conn:
            row = conn.execute(
                "SELECT * FROM usuarios WHERE email = ? AND password_hash = ? AND activo = 1",
                (email.strip().lower(), _hash(password)),
            ).fetchone()
            return dict(row) if row else None

    def crear_usuario(self, email: str, password: str, nombre: str, rol: str, admin_id: int) -> int:
        with self._conn() as conn:
            cur = conn.execute(
                "INSERT INTO usuarios (uuid, email, password_hash, nombre, rol, admin_id, creado_en) VALUES (?,?,?,?,?,?,?)",
                (str(uuid.uuid4()), email.strip().lower(), _hash(password),
                 nombre, rol, admin_id, datetime.now().isoformat()),
            )
            return cur.lastrowid

    def obtener_usuario(self, usuario_id: int) -> Optional[dict]:
        with self._conn() as conn:
            row = conn.execute("SELECT * FROM usuarios WHERE id = ?", (usuario_id,)).fetchone()
            return dict(row) if row else None

    def listar_usuarios(self, admin_id: int) -> list:
        with self._conn() as conn:
            rows = conn.execute(
                "SELECT * FROM usuarios WHERE admin_id = ? OR id = ? ORDER BY nombre",
                (admin_id, admin_id),
            ).fetchall()
            return [dict(r) for r in rows]

    # ── Eventos ────────────────────────────────────────────────────────────────

    def crear_evento(self, usuario_id: int, nombre: str, fecha_evento: str = None) -> int:
        with self._conn() as conn:
            cur = conn.execute(
                "INSERT INTO eventos (usuario_id, nombre, fecha_evento, creado_en) VALUES (?,?,?,?)",
                (usuario_id, nombre, fecha_evento, datetime.now().isoformat()),
            )
            return cur.lastrowid

    def actualizar_evento(self, evento_id: int, **kwargs) -> None:
        campos = {k: v for k, v in kwargs.items()
                  if k in ("nombre", "fecha_evento", "formato", "camara_index",
                            "plantilla_id", "impresora", "copias", "activo",
                            "modo_salida", "ruta_digital", "logo_branding",
                            "papel_size", "escala_impresion", "color_modo")}
        if not campos:
            return
        sets = ", ".join(f"{k} = ?" for k in campos)
        with self._conn() as conn:
            conn.execute(
                f"UPDATE eventos SET {sets} WHERE id = ?",
                (*campos.values(), evento_id),
            )

    def obtener_evento(self, evento_id: int) -> Optional[dict]:
        with self._conn() as conn:
            row = conn.execute("SELECT * FROM eventos WHERE id = ?", (evento_id,)).fetchone()
            return dict(row) if row else None

    def listar_eventos(self, usuario_id: int) -> list:
        with self._conn() as conn:
            rows = conn.execute(
                "SELECT * FROM eventos WHERE usuario_id = ? AND activo = 1 ORDER BY creado_en DESC",
                (usuario_id,),
            ).fetchall()
            return [dict(r) for r in rows]

    def eliminar_evento(self, evento_id: int) -> None:
        with self._conn() as conn:
            conn.execute("UPDATE eventos SET activo = 0 WHERE id = ?", (evento_id,))

    # ── Plantillas ─────────────────────────────────────────────────────────────

    def crear_plantilla(self, usuario_id: int, nombre: str, ruta_json: str,
                        preview_png: str = None, es_predefinida: bool = False) -> int:
        with self._conn() as conn:
            cur = conn.execute(
                "INSERT INTO plantillas (usuario_id, nombre, ruta_json, preview_png, es_predefinida, creado_en) VALUES (?,?,?,?,?,?)",
                (usuario_id, nombre, ruta_json, preview_png, int(es_predefinida), datetime.now().isoformat()),
            )
            return cur.lastrowid

    def listar_plantillas(self, usuario_id: int) -> list:
        with self._conn() as conn:
            rows = conn.execute(
                "SELECT * FROM plantillas WHERE usuario_id = ? OR es_predefinida = 1 ORDER BY es_predefinida DESC, nombre",
                (usuario_id,),
            ).fetchall()
            return [dict(r) for r in rows]

    def obtener_plantilla(self, plantilla_id: int) -> Optional[dict]:
        with self._conn() as conn:
            row = conn.execute("SELECT * FROM plantillas WHERE id = ?", (plantilla_id,)).fetchone()
            return dict(row) if row else None

    # ── Sesiones de foto ───────────────────────────────────────────────────────

    def crear_sesion(self, evento_id: int) -> int:
        with self._conn() as conn:
            cur = conn.execute(
                "INSERT INTO sesiones_foto (evento_id, timestamp) VALUES (?,?)",
                (evento_id, datetime.now().isoformat()),
            )
            return cur.lastrowid

    def registrar_foto(self, sesion_id: int, ruta: str, indice: int) -> int:
        with self._conn() as conn:
            cur = conn.execute(
                "INSERT INTO fotos (sesion_id, ruta, indice) VALUES (?,?,?)",
                (sesion_id, ruta, indice),
            )
            conn.execute(
                "UPDATE sesiones_foto SET fotos_tomadas = fotos_tomadas + 1 WHERE id = ?",
                (sesion_id,),
            )
            return cur.lastrowid

    def marcar_fotos_elegidas(self, sesion_id: int, indices: list, ruta_tira: str = None) -> None:
        with self._conn() as conn:
            conn.execute("UPDATE fotos SET elegida = 0 WHERE sesion_id = ?", (sesion_id,))
            for idx in indices:
                conn.execute(
                    "UPDATE fotos SET elegida = 1 WHERE sesion_id = ? AND indice = ?",
                    (sesion_id, idx),
                )
            conn.execute(
                "UPDATE sesiones_foto SET fotos_elegidas = ?, ruta_tira = ? WHERE id = ?",
                (",".join(str(i) for i in indices), ruta_tira, sesion_id),
            )

    def obtener_fotos_sesion(self, sesion_id: int) -> list:
        with self._conn() as conn:
            rows = conn.execute(
                "SELECT * FROM fotos WHERE sesion_id = ? ORDER BY indice",
                (sesion_id,),
            ).fetchall()
            return [dict(r) for r in rows]

    def eliminar_sesion(self, sesion_id: int) -> None:
        with self._conn() as conn:
            conn.execute("DELETE FROM impresiones WHERE sesion_id = ?", (sesion_id,))
            conn.execute("DELETE FROM fotos WHERE sesion_id = ?", (sesion_id,))
            conn.execute("DELETE FROM sesiones_foto WHERE id = ?", (sesion_id,))

    def registrar_impresion(self, sesion_id: int, impresora: str, copias: int = 1) -> int:
        with self._conn() as conn:
            cur = conn.execute(
                "INSERT INTO impresiones (sesion_id, timestamp, impresora, copias) VALUES (?,?,?,?)",
                (sesion_id, datetime.now().isoformat(), impresora, copias),
            )
            conn.execute(
                "UPDATE sesiones_foto SET impresa = 1 WHERE id = ?", (sesion_id,)
            )
            return cur.lastrowid

    def actualizar_estado_impresion(self, impresion_id: int, estado: str) -> None:
        with self._conn() as conn:
            conn.execute(
                "UPDATE impresiones SET estado = ? WHERE id = ?", (estado, impresion_id)
            )

    def listar_sesiones_evento(self, evento_id: int) -> list:
        with self._conn() as conn:
            rows = conn.execute(
                "SELECT * FROM sesiones_foto WHERE evento_id = ? ORDER BY timestamp DESC",
                (evento_id,),
            ).fetchall()
            return [dict(r) for r in rows]

    # ── Configuración ──────────────────────────────────────────────────────────

    def get_config(self, clave: str, default=None):
        with self._conn() as conn:
            row = conn.execute("SELECT valor FROM configuracion WHERE clave = ?", (clave,)).fetchone()
            return row["valor"] if row else default

    def set_config(self, clave: str, valor: str) -> None:
        with self._conn() as conn:
            conn.execute(
                "INSERT INTO configuracion (clave, valor) VALUES (?,?) ON CONFLICT(clave) DO UPDATE SET valor=excluded.valor",
                (clave, valor),
            )

    def contar_sesiones_total(self) -> int:
        """Total de sesiones creadas en toda la DB (para límite trial)."""
        with self._conn() as conn:
            row = conn.execute("SELECT COUNT(*) as n FROM sesiones_foto").fetchone()
            return row["n"] if row else 0

    # ── Estadísticas ───────────────────────────────────────────────────────────

    # ── Cola de impresión inteligente ──────────────────────────────────────────

    def cola_agregar(self, evento_id: int, sesion_id: int | None, ruta_tira: str) -> int:
        with self._conn() as conn:
            cur = conn.execute(
                "INSERT INTO cola_impresion (evento_id, sesion_id, ruta_tira, creado_en) VALUES (?,?,?,?)",
                (evento_id, sesion_id, ruta_tira, datetime.now().isoformat()),
            )
            return cur.lastrowid

    def cola_pendiente(self, evento_id: int) -> dict | None:
        """Devuelve el item más antiguo de la cola para este evento, o None."""
        with self._conn() as conn:
            row = conn.execute(
                "SELECT * FROM cola_impresion WHERE evento_id = ? ORDER BY id ASC LIMIT 1",
                (evento_id,),
            ).fetchone()
            return dict(row) if row else None

    def cola_todos(self, evento_id: int) -> list[dict]:
        with self._conn() as conn:
            rows = conn.execute(
                "SELECT * FROM cola_impresion WHERE evento_id = ? ORDER BY id ASC",
                (evento_id,),
            ).fetchall()
            return [dict(r) for r in rows]

    def cola_count(self, evento_id: int) -> int:
        with self._conn() as conn:
            row = conn.execute(
                "SELECT COUNT(*) as n FROM cola_impresion WHERE evento_id = ?",
                (evento_id,),
            ).fetchone()
            return row["n"]

    def cola_eliminar(self, cola_id: int) -> None:
        with self._conn() as conn:
            conn.execute("DELETE FROM cola_impresion WHERE id = ?", (cola_id,))

    # ── Estadísticas ───────────────────────────────────────────────────────────

    def stats_evento(self, evento_id: int) -> dict:
        with self._conn() as conn:
            sesiones = conn.execute(
                "SELECT COUNT(*) as total, SUM(impresa) as impresas FROM sesiones_foto WHERE evento_id = ?",
                (evento_id,),
            ).fetchone()
            return {
                "sesiones": sesiones["total"] or 0,
                "impresas": sesiones["impresas"] or 0,
            }
