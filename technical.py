# -*- coding: utf-8 -*-
import numpy as np
import pandas as pd

def calculate_rsi(close, period=14):
    delta = close.diff()
    gain = delta.clip(lower=0)
    loss = -delta.clip(upper=0)
    avg_gain = gain.ewm(alpha=1 / period, adjust=False).mean()
    avg_loss = loss.ewm(alpha=1 / period, adjust=False).mean()
    rs = avg_gain / avg_loss.replace(0, np.nan)
    return 100 - (100 / (1 + rs))

def calculate_atr(df, period=14):
    high_low = df["high"] - df["low"]
    high_close = (df["high"] - df["close"].shift()).abs()
    low_close = (df["low"] - df["close"].shift()).abs()
    tr = pd.concat([high_low, high_close, low_close], axis=1).max(axis=1)
    return tr.ewm(alpha=1 / period, adjust=False).mean()

def add_indicators(df):
    df = df.copy()
    for n in [5, 10, 20, 50, 150, 200]:
        df[f"ma{n}"] = df["close"].rolling(n).mean()
    df["vol_ma20"] = df["volume"].rolling(20).mean()
    df["vol_ma50"] = df["volume"].rolling(50).mean()
    df["rsi"] = calculate_rsi(df["close"])
    df["atr"] = calculate_atr(df)
    df["atr_pct"] = df["atr"] / df["close"] * 100
    df["volume_ratio_20"] = df["volume"] / df["vol_ma20"]
    df["volume_ratio_50"] = df["volume"] / df["vol_ma50"]
    df["high_60"] = df["high"].rolling(60).max()
    df["high_120"] = df["high"].rolling(120).max()
    df["high_252"] = df["high"].rolling(252).max()
    df["low_252"] = df["low"].rolling(252).min()
    df["return_20d"] = df["close"].pct_change(20) * 100
    df["return_60d"] = df["close"].pct_change(60) * 100
    df["return_120d"] = df["close"].pct_change(120) * 100
    return df

def relative_strength(stock_df, market_df, lookback=120):
    if stock_df is None or market_df is None or len(stock_df) <= lookback or len(market_df) <= lookback:
        return {"rs_ratio": np.nan, "stock_return": np.nan, "market_return": np.nan, "rs_score": 0}
    stock_return = stock_df["close"].iloc[-1] / stock_df["close"].iloc[-lookback] - 1
    market_return = market_df["close"].iloc[-1] / market_df["close"].iloc[-lookback] - 1
    rs_ratio = np.nan if market_return == 0 else stock_return / market_return
    if pd.isna(rs_ratio):
        score = 0
    elif rs_ratio >= 2:
        score = 10
    elif rs_ratio >= 1.5:
        score = 8
    elif rs_ratio >= 1.2:
        score = 6
    elif rs_ratio >= 1:
        score = 4
    else:
        score = 0
    return {
        "rs_ratio": round(float(rs_ratio), 2) if pd.notna(rs_ratio) else np.nan,
        "stock_return": round(float(stock_return * 100), 2),
        "market_return": round(float(market_return * 100), 2),
        "rs_score": score,
    }
