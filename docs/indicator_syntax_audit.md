# Audit syntaxe indicateurs Builder

Date : 11/05/2026

## Principe retenu

Le code local reste la source de vérité d'exécution : `indicators.registry.calculate_indicator()` calcule les valeurs et `indicators/schema.py` décrit le contrat Builder. Les sources externes ci-dessous servent uniquement à vérifier les conventions de nommage et les signatures usuelles.

## Sources consultées

- TA-Lib Python, momentum indicators : https://ta-lib.github.io/ta-lib-python/func_groups/momentum_indicators.html
- TA-Lib Python, volatility indicators : https://ta-lib.github.io/ta-lib-python/func_groups/volatility_indicators.html
- TA-Lib Python, volume indicators : https://ta-lib.github.io/ta-lib-python/func_groups/volume_indicators.html
- TA-Lib Python, overlap studies : https://ta-lib.github.io/ta-lib-python/func_groups/overlap_studies.html
- Technical Analysis Library in Python (`ta`) : https://technical-analysis-library-in-python.readthedocs.io/en/stable/ta.html
- Pandas TA Classic indicators reference : https://xgboosted.github.io/pandas-ta-classic/indicators.html

## Décisions par famille

| Indicateur local | Syntaxe externe vérifiée | Syntaxe locale retenue | Décision |
|---|---|---|---|
| `adx` | TA-Lib : `ADX(high, low, close, timeperiod=14)` ; Pandas TA Classic expose aussi `dmp/dmn`. | `calculate_indicator("adx", df, {"period": 14}) -> {"adx", "plus_di", "minus_di"}` | Dict local conservé ; alias `adx_plus/adx_minus/+di/-di` mappés vers sous-clés. |
| `aroon` | TA-Lib : `AROON(high, low, timeperiod=14)` retourne down/up. | `{"aroon_up", "aroon_down"}` | Ordre local documenté, alias `up/down` acceptés. |
| `atr` | TA-Lib : `ATR(high, low, close, timeperiod=14)` ; `ta` : `AverageTrueRange(high, low, close, window=14)`. | Array `atr`, params `period`, `method`. | `atr_20` devient instance paramétrée ; `atr_sma_20` devient feature dérivée SMA d'ATR. |
| `bollinger` | TA-Lib : `BBANDS(close, timeperiod=5, nbdevup=2, nbdevdn=2)` retourne upper/middle/lower. | `{"upper", "middle", "lower"}`, params `period`, `std_dev`. | Aucun indicateur `bollinger_upper` séparé ; alias réécrits vers sous-clés. |
| `ema` / `sma` / `wma` | TA-Lib overlap : `EMA/SMA/WMA(close, timeperiod=30)`. | Arrays, params `period`. | Support rétrocompatible + instances `ema_21`, `ema_50`, `ema_200`, etc. |
| `macd` | TA-Lib : `MACD(close, fastperiod=12, slowperiod=26, signalperiod=9)` retourne macd/signal/hist. | `{"macd", "signal", "histogram"}` | Correction obligatoire : plus de `macd_line`/`signal_line` comme clés runtime ; elles sont des alias vers `macd`/`signal`. |
| `rsi` | TA-Lib : `RSI(close, timeperiod=14)`. | Array `rsi`, param `period`. | `rsi_period`, `rsi_overbought`, `rsi_oversold` classés paramètres, pas indicateurs. |
| `stochastic` / `stoch_rsi` | TA-Lib : `STOCH(...)` et `STOCHRSI(...)`. | `stochastic -> {"stoch_k","stoch_d"}` ; `stoch_rsi -> {"k","d","signal"}` | Alias `stoch`, `stoch_k`, `stoch_d` réécrits vers le dict local correct. |
| `cci` / `mfi` / `obv` / `roc` / `momentum` | TA-Lib documente CCI, MFI, OBV, ROC, MOM avec séries OHLCV selon cas. | Arrays locaux. | Restent des arrays ; aucun accès par sous-clé autorisé. |
| `vwap` | `ta` : `VolumeWeightedAveragePrice(high, low, close, volume, window=14)` ; Pandas TA Classic note un index DatetimeIndex. | Array `vwap`, params `period` optionnel. | Conserver syntaxe locale OHLCV + volume. |
| `donchian` | `ta` : `DonchianChannel(high, low, close, window=20)` ; Pandas TA Classic : `donchian`. | `{"upper","middle","lower"}`, params `period`. | Dict local conservé ; alias `dc_upper` etc. |
| `keltner` | `ta` : `KeltnerChannel(high, low, close, window=20, window_atr=10, multiplier=2)`. | `{"middle","upper","lower"}`, params `ema_period`, `atr_period`, `atr_multiplier`. | Dict local conservé ; alias `kelt_*` réécrits. |
| `ichimoku` | `ta` : `IchimokuIndicator(high, low, window1=9, window2=26, window3=52)`. | `{"tenkan","kijun","senkou_a","senkou_b","chikou","cloud_position"}` | Alias `tenkan_sen`, `kijun_sen`, `senkou_span_*` réécrits vers clés locales. |
| `supertrend` | Pandas TA Classic référence `supertrend`. | `{"supertrend","direction"}` | Interdire `upper/lower`; alias direction/value réécrits. |
| `vortex` | Pandas TA Classic référence `vortex`. | `{"vi_plus","vi_minus","signal","oscillator"}` | Alias `vortex_plus/minus`, `vi_plus/minus` réécrits. |
| `pivot_points` | Pandas TA Classic référence CPR/pivots ; conventions R/S classiques. | `{"pivot","r1","s1","r2","s2","r3","s3"}` | Dict local documenté. |
| `markov_switching` | Pas d'équivalent TA standard. | `{"regime","prob_regime_0","prob_regime_1","prob_regime_2","prob_regime_3"}` | Alias `markov_bull_probability` redirigé vers une clé locale réelle (`prob_regime_1`) mais documenté comme approximation de régime, pas vérité sémantique universelle. |
| `coppock_curve` / `trix` / `choppiness_index` / `kvo` | Pandas TA Classic référence `coppock`, `trix`, `chop`, `kvo`. | Arrays pour coppock/trix/chop ; dict `kvo -> {"kvo","signal"}`. | `coppock_curve_sma_5` supporté comme dérivé ; `kvo_signal` alias de sous-clé. |

