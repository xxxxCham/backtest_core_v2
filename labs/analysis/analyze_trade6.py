"""Analyse du trade #6 qui a duré 4.5 mois."""
from data.loader import load_ohlcv

# Charger les donnees
df = load_ohlcv('BTCUSDC', '30m', start='2019-06-06', end='2019-10-24')

# Calculer Bollinger
period = 20
std_dev = 2.0
close = df['close']
middle = close.rolling(period).mean()
std = close.rolling(period).std()
upper = middle + std_dev * std
lower = middle - std_dev * std

df['bb_upper'] = upper
df['bb_lower'] = lower
width = upper - lower

# Calculer bb_pos pour high et low
df['bb_pos_high'] = (df['high'] - lower) / width
df['bb_pos_low'] = (df['low'] - lower) / width

# Filtrer pendant le trade #6 (2019-06-06 18:00 -> 2019-10-23 16:00)
trade_start = '2019-06-06 18:00:00'
trade_end = '2019-10-23 16:00:00'

in_trade = df[(df.index >= trade_start) & (df.index <= trade_end)]

print(f'=== TRADE #6: {trade_start} -> {trade_end} ===')
print(f'Barres pendant le trade: {len(in_trade)}')
print()

# Combien de fois le TP (0.9) aurait du etre touche ?
tp_touches = (in_trade['bb_pos_high'] >= 0.9).sum()
print(f'Barres ou high >= 0.9 (TP aurait du trigger): {tp_touches}')

# Combien de fois le SL (-0.32) aurait du etre touche ?
sl_touches = (in_trade['bb_pos_low'] <= -0.32).sum()
print(f'Barres ou low <= -0.32 (SL aurait du trigger): {sl_touches}')

print()
bb_high_min = in_trade['bb_pos_high'].min()
bb_high_max = in_trade['bb_pos_high'].max()
bb_high_mean = in_trade['bb_pos_high'].mean()
print('=== Stats bb_pos_high pendant le trade ===')
print(f'Min: {bb_high_min:.3f}')
print(f'Max: {bb_high_max:.3f}')
print(f'Mean: {bb_high_mean:.3f}')

print()
print('=== Premieres 5 barres ou TP (>=0.9) aurait du etre touche ===')
tp_bars = in_trade[in_trade['bb_pos_high'] >= 0.9].head(5)
if len(tp_bars) > 0:
    print(tp_bars[['high', 'bb_upper', 'bb_lower', 'bb_pos_high']])
else:
    print('AUCUNE BARRE!')

print()
print('=== Premiere barre apres entree ===')
first_bar = in_trade.iloc[0:3]
print(first_bar[['close', 'high', 'low', 'bb_upper', 'bb_lower', 'bb_pos_high', 'bb_pos_low']])
