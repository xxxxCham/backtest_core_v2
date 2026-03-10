# Leaderboard Builder - session 20260309_135835_based_on_the_user_s_requirements_and_pro

Objective: Based on the user's requirements and provided JSON data, we need to create a Python script that simulates backtesting for an existing trading strategy while calculating performance metrics. The specific constraints are to use standard libraries except third-party ones unless explicitly allowed (in this case, `numpy` and `pandas`).

Here’s how I will approach the problem:

1. **Generate or Load Price Data**: Since real price data is not provided, we'll generate simulated stock price data.
2. **Create Trading Signals**: We’ll use a simple Moving Average Crossover strategy as an example.
3. **Backtest and Compute Metrics**:
- Calculate key performance metrics like Sharpe Ratio, Win Rate, etc.

Below is the Python script that fulfills these requirements:

```python
import numpy as np
import pandas as pd

# Simulate stock price data (random walk)
np.random.seed(42)
dates = pd.date_range('1/1/2023', periods=500)
prices = 100 * np.cumsum(np.random.randn(len(dates))) + 100
df_prices = pd.DataFrame(prices, index=dates, columns=['Close'])

# Simple Moving Average Crossover Strategy
short_window = 40
long_window = 100

df_prices['Short_MA'] = df_prices['Close'].rolling(window=short_window).mean()
df_prices['Long_MA'] = df_prices['Close'].rolling(window=long_window).mean()

# Generate trading signals (buy/sell)
df_prices['Signal'] = 0
df_prices.loc[df_prices['Short_MA'] > df_prices['Long_MA'], 'Signal'] = 1  # Buy signal when short MA crosses above long MA
df_prices.loc[df_prices['Short_MA'] < df_prices['Long_MA'], 'Signal'] = -1  # Sell signal

# Backtesting with the signals
positions = pd.DataFrame(index=df_prices.index).fillna(0)
positions['Stock'] = df_prices['Signal'].shift()  # Shift to align trades properly
portfolio = positions.multiply(df_prices['Close'], axis=0)  # Multiply holdings by price
pos_diffs = positions.diff()  # Compute differences for trade entry and exit points

# Trading strategy performance metrics
df_portfolio = pd.DataFrame(index=df_prices.index).fillna(0)
df_portfolio['Holdings'] = (positions['Stock'].shift() * df_prices['Close'])
df_portfolio['Cash'] = 100 - (pos_diffs['Stock'] * df_prices['Close']).cumsum()
df_portfolio['Total'] = df_portfolio['Cash'] + df_portfolio['Holdings']
df_portfolio['Returns'] = df_portfolio['Total'].pct_change()

# Calculate Sharpe Ratio
sharpe_ratio = df_portfolio['Returns'].mean() / df_portfolio['Returns'].std() * np.sqrt(252)

# Win Rate Calculation
wins = len(df_portfolio[df_portfolio['Returns'] > 0])
losses = len(df_portfolio[df_portfolio['Returns'] < 0])
win_rate = wins / (wins + losses) if (wins + losses) != 0 else 0

print(f"Sharpe Ratio: {sharpe_ratio:.4f}")
print(f"Win Rate: {win_rate * 100:.2f}%")

# Output metrics in JSON format
metrics = {
"total_pnl": df_portfolio['Total'].iloc[-1] - 100,
"total_return_pct": (df_portfolio['Total'].iloc[-1] / 100) - 1,
"annualized_return": df_portfolio['Returns'].mean() * 252,  # Assuming 252 trading days in a year
"sharpe_ratio": sharpe_ratio,
"win_rate_pct": win_rate * 100
}

print(metrics)
```

### Explanation:
- **Simulated Price Data**: We generate a random walk of stock prices.
- **Moving Average Crossover Strategy**:
- Use a short moving average and long moving average to create signals when they cross over each other.
- **Backtesting**:
- Calculate holdings, cash, total equity, returns, Sharpe Ratio, and win rate based on these signals.
- **Performance Metrics**: We output the calculated metrics in JSON format.

This script meets the user's requirement of using `numpy` and `pandas`, while generating simulated price data to illustrate a simple trading strategy. The backtesting performance is evaluated based on typical metrics like Sharpe Ratio, win rate, etc., which are printed out at the end.
Status: failed
Best Sharpe: -20.000
Best Continuous Score: -100.00

| Rank | Iter | Score | Sharpe | Return % | Max DD % | PF | Trades | Decision | Category |
|---|---|---|---|---|---|---|---|---|---|
| 1 | 1 | -100.00 | -20.000 | -123.20% | -100.00% | 0.47 | 205 | continue | ruined |
| 2 | 2 | -100.00 | -20.000 | -227.86% | -100.00% | 0.51 | 438 | continue | ruined |
| 3 | 3 | -100.00 | -20.000 | -230.51% | -100.00% | 0.45 | 409 | continue | ruined |
| 4 | 4 | -100.00 | -20.000 | -124.80% | -100.00% | 0.50 | 233 | continue | ruined |
| 5 | 5 | -100.00 | -20.000 | -130.27% | -100.00% | 0.46 | 219 | continue | ruined |
| 6 | 6 | -100.00 | -20.000 | -122.60% | -100.00% | 0.48 | 211 | stop | ruined |