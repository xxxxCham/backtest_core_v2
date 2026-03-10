
Exemples Numba prange pour Bollinger Bands
Les Bollinger Bands sont parfaits pour prange car les calculs sur différents paramètres (period, std_dev multiplier) ou sur plusieurs fenêtres temporelles sont indépendants. Voici des exemples concrets adaptés à backtest_core (stratégies comme bollinger_atr.py).
Tous utilisent la config optimale :
Pythonfrom numba import njit, prange
import numpy as np

@njit(cache=True, nogil=True, fastmath=True, parallel=True)
def fonction(...):
    ...
1. Sweep de paramètres Bollinger (grid search)
Parallelisation sur combinaisons period × multiplier.
Python@njit(parallel=True, cache=True, nogil=True, fastmath=True)
def bollinger_grid_sweep(
    close: np.ndarray,
    periods: np.ndarray,      # ex. [10, 20, 30, 50]
    multipliers: np.ndarray   # ex. [1.5, 2.0, 2.5]
) -> np.ndarray:
    n_periods = len(periods)
    n_mult = len(multipliers)
    results = np.empty((n_periods, n_mult), dtype=np.float64)  # PnL ou Sharpe

    for i in prange(n_periods):
        for j in prange(n_mult):  # nested prange
            period = int(periods[i])
            mult = multipliers[j]
            pnl = simulate_bollinger(close, period, mult)
            results[i, j] = pnl

    return results
Utilisation : Idéal pour remplacer un sweep séquentiel dans sweep_numba.py.
2. Calcul parallèle de Bollinger Bands sur plusieurs periods
Calcule upper/lower/middle pour plusieurs periods en une passe (utile pour multi-timeframe ou feature engineering).
Python@njit(parallel=True, cache=True, nogil=True, fastmath=True)
def multi_period_bollinger(
    close: np.ndarray,
    periods: np.ndarray,      # ex. [20, 50, 100]
    multiplier: float = 2.0
) -> np.ndarray:
    n = len(close)
    n_periods = len(periods)
    bands = np.empty((n_periods, n, 3), dtype=np.float64)  # [middle, upper, lower]

    for p_idx in prange(n_periods):
        period = int(periods[p_idx])
        if period >= n:
            continue

        middle = np.empty(n)
        std = np.empty(n)

        for i in range(n):
            if i < period - 1:
                middle[i] = std[i] = np.nan
            else:
                window = close[i - period + 1:i + 1]
                middle[i] = np.mean(window)
                std[i] = np.std(window)

        upper = middle + multiplier * std
        lower = middle - multiplier * std

        bands[p_idx, :, 0] = middle
        bands[p_idx, :, 1] = upper
        bands[p_idx, :, 2] = lower

    return bands
Gain : Évite boucles Python imbriquées → x5-10 sur gros datasets.
3. Bollinger + signal generation en parallèle (par paramètre)
Génère signaux d’entrée/sortie pour chaque combinaison de params.
Python@njit(parallel=True, cache=True, nogil=True, fastmath=True)
def bollinger_signals_sweep(
    close: np.ndarray,
    periods: np.ndarray,
    multipliers: np.ndarray
) -> np.ndarray:
    n = len(close)
    n_periods = len(periods)
    n_mult = len(multipliers)
    signals = np.empty((n_periods, n_mult, n), dtype=np.int8)  # 1=long, -1=short, 0=hold

    for i in prange(n_periods):
        for j in prange(n_mult):
            period = int(periods[i])
            mult = multipliers[j]

            middle = np.empty(n)
            upper = np.empty(n)
            lower = np.empty(n)

            for t in range(n):
                if t < period:
                    middle[t] = upper[t] = lower[t] = np.nan
                    signals[i, j, t] = 0
                else:
                    window = close[t - period + 1:t + 1]
                    middle[t] = np.mean(window)
                    std_dev = np.std(window)
                    upper[t] = middle[t] + mult * std_dev
                    lower[t] = middle[t] - mult * std_dev

                    if close[t] > upper[t]:
                        signals[i, j, t] = -1  # short
                    elif close[t] < lower[t]:
                        signals[i, j, t] = 1   # long
                    else:
                        signals[i, j, t] = 0

    return signals
