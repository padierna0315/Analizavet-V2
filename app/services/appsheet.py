import httpx
from typing import List, Optional
from pydantic import BaseModel, Field
from app.config import settings

class AppSheetPatient(BaseModel):
    session_code: str = Field(default="", alias="Codigo_Corto")
    vet_name: str = Field(default="", alias="Doctora")
    category: str = Field(default="", alias="Categoria_Examen")
    test_type: str = Field(default="", alias="Examen_Especifico")
    name: str = Field(default="", alias="Nombre_Mascota")
    species: str = Field(default="", alias="Especie")
    gender: str = Field(default="", alias="Sexo")
    age_number: str = Field(default="", alias="Edad_Numero")
    age_unit: str = Field(default="", alias="Edad_Unidad")
    owner_name: str = Field(default="", alias="Nombre_Tutor")
    breed: str = Field(default="", alias="Raza")

    class Config:
        populate_by_name = True

class AppSheetService:
    def __init__(self, api_key: Optional[str] = None, app_id: Optional[str] = None):
        self.api_key = api_key or settings.get("APPSHEET_API_KEY")
        self.app_id = app_id or settings.get("APPSHEET_APP_ID")
        self.table_name = settings.get("APPSHEET_TABLE_NAME", "Muestras_Activas")
        self.base_url = f"https://api.appsheet.com/api/v2/apps/{self.app_id}/tables/{self.table_name}/Action"

    async def fetch_active_patients(self) -> List[AppSheetPatient]:
        if not self.api_key or not self.app_id:
            raise ValueError("APPSHEET_API_KEY and APPSHEET_APP_ID must be configured")

        headers = {
            "ApplicationAccessKey": self.api_key,
            "Content-Type": "application/json"
        }
        
        payload = {
            "Action": "Find",
            "Properties": {
                "Locale": "es-CO",
                "Timezone": "SA Pacific Standard Time"
            },
            "Rows": []
        }

        async with httpx.AsyncClient() as client:
            response = await client.post(
                self.base_url,
                headers=headers,
                json=payload,
                timeout=30.0
            )
            response.raise_for_status()
            data = response.json()
            
            # AppSheet returns a list of rows
            if not isinstance(data, list):
                # Sometimes AppSheet returns a dict with "Rows" or similar depending on the exact action
                # but usually "Find" returns a list directly or a list inside a key.
                # Based on user info, it's a list of patients.
                if isinstance(data, dict) and "Rows" in data:
                    data = data["Rows"]
                else:
                    return []

            return [AppSheetPatient(**row) for row in data]
