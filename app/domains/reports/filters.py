import re
from markupsafe import Markup

def format_ref_range(value: str) -> Markup:
    """
    Filtro Jinja2 para formatear rangos de referencia.
    Separa el número de la unidad, pone exponentes en <sup> y la unidad en un <span>.
    """
    if not value or value == "N/D":
        return Markup(value if value else "")
    
    match = re.match(r"^([\d\.\-\s]+)(.*)$", value)
    if not match:
        return Markup(value)
        
    numbers = match.group(1).strip()
    unit = match.group(2).strip()
    
    if " - " in numbers:
        min_val, max_val = numbers.split(" - ", 1)
        numbers_html = f'<span class="ref-min">{min_val.strip()}</span> - <span class="ref-max">{max_val.strip()}</span>'
    else:
        numbers_html = numbers
    
    if not unit:
        return Markup(numbers_html)
        
    unit_html = re.sub(r"(x10\^|x10\*)(\d+)", r"x10<sup>\2</sup>", unit)
    
    return Markup(f'{numbers_html} <span class="ref-unit">{unit_html}</span>')
