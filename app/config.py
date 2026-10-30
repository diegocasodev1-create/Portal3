"""Configuración de la app, leída desde variables de entorno (o .env en desarrollo)."""

from functools import lru_cache
from urllib.parse import urlparse

from pydantic import SecretStr, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    sql_server: str = ""
    sql_database: str = ""
    sql_user: str = ""
    sql_password: SecretStr = SecretStr("")

    # Portal Externo (Power Pages): solo para el enlace del correo de bienvenida (v12: ya no da acceso a esta app).
    portal_base_url: str = "https://miragroup-portal-externo.powerappsportals.com"

    # Sitio Energía (Power Pages): su clave pública valida los tokens de los latidos de Energía.
    energia_portal_url: str = "https://portalenergia.powerappsportals.com"
    # Orígenes (separados por coma) que pueden llamar a POST /api/latido desde el navegador.
    latido_origins: str = (
        "https://portalenergia.powerappsportals.com,https://site-oaciopruebas2.powerappsportals.com"
    )

    # Firma la cookie de sesión y los permisos de edición de /administradores.
    session_secret: SecretStr
    # Expiración por inactividad: cada request válido renueva la cookie.
    session_max_age_min: int = 60

    graph_tenant_id: str = "e3112796-84de-4e46-a7d3-3a113c51a3bc"
    graph_client_id: str = ""
    graph_client_secret: SecretStr = SecretStr("")
    mail_sender: str = "no-reply@miragroup.cl"
    mail_enabled: bool = False

    # Microsoft Entra External ID (tenant "MiraGroup Externos"): cuentas de acceso al portal.
    extid_enabled: bool = False
    extid_tenant_id: str = ""
    extid_client_id: str = ""
    extid_client_secret: SecretStr = SecretStr("")
    extid_domain: str = ""

    log_level: str = "INFO"

    @field_validator("portal_base_url", "energia_portal_url")
    @classmethod
    def _sin_barra_final(cls, v: str) -> str:
        return v.strip().rstrip("/")

    @field_validator("session_secret")
    @classmethod
    def _secreto_largo(cls, v: SecretStr) -> SecretStr:
        if len(v.get_secret_value()) < 32:
            raise ValueError("SESSION_SECRET debe tener al menos 32 caracteres.")
        return v

    @property
    def energia_host(self) -> str:
        return (urlparse(self.energia_portal_url).hostname or "").lower()

    @property
    def latido_origenes(self) -> frozenset[str]:
        return frozenset(o.strip().rstrip("/").lower() for o in self.latido_origins.split(",") if o.strip())

    @property
    def session_max_age_s(self) -> int:
        return self.session_max_age_min * 60


@lru_cache
def get_settings() -> Settings:
    return Settings()