Préparation hors Numba
Pythonclose_array = df['close'].values.astype(np.float64)
periods = np.array([10, 20, 30, 50])
mults = np.array([1.8, 2.0, 2.2])

results = bollinger_grid_sweep(close_array, periods, mults)
Ces exemples s’intègrent directement dans vos stratégies Bollinger. Quel aspect priorisez-vous (sweep params, multi-period bands, signaux) ? Des contraintes spécifiques (ex. ATR combiné) ?Exemples prange pour RSIExemples Numba prange pour RSI
Le RSI est un indicateur classique avec un paramètre principal (period). prange est idéal pour :

Sweeps sur différents periods
Calculs multi-periods en parallèle
Génération de signaux sur plusieurs thresholds

Configuration optimale (à réutiliser) :
Pythonfrom numba import njit, prange
import numpy as np

@njit(cache=True, nogil=True, fastmath=True, parallel=True)
def fonction(...):
    ...
1. Sweep de périodes RSI (grid search)
Parallelisation sur différents periods pour trouver le meilleur (ex. Sharpe max).
Python@njit(parallel=True, cache=True, nogil=True, fastmath=True)
def rsi_period_sweep(
    close: np.ndarray,
    periods: np.ndarray,          # ex. [7, 14, 21, 28]
    overbought: float = 70.0,
    oversold: float = 30.0
) -> np.ndarray:
    n_periods = len(periods)
    results = np.empty(n_periods, dtype=np.float64)  # PnL ou Sharpe

    for i in prange(n_periods):
        period = int(periods[i])
        rsi = compute_rsi(close, period)
        signals = np.zeros(len(close), dtype=np.int8)
        signals[rsi > overbought] = -1   # short
        signals[rsi < oversold] = 1      # long

        pnl = simulate_signals(close, signals)
        results[i] = pnl

    return results
2. Calcul multi-period RSI en parallèle
Calcule RSI pour plusieurs periods en une passe (utile pour stratégies multi-RSI).
Python@njit(parallel=True, cache=True, nogil=True, fastmath=True)
def multi_period_rsi(
    close: np.ndarray,
    periods: np.ndarray           # ex. [14, 21, 28]
) -> np.ndarray:
    n = len(close)
    n_periods = len(periods)
    rsi_values = np.empty((n_periods, n), dtype=np.float64)

    for p_idx in prange(n_periods):
        period = int(periods[p_idx])
        rsi = compute_rsi(close, period)
        rsi_values[p_idx, :] = rsi

    return rsi_values
Fonction RSI de base (à placer dans le même module) :
Python@njit(cache=True, nogil=True, fastmath=True)
def compute_rsi(close: np.ndarray, period: int) -> np.ndarray:
    n = len(close)
    rsi = np.empty(n)
    rsi[:period] = np.nan

    delta = np.diff(close)
    up = np.maximum(delta, 0)
    down = np.abs(np.minimum(delta, 0))

    gain = np.empty(n)
    loss = np.empty(n)
    gain[period] = np.mean(up[:period])
    loss[period] = np.mean(down[:period])

    for i in range(period + 1, n):
        gain[i] = (gain[i-1] * (period - 1) + up[i-1]) / period
        loss[i] = (loss[i-1] * (period - 1) + down[i-1]) / period

    rs = gain[period:] / np.where(loss[period:] == 0, 1e-10, loss[period:])
    rsi[period:] = 100 - (100 / (1 + rs))

    return rsi
