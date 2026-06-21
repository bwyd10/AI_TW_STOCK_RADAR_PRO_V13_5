# -*- coding: utf-8 -*-
"""
AI台股雷達 PRO v15.2｜世界冠軍版
data_provider.py 完整修正版

重點修正：
1. 修正 Streamlit Cloud 上櫃股票池顯示 0 的問題。
2. get_isin_stocks() 改用 requests 抓 HTML，再交給 pandas.read_html 解析。
3. get_tpex_stocks() 使用多來源備援：
   - TPEx 公司基本資料 OpenAPI
   - TPEx 上櫃收盤行情 OpenAPI
   - ISIN strMode=4
4. 保留原本 app.py 相容函式：
   - get_stock_universe(include_twse=True, include_tpex=True)
   - get_price_data(stock_id, market, period="2y")
   - get_market_index(period="2y")
   - get_institutional_range(days=10)
"""

from datetime import datetime, timedelta
import time
import re

import pandas as pd
import requests
import streamlit as st
import yfinance as yf

from config import INDUSTRY_CODE_MAP, THEME_MAP, THEME_GROUP_MAP
from utils import clean_num, normalize_industry, yf_symbol, ymd_date, roc_date


HEADERS = {
    "User-Agent": "Mozilla/5.0",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,application/json,text/plain,*/*;q=0.8",
}


# =========================================================
# 共用工具
# =========================================================

def _empty_stock_df():
    return pd.DataFrame(
        columns=[
            "stock_id",
            "stock_name",
            "market",
            "industry",
        ]
    )


def _normalize_stock_rows(df, market):
    if df is None or df.empty:
        return _empty_stock_df()

    out = df.copy()

    if "stock_id" not in out.columns:
        return _empty_stock_df()

    if "stock_name" not in out.columns:
        out["stock_name"] = out["stock_id"]

    if "industry" not in out.columns:
        out["industry"] = "未分類"

    out["stock_id"] = out["stock_id"].astype(str).str.strip()
    out = out[out["stock_id"].str.match(r"^\d{4}$")]

    if out.empty:
        return _empty_stock_df()

    out["stock_name"] = out["stock_name"].astype(str).str.strip()
    out["market"] = market
    out["industry"] = out["industry"].apply(
        lambda x: normalize_industry(x, INDUSTRY_CODE_MAP)
    )

    return (
        out[["stock_id", "stock_name", "market", "industry"]]
        .drop_duplicates("stock_id")
        .reset_index(drop=True)
    )


def _parse_isin_name(value):
    """
    ISIN 第一欄常見格式：
    2330　台積電
    5536　聖暉*
    """
    s = str(value).replace("\u3000", " ").strip()

    m = re.match(r"^(\d{4})\s+(.+)$", s)
    if m:
        return m.group(1), m.group(2).strip()

    if len(s) >= 5 and s[:4].isdigit():
        return s[:4], s[4:].strip()

    return None, None


def _parse_isin_tables(tables, market_name):
    if not tables:
        return _empty_stock_df()

    df = tables[0].copy()

    if df.empty:
        return _empty_stock_df()

    try:
        df.columns = df.iloc[0]
        df = df.iloc[1:].copy()
    except Exception:
        pass

    first_col = df.columns[0]
    industry_col = "產業別" if "產業別" in df.columns else None

    rows = []

    for _, r in df.iterrows():
        stock_id, stock_name = _parse_isin_name(r.get(first_col, ""))

        if not stock_id:
            continue

        industry = r.get(industry_col, "未分類") if industry_col else "未分類"

        rows.append(
            {
                "stock_id": stock_id,
                "stock_name": stock_name,
                "industry": industry,
            }
        )

    return _normalize_stock_rows(pd.DataFrame(rows), market_name)


# =========================================================
# ISIN 股票池備援
# =========================================================

@st.cache_data(ttl=60 * 60 * 24, show_spinner=False)
def get_isin_stocks(str_mode, market_name):
    """
    strMode=2：上市
    strMode=4：上櫃

    這裡使用 requests 先抓 HTML，再 read_html。
    這比 pd.read_html(url) 在 Streamlit Cloud 上更穩。
    """
    url = f"https://isin.twse.com.tw/isin/C_public.jsp?strMode={str_mode}"

    # 方法一：requests.text
    try:
        res = requests.get(url, headers=HEADERS, timeout=25)
        res.raise_for_status()
        res.encoding = "big5"

        tables = pd.read_html(res.text)
        parsed = _parse_isin_tables(tables, market_name)

        if not parsed.empty:
            return parsed

    except Exception:
        pass

    # 方法二：requests.content
    try:
        res = requests.get(url, headers=HEADERS, timeout=25)
        res.raise_for_status()

        tables = pd.read_html(res.content, encoding="big5")
        parsed = _parse_isin_tables(tables, market_name)

        if not parsed.empty:
            return parsed

    except Exception:
        pass

    # 方法三：pandas 直接讀 URL
    try:
        tables = pd.read_html(url, encoding="big5")
        parsed = _parse_isin_tables(tables, market_name)

        if not parsed.empty:
            return parsed

    except Exception:
        pass

    return _empty_stock_df()


# =========================================================
# 上市股票
# =========================================================

@st.cache_data(ttl=60 * 60 * 12, show_spinner=False)
def get_twse_stocks():
    """
    上市股票優先使用 TWSE OpenAPI，失敗時改用 ISIN strMode=2。
    """
    try:
        url = "https://openapi.twse.com.tw/v1/opendata/t187ap03_L"
        res = requests.get(url, headers=HEADERS, timeout=25)
        res.raise_for_status()

        df = pd.DataFrame(res.json())

        if not df.empty and all(c in df.columns for c in ["公司代號", "公司簡稱", "產業別"]):
            out = df[["公司代號", "公司簡稱", "產業別"]].copy()
            out.columns = ["stock_id", "stock_name", "industry"]

            parsed = _normalize_stock_rows(out, "上市")

            if not parsed.empty:
                return parsed

    except Exception:
        pass

    return get_isin_stocks(str_mode=2, market_name="上市")


# =========================================================
# 上櫃股票
# =========================================================

@st.cache_data(ttl=60 * 60 * 12, show_spinner=False)
def get_tpex_stocks():
    """
    上櫃股票多來源備援：
    1. TPEx 公司基本資料 OpenAPI
    2. TPEx 上櫃收盤行情 OpenAPI
    3. ISIN strMode=4
    """

    # 來源一：TPEx 公司基本資料
    try:
        url = "https://www.tpex.org.tw/openapi/v1/mopsfin_t187ap03_O"
        res = requests.get(url, headers=HEADERS, timeout=25)
        res.raise_for_status()

        df = pd.DataFrame(res.json())

        if not df.empty:
            cols = list(df.columns)

            code_col = next(
                (
                    c
                    for c in cols
                    if c
                    in [
                        "公司代號",
                        "SecuritiesCompanyCode",
                        "Code",
                        "代號",
                        "有價證券代號",
                    ]
                ),
                None,
            )

            name_col = next(
                (
                    c
                    for c in cols
                    if c
                    in [
                        "公司簡稱",
                        "公司名稱",
                        "CompanyName",
                        "Name",
                        "名稱",
                        "有價證券名稱",
                    ]
                ),
                None,
            )

            industry_col = next(
                (
                    c
                    for c in cols
                    if c in ["產業別", "Industry", "產業"]
                ),
                None,
            )

            if code_col is None:
                for c in cols:
                    if df[c].astype(str).str.match(r"^\d{4}$").any():
                        code_col = c
                        break

            if name_col is None:
                for c in cols:
                    if c != code_col:
                        name_col = c
                        break

            if industry_col is None:
                df["industry_tmp"] = "未分類"
                industry_col = "industry_tmp"

            if code_col and name_col:
                out = df[[code_col, name_col, industry_col]].copy()
                out.columns = ["stock_id", "stock_name", "industry"]

                parsed = _normalize_stock_rows(out, "上櫃")

                if not parsed.empty:
                    return parsed

    except Exception:
        pass

    # 來源二：TPEx 上櫃收盤行情
    try:
        url = "https://www.tpex.org.tw/openapi/v1/tpex_mainboard_daily_close_quotes"
        res = requests.get(url, headers=HEADERS, timeout=25)
        res.raise_for_status()

        df = pd.DataFrame(res.json())

        if not df.empty:
            cols = list(df.columns)

            code_col = next(
                (
                    c
                    for c in cols
                    if c
                    in [
                        "代號",
                        "SecuritiesCompanyCode",
                        "Code",
                        "股票代號",
                        "有價證券代號",
                    ]
                ),
                None,
            )

            name_col = next(
                (
                    c
                    for c in cols
                    if c
                    in [
                        "名稱",
                        "CompanyName",
                        "Name",
                        "股票名稱",
                        "有價證券名稱",
                    ]
                ),
                None,
            )

            if code_col is None:
                for c in cols:
                    if df[c].astype(str).str.match(r"^\d{4}$").any():
                        code_col = c
                        break

            if name_col is None:
                possible = [c for c in cols if c != code_col]
                name_col = possible[0] if possible else code_col

            if code_col and name_col:
                out = df[[code_col, name_col]].copy()
                out.columns = ["stock_id", "stock_name"]
                out["industry"] = "未分類"

                parsed = _normalize_stock_rows(out, "上櫃")

                if not parsed.empty:
                    return parsed

    except Exception:
        pass

    # 來源三：ISIN 上櫃清單
    return get_isin_stocks(str_mode=4, market_name="上櫃")


# =========================================================
# 股票池
# =========================================================

@st.cache_data(ttl=60 * 60 * 12, show_spinner=False)
def get_stock_universe(include_twse=True, include_tpex=True):
    """
    取得上市＋上櫃股票池。

    PRO v15.2 修正重點：
    Streamlit Cloud 有時 TPEx OpenAPI 會回空資料，導致「上櫃 = 0」。
    這裡強制使用多層備援：
    1. get_tpex_stocks() 原本的 TPEx OpenAPI + 收盤行情 + ISIN 備援
    2. 如果合併後仍沒有任何上櫃股票，再直接呼叫 ISIN strMode=4 補回上櫃清單
    """
    frames = []

    twse_df = pd.DataFrame()
    tpex_df = pd.DataFrame()

    if include_twse:
        twse_df = get_twse_stocks()
        if twse_df is not None and not twse_df.empty:
            frames.append(twse_df)

    if include_tpex:
        tpex_df = get_tpex_stocks()

        # 關鍵修正：若 TPEx OpenAPI 失敗，直接使用 ISIN 上櫃清單備援。
        if tpex_df is None or tpex_df.empty:
            tpex_df = get_isin_stocks(str_mode=4, market_name="上櫃")

        if tpex_df is not None and not tpex_df.empty:
            frames.append(tpex_df)

    frames = [f for f in frames if f is not None and not f.empty]

    if not frames:
        return pd.DataFrame(
            columns=[
                "stock_id",
                "stock_name",
                "market",
                "industry",
                "theme",
                "theme_group",
            ]
        )

    df = pd.concat(frames, ignore_index=True)

    # 如果上市、上櫃有同代號，優先保留原本市場資料；一般股票不會重複。
    df = df.drop_duplicates(["stock_id", "market"])

    # 二次保險：使用者勾選上櫃，但合併結果仍沒有上櫃時，補抓 ISIN。
    if include_tpex and (df["market"] == "上櫃").sum() == 0:
        backup = get_isin_stocks(str_mode=4, market_name="上櫃")
        if backup is not None and not backup.empty:
            df = pd.concat([df, backup], ignore_index=True).drop_duplicates(["stock_id", "market"])

    df["stock_id"] = df["stock_id"].astype(str)
    df["industry"] = df["industry"].apply(
        lambda x: normalize_industry(x, INDUSTRY_CODE_MAP)
    )

    df["theme"] = df.apply(
        lambda r: THEME_MAP.get(str(r["stock_id"]), r["industry"]),
        axis=1,
    )

    df["theme_group"] = df["theme"].map(THEME_GROUP_MAP).fillna(df["theme"])

    return df.sort_values(["market", "stock_id"]).reset_index(drop=True)


# =========================================================
# 股價資料
# =========================================================

@st.cache_data(ttl=60 * 60 * 4, show_spinner=False)
def get_price_data(stock_id, market, period="2y"):
    try:
        df = yf.download(
            yf_symbol(stock_id, market),
            period=period,
            interval="1d",
            auto_adjust=False,
            progress=False,
            threads=False,
        )

        if df.empty:
            return pd.DataFrame()

        if isinstance(df.columns, pd.MultiIndex):
            df.columns = df.columns.get_level_values(0)

        df = df.rename(
            columns={
                "Open": "open",
                "High": "high",
                "Low": "low",
                "Close": "close",
                "Volume": "volume",
            }
        )

        return df.reset_index().dropna(subset=["close", "volume"])

    except Exception:
        return pd.DataFrame()


@st.cache_data(ttl=60 * 60 * 4, show_spinner=False)
def get_market_index(period="2y"):
    try:
        df = yf.download(
            "^TWII",
            period=period,
            interval="1d",
            auto_adjust=False,
            progress=False,
            threads=False,
        )

        if df.empty:
            return pd.DataFrame()

        if isinstance(df.columns, pd.MultiIndex):
            df.columns = df.columns.get_level_values(0)

        df = df.rename(
            columns={
                "Open": "open",
                "High": "high",
                "Low": "low",
                "Close": "close",
                "Volume": "volume",
            }
        )

        return df.reset_index().dropna(subset=["close"])

    except Exception:
        return pd.DataFrame()


# =========================================================
# 法人資料
# =========================================================

@st.cache_data(ttl=60 * 60 * 4, show_spinner=False)
def get_twse_institutional_by_date(date_ymd):
    url = "https://www.twse.com.tw/rwd/zh/fund/T86"

    params = {
        "date": date_ymd,
        "selectType": "ALL",
        "response": "json",
    }

    try:
        js = requests.get(url, params=params, headers=HEADERS, timeout=25).json()
        data = js.get("data", [])
        fields = js.get("fields", [])

        if not data:
            return pd.DataFrame()

        df = pd.DataFrame(data, columns=fields)

        required = [
            "證券代號",
            "證券名稱",
            "外陸資買賣超股數(不含外資自營商)",
            "投信買賣超股數",
            "自營商買賣超股數",
        ]

        if not all(c in df.columns for c in required):
            return pd.DataFrame()

        out = df[required].copy()
        out.columns = [
            "stock_id",
            "stock_name",
            "foreign_net",
            "trust_net",
            "dealer_net",
        ]

        out["stock_id"] = out["stock_id"].astype(str).str.strip()
        out = out[out["stock_id"].str.match(r"^\d{4}$")]

        for c in ["foreign_net", "trust_net", "dealer_net"]:
            out[c] = out[c].apply(clean_num) / 1000

        out["market"] = "上市"
        out["date"] = date_ymd

        return out

    except Exception:
        return pd.DataFrame()


@st.cache_data(ttl=60 * 60 * 4, show_spinner=False)
def get_tpex_institutional_by_date(date_obj):
    date_roc = roc_date(date_obj)

    try:
        url = "https://www.tpex.org.tw/web/stock/3insti/daily_trade/3itrade_hedge_result.php"

        params = {
            "l": "zh-tw",
            "d": date_roc,
            "se": "EW",
            "t": "D",
        }

        js = requests.get(url, params=params, headers=HEADERS, timeout=25).json()
        data = js.get("aaData", [])

        rows = []

        for row in data:
            if len(row) < 11:
                continue

            stock_id = str(row[0]).strip()

            if not stock_id.isdigit() or len(stock_id) != 4:
                continue

            stock_name = str(row[1]).strip()
            foreign_net = clean_num(row[4]) / 1000 if len(row) > 4 else 0
            trust_net = clean_num(row[7]) / 1000 if len(row) > 7 else 0
            dealer_net = clean_num(row[10]) / 1000 if len(row) > 10 else 0

            rows.append(
                [
                    stock_id,
                    stock_name,
                    foreign_net,
                    trust_net,
                    dealer_net,
                ]
            )

        out = pd.DataFrame(
            rows,
            columns=[
                "stock_id",
                "stock_name",
                "foreign_net",
                "trust_net",
                "dealer_net",
            ],
        )

        if not out.empty:
            out["market"] = "上櫃"
            out["date"] = ymd_date(date_obj)
            return out

    except Exception:
        pass

    return pd.DataFrame()


@st.cache_data(ttl=60 * 60 * 4, show_spinner=False)
def get_institutional_range(days=10):
    frames = []
    today = datetime.now()

    for i in range(days):
        dt = today - timedelta(days=i)
        ymd = ymd_date(dt)

        twse = get_twse_institutional_by_date(ymd)

        if not twse.empty:
            frames.append(twse)

        tpex = get_tpex_institutional_by_date(dt)

        if not tpex.empty:
            frames.append(tpex)

        time.sleep(0.03)

    if not frames:
        return pd.DataFrame(
            columns=[
                "stock_id",
                "stock_name",
                "foreign_net",
                "trust_net",
                "dealer_net",
                "market",
                "date",
            ]
        )

    df = pd.concat(frames, ignore_index=True)
    df["stock_id"] = df["stock_id"].astype(str)

    return df
