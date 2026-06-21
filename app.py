# -*- coding: utf-8 -*-
import io
from datetime import datetime

import numpy as np
import pandas as pd
import streamlit as st

from config import APP_CAPTION, DEFAULT_WATCHLIST
from data_provider import (
    get_stock_universe,
    get_price_data,
    get_market_index,
    get_institutional_range,
)
from technical import add_indicators
from sepa import calculate_sepa
from chip import summarize_institutional
from fundamental import get_fundamental, fundamental_score
from advisor import generate_advisor_summary
from utils import grade, safe_round

APP_TITLE_V14 = "AI台股雷達 PRO v15.2｜世界冠軍版"

st.set_page_config(page_title=APP_TITLE_V14, page_icon="🏆", layout="wide")
st.title("🏆 AI台股雷達 PRO v15.2｜世界冠軍版")
st.caption("Minervini SEPA｜CANSLIM｜VCP｜RS強度｜法人籌碼｜極簡Excel決策報告")


# =========================================================
# 工具函式
# =========================================================

def _to_float(value, default=0.0):
    try:
        if value is None:
            return default
        if isinstance(value, str):
            value = value.replace(",", "").replace("%", "").strip()
            if value in ["", "-", "--", "nan", "None"]:
                return default
        value = float(value)
        if np.isnan(value) or np.isinf(value):
            return default
        return value
    except Exception:
        return default


def _yes(value):
    return str(value).strip().lower() in ["yes", "true", "1", "通過"]


def _trend_pass_count(value):
    try:
        return int(str(value).split("/")[0])
    except Exception:
        return 0


def calculate_breakout_distance(result):
    close = _to_float(result.get("收盤價"), 0)
    high52 = _to_float(result.get("52週高點"), 0)
    low52 = _to_float(result.get("52週低點"), 0)

    distance_high = np.nan
    rise_low = np.nan

    if close > 0 and high52 > 0:
        distance_high = round((high52 - close) / high52 * 100, 2)
    if close > 0 and low52 > 0:
        rise_low = round((close - low52) / low52 * 100, 2)

    return distance_high, rise_low


def calculate_minervini_score(result):
    """
    AI冠軍分數滿分100：
    Trend 30%、RS 20%、VCP 15%、法人 15%、EPS 10%、ROE 5%、營收 5%。
    """
    trend_pass = _yes(result.get("Trend通過"))
    trend_count = _trend_pass_count(result.get("Trend通過數"))
    rs = _to_float(result.get("RS強度"), 0)
    vcp_pass = _yes(result.get("VCP通過"))
    vcp_score_raw = _to_float(result.get("VCP分"), 0)
    chip_score_raw = _to_float(result.get("法人籌碼分"), 0)
    eps = _to_float(result.get("EPS"), 0)
    eps_growth = _to_float(result.get("EPS成長%"), 0)
    roe = _to_float(result.get("ROE%"), 0)
    revenue_growth = _to_float(result.get("營收成長%"), 0)

    trend_score = 30 if trend_pass else min(30, max(0, trend_count / 8 * 30))
    rs_score = min(20, max(0, (rs - 0.8) / 0.7 * 20))
    vcp_score = 15 if vcp_pass else min(15, max(0, vcp_score_raw / 15 * 15))
    chip_score = min(15, max(0, chip_score_raw / 20 * 15))

    if eps > 0 and eps_growth >= 20:
        eps_score = 10
    elif eps > 0 and eps_growth > 0:
        eps_score = 7
    elif eps > 0:
        eps_score = 5
    else:
        eps_score = 0

    roe_score = 5 if roe >= 17 else (3 if roe >= 10 else 0)
    revenue_score = 5 if revenue_growth >= 15 else (3 if revenue_growth > 0 else 0)

    total = trend_score + rs_score + vcp_score + chip_score + eps_score + roe_score + revenue_score
    return round(min(100, max(0, total)), 2)


def minervini_stage(result):
    score = _to_float(result.get("AI冠軍分數"), 0)
    trend = _yes(result.get("Trend通過"))
    vcp = _yes(result.get("VCP通過"))
    distance = _to_float(result.get("距52週高點%"), 999)

    if score >= 85 and trend and vcp:
        return "冠軍股候選"
    if score >= 75 and trend and distance <= 8:
        return "即將突破觀察"
    if score >= 65 and trend:
        return "強勢觀察"
    return "一般觀察"


