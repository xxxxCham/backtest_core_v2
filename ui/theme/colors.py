"""
Module-ID: ui.theme.colors

Purpose: Système de couleurs centralisé pour toute l'application.

Role in pipeline: configuration / theming

Key components: ColorPalette, ThemeMode, PALETTES, get_color(), ChartColors

Inputs: Nom de couleur, palette active

Outputs: Code couleur hex (#RRGGBB) ou rgba()

Dependencies: enum, dataclasses

Conventions: TOUTES les couleurs du projet doivent venir d'ici. Aucun hardcode ailleurs.

Read-if: Modification thèmes, ajout palette, changement couleurs globales.

Skip-if: Vous appelez juste get_color("success").
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Dict, Optional

# ============================================================================
# ENUMS
# ============================================================================

class ThemeMode(Enum):
    """Mode de thème global."""
    LIGHT = "light"
    DARK = "dark"
    AUTO = "auto"


class ColorPalette(Enum):
    """Palettes de couleurs disponibles."""
    DEFAULT = "default"
    OCEAN = "ocean"
    FOREST = "forest"
    SUNSET = "sunset"
    MONOCHROME = "monochrome"
    CYBERPUNK = "cyberpunk"
    TRADING = "trading"  # Nouvelle palette optimisée trading


# ============================================================================
# DÉFINITION DES PALETTES
# ============================================================================

PALETTES: Dict[ColorPalette, Dict[str, str]] = {
    ColorPalette.DEFAULT: {
        # Couleurs sémantiques
        "primary": "#2196f3",
        "secondary": "#ff9800",
        "success": "#4caf50",
        "warning": "#ff9800",
        "error": "#f44336",
        "info": "#00bcd4",

        # Arrière-plans
        "background": "#0e1117",
        "surface": "#1e2130",
        "surface_variant": "#262b3d",

        # Textes
        "text": "#fafafa",
        "text_primary": "#a8b2d1",
        "text_secondary": "#b0b0b0",
        "text_muted": "#6c7086",

        # Charts - Trading
        "chart_up": "#26a69a",
        "chart_down": "#ef5350",
        "candle_up": "#26a69a",
        "candle_down": "#ef5350",

        # Charts - Equity
        "equity_line": "#26a69a",
        "equity_fill": "rgba(38, 166, 154, 0.15)",
        "drawdown_line": "#ef5350",
        "drawdown_fill": "rgba(239, 83, 80, 0.3)",
        "capital_line": "rgba(200, 200, 200, 0.5)",

        # Charts - Trades
        "entry_long": "#42a5f5",
        "entry_short": "#ab47bc",
        "exit_profit": "#4caf50",
        "exit_loss": "#f44336",
        "stop_loss": "#ef5350",
        "take_profit": "#4caf50",

        # Charts - Indicateurs
        "bb_mid": "#ffa726",
        "bb_bands": "#42a5f5",
        "bb_bands_rgba": "rgba(66, 165, 245, 0.1)",
        "bb_entry_z": "rgba(255, 204, 128, 0.9)",
        "ema_fast": "#42a5f5",
        "ema_slow": "#ffb74d",
        "ema_center": "#42a5f5",
        "macd_line": "#26a69a",
        "macd_signal": "#ef5350",
        "rsi_line": "#42a5f5",
        "rsi_oversold": "#26a69a",
        "rsi_overbought": "#ef5350",
        "atr_line": "#ab47bc",
        "atr_threshold": "#ffa726",
        "atr_channel_upper": "#ef5350",
        "atr_channel_lower": "#26a69a",
        "stoch_k": "#42a5f5",
        "stoch_d": "#ffb74d",

        # Charts - Diagrammes stratégies
        "price_line": "#e0e0e0",
        "bollinger_low": "rgba(100, 160, 200, 0.6)",
        "bollinger_high": "rgba(100, 160, 200, 0.6)",
        "bollinger_fill": "rgba(100, 160, 200, 0.15)",
        "bollinger_mid": "rgba(140, 200, 255, 0.9)",
        "stop_long": "rgba(239, 83, 80, 0.7)",
        "stop_short": "rgba(239, 83, 80, 0.7)",
        "entry_level_long": "rgba(76, 175, 80, 0.9)",
        "entry_level_short": "rgba(171, 71, 188, 0.9)",
        "annotation_stop": "#ef9a9a",
        "annotation_tp": "#81c784",

        # UI - Grilles et bordures
        "grid_color": "rgba(128, 128, 128, 0.1)",
        "border": "rgba(128, 128, 128, 0.3)",
        "divider": "rgba(128, 128, 128, 0.2)",

        # Agents LLM
        "agent_analyst": "#42a5f5",
        "agent_strategist": "#4caf50",
        "agent_critic": "#ff9800",
        "agent_validator": "#ab47bc",
    },

    ColorPalette.OCEAN: {
        "primary": "#0077b6",
        "secondary": "#00b4d8",
        "success": "#06d6a0",
        "warning": "#ffd166",
        "error": "#ef476f",
        "info": "#118ab2",
        "background": "#03045e",
        "surface": "#023e8a",
        "surface_variant": "#0077b6",
        "text": "#caf0f8",
        "text_primary": "#caf0f8",
        "text_secondary": "#90e0ef",
        "text_muted": "#48cae4",
        "chart_up": "#06d6a0",
        "chart_down": "#ef476f",
        "candle_up": "#06d6a0",
        "candle_down": "#ef476f",
        "equity_line": "#06d6a0",
        "equity_fill": "rgba(6, 214, 160, 0.15)",
        "drawdown_line": "#ef476f",
        "drawdown_fill": "rgba(239, 71, 111, 0.3)",
        "capital_line": "rgba(144, 224, 239, 0.5)",
        "entry_long": "#00b4d8",
        "entry_short": "#7209b7",
        "exit_profit": "#06d6a0",
        "exit_loss": "#ef476f",
        "stop_loss": "#ef476f",
        "take_profit": "#06d6a0",
        "bb_mid": "#ffd166",
        "bb_bands": "#00b4d8",
        "bb_bands_rgba": "rgba(0, 180, 216, 0.1)",
        "bb_entry_z": "rgba(255, 209, 102, 0.9)",
        "ema_fast": "#00b4d8",
        "ema_slow": "#ffd166",
        "ema_center": "#00b4d8",
        "macd_line": "#06d6a0",
        "macd_signal": "#ef476f",
        "rsi_line": "#00b4d8",
        "rsi_oversold": "#06d6a0",
        "rsi_overbought": "#ef476f",
        "atr_line": "#7209b7",
        "atr_threshold": "#ffd166",
        "atr_channel_upper": "#ef476f",
        "atr_channel_lower": "#06d6a0",
        "stoch_k": "#00b4d8",
        "stoch_d": "#ffd166",
        "price_line": "#caf0f8",
        "bollinger_low": "rgba(0, 180, 216, 0.6)",
        "bollinger_high": "rgba(0, 180, 216, 0.6)",
        "bollinger_fill": "rgba(0, 180, 216, 0.15)",
        "bollinger_mid": "rgba(144, 224, 239, 0.9)",
        "stop_long": "rgba(239, 71, 111, 0.7)",
        "stop_short": "rgba(239, 71, 111, 0.7)",
        "entry_level_long": "rgba(6, 214, 160, 0.9)",
        "entry_level_short": "rgba(114, 9, 183, 0.9)",
        "annotation_stop": "#f8a5b8",
        "annotation_tp": "#7ddba3",
        "grid_color": "rgba(144, 224, 239, 0.1)",
        "border": "rgba(144, 224, 239, 0.3)",
        "divider": "rgba(144, 224, 239, 0.2)",
        "agent_analyst": "#00b4d8",
        "agent_strategist": "#06d6a0",
        "agent_critic": "#ffd166",
        "agent_validator": "#7209b7",
    },

    ColorPalette.FOREST: {
        "primary": "#2d6a4f",
        "secondary": "#40916c",
        "success": "#52b788",
        "warning": "#e9c46a",
        "error": "#e76f51",
        "info": "#74c69d",
        "background": "#1b4332",
        "surface": "#2d6a4f",
        "surface_variant": "#40916c",
        "text": "#d8f3dc",
        "text_primary": "#d8f3dc",
        "text_secondary": "#95d5b2",
        "text_muted": "#74c69d",
        "chart_up": "#52b788",
        "chart_down": "#e76f51",
        "candle_up": "#52b788",
        "candle_down": "#e76f51",
        "equity_line": "#52b788",
        "equity_fill": "rgba(82, 183, 136, 0.15)",
        "drawdown_line": "#e76f51",
        "drawdown_fill": "rgba(231, 111, 81, 0.3)",
        "capital_line": "rgba(149, 213, 178, 0.5)",
        "entry_long": "#74c69d",
        "entry_short": "#9b2226",
        "exit_profit": "#52b788",
        "exit_loss": "#e76f51",
        "stop_loss": "#e76f51",
        "take_profit": "#52b788",
        "bb_mid": "#e9c46a",
        "bb_bands": "#74c69d",
        "bb_bands_rgba": "rgba(116, 198, 157, 0.1)",
        "bb_entry_z": "rgba(233, 196, 106, 0.9)",
        "ema_fast": "#74c69d",
        "ema_slow": "#e9c46a",
        "ema_center": "#74c69d",
        "macd_line": "#52b788",
        "macd_signal": "#e76f51",
        "rsi_line": "#74c69d",
        "rsi_oversold": "#52b788",
        "rsi_overbought": "#e76f51",
        "atr_line": "#9b2226",
        "atr_threshold": "#e9c46a",
        "atr_channel_upper": "#e76f51",
        "atr_channel_lower": "#52b788",
        "stoch_k": "#74c69d",
        "stoch_d": "#e9c46a",
        "price_line": "#d8f3dc",
        "bollinger_low": "rgba(116, 198, 157, 0.6)",
        "bollinger_high": "rgba(116, 198, 157, 0.6)",
        "bollinger_fill": "rgba(116, 198, 157, 0.15)",
        "bollinger_mid": "rgba(149, 213, 178, 0.9)",
        "stop_long": "rgba(231, 111, 81, 0.7)",
        "stop_short": "rgba(231, 111, 81, 0.7)",
        "entry_level_long": "rgba(82, 183, 136, 0.9)",
        "entry_level_short": "rgba(155, 34, 38, 0.9)",
        "annotation_stop": "#f4a298",
        "annotation_tp": "#95d5b2",
        "grid_color": "rgba(149, 213, 178, 0.1)",
        "border": "rgba(149, 213, 178, 0.3)",
        "divider": "rgba(149, 213, 178, 0.2)",
        "agent_analyst": "#74c69d",
        "agent_strategist": "#52b788",
        "agent_critic": "#e9c46a",
        "agent_validator": "#9b2226",
    },

    ColorPalette.SUNSET: {
        "primary": "#ff6b6b",
        "secondary": "#feca57",
        "success": "#1dd1a1",
        "warning": "#feca57",
        "error": "#ee5a24",
        "info": "#54a0ff",
        "background": "#2c2c54",
        "surface": "#474787",
        "surface_variant": "#5a5a8f",
        "text": "#f5f6fa",
        "text_primary": "#f5f6fa",
        "text_secondary": "#dcdde1",
        "text_muted": "#a5a5c0",
        "chart_up": "#1dd1a1",
        "chart_down": "#ee5a24",
        "candle_up": "#1dd1a1",
        "candle_down": "#ee5a24",
        "equity_line": "#1dd1a1",
        "equity_fill": "rgba(29, 209, 161, 0.15)",
        "drawdown_line": "#ee5a24",
        "drawdown_fill": "rgba(238, 90, 36, 0.3)",
        "capital_line": "rgba(220, 221, 225, 0.5)",
        "entry_long": "#54a0ff",
        "entry_short": "#ff6b6b",
        "exit_profit": "#1dd1a1",
        "exit_loss": "#ee5a24",
        "stop_loss": "#ee5a24",
        "take_profit": "#1dd1a1",
        "bb_mid": "#feca57",
        "bb_bands": "#54a0ff",
        "bb_bands_rgba": "rgba(84, 160, 255, 0.1)",
        "bb_entry_z": "rgba(254, 202, 87, 0.9)",
        "ema_fast": "#54a0ff",
        "ema_slow": "#feca57",
        "ema_center": "#54a0ff",
        "macd_line": "#1dd1a1",
        "macd_signal": "#ee5a24",
        "rsi_line": "#54a0ff",
        "rsi_oversold": "#1dd1a1",
        "rsi_overbought": "#ee5a24",
        "atr_line": "#ff6b6b",
        "atr_threshold": "#feca57",
        "atr_channel_upper": "#ee5a24",
        "atr_channel_lower": "#1dd1a1",
        "stoch_k": "#54a0ff",
        "stoch_d": "#feca57",
        "price_line": "#f5f6fa",
        "bollinger_low": "rgba(84, 160, 255, 0.6)",
        "bollinger_high": "rgba(84, 160, 255, 0.6)",
        "bollinger_fill": "rgba(84, 160, 255, 0.15)",
        "bollinger_mid": "rgba(220, 221, 225, 0.9)",
        "stop_long": "rgba(238, 90, 36, 0.7)",
        "stop_short": "rgba(238, 90, 36, 0.7)",
        "entry_level_long": "rgba(29, 209, 161, 0.9)",
        "entry_level_short": "rgba(255, 107, 107, 0.9)",
        "annotation_stop": "#f8a5a5",
        "annotation_tp": "#7ee8c7",
        "grid_color": "rgba(220, 221, 225, 0.1)",
        "border": "rgba(220, 221, 225, 0.3)",
        "divider": "rgba(220, 221, 225, 0.2)",
        "agent_analyst": "#54a0ff",
        "agent_strategist": "#1dd1a1",
        "agent_critic": "#feca57",
        "agent_validator": "#ff6b6b",
    },

    ColorPalette.CYBERPUNK: {
        "primary": "#00ffff",
        "secondary": "#ff00ff",
        "success": "#00ff00",
        "warning": "#ffff00",
        "error": "#ff0000",
        "info": "#00ffff",
        "background": "#0a0a0a",
        "surface": "#1a1a2e",
        "surface_variant": "#16213e",
        "text": "#eaeaea",
        "text_primary": "#eaeaea",
        "text_secondary": "#00ffff",
        "text_muted": "#888888",
        "chart_up": "#00ff00",
        "chart_down": "#ff00ff",
        "candle_up": "#00ff00",
        "candle_down": "#ff00ff",
        "equity_line": "#00ff00",
        "equity_fill": "rgba(0, 255, 0, 0.15)",
        "drawdown_line": "#ff00ff",
        "drawdown_fill": "rgba(255, 0, 255, 0.3)",
        "capital_line": "rgba(0, 255, 255, 0.5)",
        "entry_long": "#00ffff",
        "entry_short": "#ff00ff",
        "exit_profit": "#00ff00",
        "exit_loss": "#ff0000",
        "stop_loss": "#ff0000",
        "take_profit": "#00ff00",
        "bb_mid": "#ffff00",
        "bb_bands": "#00ffff",
        "bb_bands_rgba": "rgba(0, 255, 255, 0.1)",
        "bb_entry_z": "rgba(255, 255, 0, 0.9)",
        "ema_fast": "#00ffff",
        "ema_slow": "#ffff00",
        "ema_center": "#00ffff",
        "macd_line": "#00ff00",
        "macd_signal": "#ff00ff",
        "rsi_line": "#00ffff",
        "rsi_oversold": "#00ff00",
        "rsi_overbought": "#ff0000",
        "atr_line": "#ff00ff",
        "atr_threshold": "#ffff00",
        "atr_channel_upper": "#ff0000",
        "atr_channel_lower": "#00ff00",
        "stoch_k": "#00ffff",
        "stoch_d": "#ffff00",
        "price_line": "#eaeaea",
        "bollinger_low": "rgba(0, 255, 255, 0.6)",
        "bollinger_high": "rgba(0, 255, 255, 0.6)",
        "bollinger_fill": "rgba(0, 255, 255, 0.15)",
        "bollinger_mid": "rgba(255, 255, 0, 0.9)",
        "stop_long": "rgba(255, 0, 0, 0.7)",
        "stop_short": "rgba(255, 0, 0, 0.7)",
        "entry_level_long": "rgba(0, 255, 0, 0.9)",
        "entry_level_short": "rgba(255, 0, 255, 0.9)",
        "annotation_stop": "#ff6666",
        "annotation_tp": "#66ff66",
        "grid_color": "rgba(0, 255, 255, 0.1)",
        "border": "rgba(0, 255, 255, 0.3)",
        "divider": "rgba(0, 255, 255, 0.2)",
        "agent_analyst": "#00ffff",
        "agent_strategist": "#00ff00",
        "agent_critic": "#ffff00",
        "agent_validator": "#ff00ff",
    },

    ColorPalette.MONOCHROME: {
        "primary": "#888888",
        "secondary": "#666666",
        "success": "#a0a0a0",
        "warning": "#c0c0c0",
        "error": "#505050",
        "info": "#707070",
        "background": "#1a1a1a",
        "surface": "#2a2a2a",
        "surface_variant": "#3a3a3a",
        "text": "#e0e0e0",
        "text_primary": "#e0e0e0",
        "text_secondary": "#909090",
        "text_muted": "#606060",
        "chart_up": "#a0a0a0",
        "chart_down": "#505050",
        "candle_up": "#a0a0a0",
        "candle_down": "#505050",
        "equity_line": "#a0a0a0",
        "equity_fill": "rgba(160, 160, 160, 0.15)",
        "drawdown_line": "#505050",
        "drawdown_fill": "rgba(80, 80, 80, 0.3)",
        "capital_line": "rgba(144, 144, 144, 0.5)",
        "entry_long": "#888888",
        "entry_short": "#666666",
        "exit_profit": "#a0a0a0",
        "exit_loss": "#505050",
        "stop_loss": "#505050",
        "take_profit": "#a0a0a0",
        "bb_mid": "#c0c0c0",
        "bb_bands": "#888888",
        "bb_bands_rgba": "rgba(136, 136, 136, 0.1)",
        "bb_entry_z": "rgba(192, 192, 192, 0.9)",
        "ema_fast": "#888888",
        "ema_slow": "#c0c0c0",
        "ema_center": "#888888",
        "macd_line": "#a0a0a0",
        "macd_signal": "#505050",
        "rsi_line": "#888888",
        "rsi_oversold": "#a0a0a0",
        "rsi_overbought": "#505050",
        "atr_line": "#666666",
        "atr_threshold": "#c0c0c0",
        "atr_channel_upper": "#505050",
        "atr_channel_lower": "#a0a0a0",
        "stoch_k": "#888888",
        "stoch_d": "#c0c0c0",
        "price_line": "#e0e0e0",
        "bollinger_low": "rgba(136, 136, 136, 0.6)",
        "bollinger_high": "rgba(136, 136, 136, 0.6)",
        "bollinger_fill": "rgba(136, 136, 136, 0.15)",
        "bollinger_mid": "rgba(192, 192, 192, 0.9)",
        "stop_long": "rgba(80, 80, 80, 0.7)",
        "stop_short": "rgba(80, 80, 80, 0.7)",
        "entry_level_long": "rgba(160, 160, 160, 0.9)",
        "entry_level_short": "rgba(102, 102, 102, 0.9)",
        "annotation_stop": "#808080",
        "annotation_tp": "#b0b0b0",
        "grid_color": "rgba(144, 144, 144, 0.1)",
        "border": "rgba(144, 144, 144, 0.3)",
        "divider": "rgba(144, 144, 144, 0.2)",
        "agent_analyst": "#888888",
        "agent_strategist": "#a0a0a0",
        "agent_critic": "#c0c0c0",
        "agent_validator": "#666666",
    },

    ColorPalette.TRADING: {
        # Palette optimisée pour le trading avec contrastes forts
        "primary": "#2196f3",
        "secondary": "#ff9800",
        "success": "#00e676",  # Vert vif profits
        "warning": "#ffab00",
        "error": "#ff5252",    # Rouge vif pertes
        "info": "#40c4ff",
        "background": "#0d1117",
        "surface": "#161b22",
        "surface_variant": "#21262d",
        "text": "#f0f6fc",
        "text_primary": "#c9d1d9",
        "text_secondary": "#8b949e",
        "text_muted": "#6e7681",
        "chart_up": "#00e676",
        "chart_down": "#ff5252",
        "candle_up": "#00e676",
        "candle_down": "#ff5252",
        "equity_line": "#00e676",
        "equity_fill": "rgba(0, 230, 118, 0.1)",
        "drawdown_line": "#ff5252",
        "drawdown_fill": "rgba(255, 82, 82, 0.2)",
        "capital_line": "rgba(201, 209, 217, 0.4)",
        "entry_long": "#40c4ff",
        "entry_short": "#e040fb",
        "exit_profit": "#00e676",
        "exit_loss": "#ff5252",
        "stop_loss": "#ff5252",
        "take_profit": "#00e676",
        "bb_mid": "#ffab00",
        "bb_bands": "#40c4ff",
        "bb_bands_rgba": "rgba(64, 196, 255, 0.1)",
        "bb_entry_z": "rgba(255, 171, 0, 0.9)",
        "ema_fast": "#40c4ff",
        "ema_slow": "#ffab00",
        "ema_center": "#40c4ff",
        "macd_line": "#00e676",
        "macd_signal": "#ff5252",
        "rsi_line": "#40c4ff",
        "rsi_oversold": "#00e676",
        "rsi_overbought": "#ff5252",
        "atr_line": "#e040fb",
        "atr_threshold": "#ffab00",
        "atr_channel_upper": "#ff5252",
        "atr_channel_lower": "#00e676",
        "stoch_k": "#40c4ff",
        "stoch_d": "#ffab00",
        "price_line": "#c9d1d9",
        "bollinger_low": "rgba(64, 196, 255, 0.6)",
        "bollinger_high": "rgba(64, 196, 255, 0.6)",
        "bollinger_fill": "rgba(64, 196, 255, 0.1)",
        "bollinger_mid": "rgba(255, 171, 0, 0.9)",
        "stop_long": "rgba(255, 82, 82, 0.7)",
        "stop_short": "rgba(255, 82, 82, 0.7)",
        "entry_level_long": "rgba(0, 230, 118, 0.9)",
        "entry_level_short": "rgba(224, 64, 251, 0.9)",
        "annotation_stop": "#ff8a80",
        "annotation_tp": "#69f0ae",
        "grid_color": "rgba(139, 148, 158, 0.1)",
        "border": "rgba(139, 148, 158, 0.3)",
        "divider": "rgba(139, 148, 158, 0.2)",
        "agent_analyst": "#40c4ff",
        "agent_strategist": "#00e676",
        "agent_critic": "#ffab00",
        "agent_validator": "#e040fb",
    },
}


# ============================================================================
# ÉTAT GLOBAL ET GETTERS
# ============================================================================

# Palette active par défaut
_active_palette: ColorPalette = ColorPalette.TRADING
_theme_mode: ThemeMode = ThemeMode.DARK


def set_palette(palette: ColorPalette) -> None:
    """Change la palette active."""
    global _active_palette
    _active_palette = palette


def get_palette() -> ColorPalette:
    """Retourne la palette active."""
    return _active_palette


def set_theme_mode(mode: ThemeMode) -> None:
    """Change le mode de thème."""
    global _theme_mode
    _theme_mode = mode


def get_theme_mode() -> ThemeMode:
    """Retourne le mode de thème actif."""
    return _theme_mode


def get_color(
    name: str,
    palette: Optional[ColorPalette] = None,
    fallback: str = "#888888"
) -> str:
    """
    Récupère une couleur par son nom.

    Args:
        name: Nom de la couleur (ex: "success", "chart_up", "equity_line")
        palette: Palette à utiliser (None = palette active)
        fallback: Couleur de fallback si non trouvée

    Returns:
        Code couleur hex ou rgba
    """
    p = palette or _active_palette
    colors = PALETTES.get(p, PALETTES[ColorPalette.DEFAULT])
    return colors.get(name, fallback)


def get_colors(palette: Optional[ColorPalette] = None) -> Dict[str, str]:
    """
    Retourne toutes les couleurs d'une palette.

    Args:
        palette: Palette à utiliser (None = palette active)

    Returns:
        Dictionnaire complet des couleurs
    """
    p = palette or _active_palette
    return PALETTES.get(p, PALETTES[ColorPalette.DEFAULT]).copy()


def get_palette_names() -> list[str]:
    """Retourne la liste des noms de palettes disponibles."""
    return [p.value for p in ColorPalette]


# ============================================================================
# HELPERS SPÉCIALISÉS
# ============================================================================

def get_profit_color(pnl: float, palette: Optional[ColorPalette] = None) -> str:
    """Retourne la couleur appropriée pour un PnL (profit/perte)."""
    return get_color("success" if pnl >= 0 else "error", palette)


def get_trade_color(
    side: str,
    action: str,
    pnl: Optional[float] = None,
    palette: Optional[ColorPalette] = None
) -> str:
    """
    Retourne la couleur pour un trade.

    Args:
        side: "LONG" ou "SHORT"
        action: "entry" ou "exit"
        pnl: PnL pour les exits (détermine profit/loss)
        palette: Palette à utiliser
    """
    if action == "entry":
        return get_color("entry_long" if side == "LONG" else "entry_short", palette)
    else:
        if pnl is not None:
            return get_color("exit_profit" if pnl >= 0 else "exit_loss", palette)
        return get_color("text_secondary", palette)


def get_agent_color(agent_role: str, palette: Optional[ColorPalette] = None) -> str:
    """Retourne la couleur pour un agent LLM."""
    role_map = {
        "analyst": "agent_analyst",
        "strategist": "agent_strategist",
        "critic": "agent_critic",
        "validator": "agent_validator",
    }
    color_key = role_map.get(agent_role.lower(), "primary")
    return get_color(color_key, palette)


# ============================================================================
# DATACLASS POUR CONFIGURATION CHARTS
# ============================================================================

@dataclass
class ChartColorConfig:
    """Configuration complète des couleurs pour un graphique."""

    # Récupérées depuis la palette active
    candle_up: str = ""
    candle_down: str = ""
    equity_line: str = ""
    equity_fill: str = ""
    drawdown_line: str = ""
    drawdown_fill: str = ""
    entry_long: str = ""
    entry_short: str = ""
    exit_profit: str = ""
    exit_loss: str = ""
    grid_color: str = ""
    text_primary: str = ""
    background: str = ""

    @classmethod
    def from_palette(cls, palette: Optional[ColorPalette] = None) -> "ChartColorConfig":
        """Crée une config depuis une palette."""
        return cls(
            candle_up=get_color("candle_up", palette),
            candle_down=get_color("candle_down", palette),
            equity_line=get_color("equity_line", palette),
            equity_fill=get_color("equity_fill", palette),
            drawdown_line=get_color("drawdown_line", palette),
            drawdown_fill=get_color("drawdown_fill", palette),
            entry_long=get_color("entry_long", palette),
            entry_short=get_color("entry_short", palette),
            exit_profit=get_color("exit_profit", palette),
            exit_loss=get_color("exit_loss", palette),
            grid_color=get_color("grid_color", palette),
            text_primary=get_color("text_primary", palette),
            background=get_color("background", palette),
        )


# ============================================================================
# EXPORTS
# ============================================================================

__all__ = [
    # Enums
    "ThemeMode",
    "ColorPalette",
    # Data
    "PALETTES",
    # Setters/Getters
    "set_palette",
    "get_palette",
    "set_theme_mode",
    "get_theme_mode",
    "get_color",
    "get_colors",
    "get_palette_names",
    # Helpers
    "get_profit_color",
    "get_trade_color",
    "get_agent_color",
    # Dataclass
    "ChartColorConfig",
]