3. Signaux RSI avec différents thresholds en parallèle
Génère signaux pour plusieurs combinaisons overbought/oversold.
Python@njit(parallel=True, cache=True, nogil=True, fastmath=True)
def rsi_signals_sweep(
    close: np.ndarray,
    periods: np.ndarray,
    overbought_levels: np.ndarray,   # ex. [70, 75, 80]
    oversold_levels: np.ndarray      # ex. [30, 25, 20]
) -> np.ndarray:
    n_periods = len(periods)
    n_ob = len(overbought_levels)
    n_os = len(oversold_levels)
    signals = np.empty((n_periods, n_ob, n_os, len(close)), dtype=np.int8)

    for p in prange(n_periods):
        for ob in prange(n_ob):
            for os in prange(n_os):
                period = int(periods[p])
                ob_lvl = overbought_levels[ob]
                os_lvl = oversold_levels[os]

                rsi = compute_rsi(close, period)
                sig = np.zeros(len(close), dtype=np.int8)
                sig[rsi > ob_lvl] = -1
                sig[rsi < os_lvl] = 1
                signals[p, ob, os, :] = sig

    return signals
Préparation hors Numba
Pythonclose_array = df['close'].values.astype(np.float64)
periods = np.array([10, 14, 21])

results = rsi_period_sweep(close_array, periods)
Ces exemples s’intègrent facilement dans indicators/rsi.py ou une stratégie RSI. Quel cas priorisez-vous (sweep simple, multi-period, signaux avancés) ? Besoin d’intégration avec divergence ou autre ?Exemples prange pour MACDExemples Numba prange pour MACD
Le MACD (fast EMA, slow EMA, signal line) a trois paramètres principaux à optimiser : fast_period, slow_period, signal_period. prange excelle pour paralleliser les sweeps ou multi-configs.
Configuration optimale (réutilisable) :
Pythonfrom numba import njit, prange
import numpy as np

@njit(cache=True, nogil=True, fastmath=True, parallel=True)
def fonction(...):
    ...
1. Sweep de paramètres MACD (grid search)
Parallelisation sur combinaisons fast/slow/signal.
Python@njit(parallel=True, cache=True, nogil=True, fastmath=True)
def macd_grid_sweep(
    close: np.ndarray,
    fast_periods: np.ndarray,    # ex. [8, 12, 16]
    slow_periods: np.ndarray,    # ex. [21, 26, 30]
    signal_periods: np.ndarray   # ex. [9, 12]
) -> np.ndarray:
    n_fast = len(fast_periods)
    n_slow = len(slow_periods)
    n_sig = len(signal_periods)
    results = np.empty((n_fast, n_slow, n_sig), dtype=np.float64)  # PnL ou Sharpe

    for i in prange(n_fast):
        for j in prange(n_slow):
            for k in prange(n_sig):
                fast = int(fast_periods[i])
                slow = int(slow_periods[j])
                sig = int(signal_periods[k])
                if fast >= slow:
                    results[i, j, k] = np.nan
                    continue
                macd_line, signal_line = compute_macd(close, fast, slow, sig)
                signals = np.where(macd_line > signal_line, 1, -1)  # crossover simple
                pnl = simulate_signals(close, signals)
                results[i, j, k] = pnl

    return results
2. Calcul multi-config MACD en parallèle
Calcule MACD line + signal pour plusieurs triplets de params.
Python@njit(parallel=True, cache=True, nogil=True, fastmath=True)
def multi_macd(
    close: np.ndarray,
    configs: np.ndarray           # Shape (n_configs, 3) → [fast, slow, signal]
) -> np.ndarray:
    n = len(close)
    n_configs = configs.shape[0]
    macd_lines = np.empty((n_configs, n), dtype=np.float64)
    signal_lines = np.empty((n_configs, n), dtype=np.float64)

    for cfg_idx in prange(n_configs):
        fast = int(configs[cfg_idx, 0])
        slow = int(configs[cfg_idx, 1])
        sig = int(configs[cfg_idx, 2])
        macd_line, signal_line = compute_macd(close, fast, slow, sig)
        macd_lines[cfg_idx, :] = macd_line
        signal_lines[cfg_idx, :] = signal_line

    return macd_lines, signal_lines