def enrich_minervini_fields(result):
    distance_high, rise_low = calculate_breakout_distance(result)
    result["距52週高點%"] = distance_high
    result["距52週低點漲幅%"] = rise_low
    result["AI冠軍分數"] = calculate_minervini_score(result)
    result["Minervini階段"] = minervini_stage(result)
    return result


# =========================================================
# 側邊欄
# =========================================================

with st.sidebar:
    st.header("模式設定")
    mode = st.radio(
        "選擇模式",
        ["個股診斷", "冠軍股排行", "世界冠軍股掃描器"],
        index=0,
    )
    display_mode = st.radio("顯示模式", ["AI投資顧問版", "專業數據版"], index=0)

    st.divider()
    st.header("股票範圍")
    include_twse = st.checkbox("上市", value=True)
    include_tpex = st.checkbox("上櫃", value=True)

    st.divider()
    st.header("法人資料")
    institutional_days = st.slider("抓取最近幾天法人資料", 3, 20, 10, 1)

    st.divider()
    st.header("冠軍股排行設定")
    watchlist_text = st.text_area(
        "排行股票清單（每行一檔）",
        value=DEFAULT_WATCHLIST,
        height=160,
        help="冠軍股排行模式使用；Minervini掃描器可選全市場或自選清單。",
    )
    min_total_score = st.slider("最低 SEPA總分", 0, 100, 60, 5)

    st.divider()
    st.header("Minervini掃描設定")
    scan_scope = st.radio("掃描範圍", ["全市場", "自選清單"], index=0)
    max_scan_count = st.number_input(
        "最多掃描檔數（0=不限）",
        min_value=0,
        max_value=3000,
        value=0,
        step=50,
        help="全市場約1900檔，第一次掃描會比較久；若Streamlit Cloud逾時，可先設300或500分批掃。",
    )
    min_champion_score = st.slider("最低 AI冠軍分數", 0, 100, 75, 5)
    min_rs = st.slider("最低 RS強度", 0.5, 2.5, 1.05, 0.05)
    near_high_pct = st.slider("距52週高點以內%", 0, 50, 25, 1)
    min_roe = st.slider("最低 ROE%", 0, 40, 10, 1)
    min_revenue_growth = st.slider("最低營收成長%", -50, 100, 0, 5)
    min_chip_score = st.slider("最低法人籌碼分", 0, 30, 5, 1)
    require_trend = st.checkbox("必須通過 Trend Template", value=True)
    require_vcp = st.checkbox("必須通過 VCP", value=False)
    only_positive_eps = st.checkbox("EPS必須大於0", value=True)
    price_top_n = st.slider("三段股價各取前幾名", 3, 20, 10, 1)


# =========================================================
# 診斷核心
# =========================================================

