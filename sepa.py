# -*- coding: utf-8 -*-
import numpy as np
import pandas as pd
from technical import relative_strength

def trend_template(df):
    if df is None or len(df) < 252:
        return {"trend_score": 0, "trend_pass": False, "trend_pass_count": 0, "trend_details": {}, "high52": np.nan, "low52": np.nan}
    latest = df.iloc[-1]
    high52 = df["high"].tail(252).max()
    low52 = df["low"].tail(252).min()
    details = {
        "股價 > MA50": latest["close"] > latest["ma50"],
        "股價 > MA150": latest["close"] > latest["ma150"],
        "股價 > MA200": latest["close"] > latest["ma200"],
        "MA50 > MA150": latest["ma50"] > latest["ma150"],
        "MA150 > MA200": latest["ma150"] > latest["ma200"],
        "MA200上升30日": latest["ma200"] > df["ma200"].iloc[-30],
        "距52週高點25%內": latest["close"] >= high52 * 0.75,
        "高於52週低點30%以上": latest["close"] >= low52 * 1.30,
    }
    pass_count = sum(bool(v) for v in details.values())
    score = round(pass_count / 8 * 20, 2)
    return {
        "trend_score": score,
        "trend_pass": pass_count == 8,
        "trend_pass_count": pass_count,
        "trend_details": details,
        "high52": round(float(high52), 2),
        "low52": round(float(low52), 2),
    }

def detect_vcp(df, windows=(60, 45, 30, 15)):
    if df is None or len(df) < sum(windows):
        return {"vcp_score": 0, "vcp_pass": False, "contractions": [], "volume_dry_up": False}
    tail = df.tail(sum(windows)).copy()
    contractions = []
    pos = 0
    for w in windows:
        part = tail.iloc[pos:pos+w]
        hi = part["high"].max()
        lo = part["low"].min()
        c = (hi - lo) / hi * 100 if hi else np.nan
        contractions.append(round(float(c), 2) if pd.notna(c) else np.nan)
        pos += w
    valid = len(contractions) >= 4 and all(pd.notna(x) for x in contractions)
    contracting = valid and contractions[0] > contractions[1] > contractions[2] > contractions[3]
    recent_vol = df["volume"].tail(10).mean()
    prior_vol = df["volume"].tail(60).head(50).mean()
    volume_dry_up = bool(recent_vol < prior_vol * 0.8) if prior_vol and pd.notna(prior_vol) else False
    score = 0
    if contracting:
        score += 7
    if volume_dry_up:
        score += 3
    return {"vcp_score": score, "vcp_pass": score >= 7, "contractions": contractions, "volume_dry_up": volume_dry_up}

def breakout_score(df):
    if df is None or len(df) < 60:
        return {"breakout_score": 0, "breakout_pass": False, "breakout_signal": "資料不足"}
    latest = df.iloc[-1]
    high60_prev = df["high"].iloc[-61:-1].max()
    high120_prev = df["high"].iloc[-121:-1].max() if len(df) >= 121 else high60_prev
    vr50 = latest.get("volume_ratio_50", np.nan)
    score = 0
    signals = []
    if latest["close"] > high60_prev:
        score += 4
        signals.append("突破60日高")
    if latest["close"] > high120_prev:
        score += 3
        signals.append("突破120日高")
    if pd.notna(vr50) and vr50 >= 1.5:
        score += 3
        signals.append("量大於50日均量1.5倍")
    if pd.notna(vr50) and vr50 >= 2:
        score += 1
        signals.append("爆量2倍")
    score = min(10, score)
    return {"breakout_score": score, "breakout_pass": score >= 7, "breakout_signal": "、".join(signals) if signals else "未突破"}

def calculate_sepa(stock_df, market_df):
    trend = trend_template(stock_df)
    rs = relative_strength(stock_df, market_df, lookback=120)
    vcp = detect_vcp(stock_df)
    br = breakout_score(stock_df)
    total = trend["trend_score"] + rs["rs_score"] + vcp["vcp_score"] + br["breakout_score"]
    out = {}
    out.update(trend)
    out.update(rs)
    out.update(vcp)
    out.update(br)
    out["sepa_technical_score"] = round(float(total), 2)
    return out