## Alias explicitement non promus comme indicateurs

| Token | Classification | Raison |
|---|---|---|
| `rsi_overbought`, `rsi_oversold`, `rsi_period` | `parameter_alias` | Paramètres de stratégie/indicateur, lus via `params.get(...)`. |
| `adx_threshold`, `adx_filter`, `atr_mult`, `stop_atr_mult`, `tp_atr_mult` | `parameter_alias` | Seuils ou multiplicateurs, pas des séries calculées. |
| `ema_21`, `ema_50`, `ema_200`, `atr_20` | `parameterized_indicator_instance` | Instances nommées d'un indicateur canonique, calculées sous leur propre clé. |
| `macd_hist`, `macd_histogram`, `macd_line`, `signal_line` | `output_key_alias` | Alias de sous-clés de `indicators["macd"]`. |
| `tenkan_sen`, `kijun_sen` | `output_key_alias` | Alias de sous-clés de `indicators["ichimoku"]`. |
| `atr_sma_20`, `atr_sma`, `coppock_curve_sma_5` | `derived_feature` | Calculées après la source canonique, sous leur propre clé si demandées. |
| `obv_divergence_bullish` | `derived_feature` non supportée | Rejet explicite : une divergence doit être codée dans `generate_signals()` avec une logique vectorisée. |
| `markov_bull_probability` | `output_key_alias` | Alias toléré vers une probabilité de régime locale ; à utiliser comme filtre de régime, pas trigger rapide. |

## Contrat local ajouté

- Source centrale : `indicators/schema.py`.
- Fonctions de consommation : `canonicalize_indicator_alias`, `get_indicator_schema`, `get_output_key_alias`, `is_dict_indicator`, `get_builder_access_example`, `get_stable_alias_map`, `parse_parameterized_indicator_instance`, `parse_derived_feature`, `classify_indicator_token`.
- Chaque `IndicatorSchema` expose aussi `calculation_function`, dérivé du registre local (`indicators.registry.get_indicator(...).function`), pour relier l'inventaire Builder à la fonction de calcul réelle.
- Le moteur accepte maintenant `required_indicator_configs` et les instances nommées dans `required_indicators`.
- `fear_greed` conserve son paramètre `column` configurable, mais le contrat Builder déclare la dépendance par défaut `fear_greed` car le calcul local échoue si cette colonne n'est pas présente.
