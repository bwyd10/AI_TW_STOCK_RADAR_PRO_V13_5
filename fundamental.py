# -*- coding: utf-8 -*-
import numpy as np
import pandas as pd
import yfinance as yf
from utils import yf_symbol

def get_fundamental(stock_id, market):
    data = {
        "eps": np.nan, "eps_growth": np.nan, "free_cash_flow": np.nan,
        "dividend_rate": np.nan, "profit_margin": np.nan, "debt_to_equity": np.nan,
        "roic": np.nan, "roe": np.nan, "revenue_growth": np.nan, "gross_margin": np.nan,
        "market_cap": np.nan, "pe": np.nan, "forward_pe": np.nan, "peg": np.nan,
        "fundamental_note": "Yahoo財務資料不足",
    }
    try:
        ticker = yf.Ticker(yf_symbol(stock_id, market))
        info = ticker.info or {}
        data["eps"] = info.get("trailingEps", np.nan)
        data["free_cash_flow"] = info.get("freeCashflow", np.nan)
        data["dividend_rate"] = info.get("dividendRate", np.nan)
        data["debt_to_equity"] = info.get("debtToEquity", np.nan)
        data["market_cap"] = info.get("marketCap", np.nan)
        data["pe"] = info.get("trailingPE", np.nan)
        data["forward_pe"] = info.get("forwardPE", np.nan)
        data["peg"] = info.get("pegRatio", np.nan)
        for source, target in [
            ("profitMargins", "profit_margin"), ("returnOnCapital", "roic"),
            ("returnOnEquity", "roe"), ("revenueGrowth", "revenue_growth"),
            ("grossMargins", "gross_margin"), ("earningsQuarterlyGrowth", "eps_growth"),
        ]:
            v = info.get(source, np.nan)
            data[target] = v * 100 if pd.notna(v) else np.nan
        valid_count = sum(pd.notna(data[k]) for k in ["eps", "free_cash_flow", "profit_margin", "roic", "roe", "revenue_growth", "pe", "peg"])
        if valid_count >= 5: data["fundamental_note"] = "財務資料較完整"
        elif valid_count >= 2: data["fundamental_note"] = "財務資料部分缺漏"
    except Exception as e:
        data["fundamental_note"] = f"財務資料抓取失敗：{e}"
    return data

def fundamental_score(f):
    score = 0
    details = {}
    rules = [
        ("EPS > 0", f.get("eps"), lambda x: x > 0, 3),
        ("EPS成長 > 15%", f.get("eps_growth"), lambda x: x >= 15, 4),
        ("營收成長 > 10%", f.get("revenue_growth"), lambda x: x >= 10, 4),
        ("ROE > 15%", f.get("roe"), lambda x: x >= 15, 4),
        ("ROIC > 10%", f.get("roic"), lambda x: x >= 10, 4),
        ("淨利率 > 10%", f.get("profit_margin"), lambda x: x >= 10, 3),
        ("FCF > 0", f.get("free_cash_flow"), lambda x: x > 0, 2),
        ("PEG < 1.5", f.get("peg"), lambda x: 0 < x <= 1.5, 2),
        ("負債權益比 < 100", f.get("debt_to_equity"), lambda x: x < 100, 2),
    ]
    for name, val, fn, w in rules:
        if pd.isna(val):
            details[name] = "資料不足"
        else:
            ok = bool(fn(float(val)))
            details[name] = "Yes" if ok else "No"
            if ok: score += w
    return {"fundamental_score": min(25, score), "fundamental_details": details}
