"""Modelos de entrada de la API, con mensajes de validación en español."""

import re
from typing import Any

from pydantic import BaseModel, ConfigDict, field_validator, model_validator

CORREO_RE = re.compile(
    r"^[a-z0-9.!#$%&'*+/=?^_`{|}~-]+"
    r"@[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?(?:\.[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?)+$"
)

LARGO_CORREO = 256
LARGO_NOMBRE = 100
LARGO_APELLIDO = 100
LARGO_GERENCIA = 150
LARGO_NOMBRE_ADMIN = 150
# Valores de core.UsuariosEntel.Cliente (v12).
CLIENTES = ("Entel", "MiraGroup", "Otro")


def normalizar_correo(valor: str) -> str:
    return valor.strip().lower()


def _a_texto(v: Any) -> str:
    if v is None:
        return ""
    if not isinstance(v, str):
        raise ValueError("Debe ser texto.")
    return v.strip()


class _DatosUsuario(BaseModel):
    # validate_default: un campo ausente también pasa por su validador (p. ej. «El cliente es obligatorio»).
    model_config = ConfigDict(extra="ignore", validate_default=True)

    nombre: str = ""
    apellido: str = ""
    gerencia: str = ""
    cliente: str = ""
    portal1: bool = False
    portal2: bool = False
    portal3: bool = False

    @field_validator("nombre", "apellido", "gerencia", mode="before")
    @classmethod
    def _texto(cls, v: Any) -> str:
        return _a_texto(v)

    @field_validator("nombre")
    @classmethod
    def _nombre(cls, v: str) -> str:
        if not v:
            raise ValueError("El nombre es obligatorio.")
        if len(v) > LARGO_NOMBRE:
            raise ValueError(f"El nombre no puede superar {LARGO_NOMBRE} caracteres.")
        return v

    @field_validator("apellido")
    @classmethod
    def _apellido(cls, v: str) -> str:
        if len(v) > LARGO_APELLIDO:
            raise ValueError(f"El apellido no puede superar {LARGO_APELLIDO} caracteres.")
        return v

    @field_validator("gerencia")
    @classmethod
    def _gerencia(cls, v: str) -> str:
        if not v:
            raise ValueError("La gerencia es obligatoria.")
        if len(v) > LARGO_GERENCIA:
            raise ValueError(f"La gerencia no puede superar {LARGO_GERENCIA} caracteres.")
        return v

    @field_validator("cliente", mode="before")
    @classmethod
    def _cliente(cls, v: Any) -> str:
        texto = _a_texto(v)
        if not texto:
            raise ValueError("El cliente es obligatorio.")
        canonico = next((c for c in CLIENTES if c.casefold() == texto.casefold()), None)
        if canonico is None:
            raise ValueError("El cliente debe ser Entel, MiraGroup u Otro.")
        return canonico

    @model_validator(mode="after")
    def _al_menos_un_portal(self):
        if not (self.portal1 or self.portal2 or self.portal3):
            raise ValueError("Debes marcar al menos un portal.")
        return self


def _validar_correo(v: Any) -> str:
    correo = normalizar_correo(_a_texto(v))
    if not correo:
        raise ValueError("El correo es obligatorio.")
    if len(correo) > LARGO_CORREO:
        raise ValueError(f"El correo no puede superar {LARGO_CORREO} caracteres.")
    if not CORREO_RE.match(correo):
        raise ValueError("El correo no tiene un formato válido.")
    return correo


def _clave(v: Any) -> str:
    """Las contraseñas no se recortan: los espacios cuentan."""
    if v is None:
        return ""
    if not isinstance(v, str):
        raise ValueError("Debe ser texto.")
    return v


class UsuarioCrear(_DatosUsuario):
    correo: str = ""

    @field_validator("correo", mode="before")
    @classmethod
    def _correo(cls, v: Any) -> str:
        return _validar_correo(v)


class UsuarioEditar(_DatosUsuario):
    """El correo no se edita: si viene en el cuerpo, se ignora."""


# ---------------------------------------------------------------------------
# Login y administradores (v12)
# ---------------------------------------------------------------------------

class _ConClaves(BaseModel):
    # validate_default: un campo ausente también pasa por su validador (p. ej. «El cliente es obligatorio»).
    model_config = ConfigDict(extra="ignore", validate_default=True)


class Ingreso(_ConClaves):
    correo: str = ""
    contrasena: str = ""

    @field_validator("correo", mode="before")
    @classmethod
    def _correo(cls, v: Any) -> str:
        # Sin validar el formato: un correo raro solo debe dar «Correo o contraseña incorrectos».
        return normalizar_correo(_a_texto(v))[:LARGO_CORREO]

    @field_validator("contrasena", mode="before")
    @classmethod
    def _contrasena(cls, v: Any) -> str:
        return _clave(v)


class CambioContrasena(_ConClaves):
    actual: str = ""
    nueva: str = ""
    confirmacion: str = ""

    @field_validator("actual", "nueva", "confirmacion", mode="before")
    @classmethod
    def _claves(cls, v: Any) -> str:
        return _clave(v)


class VerificarAdministrador(_ConClaves):
    contrasena: str = ""

    @field_validator("contrasena", mode="before")
    @classmethod
    def _contrasena(cls, v: Any) -> str:
        return _clave(v)


class AdministradorEditar(_ConClaves):
    """Ficha de un administrador. La contraseña nueva es opcional (vacía = no se cambia)."""

    permiso: str = ""
    nombre: str = ""
    correo: str = ""
    nuevaContrasena: str = ""
    confirmacion: str = ""

    @field_validator("permiso", mode="before")
    @classmethod
    def _permiso(cls, v: Any) -> str:
        return v if isinstance(v, str) else ""

    @field_validator("nombre", mode="before")
    @classmethod
    def _nombre(cls, v: Any) -> str:
        nombre = _a_texto(v)
        if not nombre:
            raise ValueError("El nombre es obligatorio.")
        if len(nombre) > LARGO_NOMBRE_ADMIN:
            raise ValueError(f"El nombre no puede superar {LARGO_NOMBRE_ADMIN} caracteres.")
        return nombre

    @field_validator("correo", mode="before")
    @classmethod
    def _correo(cls, v: Any) -> str:
        return _validar_correo(v)

    @field_validator("nuevaContrasena", "confirmacion", mode="before")
    @classmethod
    def _claves(cls, v: Any) -> str:
        return _clave(v)
