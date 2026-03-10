"""
Module d'intégration du cache amélioré dans helpers.py

Ajoute les fonctions de cache TTL intelligent pour remplacer le cache session state basique.
"""

def integrate_cache_manager_into_load_selected_data():
    """
    Code d'intégration pour load_selected_data avec cache manager.

    Cette fonction montre comment modifier load_selected_data pour utiliser
    le cache manager au lieu du cache session state basique.
    """

    # Code à intégrer dans load_selected_data de helpers.py :
    integration_code = """
def load_selected_data(
    symbol: str,
    timeframe: str,
    start_date: Optional[object],
    end_date: Optional[object],
) -> Tuple[Optional[pd.DataFrame], str]:
    from .cache_manager import get_cached_data, cache_data

    # Vérifier cache d'abord
    cached_df = get_cached_data(symbol, timeframe, start_date, end_date)
    if cached_df is not None:
        # Mise à jour session state avec données cached
        st.session_state["ohlcv_df"] = cached_df
        st.session_state["ohlcv_cache_key"] = _data_cache_key(
            symbol, timeframe, start_date, end_date
        )
        st.session_state["ohlcv_status_msg"] = "📋 Données du cache (5min TTL)"
        return cached_df, "📋 Données du cache (5min TTL)"

    # Charger depuis source si pas en cache
    start_str = str(start_date) if start_date else None
    end_str = str(end_date) if end_date else None
    df, msg = safe_load_data(symbol, timeframe, start_str, end_str)
    if df is not None:
        # Mettre en cache les nouvelles données
        cache_data(symbol, timeframe, start_date, end_date, df)
        st.session_state["ohlcv_df"] = df
        st.session_state["ohlcv_cache_key"] = _data_cache_key(
            symbol, timeframe, start_date, end_date
        )
        st.session_state["ohlcv_status_msg"] = msg
    return df, msg
    """

    return integration_code


def add_cache_cleanup_to_sidebar():
    """
    Code d'ajout d'un bouton de nettoyage cache dans la sidebar.
    """

    cleanup_code = """
    # Ajout dans sidebar.py - section debug
    if st.sidebar.button("🗑️ Nettoyer cache données"):
        from ui.cache_manager import clear_data_cache, get_cache_stats
        stats_before = get_cache_stats()
        clear_data_cache()
        st.sidebar.success(f"Cache nettoyé! ({stats_before['total_entries']} entrées supprimées)")

    # Optionnel : afficher stats cache
    if st.sidebar.checkbox("📊 Stats cache", value=False):
        from ui.cache_manager import get_cache_stats
        stats = get_cache_stats()
        st.sidebar.json(stats)
    """

    return cleanup_code