@st.cache_data(ttl=60 * 60 * 4, show_spinner=False)
def diagnose_stock(stock_id, stock_info_dict, inst_df):
    stock_id = str(stock_id).strip()
    info = stock_info_dict.get(stock_id)
    if info is None:
        return None

    market = info["market"]
    price = get_price_data(stock_id, market)
    market_df = get_market_index()

    if price.empty or len(price) < 252:
        return {
            "股票代號": stock_id,
            "股票名稱": info["stock_name"],
            "市場": market,
            "錯誤": "股價資料不足，至少需要約252個交易日資料。",
        }

    price = add_indicators(price)
    market_df = add_indicators(market_df) if not market_df.empty else market_df
    latest = price.iloc[-1]

    sepa = calculate_sepa(price, market_df)
    chip = summarize_institutional(inst_df, stock_id)
    f = get_fundamental(stock_id, market)

    if pd.isna(f.get("pe")) and pd.notna(f.get("eps")) and f.get("eps", 0) > 0:
        f["pe"] = float(latest["close"]) / float(f["eps"])

    fs = fundamental_score(f)
    total_score = round(
        sepa["sepa_technical_score"] + chip["chip_score"] + fs["fundamental_score"],
        2,
    )

    strategy = "只觀察"
    if total_score >= 85 and sepa["trend_pass"] and chip["chip_score"] >= 15:
        strategy = "冠軍股候選，可等突破或回測小量"
    elif total_score >= 75 and sepa["trend_pass_count"] >= 6:
        strategy = "強勢觀察，等型態完成"
    elif total_score >= 65:
        strategy = "觀察名單"
    else:
        strategy = "暫不進場"

    result = {
        "日期": datetime.now().strftime("%Y-%m-%d"),
        "股票代號": stock_id,
        "股票名稱": info["stock_name"],
        "市場": market,
        "官方產業": info["industry"],
        "主流族群": info["theme"],
        "族群大類": info["theme_group"],
        "收盤價": safe_round(latest["close"]),
        "量比50日": safe_round(latest.get("volume_ratio_50", np.nan)),
        "RSI": safe_round(latest.get("rsi", np.nan)),
        "MA50": safe_round(latest["ma50"]),
        "MA150": safe_round(latest["ma150"]),
        "MA200": safe_round(latest["ma200"]),
        "ATR%": safe_round(latest.get("atr_pct", np.nan)),
        "52週高點": sepa.get("high52", np.nan),
        "52週低點": sepa.get("low52", np.nan),
        "SEPA技術分": sepa["sepa_technical_score"],
        "Trend分": sepa["trend_score"],
        "Trend通過數": f'{sepa["trend_pass_count"]}/8',
        "Trend通過": "Yes" if sepa["trend_pass"] else "No",
        "RS強度": sepa["rs_ratio"],
        "個股120日漲幅%": sepa["stock_return"],
        "大盤120日漲幅%": sepa["market_return"],
        "VCP分": sepa["vcp_score"],
        "VCP通過": "Yes" if sepa["vcp_pass"] else "No",
        "VCP收縮": " → ".join(map(str, sepa["contractions"])),
        "量縮": "Yes" if sepa["volume_dry_up"] else "No",
        "突破分": sepa["breakout_score"],
        "突破訊號": sepa["breakout_signal"],
        "法人籌碼分": chip["chip_score"],
        "法人日期": chip["latest_inst_date"],
        "外資買超張": chip["foreign_today"],
        "投信買超張": chip["trust_today"],
        "自營商買超張": chip["dealer_today"],
        "外資連買": chip["foreign_consecutive"],
        "投信連買": chip["trust_consecutive"],
        "三大法人同步買超": chip["three_institution_sync"],
        "外資投信同步": chip["foreign_trust_sync"],
        "籌碼訊號": chip["chip_signal"],
        "財務品質分": fs["fundamental_score"],
        "EPS": f["eps"],
        "EPS成長%": safe_round(f["eps_growth"]),
        "營收成長%": safe_round(f["revenue_growth"]),
        "ROE%": safe_round(f["roe"]),
        "ROIC%": safe_round(f["roic"]),
        "淨利率%": safe_round(f["profit_margin"]),
        "PE": safe_round(f["pe"]),
        "PEG": safe_round(f["peg"]),
        "FCF": f["free_cash_flow"],
        "負債權益比": safe_round(f["debt_to_equity"]),
        "財務備註": f["fundamental_note"],
        "SEPA總分": total_score,
        "等級": grade(total_score),
        "策略": strategy,
        "_trend_details": sepa["trend_details"],
        "_fundamental_details": fs["fundamental_details"],
    }

    return enrich_minervini_fields(result)


# =========================================================
# 畫面渲染
# =========================================================

def render_advisor(result):
    advisor = generate_advisor_summary(result)
    st.subheader("🏆 AI投資顧問")
    a1, a2, a3, a4 = st.columns([2, 1, 1, 1])
    with a1:
        st.markdown(f"## {advisor['stars']}")
        st.markdown(f"### AI評級：{advisor['rating']}")
    with a2:
        st.metric("SEPA總分", result["SEPA總分"])
    with a3:
        st.metric("AI冠軍分數", result.get("AI冠軍分數", 0))
    with a4:
        st.metric("投資建議", advisor["action"])
    st.info(advisor["comment"])

    st.subheader("🚦 五大燈號")
    l1, l2, l3, l4, l5 = st.columns(5)
    l1.metric("財務", advisor["financial"])
    l2.metric("成長", advisor["growth"])
    l3.metric("趨勢", advisor["trend"])
    l4.metric("法人", advisor["chip"])
    l5.metric("風險", advisor["risk"])

    st.subheader("📈 AI操作建議")
    st.success("進場建議：" + advisor["entry"])
    st.warning("停損建議：" + advisor["stop_loss"])
    st.info("停利建議：" + advisor["take_profit"])


