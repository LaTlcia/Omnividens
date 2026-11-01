"""Compatibility imports for grouped local configuration readers."""
from lilyrex.configuration.app import (
    AppConfig, ConnectionConfig, IdentityConfig, MasterdataUpdateConfig, load_app_config,
)
from lilyrex.configuration.document import ConfigError, read_document
from lilyrex.configuration.passives import load_passive_settings
from lilyrex.configuration.preview import PARAMETERS, PreviewConfig, load_config

__all__ = [
    'AppConfig', 'ConnectionConfig', 'IdentityConfig', 'MasterdataUpdateConfig',
    'ConfigError', 'PreviewConfig', 'PARAMETERS', 'read_document', 'load_app_config',
    'load_config', 'load_passive_settings',
]
