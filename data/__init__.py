"""
Module-ID: data.__init__

Purpose: Package data - exports loader functions (load_ohlcv, discover_available_data).

Role in pipeline: data input

Key components: Re-exports load_ohlcv, discover_available_data

Inputs: None (module imports only)

Outputs: Public API via __all__

Dependencies: .loader

Conventions: __all__ définit API publique.

Read-if: Modification exports ou structure package.

Skip-if: Vous importez directement depuis data.loader.
"""

from .loader import discover_available_data, load_ohlcv

__all__ = ["load_ohlcv", "discover_available_data"]