def render_professional(result):
    st.subheader("📊 專業數據")
    c1, c2, c3, c4, c5 = st.columns(5)
    c1.metric("SEPA技術分", result["SEPA技術分"])
    c2.metric("AI冠軍分數", result.get("AI冠軍分數", 0))
    c3.metric("法人籌碼分", result["法人籌碼分"])
    c4.metric("財務品質分", result["財務品質分"])
    c5.metric("距52週高點%", result.get("距52週高點%", np.nan))

    with st.expander("完整資料表", expanded=False):
        main_cols = [k for k in result.keys() if not k.startswith("_")]
        st.dataframe(pd.DataFrame([result])[main_cols], use_container_width=True, hide_index=True)

    col_a, col_b = st.columns(2)
    with col_a:
        st.subheader("Trend Template 明細")
        st.dataframe(
            pd.DataFrame([
                {"條件": k, "是否通過": "Yes" if v else "No"}
                for k, v in result["_trend_details"].items()
            ]),
            use_container_width=True,
            hide_index=True,
        )
    with col_b:
        st.subheader("財務條件明細")
        st.dataframe(
            pd.DataFrame([
                {"條件": k, "結果": v}
                for k, v in result["_fundamental_details"].items()
            ]),
            use_container_width=True,
            hide_index=True,
        )


def pass_minervini_filter(r):
    if r is None or "錯誤" in r:
        return False
    if _to_float(r.get("AI冠軍分數"), 0) < min_champion_score:
        return False
    if _to_float(r.get("SEPA總分"), 0) < min_total_score:
        return False
    if _to_float(r.get("RS強度"), 0) < min_rs:
        return False
    if _to_float(r.get("距52週高點%"), 999) > near_high_pct:
        return False
    if _to_float(r.get("ROE%"), 0) < min_roe:
        return False
    if _to_float(r.get("營收成長%"), 0) < min_revenue_growth:
        return False
    if _to_float(r.get("法人籌碼分"), 0) < min_chip_score:
        return False
    if require_trend and not _yes(r.get("Trend通過")):
        return False
    if require_vcp and not _yes(r.get("VCP通過")):
        return False
    if only_positive_eps and _to_float(r.get("EPS"), 0) <= 0:
        return False
    return True


def _sort_world_champion(df):
    if df is None or df.empty:
        return pd.DataFrame()
    sort_cols = [
        "AI冠軍分數", "SEPA總分", "RS強度",
        "法人籌碼分", "距52週高點%", "ROE%", "營收成長%",
    ]
    for c in sort_cols:
        if c in df.columns:
            df[c] = pd.to_numeric(df[c], errors="coerce")
    use_cols = [c for c in sort_cols if c in df.columns]
    ascending = [False, False, False, False, True, False, False][: len(use_cols)]
    return df.sort_values(use_cols, ascending=ascending).reset_index(drop=True)


def build_price_bucket_top10(result_df, top_n=10):
    """
    將候選股依股價切成三段：
    1. 100元以下
    2. 100～500元
    3. 500元以上
    各取 AI冠軍分數排序前 top_n 名。
    """
    if result_df is None or result_df.empty or "收盤價" not in result_df.columns:
        return {}, pd.DataFrame()

    df = result_df.copy()
    df["收盤價"] = pd.to_numeric(df["收盤價"], errors="coerce")
    df = df.dropna(subset=["收盤價"])

    buckets = {
        "100元以下 TOP10": df[df["收盤價"] < 100].copy(),
        "100～500元 TOP10": df[(df["收盤價"] >= 100) & (df["收盤價"] <= 500)].copy(),
        "500元以上 TOP10": df[df["收盤價"] > 500].copy(),
    }

    output = {}
    all_rows = []
    for name, sub in buckets.items():
        sub = _sort_world_champion(sub).head(int(top_n)).copy()
        if not sub.empty:
            sub.insert(0, "股價區間", name.replace(" TOP10", ""))
            sub.insert(1, "區間排名", range(1, len(sub) + 1))
        output[name] = sub
        all_rows.append(sub)

    combined = pd.concat(all_rows, ignore_index=True) if all_rows else pd.DataFrame()
    return output, combined