Fonction MACD de base (à placer avec les exemples) :
Python@njit(cache=True, nogil=True, fastmath=True)
def compute_macd(close: np.ndarray, fast_period: int, slow_period: int, signal_period: int) -> tuple:
    n = len(close)
    macd_line = np.empty(n)
    signal_line = np.empty(n)
    macd_line[:] = np.nan
    signal_line[:] = np.nan

    ema_fast = ema(close, fast_period)
    ema_slow = ema(close, slow_period)
    macd_line = ema_fast - ema_slow

    signal_line = ema(macd_line, signal_period)

    return macd_line, signal_line

@njit(cache=True, nogil=True, fastmath=True)
def ema(data: np.ndarray, period: int) -> np.ndarray:
    n = len(data)
    ema_arr = np.empty(n)
    ema_arr[:period] = np.nan
    multiplier = 2.0 / (period + 1)
    ema_arr[period-1] = np.mean(data[:period])
    for i in range(period, n):
        ema_arr[i] = (data[i] - ema_arr[i-1]) * multiplier + ema_arr[i-1]
    return ema_arr
3. Signaux MACD crossover en parallèle
Génère signaux pour plusieurs configs.
Python@njit(parallel=True, cache=True, nogil=True, fastmath=True)
def macd_signals_sweep(
    close: np.ndarray,
    configs: np.ndarray           # Shape (n_configs, 3)
) -> np.ndarray:
    n = len(close)
    n_configs = configs.shape[0]
    signals = np.empty((n_configs, n), dtype=np.int8)

    for cfg_idx in prange(n_configs):
        fast = int(configs[cfg_idx, 0])
        slow = int(configs[cfg_idx, 1])
        sig = int(configs[cfg_idx, 2])
        macd_line, signal_line = compute_macd(close, fast, slow, sig)
        sig_arr = np.zeros(n, dtype=np.int8)
        sig_arr[1:] = np.where(macd_line[1:] > signal_line[1:], 1,
                               np.where(macd_line[1:] < signal_line[1:], -1, 0))
        signals[cfg_idx, :] = sig_arr

    return signals
Préparation hors Numba
Pythonclose_array = df['close'].values.astype(np.float64)
configs = np.array([[8,21,9], [12,26,9], [16,35,12]])

results = macd_grid_sweep(close_array, np.array([8,12]), np.array([21,26]), np.array([9]))
Ces exemples s’intègrent dans indicators/macd.py ou une stratégie MACD cross. Quel cas priorisez-vous (sweep complet, signaux, histogramme ajouté) ? Besoin d’histogramme ou zero-line cross ?Optimisation EMA avec prangeExemples Numba prange pour EMA (Exponential Moving Average)
L’EMA est un calcul récursif séquentiel par nature (chaque valeur dépend de la précédente), donc pas directement parallélisable bar-par-bar. Cependant, prange est très efficace pour :

Calculer plusieurs EMA (différents periods) en parallèle
Sweeps de periods
EMA sur plusieurs séries indépendantes (multi-symboles ou multi-timeframes)

Configuration optimale (à réutiliser) :
Pythonfrom numba import njit, prange
import numpy as np

@njit(cache=True, nogil=True, fastmath=True, parallel=True)
def fonction(...):
    ...
1. Multi-period EMA en parallèle (le plus utile)
Calcule plusieurs EMA (différents periods) sur la même série en une seule passe.
Python@njit(parallel=True, cache=True, nogil=True, fastmath=True)
def multi_period_ema(
    close: np.ndarray,
    periods: np.ndarray           # ex. [10, 20, 50, 200]
) -> np.ndarray:
    n = len(close)
    n_periods = len(periods)
    ema_values = np.empty((n_periods, n), dtype=np.float64)

    for p_idx in prange(n_periods):
        period = int(periods[p_idx])
        multiplier = 2.0 / (period + 1.0)
        ema = np.empty(n)
        ema[:period] = np.nan

        # Initialisation avec SMA simple
        if n > period:
            ema[period-1] = np.mean(close[:period])
            for i in range(period, n):
                ema[i] = (close[i] - ema[i-1]) * multiplier + ema[i-1]

        ema_values[p_idx, :] = ema

    return ema_values
