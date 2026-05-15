"""
Registry of standardized veterinary medical parameters and reference ranges.
Source: Estandarización de Parámetros Veterinarios Máquinas.md
"""

from typing import Dict, Any, Optional
import json
import os
from pathlib import Path
from copy import deepcopy

import unicodedata
import re

# Master Registry of Veterinary Standards (Factory Defaults)
_DEFAULT_VETERINARY_STANDARDS: Dict[str, Dict[str, Any]] = {
    # ============================================================
    # LÍNEA ROJA (Red Blood Cell Series)
    # ============================================================
    'RBC': {
        'name': 'Eritrocitos',
        'unit': 'x10^6/µL',
        'ranges': {
            'canine': {'min': 5.65, 'max': 8.87},
            'feline': {'min': 6.54, 'max': 12.20}
        },
        'short_name': 'Eritrocitos'
    },
    'HGB': {
        'name': 'Hemoglobina',
        'unit': 'g/L',
        'ranges': {
            'canine': {'min': 131.00, 'max': 205.00},
            'feline': {'min': 98.00, 'max': 162.00}
        },
        'short_name': 'Hemoglobina'
    },
    'HCT': {
        'name': 'Hematocrito',
        'unit': '%',
        'ranges': {
            'canine': {'min': 37.30, 'max': 61.70},
            'feline': {'min': 30.30, 'max': 52.30}
        },
        'short_name': 'Hematocrito'
    },
    'MCV': {
        'name': 'Volumen Corpuscular Medio',
        'unit': 'fL',
        'ranges': {
            'canine': {'min': 61.60, 'max': 73.50},
            'feline': {'min': 35.90, 'max': 53.10}
        },
        'short_name': 'Volumen_Corpuscular_Medio'
    },
    'MCH': {
        'name': 'Hemoglobina Corpuscular Media',
        'unit': 'pg',
        'ranges': {
            'canine': {'min': 21.20, 'max': 25.90},
            'feline': {'min': 11.80, 'max': 17.30}
        },
        'short_name': 'Hemoglobina_Corpuscular_Media'
    },
    'MCHC': {
        'name': 'Concentración de Hemoglobina Corpuscular Media',
        'unit': 'g/L',
        'ranges': {
            'canine': {'min': 320.00, 'max': 379.00},
            'feline': {'min': 281.00, 'max': 358.00}
        },
        'short_name': 'Concentracion_Hemoglobina_Corpuscular_Media'
    },
    'RDW-CV': {
        'name': 'Amplitud de Distribución Eritrocitaria (coeficiente de variación)',
        'unit': '%',
        'ranges': {
            'canine': {'min': 11.20, 'max': 17.10},
            'feline': {'min': 20.90, 'max': 33.60}
        },
        'short_name': 'RDW_CV'
    },
    'RDW-SD': {
        'name': 'Amplitud de Distribución Eritrocitaria (desviación estándar)',
        'unit': 'fL',
        'ranges': {
            'canine': {'min': 25.60, 'max': 41.60},
            'feline': {'min': 16.00, 'max': 27.40}
        },
        'short_name': 'RDW_SD'
    },
    'HDW-CV': {
        'name': 'Ancho de Distribución de Hemoglobina (Coeficiente de Variación)',
        'unit': '%',
        'ranges': {
            'canine': {'min': 7.00, 'max': 20.00},
            'feline': {'min': 7.00, 'max': 30.00}
        },
        'short_name': 'HDW_CV'
    },
    'HDW-SD': {
        'name': 'Ancho de Distribución de Hemoglobina (Desviación Estándar)',
        'unit': 'pg',
        'ranges': {
            'canine': {'min': 2.00, 'max': 8.00},
            'feline': {'min': 2.00, 'max': 8.00}
        },
        'short_name': 'HDW_SD'
    },

    # ============================================================
    # MORFOLOGÍA AVANZADA / REGENERACIÓN
    # ============================================================
    'RET#': {
        'name': 'Reticulocitos Absolutos',
        'unit': 'x10^3/µL',
        'ranges': {
            'canine': {'min': 3.00, 'max': 110.00},
            'feline': {'min': 3.00, 'max': 50.00}
        },
        'short_name': 'Reticulocitos'
    },
    'RET%': {
        'name': 'Reticulocitos %',
        'unit': '%',
        'ranges': {
            'canine': {'min': 0.00, 'max': 1.50},
            'feline': {'min': 0.00, 'max': 1.00}
        },
        'short_name': 'Reticulocitos_Pct'
    },
    'ETG#': {
        'name': 'Eritrocitos Fantasma',
        'unit': 'x10^3/µL',
        'ranges': {
            'canine': {'min': 0.00, 'max': 0.50},
            'feline': {'min': 0.00, 'max': 0.60}
        },
        'short_name': 'Eritrocitos_Fantasma'
    },
    'ETG%': {
        'name': 'Eritrocitos Fantasma %',
        'unit': '%',
        'ranges': {
            'canine': {'min': 0.00, 'max': 0.16},
            'feline': {'min': 0.00, 'max': 0.25}
        },
        'short_name': 'Eritrocitos_Fantasma_Pct'
    },
    'SPH#': {
        'name': 'Esferocitos',
        'unit': 'x10^3/µL',
        'ranges': {
            'canine': {'min': 0.00, 'max': 130.00},
            'feline': {'min': 0.00, 'max': 193.66}
        },
        'short_name': 'Esferocitos'
    },
    'SPH%': {
        'name': 'Esferocitos %',
        'unit': '%',
        'ranges': {
            'canine': {'min': 0.00, 'max': 1.54},
            'feline': {'min': 0.00, 'max': 2.71}
        },
        'short_name': 'Esferocitos_Pct'
    },

    # ============================================================
    # LÍNEA BLANCA (White Blood Cell Series — 7-part)
    # ============================================================
    'WBC': {
        'name': 'Leucocitos',
        'unit': 'x10^3/µL',
        'ranges': {
            'canine': {'min': 5.05, 'max': 16.76},
            'feline': {'min': 2.8, 'max': 17.0}
        },
        'short_name': 'Leucocitos'
    },
    'NEU#': {
        'name': 'Neutrófilos',
        'unit': 'x10^3/µL',
        'ranges': {
            'canine': {'min': 2.95, 'max': 11.64},
            'feline': {'min': 2.30, 'max': 10.29}
        },
        'short_name': 'Neutrofilos'
    },
    'NEU%': {
        'name': 'Neutrófilos %',
        'unit': '%',
        'ranges': {
            'canine': {'min': 52.00, 'max': 78.00},
            'feline': {'min': 38.00, 'max': 80.00}
        },
        'short_name': 'Neutrofilos_Pct'
    },
    'NST#': {
        'name': 'Neutrófilos en Banda',
        'unit': 'x10^3/µL',
        'ranges': {
            'canine': {'min': 0.00, 'max': 0.80},
            'feline': {'min': 0.00, 'max': 0.80}
        },
        'short_name': 'Neutrofilos_Banda'
    },
    'NST/WBC%': {
        'name': 'Relación bandas/Leucocitos totales %',
        'unit': '%',
        'ranges': {
            'canine': {'min': 0.00, 'max': 10.00},
            'feline': {'min': 0.00, 'max': 10.00}
        },
        'short_name': 'Bandas_Leucocitos_Pct'
    },
    'NST/NEU%': {
        'name': 'Relación bandas/Neutrófilos totales %',
        'unit': '%',
        'ranges': {
            'canine': {'min': 0.00, 'max': 20.00},
            'feline': {'min': 0.00, 'max': 15.00}
        },
        'short_name': 'Bandas_Neutrofilos_Pct'
    },
    'NSG#': {
        'name': 'Neutrófilos Segmentados',
        'unit': 'x10^3/µL',
        'ranges': {
            'canine': {'min': 2.50, 'max': 11.30},
            'feline': {'min': 2.30, 'max': 12.50}
        },
        'short_name': 'Neutrofilos_Segmentados'
    },
    'NSG%': {
        'name': 'Neutrófilos Segmentados %',
        'unit': '%',
        'ranges': {
            'canine': {'min': 50.00, 'max': 75.00},
            'feline': {'min': 35.00, 'max': 75.00}
        },
        'short_name': 'Neutrofilos_Segmentados_Pct'
    },
    'NSH#': {
        'name': 'Neutrófilos Hipersegmentados',
        'unit': 'x10^3/µL',
        'ranges': {
            'canine': {'min': 0.00, 'max': 0.40},
            'feline': {'min': 0.00, 'max': 0.30}
        },
        'short_name': 'Neutrofilos_Hipersegmentados'
    },
    'NSH/WBC%': {
        'name': 'Relación hipersegmentado/Leucocitos %',
        'unit': '%',
        'ranges': {
            'canine': {'min': 0.00, 'max': 5.00},
            'feline': {'min': 0.00, 'max': 3.00}
        },
        'short_name': 'Hipersegmentados_Leucocitos_Pct'
    },
    'NSH/NEU%': {
        'name': 'Relación hipersegmentado/Neutrófilos %',
        'unit': '%',
        'ranges': {
            'canine': {'min': 0.00, 'max': 7.00},
            'feline': {'min': 0.00, 'max': 4.00}
        },
        'short_name': 'Hipersegmentados_Neutrofilos_Pct'
    },
    'LYM#': {
        'name': 'Linfocitos',
        'unit': 'x10^3/µL',
        'ranges': {
            'canine': {'min': 1.05, 'max': 5.10},
            'feline': {'min': 0.92, 'max': 6.88}
        },
        'short_name': 'Linfocitos'
    },
    'LYM%': {
        'name': 'Linfocitos %',
        'unit': '%',
        'ranges': {
            'canine': {'min': 16.00, 'max': 41.50},
            'feline': {'min': 16.00, 'max': 47.50}
        },
        'short_name': 'Linfocitos_Pct'
    },
    'MON#': {
        'name': 'Monocitos',
        'unit': 'x10^3/µL',
        'ranges': {
            'canine': {'min': 0.16, 'max': 1.12},
            'feline': {'min': 0.05, 'max': 0.67}
        },
        'short_name': 'Monocitos'
    },
    'MON%': {
        'name': 'Monocitos %',
        'unit': '%',
        'ranges': {
            'canine': {'min': 1.00, 'max': 13.00},
            'feline': {'min': 1.00, 'max': 7.60}
        },
        'short_name': 'Monocitos_Pct'
    },
    'EOS#': {
        'name': 'Eosinófilos',
        'unit': 'x10^3/µL',
        'ranges': {
            'canine': {'min': 0.06, 'max': 1.23},
            'feline': {'min': 0.17, 'max': 1.57}
        },
        'short_name': 'Eosinofilos'
    },
    'EOS%': {
        'name': 'Eosinófilos %',
        'unit': '%',
        'ranges': {
            'canine': {'min': 0.50, 'max': 11.85},
            'feline': {'min': 1.00, 'max': 11.10}
        },
        'short_name': 'Eosinofilos_Pct'
    },
    'BAS#': {
        'name': 'Basófilos',
        'unit': 'x10^3/µL',
        'ranges': {
            'canine': {'min': 0.00, 'max': 0.10},
            'feline': {'min': 0.00, 'max': 0.26}
        },
        'short_name': 'Basofilos'
    },
    'BAS%': {
        'name': 'Basófilos %',
        'unit': '%',
        'ranges': {
            'canine': {'min': 0.00, 'max': 0.90},
            'feline': {'min': 0.00, 'max': 0.70}
        },
        'short_name': 'Basofilos_Pct'
    },

    # --- Parámetros adicionales de línea blanca (sin rangos establecidos) ---
    'LUC#': {
        'name': 'Grandes Células Inmaduras',
        'short_name': 'LUC',
        'unit': 'x10^3/µL',
        'ranges': {'canine': None, 'feline': None}
    },
    'LUC%': {
        'name': 'Grandes Células Inmaduras %',
        'short_name': 'LUC_Pct',
        'unit': '%',
        'ranges': {'canine': None, 'feline': None}
    },
    'IG#': {
        'name': 'Granulocitos Inmaduros',
        'short_name': 'IG',
        'unit': 'x10^3/µL',
        'ranges': {'canine': None, 'feline': None}
    },
    'IG%': {
        'name': 'Granulocitos Inmaduros %',
        'short_name': 'IG_Pct',
        'unit': '%',
        'ranges': {'canine': None, 'feline': None}
    },

    # ============================================================
    # PLAQUETAS
    # ============================================================
    'PLT': {
        'name': 'Plaquetas',
        'unit': 'x10^3/µL',
        'ranges': {
            'canine': {'min': 148.00, 'max': 484.00},
            'feline': {'min': 151.00, 'max': 600.00}
        },
        'short_name': 'Plaquetas'
    },
    'MPV': {
        'name': 'Volumen Plaquetario Medio',
        'unit': 'fL',
        'ranges': {
            'canine': {'min': 8.70, 'max': 13.20},
            'feline': {'min': 11.40, 'max': 21.60}
        },
        'short_name': 'Volumen_Plaquetario_Medio'
    },
    'PDW': {
        'name': 'Amplitud de la Distribución Plaquetaria',
        'unit': '%',
        'ranges': {
            'canine': {'min': 9.10, 'max': 19.40},
            'feline': {'min': 9.10, 'max': 19.40}
        },
        'short_name': 'Distribucion_Plaquetaria'
    },
    'PCT': {
        'name': 'Plaquetocrito',
        'unit': '%',
        'ranges': {
            'canine': {'min': 1.40, 'max': 4.60},
            'feline': {'min': 1.70, 'max': 8.60}
        },
        'short_name': 'Plaquetocrito'
    },
    'APLT#': {
        'name': 'Plaquetas Agregadas',
        'unit': 'x10^3/µL',
        'ranges': {
            'canine': {'min': 0.00, 'max': 0.15},
            'feline': {'min': 0.00, 'max': 0.15}
        },
        'short_name': 'Plaquetas_Agregadas'
    },
    'P-LCC': {
        'name': 'Recuento de Plaquetas Grandes',
        'unit': 'x10^3/µL',
        'ranges': {
            'canine': {'min': 0.00, 'max': 66.00},
            'feline': {'min': 0.00, 'max': 103.00}
        },
        'short_name': 'Plaquetas_Grandes'
    },
    'P-LCR': {
        'name': 'Relación de Plaquetas Grandes',
        'unit': '%',
        'ranges': {
            'canine': {'min': 0.00, 'max': 25.00},
            'feline': {'min': 0.00, 'max': 30.00}
        },
        'short_name': 'Relacion_Plaquetas_Grandes'
    },

    # ============================================================
    # INMUNOENSAYOS
    # ============================================================
    'cCRP': {
        'name': 'Proteína C Reactiva Canina',
        'unit': 'mg/L',
        'ranges': {
            'canine': {'min': 2.00, 'max': 8.00},
            'feline': {'min': 2.00, 'max': 8.00}
        },
        'short_name': 'PCR_Canina'
    },
    'fSAA': {
        'name': 'Amiloide A Sérico Felino',
        'unit': 'mg/L',
        'ranges': {
            'canine': None,
            'feline': {'min': 0.0, 'max': 5.0}
        },
        'short_name': 'SAA_Felino'
    },
    'cPL': {
        'name': 'Lipasa Pancreática Canina',
        'unit': 'µg/L',
        'ranges': {
            'canine': {'min': 9.10, 'max': 19.40},
            'feline': {'min': 9.10, 'max': 19.40}
        },
        'short_name': 'Lipasa_Pancreatica_Canina'
    },
    'fPL': {
        'name': 'Lipasa Pancreática Felina',
        'unit': 'µg/L',
        'ranges': {
            'canine': None,
            'feline': {'min': 0.0, 'max': 3.5}
        },
        'short_name': 'Lipasa_Pancreatica_Felina'
    },
    'cT4': {
        'name': 'Tiroxina Canina',
        'unit': 'µg/dL',
        'ranges': {
            'canine': {'min': 1.0, 'max': 4.0},
            'feline': None
        },
        'short_name': 'Tiroxina_Canina'
    },
    'fT4': {
        'name': 'Tiroxina Felina',
        'unit': 'µg/dL',
        'ranges': {
            'canine': None,
            'feline': {'min': 1.2, 'max': 4.0}
        },
        'short_name': 'Tiroxina_Felina'
    },
    'cProg': {
        'name': 'Progesterona Canina',
        'unit': 'ng/mL',
        'ranges': {
            'canine': {'min': 0.0, 'max': 1.0},
            'feline': None
        },
        'short_name': 'Progesterona_Canina'
    },
    'cNT-proBNP': {
        'name': 'Péptido Natriurético Cerebral (Canino)',
        'unit': 'pmol/L',
        'ranges': {
            'canine': {'min': 0.0, 'max': 900.0},
            'feline': None
        },
        'short_name': 'NT_proBNP_Canino'
    },
    'fNT-proBNP': {
        'name': 'Péptido Natriurético Cerebral (Felino)',
        'unit': 'pmol/L',
        'ranges': {
            'canine': None,
            'feline': {'min': 0.0, 'max': 100.0}
        },
        'short_name': 'NT_proBNP_Felino'
    },

    # ============================================================
    # MORFOLOGÍA DE ORINA
    # ============================================================
    'URBC#': {
        'name': 'Glóbulos Rojos en Orina',
        'unit': 'cél/µL',
        'ranges': {
            'canine': {'min': 0.0, 'max': 5.0},
            'feline': {'min': 0.0, 'max': 5.0}
        },
        'short_name': 'GR_Orina'
    },
    'UWBC#': {
        'name': 'Leucocitos en Orina',
        'unit': 'cél/µL',
        'ranges': {
            'canine': {'min': 0.0, 'max': 5.0},
            'feline': {'min': 0.0, 'max': 5.0}
        },
        'short_name': 'Leucocitos_Orina'
    },
    'RTE#': {
        'name': 'Células Epiteliales Renales',
        'unit': 'cél/µL',
        'ranges': {
            'canine': {'min': 0.0, 'max': 0.0},
            'feline': {'min': 0.0, 'max': 0.0}
        },
        'short_name': 'Celulas_Renales'
    },
    'SEC#': {
        'name': 'Células Escamosas',
        'unit': 'cél/µL',
        'ranges': {
            'canine': None,
            'feline': None
        },
        'short_name': 'Celulas_Escamosas'
    },
    'TEC#': {
        'name': 'Células Transicionales',
        'unit': 'cél/µL',
        'ranges': {
            'canine': None,
            'feline': None
        },
        'short_name': 'Celulas_Transicionales'
    },
    'UBAC#': {
        'name': 'Bacterias Generales en Orina',
        'unit': 'bac/µL',
        'ranges': {
            'canine': {'min': 0.0, 'max': 0.0},
            'feline': {'min': 0.0, 'max': 0.0}
        },
        'short_name': 'Bacterias_Orina'
    },
    'UCOS#': {
        'name': 'Bacterias Formadoras de Cocos en Orina',
        'unit': 'bac/µL',
        'ranges': {
            'canine': {'min': 0.0, 'max': 0.0},
            'feline': {'min': 0.0, 'max': 0.0}
        },
        'short_name': 'Cocos_Orina'
    },
    'UYEA#': {
        'name': 'Levaduras y Hongos en Orina',
        'unit': 'cél/µL',
        'ranges': {
            'canine': {'min': 0.0, 'max': 0.0},
            'feline': {'min': 0.0, 'max': 0.0}
        },
        'short_name': 'Levaduras_Orina'
    },
    'FAT#': {
        'name': 'Cuerpos Lipídicos/Grasa en Orina',
        'unit': 'cél/µL',
        'ranges': {
            'canine': None,
            'feline': None
        },
        'short_name': 'Cuerpos_Lipidicos_Orina'
    },
    'PHL#': {
        'name': 'Células Sanguíneas Alteradas en Orina',
        'unit': 'cél/µL',
        'ranges': {
            'canine': {'min': 0.0, 'max': 0.0},
            'feline': {'min': 0.0, 'max': 0.0}
        },
        'short_name': 'Celulas_Sanguineas_Alteradas_Orina'
    },

    # ============================================================
    # CRISTALES Y CILINDROS DE ORINA
    # NOTA: COD# renombrado a CODC# para evitar colisión con
    # Coccidia spp. del examen de heces.
    # ============================================================
    'MAP#': {
        'name': 'Estruvita (Fosfato Amónico Magnésico)',
        'unit': '',
        'ranges': {
            'canine': None,
            'feline': None
        },
        'short_name': 'Estruvita'
    },
    'COMC#': {
        'name': 'Oxalato de Calcio Monohidratado',
        'unit': '',
        'ranges': {
            'canine': {'min': 0.0, 'max': 0.0},
            'feline': {'min': 0.0, 'max': 0.0}
        },
        'short_name': 'Oxalato_Calcio_Mono'
    },
    'CODC#': {
        'name': 'Oxalato de Calcio Dihidratado',
        'unit': '',
        'ranges': {
            'canine': {'min': 0.00, 'max': 66.00},
            'feline': {'min': 0.00, 'max': 66.00}
        },
        'short_name': 'Oxalato_Calcio_Dihidrato'
    },
    'CP#': {
        'name': 'Fosfato de Calcio',
        'unit': '',
        'ranges': {
            'canine': {'min': 0.0, 'max': 0.0},
            'feline': {'min': 0.0, 'max': 0.0}
        },
        'short_name': 'Fosfato_Calcio'
    },
    'AUC#': {
        'name': 'Urato de Amonio',
        'unit': '',
        'ranges': {
            'canine': {'min': 0.0, 'max': 0.0},
            'feline': {'min': 0.0, 'max': 0.0}
        },
        'short_name': 'Urato_Amonio'
    },
    'CYSC#': {
        'name': 'Cistina',
        'unit': '',
        'ranges': {
            'canine': {'min': 0.0, 'max': 0.0},
            'feline': {'min': 0.0, 'max': 0.0}
        },
        'short_name': 'Cistina'
    },
    'CC#': {
        'name': 'Carbonato de Calcio',
        'unit': '',
        'ranges': {
            'canine': {'min': 0.0, 'max': 0.0},
            'feline': {'min': 0.0, 'max': 0.0}
        },
        'short_name': 'Carbonato_Calcio'
    },
    'UBilC#': {
        'name': 'Bilirrubina en Orina',
        'unit': '',
        'ranges': {
            'canine': None,
            'feline': {'min': 0.0, 'max': 0.0}
        },
        'short_name': 'Bilirrubina_Orina'
    },
    'HYA#': {
        'name': 'Cilindros Hialinos',
        'unit': '',
        'ranges': {
            'canine': None,
            'feline': None
        },
        'short_name': 'Cilindros_Hialinos'
    },
    'GRA#': {
        'name': 'Cilindros Granulosos',
        'unit': '',
        'ranges': {
            'canine': {'min': 0.0, 'max': 0.0},
            'feline': {'min': 0.0, 'max': 0.0}
        },
        'short_name': 'Cilindros_Granulosos'
    },
    'WAC#': {
        'name': 'Cilindros Leucocitarios',
        'unit': '',
        'ranges': {
            'canine': {'min': 0.0, 'max': 0.0},
            'feline': {'min': 0.0, 'max': 0.0}
        },
        'short_name': 'Cilindros_Leucocitarios'
    },
    'URBC-C#': {
        'name': 'Cilindros Eritrocíticos',
        'unit': '',
        'ranges': {
            'canine': {'min': 0.0, 'max': 0.0},
            'feline': {'min': 0.0, 'max': 0.0}
        },
        'short_name': 'Cilindros_Eritrociticos'
    },
    'RTC#': {
        'name': 'Cilindros Celulares/Renales',
        'unit': '',
        'ranges': {
            'canine': {'min': 0.0, 'max': 0.0},
            'feline': {'min': 0.0, 'max': 0.0}
        },
        'short_name': 'Cilindros_Celulares'
    },

    # ============================================================
    # COPROLÓGICOS
    # ============================================================
    'ALE#': {
        'name': 'Huevos de Nematodos',
        'unit': '',
        'ranges': {
            'canine': {'min': 0.0, 'max': 0.0},
            'feline': {'min': 0.0, 'max': 0.0}
        },
        'short_name': 'Nematodos'
    },
    'ANE#': {
        'name': 'Huevos de Ancylostoma',
        'unit': '',
        'ranges': {
            'canine': {'min': 0.0, 'max': 0.0},
            'feline': {'min': 0.0, 'max': 0.0}
        },
        'short_name': 'Ancylostoma'
    },
    'TRE#': {
        'name': 'Huevos de Trematodos',
        'unit': '',
        'ranges': {
            'canine': {'min': 0.0, 'max': 0.0},
            'feline': {'min': 0.0, 'max': 0.0}
        },
        'short_name': 'Trematodos'
    },
    'DIP#': {
        'name': 'Huevos de Diphyllobothrium',
        'unit': '',
        'ranges': {
            'canine': {'min': 0.0, 'max': 0.0},
            'feline': {'min': 0.0, 'max': 0.0}
        },
        'short_name': 'Diphyllobothrium'
    },
    'SPI#': {
        'name': 'Huevos de Spirometra',
        'unit': '',
        'ranges': {
            'canine': {'min': 0.0, 'max': 0.0},
            'feline': {'min': 0.0, 'max': 0.0}
        },
        'short_name': 'Spirometra'
    },
    'TtE#': {
        'name': 'Huevos de Trichuris trichiura',
        'unit': '',
        'ranges': {
            'canine': {'min': 0.0, 'max': 0.0},
            'feline': {'min': 0.0, 'max': 0.0}
        },
        'short_name': 'Trichuris_trichiura'
    },
    'CEE#': {
        'name': 'Huevos de Taenia',
        'unit': '',
        'ranges': {
            'canine': {'min': 0.0, 'max': 0.0},
            'feline': {'min': 0.0, 'max': 0.0}
        },
        'short_name': 'Taenia'
    },
    'TRI#': {
        'name': 'Trichomonas spp.',
        'unit': '',
        'ranges': {
            'canine': {'min': 0.0, 'max': 0.0},
            'feline': {'min': 0.0, 'max': 0.0}
        },
        'short_name': 'Trichomonas'
    },
    'FLA#': {
        'name': 'Giardia',
        'unit': '',
        'ranges': {
            'canine': {'min': 0.0, 'max': 0.0},
            'feline': {'min': 0.0, 'max': 0.0}
        },
        'short_name': 'Giardia'
    },
    'COD#': {
        'name': 'Coccidia spp.',
        'unit': '',
        'ranges': {
            'canine': {'min': 0.0, 'max': 0.0},
            'feline': {'min': 0.0, 'max': 0.0}
        },
        'short_name': 'Coccidia'
    },
    'COD0#': {
        'name': 'Coccidia spp. estadio 0',
        'unit': '',
        'ranges': {
            'canine': {'min': 0.0, 'max': 0.0},
            'feline': {'min': 0.0, 'max': 0.0}
        },
        'short_name': 'Coccidia'
    },
    'COD1#': {
        'name': 'Coccidia spp. estadio 1',
        'unit': '',
        'ranges': {
            'canine': {'min': 0.0, 'max': 0.0},
            'feline': {'min': 0.0, 'max': 0.0}
        },
        'short_name': 'Coccidia'
    },
    'COD2#': {
        'name': 'Coccidia spp. estadio 2',
        'unit': '',
        'ranges': {
            'canine': {'min': 0.0, 'max': 0.0},
            'feline': {'min': 0.0, 'max': 0.0}
        },
        'short_name': 'Coccidia'
    },
    'Tg#': {
        'name': 'Toxoplasma gondii',
        'unit': '',
        'ranges': {
            'canine': {'min': 0.0, 'max': 0.0},
            'feline': {'min': 0.0, 'max': 0.0}
        },
        'short_name': 'Toxoplasma'
    },

    # ============================================================
    # MICROBIOTA
    # ============================================================
    'COS#': {
        'name': 'Cocos',
        'unit': '',
        'ranges': {
            'canine': {'min': 20.0, 'max': 120.0},
            'feline': {'min': 20.0, 'max': 120.0}
        },
        'short_name': 'Cocos'
    },
    'BACI#': {
        'name': 'Bacilos',
        'unit': '',
        'ranges': {
            'canine': {'min': 80.0, 'max': 2200.0},
            'feline': {'min': 80.0, 'max': 2200.0}
        },
        'short_name': 'Bacilos'
    },
    'C/B#': {
        'name': 'Coco/bacilo',
        'unit': '',
        'ranges': {
            'canine': {'min': 0.01, 'max': 0.15},
            'feline': {'min': 0.01, 'max': 0.15}
        },
        'short_name': 'Coco/bacilo'
    },
    'CAM#': {
        'name': 'Campylobacter spp.',
        'unit': '',
        'ranges': {
            'canine': {'min': 0.0, 'max': 0.0},
            'feline': {'min': 0.0, 'max': 0.0}
        },
        'short_name': 'Campylobacter'
    },
    'BAC#': {
        'name': 'Bacterias',
        'unit': '',
        'ranges': {
            'canine': {'min': 0.0, 'max': 6.0},
            'feline': {'min': 0.0, 'max': 6.0}
        },
        'short_name': 'Bacterias'
    },
    'SS1#': {
        'name': 'Salmonella spp. tipo 1',
        'unit': '',
        'ranges': {
            'canine': {'min': 0.0, 'max': 0.0},
            'feline': {'min': 0.0, 'max': 0.0}
        },
        'short_name': 'Salmonella'
    },
    'SS2#': {
        'name': 'Salmonella spp. tipo 2',
        'unit': '',
        'ranges': {
            'canine': {'min': 0.0, 'max': 0.0},
            'feline': {'min': 0.0, 'max': 0.0}
        },
        'short_name': 'Salmonella'
    },
    'YEA#': {
        'name': 'Levaduras',
        'unit': '',
        'ranges': {
            'canine': {'min': 0.0, 'max': 10.0},
            'feline': {'min': 0.0, 'max': 10.0}
        },
        'short_name': 'Levaduras'
    },

    # ============================================================
    # CÉLULAS Y SANGRE
    # ============================================================
    'RBC#': {
        'name': 'Eritrocitos',
        'unit': '',
        'ranges': {
            'canine': {'min': 0.0, 'max': 0.0},
            'feline': {'min': 0.0, 'max': 0.0}
        },
        'short_name': 'Eritrocitos'
    },
    'WBC#': {
        'name': 'Leucocitos',
        'unit': '',
        'ranges': {
            'canine': {'min': 0.0, 'max': 0.0},
            'feline': {'min': 0.0, 'max': 0.0}
        },
        'short_name': 'Leucocitos'
    },
    'EPC#': {
        'name': 'Celulas Epiteliales',
        'unit': '',
        'ranges': {
            'canine': {'min': 0.0, 'max': 0.0},
            'feline': {'min': 0.0, 'max': 0.0}
        },
        'short_name': 'Celulas'
    },

    # ============================================================
    # DIGESTIBILIDAD
    # ============================================================
    'STA#': {
        'name': 'Almidón no digerido',
        'unit': '',
        'ranges': {
            'canine': {'min': 0.0, 'max': 2.0},
            'feline': {'min': 0.0, 'max': 2.0}
        },
        'short_name': 'Almidon'
    },
    'LFAT#': {
        'name': 'Grasa ligera',
        'unit': '',
        'ranges': {
            'canine': {'min': 0.0, 'max': 0.2},
            'feline': {'min': 0.0, 'max': 0.2}
        },
        'short_name': 'Grasa'
    },
    'PLA#': {
        'name': 'Fibra vegetal',
        'unit': '',
        'ranges': {
            'canine': {'min': 0.0, 'max': 0.1},
            'feline': {'min': 0.0, 'max': 0.1}
        },
        'short_name': 'Fibra'
    },
    'AF#': {
        'name': 'Grasa',
        'unit': '',
        'ranges': {
            'canine': {'min': 0.0, 'max': 0.1},
            'feline': {'min': 0.0, 'max': 0.1}
        },
        'short_name': 'Grasa'
    },

    # ============================================================
    # QUÍMICA SANGUÍNEA — Enzimas
    # ============================================================
    'ALP': {
        'name': 'Fosfatasa Alcalina',
        'unit': 'U/L',
        'ranges': {
            'canine': {'min': 20.0, 'max': 150.0},
            'feline': {'min': 10.0, 'max': 80.0}
        },
        'short_name': 'Fosfatasa_Alcalina'
    },
    'ALT': {
        'name': 'Alanina Aminotransferasa',
        'unit': 'U/L',
        'ranges': {
            'canine': {'min': 10.0, 'max': 100.0},
            'feline': {'min': 10.0, 'max': 100.0}
        },
        'short_name': 'ALT'
    },
    'AST': {
        'name': 'Aspartato Aminotransferasa',
        'unit': 'U/L',
        'ranges': {
            'canine': {'min': 10.0, 'max': 50.0},
            'feline': {'min': 10.0, 'max': 50.0}
        },
        'short_name': 'AST'
    },
    'GGT': {
        'name': 'Gamma-Glutamil Transferasa',
        'unit': 'U/L',
        'ranges': {
            'canine': {'min': 0.0, 'max': 10.0},
            'feline': {'min': 0.0, 'max': 10.0}
        },
        'short_name': 'GGT'
    },
    'CPK': {
        'name': 'Creatina Quinasa',
        'unit': 'U/L',
        'ranges': {
            'canine': {'min': 50.0, 'max': 200.0},
            'feline': {'min': 50.0, 'max': 250.0}
        },
        'short_name': 'CPK'
    },
    'v-LIP': {
        'name': 'Lipasa Veterinaria',
        'unit': 'U/L',
        'ranges': {
            'canine': {'min': 200.0, 'max': 800.0},
            'feline': {'min': 100.0, 'max': 600.0}
        },
        'short_name': 'Lipasa_Veterinaria'
    },
    'v-AMY': {
        'name': 'Amilasa Veterinaria',
        'unit': 'U/L',
        'ranges': {
            'canine': {'min': 400.0, 'max': 1500.0},
            'feline': {'min': 500.0, 'max': 1500.0}
        },
        'short_name': 'Amilasa_Veterinaria'
    },
    'LDH': {
        'name': 'Deshidrogenasa Láctica',
        'unit': 'U/L',
        'ranges': {
            'canine': {'min': 0.0, 'max': 200.0},
            'feline': {'min': 0.0, 'max': 200.0}
        },
        'short_name': 'LDH'
    },

    # ============================================================
    # QUÍMICA SANGUÍNEA — Metabólicos / Renales
    # ============================================================
    'BUN': {
        'name': 'Nitrógeno Ureico',
        'unit': 'mg/dL',
        'ranges': {
            'canine': {'min': 15.0, 'max': 35.0},
            'feline': {'min': 15.0, 'max': 35.0}
        },
        'short_name': 'Nitrogeno_Ureico'
    },
    'UA': {
        'name': 'Ácido Úrico',
        'unit': 'mg/dL',
        'ranges': {
            'canine': {'min': 2.0, 'max': 9.0},
            'feline': {'min': 0.5, 'max': 7.0},
        },
        'short_name': 'Acido_Urico'
    },
    'BUNCRE': {
        'name': 'Relación BUN/CRE',
        'unit': '',
        'ranges': {
            'canine': {'min': 10.0, 'max': 27.0},
            'feline': {'min': 10.0, 'max': 30.0},
        },
        'short_name': 'Relacion_BUN_CRE'
    },
    'UREA': {
        'name': 'Urea',
        'unit': 'mg/dL',
        'ranges': {
            'canine': {'min': 32.1, 'max': 74.9},
            'feline': {'min': 32.1, 'max': 74.9},
        },
        'short_name': 'Urea'
    },
    'CRE': {
        'name': 'Creatinina',
        'unit': 'mg/dL',
        'ranges': {
            'canine': {'min': 0.6, 'max': 1.6},
            'feline': {'min': 0.8, 'max': 2.0}
        },
        'short_name': 'Creatinina'
    },
    'GLU': {
        'name': 'Glucosa',
        'unit': 'mg/dL',
        'ranges': {
            'canine': {'min': 70.0, 'max': 110.0},
            'feline': {'min': 70.0, 'max': 150.0}
        },
        'short_name': 'Glucosa'
    },
    'IP': {
        'name': 'Fósforo Inorgánico',
        'unit': 'mg/dL',
        'ranges': {
            'canine': {'min': 2.5, 'max': 6.0},
            'feline': {'min': 3.0, 'max': 6.5}
        },
        'short_name': 'Fosforo_Inorganico'
    },
    'Ca': {
        'name': 'Calcio Total',
        'unit': 'mg/dL',
        'ranges': {
            'canine': {'min': 9.0, 'max': 11.5},
            'feline': {'min': 8.5, 'max': 10.5}
        },
        'short_name': 'Calcio_Total'
    },
    'TP': {
        'name': 'Proteína Total',
        'unit': 'g/dL',
        'ranges': {
            'canine': {'min': 5.5, 'max': 7.5},
            'feline': {'min': 6.0, 'max': 8.0}
        },
        'short_name': 'Proteina_Total'
    },
    'ALB': {
        'name': 'Albúmina',
        'unit': 'g/dL',
        'ranges': {
            'canine': {'min': 2.5, 'max': 4.0},
            'feline': {'min': 2.5, 'max': 4.0}
        },
        'short_name': 'Albumina'
    },
    'TCHO': {
        'name': 'Colesterol Total',
        'unit': 'mg/dL',
        'ranges': {
            'canine': {'min': 130.0, 'max': 300.0},
            'feline': {'min': 80.0, 'max': 220.0}
        },
        'short_name': 'Colesterol_Total'
    },
    'TG': {
        'name': 'Triglicéridos',
        'unit': 'mg/dL',
        'ranges': {
            'canine': {'min': 20.0, 'max': 110.0},
            'feline': {'min': 20.0, 'max': 110.0}
        },
        'short_name': 'Trigliceridos'
    },
    'TBIL': {
        'name': 'Bilirrubina Total',
        'unit': 'mg/dL',
        'ranges': {
            'canine': {'min': 0.0, 'max': 0.5},
            'feline': {'min': 0.0, 'max': 0.5}
        },
        'short_name': 'Bilirrubina_Total'
    },
    'NH3': {
        'name': 'Amoníaco',
        'unit': 'µg/dL',
        'ranges': {
            'canine': {'min': 0.0, 'max': 100.0},
            'feline': {'min': 0.0, 'max': 100.0}
        },
        'short_name': 'Amoniaco'
    },

    # ============================================================
    # ELECTROLITOS
    # ============================================================
    'Na': {
        'name': 'Sodio',
        'unit': 'mEq/L',
        'ranges': {
            'canine': {'min': 140.0, 'max': 155.0},
            'feline': {'min': 145.0, 'max': 155.0}
        },
        'short_name': 'Sodio'
    },
    'K': {
        'name': 'Potasio',
        'unit': 'mEq/L',
        'ranges': {
            'canine': {'min': 3.5, 'max': 5.5},
            'feline': {'min': 3.5, 'max': 5.5}
        },
        'short_name': 'Potasio'
    },
    'Cl': {
        'name': 'Cloruro',
        'unit': 'mEq/L',
        'ranges': {
            'canine': {'min': 105.0, 'max': 115.0},
            'feline': {'min': 115.0, 'max': 125.0}
        },
        'short_name': 'Cloruro'
    },

    # ============================================================
    # PARÁMETROS ADICIONALES DE IMAGEN
    # ============================================================
    'RBC_PLT': {
        'name': 'Distribución RBC PLT',
        'short_name': 'Distribucion_RBC_PLT',
        'unit': '',
        'ranges': {'canine': None, 'feline': None}
    },
    'NRBC#': {
        'name': 'Eritrocitos Nucleados',
        'short_name': 'NRBC',
        'unit': 'x10^3/µL',
        'ranges': {'canine': {'min': 0.0, 'max': 0.0}, 'feline': {'min': 0.0, 'max': 0.0}}
    },
    'NRBC%': {
        'name': 'Eritrocitos Nucleados %',
        'short_name': 'NRBC_Pct',
        'unit': '%',
        'ranges': {'canine': {'min': 0.0, 'max': 0.0}, 'feline': {'min': 0.0, 'max': 0.0}}
    },
    'IRF': {
        'name': 'Fracción de Reticulocitos Inmaduros',
        'short_name': 'IRF',
        'unit': '%',
        'ranges': {'canine': None, 'feline': None}
    },
    'LFR': {
        'name': 'Fracción de Reticulocitos de Baja Fluorescencia',
        'short_name': 'LFR',
        'unit': '%',
        'ranges': {'canine': None, 'feline': None}
    },
    'MFR': {
        'name': 'Fracción de Reticulocitos de Media Fluorescencia',
        'short_name': 'MFR',
        'unit': '%',
        'ranges': {'canine': None, 'feline': None}
    },
    'HFR': {
        'name': 'Fracción de Reticulocitos de Alta Fluorescencia',
        'short_name': 'HFR',
        'unit': '%',
        'ranges': {'canine': None, 'feline': None}
    },
    'PLT-I': {
        'name': 'Plaquetas Inmaduras',
        'short_name': 'PLT-I',
        'unit': 'x10^3/µL',
        'ranges': {'canine': None, 'feline': None}
    },
    'PLT-O': {
        'name': 'Plaquetas Ópticas',
        'short_name': 'PLT-O',
        'unit': 'x10^3/µL',
        'ranges': {'canine': None, 'feline': None}
    },
    'PLT-F': {
        'name': 'Plaquetas Fluorescentes',
        'short_name': 'PLT-F',
        'unit': 'x10^3/µL',
        'ranges': {'canine': None, 'feline': None}
    },
    'IPF': {
        'name': 'Fracción de Plaquetas Inmaduras',
        'short_name': 'IPF',
        'unit': '%',
        'ranges': {'canine': None, 'feline': None}
    },
    'FECES': {
        'name': 'Heces',
        'short_name': 'Heces',
        'unit': '',
        'ranges': {'canine': None, 'feline': None}
    },
}