# =========================================================
# PRO v15.2 Excel 極簡報告工具
# =========================================================

SIMPLE_REPORT_COLS = [
    "排名", "股票代號", "股票名稱", "收盤價", "主流族群",
    "AI冠軍分數", "AI評級", "投資建議", "AI白話解讀",
]

FINAL_EXCEL_COL_RENAME = {
    "股票代號": "代號",
    "股票名稱": "名稱",
    "收盤價": "股價",
    "主流族群": "族群",
}

# 使用者指定 Excel 最終欄位：
# 排名｜代號｜名稱｜股價｜族群｜AI冠軍分數｜AI評級｜投資建議｜AI白話解讀
FINAL_EXCEL_COLS = [
    "排名", "代號", "名稱", "股價", "族群",
    "AI冠軍分數", "AI評級", "投資建議", "AI白話解讀",
]


def _to_final_excel_cols(df):
    """把畫面與 Excel 報告統一縮成 9 欄，移除所有技術專有名詞。"""
    if df is None or df.empty:
        return pd.DataFrame(columns=FINAL_EXCEL_COLS)

    out = df.copy()

    # 若股價區間表使用「區間排名」，統一改成「排名」。
    if "排名" not in out.columns and "區間排名" in out.columns:
        out = out.rename(columns={"區間排名": "排名"})

    # 若沒有排名就自動補上。
    if "排名" not in out.columns:
        out.insert(0, "排名", range(1, len(out) + 1))

    # 選取內部欄位後改成使用者要看的中文短欄名。
    keep = [c for c in SIMPLE_REPORT_COLS if c in out.columns]
    out = out[keep].rename(columns=FINAL_EXCEL_COL_RENAME)

    # 確保欄位順序固定；缺欄補空值，避免 Excel 欄位跑掉。
    for c in FINAL_EXCEL_COLS:
        if c not in out.columns:
            out[c] = ""

    return out[FINAL_EXCEL_COLS]


def _select_existing_cols(df, cols):
    if df is None or df.empty:
        return pd.DataFrame()
    return df[[c for c in cols if c in df.columns]].copy()


def _simple_rank(df, cols=SIMPLE_REPORT_COLS, top_n=None):
    if df is None or df.empty:
        return pd.DataFrame(columns=FINAL_EXCEL_COLS)
    out = _sort_world_champion(df.copy())
    if "排名" in out.columns:
        out = out.drop(columns=["排名"])
    out.insert(0, "排名", range(1, len(out) + 1))
    if top_n:
        out = out.head(int(top_n))
    return _to_final_excel_cols(out)


def _price_bucket_simple(df, top_n=10):
    buckets, _ = build_price_bucket_top10(df, top_n)
    output = {}
    for name, sub in buckets.items():
        output[name] = _to_final_excel_cols(sub)
    return output


def _breakout_simple(df):
    if df is None or df.empty:
        return pd.DataFrame()
    out = df.copy()
    out["距52週高點%"] = pd.to_numeric(out.get("距52週高點%"), errors="coerce")
    out = out[
        (out["距52週高點%"] <= 5)
        & (out["Trend通過"].astype(str).str.lower().isin(["yes", "true", "1", "通過"]))
    ].copy()
    if "VCP通過" in out.columns:
        vcp_yes = out["VCP通過"].astype(str).str.lower().isin(["yes", "true", "1", "通過"])
        # 不強制每一檔都通過 VCP，但通過者排序優先。
        out["_vcp_sort"] = vcp_yes.astype(int)
    else:
        out["_vcp_sort"] = 0
    sort_cols = [c for c in ["_vcp_sort", "AI冠軍分數", "RS強度", "距52週高點%"] if c in out.columns]
    ascending = [False, False, False, True][: len(sort_cols)]
    if sort_cols:
        out = out.sort_values(sort_cols, ascending=ascending)
    out = out.drop(columns=["_vcp_sort"], errors="ignore").reset_index(drop=True)
    if "排名" in out.columns:
        out = out.drop(columns=["排名"])
    out.insert(0, "排名", range(1, len(out) + 1))
    return _to_final_excel_cols(out)