Gain : x3-8 selon nombre de periods (parfait pour EMA cross multi-niveaux).
2. Sweep de periods EMA (optimisation params)
Évalue performance (PnL) pour différents periods.
Python@njit(parallel=True, cache=True, nogil=True, fastmath=True)
def ema_period_sweep(
    close: np.ndarray,
    periods: np.ndarray           # ex. [5, 10, 20, 50, 100]
) -> np.ndarray:
    n_periods = len(periods)
    results = np.empty(n_periods, dtype=np.float64)  # PnL ou Sharpe

    for i in prange(n_periods):
        period = int(periods[i])
        ema = compute_ema(close, period)
        # Exemple simple : signal quand prix croise EMA
        signals = np.where(close > ema, 1, -1)
        pnl = simulate_signals(close, signals)
        results[i] = pnl

    return results

@njit(cache=True, nogil=True, fastmath=True)
def compute_ema(close: np.ndarray, period: int) -> np.ndarray:
    n = len(close)
    ema = np.empty(n)
    ema[:period] = np.nan
    if n <= period:
        return ema

    multiplier = 2.0 / (period + 1.0)
    ema[period-1] = np.mean(close[:period])
    for i in range(period, n):
        ema[i] = (close[i] - ema[i-1]) * multiplier + ema[i-1]
    return ema
3. EMA sur batch de séries indépendantes
Utile pour multi-symboles ou walk-forward segments.
Python@njit(parallel=True, cache=True, nogil=True, fastmath=True)
def batch_ema(
    datasets: list,               # Liste de np.ndarray (chaque série close)
    period: int
) -> np.ndarray:
    n_series = len(datasets)
    results = np.empty(n_series, dtype=np.object_)  # Chaque EMA est un array

    for i in prange(n_series):
        close = datasets[i]
        results[i] = compute_ema(close, period)

    return results
Préparation hors Numba
Pythonclose_array = df['close'].values.astype(np.float64)
periods = np.array([10, 20, 50, 200])

emas = multi_period_ema(close_array, periods)
Ces exemples s’intègrent directement dans indicators/ema.py. Le plus impactant est le multi-period (cas réel EMA cross ou MACD).
Quel cas priorisez-vous (multi-period, sweep, batch) ? Besoin d’intégration avec crossover ou autre stratégie spécifique ?Intégration EMA crossover avec prangeIntégration EMA Crossover avec prange
L’EMA crossover (fast EMA croise slow EMA) est une stratégie classique avec deux paramètres : fast_period et slow_period. prange est idéal pour paralleliser le sweep de ces combinaisons (grid search indépendant → scaling excellent sur multi-cœurs).
Configuration optimale (à copier dans votre module) :
Pythonfrom numba import njit, prange
import numpy as np

@njit(cache=True, nogil=True, fastmath=True, parallel=True)
def fonction(...):
    ...
1. Sweep complet EMA crossover (grid search parallelisé)
Parallelisation nested sur fast × slow periods → évalue PnL pour chaque paire.
Python@njit(parallel=True, cache=True, nogil=True, fastmath=True)
def ema_crossover_grid_sweep(
    close: np.ndarray,
    fast_periods: np.ndarray,    # ex. [5, 10, 15, 20]
    slow_periods: np.ndarray     # ex. [30, 50, 100, 200]
) -> np.ndarray:
    n_fast = len(fast_periods)
    n_slow = len(slow_periods)
    results = np.empty((n_fast, n_slow), dtype=np.float64)  # PnL ou Sharpe

    for i in prange(n_fast):
        for j in prange(n_slow):  # nested prange → parallelisation double niveau
            fast = int(fast_periods[i])
            slow = int(slow_periods[j])
            if fast >= slow:
                results[i, j] = np.nan
                continue

            ema_fast = compute_ema(close, fast)
            ema_slow = compute_ema(close, slow)

            # Signaux crossover
            signals = np.zeros(len(close), dtype=np.int8)
            signals[1:] = np.where(
                (ema_fast[:-1] < ema_slow[:-1]) & (ema_fast[1:] > ema_slow[1:]), 1,   # long
                np.where((ema_fast[:-1] > ema_slow[:-1]) & (ema_fast[1:] < ema_slow[1:]), -1, 0)  # short
            )

            pnl = simulate_signals(close, signals)
            results[i, j] = pnl

    return results
