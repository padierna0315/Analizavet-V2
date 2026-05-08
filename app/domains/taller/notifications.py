"""
Altavoz del Edificio - Sistema de Notificaciones OOB

Este módulo proporciona funciones para generar fragmentos HTML de notificaciones
que se actualizan vía HTMX Out-of-Band (OOB) swap. CERO JavaScript.

Uso típico:
    from app.domains.taller.notifications import notify_success, notify_error, notify_processing

    # En un endpoint que retorna HTMLResponse con OOB
    return HTMLResponse(
        content=notify_success("Operación completada") + "<div>Contenido principal...</div>"
    )
"""

import html


SUCCESS_ICON = "✓"
ERROR_ICON = "✕"
PROCESSING_ICON = "⟳"


def _build_notification_html(
    message: str,
    notification_type: str,
    auto_dismiss: bool = True,
    extra_classes: str = ""
) -> str:
    """
    Construye el HTML de una notificación toast con HTMX OOB swap.

    Args:
        message: El mensaje a mostrar (escapado automáticamente)
        notification_type: success | error | processing
        auto_dismiss: Si es True, la notificación se auto-desvanece
        extra_classes: Clases CSS adicionales

    Returns:
        Fragmento HTML con hx-swap-oob="true"
    """
    escaped_message = html.escape(message)
    dismiss_class = "auto-dismiss" if auto_dismiss else ""
    all_classes = f"notification-toast {notification_type} {dismiss_class} {extra_classes}".strip()

    return f'<div id="notification-container" hx-swap-oob="true"><div class="{all_classes}">{SUCCESS_ICON if notification_type == "success" else ERROR_ICON if notification_type == "error" else PROCESSING_ICON} {escaped_message}</div></div>'


def notify_success(message: str, auto_dismiss: bool = True) -> str:
    """
    Genera una notificación de éxito verde con OOB swap.

    Args:
        message: El mensaje a mostrar
        auto_dismiss: Si True, se auto-desvanece en 5s (default: True)

    Returns:
        Fragmento HTML con hx-swap-oob="true"
    """
    return _build_notification_html(message, "success", auto_dismiss)


def notify_error(message: str, auto_dismiss: bool = True) -> str:
    """
    Genera una notificación de error rojo con OOB swap.

    Args:
        message: El mensaje a mostrar
        auto_dismiss: Si True, se auto-desvanece en 10s (default: True)

    Returns:
        Fragmento HTML con hx-swap-oob="true"
    """
    return _build_notification_html(message, "error", auto_dismiss)


def notify_processing(message: str, auto_dismiss: bool = False) -> str:
    """
    Genera una notificación de proceso en gris con OOB swap.

    Args:
        message: El mensaje a mostrar
        auto_dismiss: Si True, se auto-desvanece (default: False - permanece)

    Returns:
        Fragmento HTML con hx-swap-oob="true"
    """
    return _build_notification_html(message, "processing", auto_dismiss)


def notify_dismiss_all() -> str:
    """
    Genera un fragmento que limpia todas las notificaciones.

    Returns:
        Fragmento HTML con hx-swap-oob="true" que vacía el contenedor
    """
    return '<div id="notification-container" hx-swap-oob="true"></div>'


def notify_multiple(*notifications: str) -> str:
    """
    Combina múltiples notificaciones en un solo OOB swap.

    Args:
        *notifications: Múltiples llamadas a notify_success, notify_error, etc.
                       (sin el wrapper del container, solo el div.toast)

    Returns:
        Fragmento HTML con hx-swap-oob="true" conteniendo todas las notificaciones

    Ejemplo:
        notify_multiple(
            '<div class="notification-toast success">Guardado</div>',
            '<div class="notification-toast processing">Procesando...</div>'
        )
    """
    toasts = "".join(notifications)
    return f'<div id="notification-container" hx-swap-oob="true">{toasts}</div>'