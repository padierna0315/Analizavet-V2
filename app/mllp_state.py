"""
Estado compartido del servidor MLLP.
Módulo separado para evitar imports circulares y compartir estado
correctamente entre main.py y routers/mllp.py.
"""

running: bool = False
adapters: list = []
