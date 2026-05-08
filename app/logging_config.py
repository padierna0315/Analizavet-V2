import logfire

# Logfire local mode - no cloud, no token required
logfire.configure(
    send_to_logfire=False,  # Modo local — sin conexión a internet
)
logfire.info("🔥 Logfire activo en modo local — logs visibles aquí")

# Legacy function preserved for backward compatibility
def setup_logging(log_level: str = "INFO"):
    """Legacy function kept for compatibility. Logfire is now the primary logger."""
    # Logfire handles all logging automatically
    # This function no longer needs to configure loguru
    pass