2. Fonctions auxiliaires (EMA + simulation)
À placer dans le même fichier (déjà optimisées).
Python@njit(cache=True, nogil=True, fastmath=True)
def compute_ema(close: np.ndarray, period: int) -> np.ndarray:
    n = len(close)
    ema = np.empty(n)
    ema[:period] = np.nan
    if n <= period:
        return ema

    multiplier = 2.0 / (period + 1.0)
    ema[period-1] = np.mean(close[:period])
    for i in range(period, n):
        ema[i] = (close[i] - ema[i-1]) * multiplier + ema[i-1]
    return ema

@njit(cache=True, nogil=True, fastmath=True)
def simulate_signals(close: np.ndarray, signals: np.ndarray) -> float:
    # Simulation simplifiée : PnL cumulatif (sans frais/slippage)
    returns = np.diff(close) / close[:-1]
    strategy_returns = returns * signals[:-1]
    return np.prod(1 + strategy_returns) - 1  # Return total
Préparation et appel (hors Numba)
Pythonclose_array = df['close'].values.astype(np.float64)
fasts = np.array([5, 8, 10, 12, 15])
slows = np.array([30, 50, 100, 150, 200])

results_grid = ema_crossover_grid_sweep(close_array, fasts, slows)

# Trouver meilleur
best_i, best_j = np.unravel_index(np.nanargmax(results_grid), results_grid.shape)
print(f"Meilleur: fast={fasts[best_i]}, slow={slows[best_j]}, PnL={results_grid[best_i, best_j]:.2%}")
Gains attendus : Sur 20×20 = 400 combos → x5-15 vs séquentiel (selon cœurs).
Intégrez cela dans strategies/ema_cross.py ou sweep_numba.py. Besoin d’ajouter frais, position sizing, ou filtre trend ? Quelle grille de periods utilisez-vous typiquement ?Quels sont les principaux fichiers Concerné par L'intégration de prange En dehors de ceux cités Dans cette conversationPrincipaux fichiers concernés par l’intégration de prange
L’intégration de prange (parallelisation Numba) cible principalement les fichiers contenant :

Des boucles lourdes sur combinaisons de paramètres (sweeps/grid search)
Des calculs indépendants multi-params ou multi-séries (indicateurs, simulations batchées)
Des sections déjà décorées @njit (où ajouter parallel=True + prange est trivial et impactant)

En excluant ceux déjà détaillés dans nos exemples (ema.py, macd.py, rsi.py, bollinger.py, ema_cross.py), voici les fichiers prioritaires du projet backtest_core :
1. Fichiers cœur du moteur (impact maximal)

backtest/sweep_numba.py
Sweep paramétrique Numba pur → boucle principale sur combos indépendants → remplacer range par prange (nested si grid multi-dim).
backtest/simulator_fast.py
Simulation bar-par-bar vectorisée → parallelisation possible sur batchs (multi-strats ou segments walk-forward).
backtest/execution_fast.py
Exécution accélérée → souvent appelée en boucle dans sweeps → gains sur multi-runs.
backtest/worker.py
Workers multiprocessing → synergie avec nogil=True + prange interne (libère GIL).

2. Autres indicateurs complexes (boucles internes parallélisables)

