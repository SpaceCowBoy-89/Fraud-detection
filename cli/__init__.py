"""
CLI Package for Fraud Detection System

This package provides a modular command-line interface with:
- Grouped menu structure
- Help system
- Quick command shortcuts
- Responsive layouts
"""

from .helpers import console, CLIHelpers
from .menu import MenuSystem, MENU_GROUPS, QUICK_COMMANDS

__all__ = ['console', 'CLIHelpers', 'MenuSystem', 'MENU_GROUPS', 'QUICK_COMMANDS']