# Dynamic standards storage
VETERINARY_STANDARDS: Dict[str, Dict[str, Any]] = {}
JSON_PATH = Path("data/clinical_standards.json")

# Mapping of alternative abbreviations to standard keys
STANDARDS_MAPPING: Dict[str, str] = {
    # Red Series aliases
    'HGB#': 'HGB',
    'HCT#': 'HCT',

    # White Series aliases
    'LIN#': 'LYM#',
    'LIN%': 'LYM%',
    'LYMP#': 'LYM#',
    'LYMP': 'LYM#',
    'LYM': 'LYM#',
    'LyM#': 'LYM#',
    'LYMP%': 'LYM%',
    'NEU': 'NEU#',
    'EOS': 'EOS#',
    'NSG': 'NSG#',
    'NST': 'NST#',
    'NST/WBC': 'NST/WBC%',
    'NST/NEU': 'NST/NEU%',
    'NSH/WBC': 'NSH/WBC%',
    'NSH/NEU': 'NSH/NEU%',
    'NHG#': 'NSH#',
    'NHG/WBC%': 'NSH/WBC%',
    'MON': 'MON#',
    'NSH': 'NSH#',
    'BASH': 'BAS#',
    'BAS': 'BAS#',
    'RET': 'RET#',
    'SPH': 'SPH#',
    'ETG': 'ETG#',
    'APLT': 'APLT#',

    # Platelets aliases
    'PLT-AGG': 'APLT#',

    # Chemistry aliases
    'GOT': 'AST',
    'GPT': 'ALT',
    'T-CHO': 'TCHO',
    'T-BIL': 'TBIL',

    # Fecal aliases
    'TXE#': 'ANE#',
    'GIA#': 'FLA#',
    'FTg#': 'FLA#',
    'TG#': 'FLA#',
    'To#': 'FLA#',
    'TTE#': 'TtE#',
    'TtE': 'TtE#',
    'FCOD#': 'COD#',
    'CODO0#': 'COD0#',
    'coD1#': 'COD1#',
    'FCAM#': 'CAM#',
    'BACI': 'BACI#',
    'YEA': 'YEA#',
    'FYEA#': 'YEA#',
    'FWBC#': 'WBC#',
    'FRBC#': 'RBC#',
    'COS': 'COS#',
    'C/B': 'C/B#',
    'c/b': 'C/B#',

    # Urine crystal alias (renamed from COD# to avoid collision)
    'COD#_urine': 'CODC#',
}