def _institution_simple(df, top_n=30):
    if df is None or df.empty:
        return pd.DataFrame()
    out = df.copy()
    for c in ["法人籌碼分", "AI冠軍分數", "外資連買", "投信連買"]:
        if c in out.columns:
            out[c] = pd.to_numeric(out[c], errors="coerce")
    sort_cols = [c for c in ["法人籌碼分", "AI冠軍分數", "外資連買", "投信連買"] if c in out.columns]
    if sort_cols:
        out = out.sort_values(sort_cols, ascending=[False] * len(sort_cols))
    out = out.reset_index(drop=True)
    if "排名" in out.columns:
        out = out.drop(columns=["排名"])
    out.insert(0, "排名", range(1, len(out) + 1))
    return _to_final_excel_cols(out.head(int(top_n)))


def _write_excel_sheet(writer, df, sheet_name):
    if df is None or df.empty:
        pd.DataFrame({"說明": ["目前沒有符合條件的股票"]}).to_excel(
            writer, index=False, sheet_name=sheet_name[:31]
        )
    else:
        df.to_excel(writer, index=False, sheet_name=sheet_name[:31])


def _format_excel_workbook(writer):
    workbook = writer.book
    for ws in workbook.worksheets:
        ws.freeze_panes = "A2"
        ws.auto_filter.ref = ws.dimensions
        for col in ws.columns:
            max_len = 8
            col_letter = col[0].column_letter
            for cell in col:
                try:
                    value_len = len(str(cell.value)) if cell.value is not None else 0
                    max_len = max(max_len, min(value_len + 2, 36))
                except Exception:
                    pass
            ws.column_dimensions[col_letter].width = max_len


# =========================================================
# 股票池與法人資料
# =========================================================

stocks = get_stock_universe(include_twse, include_tpex)
stock_info_dict = stocks.set_index("stock_id").to_dict("index") if not stocks.empty else {}

m1, m2, m3, m4 = st.columns(4)
m1.metric("股票池", len(stocks))
m2.metric("上市", int((stocks["market"] == "上市").sum()) if not stocks.empty else 0)
m3.metric("上櫃", int((stocks["market"] == "上櫃").sum()) if not stocks.empty else 0)
m4.metric("主流族群", int(stocks["theme"].nunique()) if not stocks.empty else 0)

with st.spinner("更新法人資料中..."):
    inst_df = get_institutional_range(institutional_days)


# =========================================================
# 模式一：個股診斷
# =========================================================

if mode == "個股診斷":
    st.subheader("📊 個股診斷")
    stock_input = st.text_input("輸入股票代號", value="2330", placeholder="例如：2330、2454、5536、3017")
    run = st.button("開始診斷", type="primary")

    if run and stock_input:
        result = diagnose_stock(stock_input, stock_info_dict, inst_df)
        if result is None:
            st.error("股票代號不在目前股票池，請確認代號或市場範圍。")
        elif "錯誤" in result:
            st.warning(result["錯誤"])
            st.json(result)
        else:
            st.markdown(f"## {result['股票代號']}｜{result['股票名稱']}")
            st.caption(
                f"{result['市場']}｜{result['官方產業']}｜{result['主流族群']}｜"
                f"收盤價 {result['收盤價']}｜Minervini階段：{result.get('Minervini階段')}"
            )
            render_advisor(result)
            if display_mode == "專業數據版":
                render_professional(result)
            else:
                with st.expander("查看專業數據", expanded=False):
                    render_professional(result)


# =========================================================
# 模式二：冠軍股排行
# =========================================================

