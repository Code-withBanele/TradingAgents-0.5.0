from copy import deepcopy

import tradingagents.default_config as default_config

# Use default config but allow it to be overridden
_config: dict | None = None


def _deep_merge(base: dict, incoming: dict) -> dict:
    """Recursively merge nested dictionaries while keeping scalar replacement semantics."""
    merged = deepcopy(base)
    for key, value in incoming.items():
        existing = merged.get(key)
        if isinstance(value, dict) and isinstance(existing, dict):
            merged[key] = _deep_merge(existing, value)
        else:
            merged[key] = deepcopy(value)
    return merged


def initialize_config():
    """Initialize the configuration with default values."""
    global _config
    if _config is None:
        _config = deepcopy(default_config.DEFAULT_CONFIG)


def set_config(config: dict):
    """Update the configuration with custom values.

    Nested dict-valued keys are merged recursively so partial updates keep the
    existing defaults for untouched leaves while explicit scalar values replace
    the previous value.
    """
    global _config
    initialize_config()
    _config = _deep_merge(_config, deepcopy(config))


def get_config() -> dict:
    """Get the current configuration."""
    if _config is None:
        initialize_config()
    return deepcopy(_config)


# Initialize with default config
initialize_config()
