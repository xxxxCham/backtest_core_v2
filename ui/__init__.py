"""
Module-ID: ui.__init__

Purpose: Package UI - centralizes Streamlit app et components.

Role in pipeline: user interface

Key components: Re-exports components API

Inputs: None (module imports only)

Outputs: Public API via __all__

Dependencies: .app (main Streamlit), .components (UI widgets)

Conventions: __all__ optionnel; app.py est point d'entrée (streamlit run).

Read-if: Modification exports ou app entry point.

Skip-if: Vous lancez `streamlit run ui/app.py`.
"""
