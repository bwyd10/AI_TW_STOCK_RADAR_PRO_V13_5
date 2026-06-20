# -*- coding: utf-8 -*-
import io
from datetime import datetime
import numpy as np
import pandas as pd
import streamlit as st

from config import APP_TITLE, APP_CAPTION, DEFAULT_WATCHLIST
from data_provider import get_stock_universe, get_price_data, get_market_index, get_institutional_range
from technical import add_indicators
from sepa import calculate_sepa
from chip import summarize_institutional
from fundamental import get_fundamental, fundamental_score
from advisor import generate_advisor_summary
from utils import grade, safe_round

st.set_page_config(page_title=APP_TITLE, page_icon="🏆", layout="wide")
st.title("🏆 AI台股雷達 PRO v13.5｜投資顧問版")
st.caption(APP_CAPTION)

with st.sidebar:
    st.header("模式設定")
    mode = st.radio("選擇模式", ["個股診斷", "冠軍股排行"], index=0)
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
        height=200,
        help="為了速度，PRO v13.5 預設用自選清單排行，不掃描全市場。"
    )
    min_total_score = st.slider("最低 SEPA總分", 0, 100, 60, 5)

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
        return {"股票代號": stock_id, "股票名稱": info["stock_name"], "市場": market, "錯誤": "股價資料不足，至少需要約252個交易日資料。"}

    price = add_indicators(price)
    market_df = add_indicators(market_df) if not market_df.empty else market_df
    latest = price.iloc[-1]

    sepa = calculate_sepa(price, market_df)
    chip = summarize_institutional(inst_df, stock_id)
    f = get_fundamental(stock_id, market)

    if pd.isna(f.get("pe")) and pd.notna(f.get("eps")) and f.get("eps", 0) > 0:
        f["pe"] = float(latest["close"]) / float(f["eps"])

    fs = fundamental_score(f)
    total_score = round(sepa["sepa_technical_score"] + chip["chip_score"] + fs["fundamental_score"], 2)

    strategy = "只觀察"
    if total_score >= 85 and sepa["trend_pass"] and chip["chip_score"] >= 15:
        strategy = "冠軍股候選，可等突破或回測小量"
    elif total_score >= 75 and sepa["trend_pass_count"] >= 6:
        strategy = "強勢觀察，等型態完成"
    elif total_score >= 65:
        strategy = "觀察名單"
    else:
        strategy = "暫不進場"

    return {
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

def render_advisor(result):
    advisor = generate_advisor_summary(result)
    st.subheader("🏆 AI投資顧問")
    a1, a2, a3 = st.columns([2, 1, 1])
    with a1:
        st.markdown(f"## {advisor['stars']}")
        st.markdown(f"### AI評級：{advisor['rating']}")
    with a2:
        st.metric("SEPA總分", result["SEPA總分"])
    with a3:
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
    c1, c2, c3, c4 = st.columns(4)
    c1.metric("SEPA技術分", result["SEPA技術分"])
    c2.metric("法人籌碼分", result["法人籌碼分"])
    c3.metric("財務品質分", result["財務品質分"])
    c4.metric("等級", result["等級"])

    with st.expander("完整資料表", expanded=False):
        main_cols = [k for k in result.keys() if not k.startswith("_")]
        st.dataframe(pd.DataFrame([result])[main_cols], use_container_width=True, hide_index=True)

    col_a, col_b = st.columns(2)
    with col_a:
        st.subheader("Trend Template 明細")
        st.dataframe(pd.DataFrame([{"條件": k, "是否通過": "Yes" if v else "No"} for k, v in result["_trend_details"].items()]), use_container_width=True, hide_index=True)
    with col_b:
        st.subheader("財務條件明細")
        st.dataframe(pd.DataFrame([{"條件": k, "結果": v} for k, v in result["_fundamental_details"].items()]), use_container_width=True, hide_index=True)

stocks = get_stock_universe(include_twse, include_tpex)
stock_info_dict = stocks.set_index("stock_id").to_dict("index") if not stocks.empty else {}

m1, m2, m3, m4 = st.columns(4)
m1.metric("股票池", len(stocks))
m2.metric("上市", int((stocks["market"] == "上市").sum()) if not stocks.empty else 0)
m3.metric("上櫃", int((stocks["market"] == "上櫃").sum()) if not stocks.empty else 0)
m4.metric("主流族群", int(stocks["theme"].nunique()) if not stocks.empty else 0)

with st.spinner("更新法人資料中..."):
    inst_df = get_institutional_range(institutional_days)

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
            st.caption(f"{result['市場']}｜{result['官方產業']}｜{result['主流族群']}｜收盤價 {result['收盤價']}")
            render_advisor(result)
            if display_mode == "專業數據版":
                render_professional(result)
            else:
                with st.expander("查看專業數據", expanded=False):
                    render_professional(result)

else:
    st.subheader("🏆 冠軍股排行")
    codes = [x.strip() for x in watchlist_text.replace(",", "\n").splitlines() if x.strip()]
    if st.button("產生排行", type="primary"):
        rows = []
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
            rank = rank.sort_values(["SEPA總分", "SEPA技術分", "法人籌碼分", "RS強度"], ascending=False).reset_index(drop=True)
            rank.insert(0, "排名", range(1, len(rank) + 1))
            show_cols = ["排名","股票代號","股票名稱","市場","主流族群","收盤價","SEPA總分","AI評級","投資建議","法人籌碼分","財務品質分","Trend通過","AI白話解讀"]
            show_cols = [c for c in show_cols if c in rank.columns]
            st.dataframe(rank[show_cols], use_container_width=True, hide_index=True)

            buffer = io.BytesIO()
            rank.to_excel(buffer, index=False)
            buffer.seek(0)
            st.download_button(
                "下載冠軍股排行 Excel",
                data=buffer.getvalue(),
                file_name=f"PRO_v13_5_投資顧問排行_{datetime.now().strftime('%Y%m%d')}.xlsx",
                mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            )

st.divider()
st.caption("提醒：本工具僅供量化研究與教學，不構成投資建議。法人與財務資料可能因資料源延遲或缺漏而不完整。")