# Mapping of standard keys to legacy HemogramData fields (Core model compatibility)
LEGACY_HEMOGRAM_MAPPING: Dict[str, str] = {
    'RBC': 'hematies',
    'HGB': 'hemoglobina',
    'HCT': 'hematocrito',
    'MCV': 'vcm',
    'MCH': 'hcm',
    'MCHC': 'chcm',
    'PLT': 'plaquetas',
    'WBC': 'leucocitos',
    'NEU#': 'neutrofilos_segmentados',
    'LYM#': 'linfocitos',
    'MON#': 'monocitos',
    'EOS#': 'eosinofilos',
    'BAS#': 'basofilos',
}

# Set of known chemistry codes for validation
CHEMISTRY_CODES = {
    'ALP', 'ALT', 'AST', 'GGT', 'CPK', 'v-LIP', 'v-AMY', 'LDH',
    'BUN', 'CRE', 'GLU', 'IP', 'Ca', 'TP', 'ALB', 'TCHO', 'TG', 'TBIL', 'NH3',
    'Na', 'K', 'Cl', 'UA',
}

# ── Agrupamiento de parámetros por sección ──────────────────────────────────
PARAMETER_GROUPS = {
    "QUÍMICA SANGUÍNEA": [
        "ALP", "ALT", "AST", "GGT", "CPK", "v-LIP", "v-AMY", "LDH",
        "BUN", "UREA", "CRE", "BUNCRE", "GLU", "IP", "Ca", "UA", "TP", "ALB", "TCHO", "TG",
        "TBIL", "NH3", "Na", "K", "Cl",
    ],
    "Línea Blanca": [
        "WBC", "NEU#", "NST#", "NSG#", "NSH#",
        "LYM#", "MON#", "EOS#", "BAS#",
        "NEU%", "NST/WBC%", "NST/NEU%", "NSG%",
        "NSH/WBC%", "NSH/NEU%",
        "LYM%", "MON%", "EOS%", "BAS%",
        "LUC#", "LUC%", "IG#", "IG%",
    ],
    "Línea Roja": [
        "RBC", "HGB", "HCT", "MCV", "MCH", "MCHC",
        "RDW-CV", "RDW-SD", "RET#", "RET%",
        "HDW-CV", "HDW-SD",
        "ETG#", "ETG%", "SPH#", "SPH%",
        "NRBC#", "NRBC%", "IRF", "LFR", "MFR", "HFR",
        "RBC_PLT",
    ],
    "Plaquetas": [
        "PLT", "MPV", "PDW", "PCT",
        "APLT#", "P-LCC", "P-LCR",
        "PLT-I", "PLT-O", "PLT-F", "IPF",
    ],
    "COPROLÓGICOS": [
        "ALE#", "ANE#", "TRE#", "DIP#", "SPI#", "TtE#", "CEE#",
        "TRI#", "FLA#", "COD#", "COD0#", "COD1#", "COD2#", "Tg#",
    ],
    "MICROBIOTA": [
        "COS#", "BACI#", "C/B#", "CAM#", "BAC#", "SS1#", "SS2#", "YEA#",
    ],
    "CÉLULAS Y SANGRE": [
        "RBC#", "WBC#", "EPC#",
    ],
    "DIGESTIBILIDAD": [
        "STA#", "LFAT#", "PLA#", "AF#",
    ],
}