elif mode == "冠軍股排行":
    st.subheader("🏆 冠軍股排行")
    codes = [x.strip() for x in watchlist_text.replace(",", "\n").splitlines() if x.strip()]

    if st.button("產生排行", type="primary"):
        rows = []
        if not codes:
            st.warning("請先輸入股票清單。")
        else:
            progress = st.progress(0)
            for i, code in enumerate(codes, 1):
                r = diagnose_stock(code, stock_info_dict, inst_df)
                if r and "錯誤" not in r and r["SEPA總分"] >= min_total_score:
                    advisor = generate_advisor_summary(r)
                    r2 = {k: v for k, v in r.items() if not k.startswith("_")}
                    r2["AI評級"] = advisor["rating"]
                    r2["投資建議"] = advisor["action"]
                    r2["AI白話解讀"] = advisor["comment"]
                    rows.append(r2)
                progress.progress(i / len(codes))

            rank = pd.DataFrame(rows)
            if rank.empty:
                st.warning("目前沒有符合條件的股票。")
            else:
                rank = rank.sort_values(
                    ["AI冠軍分數", "SEPA總分", "SEPA技術分", "法人籌碼分", "RS強度"],
                    ascending=False,
                ).reset_index(drop=True)
                rank.insert(0, "排名", range(1, len(rank) + 1))
                rank_simple = _to_final_excel_cols(rank)
                st.dataframe(rank_simple, use_container_width=True, hide_index=True)

                buffer = io.BytesIO()
                rank_simple.to_excel(buffer, index=False)
                buffer.seek(0)
                st.download_button(
                    "下載冠軍股排行 Excel",
                    data=buffer.getvalue(),
                    file_name=f"PRO_v15_2_冠軍股排行_{datetime.now().strftime('%Y%m%d')}.xlsx",
                    mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                )


# =========================================================
# 模式三：世界冠軍股掃描器
# =========================================================

