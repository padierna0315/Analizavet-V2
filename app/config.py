from dynaconf import Dynaconf
from pathlib import Path

# Definimos el directorio raíz (donde vive app/ y settings.toml)
BASE_DIR = Path(__file__).resolve().parent.parent

settings = Dynaconf(
    envvar_prefix="ANALIZAVET",
    settings_files=[
        str(BASE_DIR / "settings.toml"),
        str(BASE_DIR / ".secrets.toml")
    ],
    # Dynaconf environments support
    environments=True,
    env_switcher="ANALIZAVET_ENV",
    default_env="default",
    # AppSheet Integration Defaults
    APPSHEET_API_KEY=None,
    APPSHEET_APP_ID=None,
    APPSHEET_TABLE_NAME="Muestras_Activas",
)