# Orden de grupos para el PDF (mantiene la secuencia correcta)
PARAMETER_GROUPS_ORDER = list(PARAMETER_GROUPS.keys())


def _sanitize_name_for_short(text: str) -> str:
    """Remove accents, spaces, and special characters for a safe short name.
    'Ancho de Distribución Eritrocitaria (CV)' → 'Ancho_de_Distribucion_Eritrocitaria_CV'
    'Plaquetas (Absoluto)#' → 'Plaquetas_Absoluto'
    """
    nfd = unicodedata.normalize("NFD", text)
    # Remove combining characters (accents)
    ascii_text = "".join(c for c in nfd if unicodedata.category(c) != "Mn")
    # Replace spaces with underscores
    sanitized = ascii_text.replace(" ", "_")
    # Remove any characters not alphanumeric or underscore
    sanitized = re.sub(r"[^\w]+", "", sanitized)
    return sanitized.strip("_")


def get_parameter_name(code: str, short: bool = False) -> str:
    """Get parameter name (either full or short) from the clinical standards registry.

    Args:
        code: The parameter code to look up
        short: If True, return short_name (fallback to name); if False, return full name

    Returns:
        str: The parameter name (full or short)
    """
    # First, resolve any aliases from STANDARDS_MAPPING
    resolved_code = STANDARDS_MAPPING.get(code, code)

    param = VETERINARY_STANDARDS.get(resolved_code)
    if param:
        if short:
            if "short_name" in param:
                return param["short_name"]
            elif "name" in param:
                return _sanitize_name_for_short(param["name"])
        return param.get("name", resolved_code)

    # Fallback to lowercased original code if no standard or mapping is found
    return code.lower()