indicators/supertrend.py
Calculs ATR + trend multiplicateur → sweep sur multiplier/period.
indicators/ichimoku.py
Multi-lignes (9/26/52 periods) → calcul parallèle des composants.
indicators/atr.py
Base pour beaucoup de stratégies → multi-period en prange.
indicators/adx.py
DX/ADX multi-period → parallèle sur windows.
indicators/donchian.py ou keltner.py
Channel-based → similaire Bollinger, sweep facile.

3. Stratégies combinées

strategies/bollinger_atr.py (et v2/v3)
Bollinger + ATR filter → sweep nested (period, mult, atr_period).
strategies/fvg_strategy.py
Fair Value Gaps → détections multiples → parallèle sur thresholds.

Recommandations rapides

Priorisez sweep_numba.py et simulator_fast.py : gains x3-10 sur sweeps > 1000 combos.
Ajoutez systématiquement parallel=True aux @njit existants, puis remplacez les boucles externes par prange.
Testez avec NUMBA_NUM_THREADS élevé (vos 64 Go RAM supportent bien).

Quel fichier voulez-vous cibler en premier pour un exemple concret d’intégration prange ? (ex. sweep_numba.py ou supertrend.py)Et si toutes ces applications, si toutes ces améliorations Était opérationnel sur le code. Tu estimerais Admettons pour un gros sweet avec 5000000 de combinaisons. Sur 150000 bar Une vitesse en terme de run par 2nde, à combien ?Estimation de vitesse pour un sweep de 5 000 000 combinaisons sur 150 000 bars
Avec toutes les optimisations Numba/prange appliquées (parallel=True, fastmath, nogil, prange nested, TBB threading, cache=True), sur votre setup CPU (beaucoup de cœurs + 64 Go RAM), voici une estimation réaliste.
Hypothèses

Stratégie moyenne (ex. EMA cross, MACD, Bollinger simple) → quelques indicateurs légers, pas de Monte Carlo ou features très lourdes.
150 000 bars → série longue mais gérable en mémoire (pré-extraite en np.ndarray).
Chaque combinaison = 1 simulation complète indépendante.
Hardware : ~24-32 cœurs logiques (typique haut de gamme 2026), RAM abondante.

Vitesse estimée
~8 000 à 15 000 runs par seconde (combinaisons évaluées/sec).

Conservateur : 8 000–10 000 runs/sec (stratégie avec 3-4 indicateurs).
Optimiste : 12 000–15 000 runs/sec (stratégie légère + scaling parfait).

Temps total pour 5M combos :

~5–10 minutes (300–600 sec).

Facteurs d'influence

Si stratégie plus lourde (Ichimoku, multi-indicateurs) → ~4 000–8 000 runs/sec.
Si grid très nested mais bien parallélisé → proche du haut de fourchette.
Gains viennent surtout de prange + variables env optimales.

Variables d’environnement recommandées (max scaling)




















VariableValeur recommandéeEffetNUMBA_NUM_THREADS24Utilise tous vos cœurs logiquesNUMBA_THREADING_LAYERtbbMeilleur scaling que OpenMP (souvent +20-30%)
Commandes pour les définir
PowerShell
text$env:NUMBA_NUM_THREADS="24"
$env:NUMBA_THREADING_LAYER="tbb"
python -m cli.__main__ ...
CMD
textset NUMBA_NUM_THREADS=24
set NUMBA_THREADING_LAYER=tbb
python -m cli.__main__ ...
Bash/Linux
textexport NUMBA_NUM_THREADS=24
export NUMBA_THREADING_LAYER=tbb
python -m cli.__main__ ...
Testez d’abord sur un petit sweep (10k combos) pour valider le scaling réel sur votre machine → ajustez NUMBA_NUM_THREADS au nombre de cœurs physiques (pas hyper-threading pour TBB).
Quelle stratégie exacte visez-vous pour ce sweep massif ? Je peux affiner l’estimation.