else:
    st.subheader("🔎 世界冠軍股掃描器｜PRO v15.2 極簡決策報告")
    st.info("此模式會逐檔診斷上市櫃股票，第一次全市場掃描會比較久；掃過的資料會被 Streamlit 快取。")

    watchlist_codes = [x.strip() for x in watchlist_text.replace(",", "\n").splitlines() if x.strip()]
    if scan_scope == "全市場":
        scan_codes = stocks["stock_id"].astype(str).tolist() if not stocks.empty else []
    else:
        scan_codes = watchlist_codes

    if max_scan_count and max_scan_count > 0:
        scan_codes = scan_codes[: int(max_scan_count)]

    s1, s2, s3 = st.columns(3)
    s1.metric("本次預計掃描", len(scan_codes))
    s2.metric("最低AI冠軍分數", min_champion_score)
    s3.metric("距52週高點以內", f"{near_high_pct}%")

    if st.button("開始 PRO v15.2 世界冠軍股掃描", type="primary"):
        if not scan_codes:
            st.warning("沒有可掃描的股票。")
        else:
            rows = []
            errors = []
            progress = st.progress(0)
            status = st.empty()

            for i, code in enumerate(scan_codes, 1):
                status.write(f"掃描中：{i}/{len(scan_codes)}｜{code}")
                r = diagnose_stock(code, stock_info_dict, inst_df)
                if r is None:
                    errors.append({"股票代號": code, "錯誤": "不在股票池"})
                elif "錯誤" in r:
                    errors.append(r)
                elif pass_minervini_filter(r):
                    advisor = generate_advisor_summary(r)
                    r2 = {k: v for k, v in r.items() if not k.startswith("_")}
                    r2["AI評級"] = advisor["rating"]
                    r2["投資建議"] = advisor["action"]
                    r2["AI白話解讀"] = advisor["comment"]
                    rows.append(r2)

                progress.progress(i / len(scan_codes))

            status.write("掃描完成。")
            result_df = pd.DataFrame(rows)

            if result_df.empty:
                st.warning("本次沒有掃到符合 Minervini 條件的股票。可放寬 RS、VCP、ROE 或距52週高點條件再試。")
            else:
                result_df = result_df.sort_values(
                    ["AI冠軍分數", "SEPA總分", "RS強度", "法人籌碼分", "距52週高點%"],
                    ascending=[False, False, False, False, True],
                ).reset_index(drop=True)
                result_df.insert(0, "排名", range(1, len(result_df) + 1))

                st.success(f"找到 {len(result_df)} 檔符合條件的 Minervini 候選股。")

                top_df = result_df[result_df["Minervini階段"].isin(["冠軍股候選", "即將突破觀察"])]
                breakout_df = result_df[_to_float(0) == 1] if False else result_df[
                    pd.to_numeric(result_df["距52週高點%"], errors="coerce") <= 5
                ]

                # PRO v15.2：Excel 只輸出 9 欄極簡決策報告。
                champion_top30 = _simple_rank(result_df, SIMPLE_REPORT_COLS, top_n=30)
                price_buckets_simple = _price_bucket_simple(result_df, price_top_n)
                breakout_simple = _breakout_simple(result_df)
                institution_simple = _institution_simple(result_df, top_n=30)
                complete_df = result_df.copy()

                tab1, tab2, tab3, tab4, tab5, tab6, tab7 = st.tabs([
                    "🏆 冠軍股TOP30",
                    "💰 100元以下",
                    "💎 100～500元",
                    "👑 500元以上",
                    "🚀 即將突破",
                    "🏦 法人追蹤",
                    "📊 完整分析",
                ])

                with tab1:
                    st.dataframe(champion_top30, use_container_width=True, hide_index=True)

                def show_simple_bucket(tab, title):
                    with tab:
                        dfb = price_buckets_simple.get(title, pd.DataFrame())
                        if dfb.empty:
                            st.info(f"目前沒有符合條件的 {title.replace(' TOP10', '')} 潛力股。")
                        else:
                            st.dataframe(dfb, use_container_width=True, hide_index=True)

                show_simple_bucket(tab2, "100元以下 TOP10")
                show_simple_bucket(tab3, "100～500元 TOP10")
                show_simple_bucket(tab4, "500元以上 TOP10")

                with tab5:
                    if breakout_simple.empty:
                        st.info("目前沒有距離52週高點5%以內且趨勢通過的股票。")
                    else:
                        st.dataframe(breakout_simple, use_container_width=True, hide_index=True)

                with tab6:
                    if institution_simple.empty:
                        st.info("目前沒有法人籌碼資料。")
                    else:
                        st.dataframe(institution_simple, use_container_width=True, hide_index=True)

                with tab7:
                    st.caption("完整分析保留所有程式計算欄位，給進階研究或除錯使用。")
                    st.dataframe(complete_df, use_container_width=True, hide_index=True)
                    if errors:
                        with st.expander("查看掃描失敗清單", expanded=False):
                            st.dataframe(pd.DataFrame(errors), use_container_width=True, hide_index=True)

                buffer = io.BytesIO()
                with pd.ExcelWriter(buffer, engine="openpyxl") as writer:
                    _write_excel_sheet(writer, champion_top30, "冠軍股TOP30")
                    _write_excel_sheet(writer, price_buckets_simple.get("100元以下 TOP10"), "100以下TOP10")
                    _write_excel_sheet(writer, price_buckets_simple.get("100～500元 TOP10"), "100-500TOP10")
                    _write_excel_sheet(writer, price_buckets_simple.get("500元以上 TOP10"), "500以上TOP10")
                    _write_excel_sheet(writer, breakout_simple, "即將突破名單")
                    _write_excel_sheet(writer, institution_simple, "法人追蹤榜")
                    # PRO v15.2：Excel 只輸出使用者指定的 9 欄，
                    # 不再輸出完整分析與掃描失敗表，避免報表又出現大量專有名詞。
                    _format_excel_workbook(writer)
                buffer.seek(0)
                st.download_button(
                    "下載 PRO v15.2 世界冠軍極簡報告 Excel",
                    data=buffer.getvalue(),
                    file_name=f"PRO_v15_2_世界冠軍極簡報告_{datetime.now().strftime('%Y%m%d')}.xlsx",
                    mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                )

st.divider()
st.caption("提醒：本工具僅供量化研究與教學，不構成投資建議。法人、財務與股價資料可能因資料源延遲或缺漏而不完整。")
