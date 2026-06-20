# -*- coding: utf-8 -*-
import numpy as np
import pandas as pd

def clean_num(x, default=0.0):
    if pd.isna(x):
        return default
    s = str(x).replace(",", "").replace("--", "0").replace("X", "0").replace("%", "").strip()
    try:
        return float(s)
    except Exception:
        return default

def roc_date(dt):
    return f"{dt.year - 1911}/{dt.month:02d}/{dt.day:02d}"

def ymd_date(dt):
    return dt.strftime("%Y%m%d")

def normalize_industry(value, industry_map):
    if pd.isna(value):
        return "未分類"
    s = str(value).strip()
    if s.endswith(".0"):
        s = s[:-2]
    if s.isdigit():
        s = s.zfill(2)
    return industry_map.get(s, s if s else "未分類")

def normalize_stock_id(stock_id):
    return str(stock_id).strip().zfill(4)[-4:]

def yf_symbol(stock_id, market):
    stock_id = normalize_stock_id(stock_id)
    return f"{stock_id}.TW" if market == "上市" else f"{stock_id}.TWO"

def grade(score):
    try:
        score = float(score)
    except Exception:
        score = 0
    if score >= 90:
        return "A+"
    if score >= 80:
        return "A"
    if score >= 70:
        return "B"
    if score >= 60:
        return "C"
    return "D"

def star_rating(score):
    try:
        score = float(score)
    except Exception:
        score = 0
    if score >= 90:
        return "★★★★★"
    if score >= 80:
        return "★★★★☆"
    if score >= 70:
        return "★★★☆☆"
    if score >= 60:
        return "★★☆☆☆"
    return "★☆☆☆☆"

def safe_round(x, digits=2):
    try:
        if pd.isna(x):
            return np.nan
        return round(float(x), digits)
    except Exception:
        return np.nan
