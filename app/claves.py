"""Contraseñas de los administradores: hash, verificación en tiempo constante y política.

Dos algoritmos (columna AlgoritmoHash de core.AdministradoresPortal):
  SHA2_512       los crea SQL (core.sp_CrearAdministrador / sp_RestablecerContrasenaAdmin):
                 HASHBYTES('SHA2_512', Sal + CAST(N'clave' AS VARBINARY)) = SHA-512(sal || clave en UTF-16LE).
  PBKDF2_SHA256  el que usa Portal3 al cambiar una contraseña: PBKDF2-HMAC-SHA256, 600.000 iteraciones,
                 sal de 32 bytes, 32 bytes de salida.
"""

import hashlib
import hmac
import re
import secrets

ALGORITMO_SQL = "SHA2_512"
ALGORITMO_APP = "PBKDF2_SHA256"
ITERACIONES_PBKDF2 = 600_000
LARGO_SAL = 32

# La que ponen los procedimientos de SQL al crear o restablecer un administrador.
CONTRASENA_POR_DEFECTO = "Admin@123456"
LARGO_MINIMO = 10
# Tope para que nadie pueda hacer calcular hashes de textos enormes.
LARGO_MAXIMO = 128

# Sal fija para gastar el mismo tiempo cuando el correo no existe (no revela qué correos son administradores).
_SAL_RELLENO = b"\x00" * LARGO_SAL


def calcular(algoritmo: str, clave: str, sal: bytes) -> bytes:
    if algoritmo == ALGORITMO_SQL:
        return hashlib.sha512(sal + clave.encode("utf-16-le")).digest()
    if algoritmo == ALGORITMO_APP:
        return hashlib.pbkdf2_hmac("sha256", clave.encode("utf-8"), sal, ITERACIONES_PBKDF2)
    raise ValueError("Algoritmo de contraseña desconocido")


def verificar(algoritmo: str, clave: str, sal: bytes, esperado: bytes) -> bool:
    """True si la clave corresponde al hash guardado. Un algoritmo desconocido nunca verifica."""
    if not clave or len(clave) > LARGO_MAXIMO or not sal or not esperado:
        return False
    try:
        calculado = calcular(algoritmo, clave, sal)
    except ValueError:
        return False
    return hmac.compare_digest(calculado, esperado)


def gastar_tiempo(clave: str) -> None:
    """Calcula un hash que se descarta, con el mismo costo que una verificación PBKDF2."""
    calcular(ALGORITMO_APP, (clave or "")[:LARGO_MAXIMO], _SAL_RELLENO)


def nuevo_hash(clave: str) -> tuple[bytes, bytes, str]:
    """(hash, sal, algoritmo) para guardar una contraseña nueva."""
    sal = secrets.token_bytes(LARGO_SAL)
    return calcular(ALGORITMO_APP, clave, sal), sal, ALGORITMO_APP


def error_politica(nueva: str) -> str | None:
    """Mensaje del primer requisito que no cumple la contraseña nueva, o None si está bien."""
    if len(nueva) < LARGO_MINIMO:
        return f"La contraseña debe tener al menos {LARGO_MINIMO} caracteres."
    if len(nueva) > LARGO_MAXIMO:
        return f"La contraseña no puede superar {LARGO_MAXIMO} caracteres."
    if not re.search(r"[A-ZÁÉÍÓÚÑÜ]", nueva):
        return "La contraseña debe tener al menos una mayúscula."
    if not re.search(r"[a-záéíóúñü]", nueva):
        return "La contraseña debe tener al menos una minúscula."
    if not re.search(r"[0-9]", nueva):
        return "La contraseña debe tener al menos un número."
    if not re.search(r"[^A-Za-z0-9ÁÉÍÓÚÑÜáéíóúñü\s]", nueva):
        return "La contraseña debe tener al menos un símbolo."
    if nueva == CONTRASENA_POR_DEFECTO:
        return "No puedes usar la contraseña por defecto."
    return None