def get_parameter_group(parameter_code: str) -> str:
    """Retorna el nombre del grupo al que pertenece un parameter_code.
    Si no está en ningún grupo conocido, retorna 'OTROS'.
    """
    for group_name, codes in PARAMETER_GROUPS.items():
        if parameter_code in codes:
            return group_name
    return "OTROS"


def load_standards_from_json():
    """Load clinical standards from JSON file into VETERINARY_STANDARDS dict."""
    JSON_PATH.parent.mkdir(parents=True, exist_ok=True)

    if not JSON_PATH.exists():
        with open(JSON_PATH, "w", encoding="utf-8") as f:
            json.dump(_DEFAULT_VETERINARY_STANDARDS, f, indent=4, ensure_ascii=False)

    try:
        with open(JSON_PATH, "r", encoding="utf-8") as f:
            data = json.load(f)
            VETERINARY_STANDARDS.clear()
            VETERINARY_STANDARDS.update(data)
    except (json.JSONDecodeError, IOError):
        # Fallback to defaults if file is corrupted
        VETERINARY_STANDARDS.clear()
        VETERINARY_STANDARDS.update(deepcopy(_DEFAULT_VETERINARY_STANDARDS))


def reset_to_defaults():
    """Overwrite JSON with factory defaults and reload."""
    JSON_PATH.parent.mkdir(parents=True, exist_ok=True)
    with open(JSON_PATH, "w", encoding="utf-8") as f:
        json.dump(_DEFAULT_VETERINARY_STANDARDS, f, indent=4, ensure_ascii=False)
    load_standards_from_json()


# Initial load
load_standards_from_json()
