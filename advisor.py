# -*- coding: utf-8 -*-
"""
AI台股雷達 PRO v13.5｜advisor.py 修正版

修正重點：
1. 補回 app.py 需要匯入的 generate_advisor_summary()。
2. 同時保留 build_advisor_report()，避免舊版程式呼叫失效。
3. generate_advisor_summary() 回傳 app.py 目前會用到的欄位：
   stars、rating、action、comment、financial、growth、trend、chip、risk、
   entry、stop_loss、take_profit
4. 加強數值轉換，避免 EPS、ROE、營收成長等欄位是 None、NaN、"--" 時造成錯誤。
"""

import math


def _to_float(value, default=0.0):
    """安全轉數字，避免 None、NaN、字串空值造成程式中斷。"""
    try:
        if value is None:
            return default
        if isinstance(value, str):
            value = value.replace(",", "").replace("%", "").strip()
            if value in ["", "-", "--", "nan", "None"]:
                return default
        value = float(value)
        if math.isnan(value) or math.isinf(value):
            return default
        return value
    except Exception:
        return default


def _light_text(light, good_text, mid_text, bad_text):
    if light == "🟢":
        return f"{light} {good_text}"
    if light == "🟡":
        return f"{light} {mid_text}"
    return f"{light} {bad_text}"


def build_advisor_report(result):
    """
    建立完整 AI 投資顧問分析資料。
    回傳內容同時支援：
    - 舊版欄位：suggestion、summary、finance_light...
    - app.py 欄位：stars、action、comment、financial...
    """

    score = _to_float(result.get("SEPA總分", 0))
    price = _to_float(result.get("收盤價", 0))
    rs = _to_float(result.get("RS強度", 0))
    chip_score = _to_float(result.get("法人籌碼分", 0))
    tech_score = _to_float(result.get("SEPA技術分", 0))
    eps = _to_float(result.get("EPS", 0))
    roe = _to_float(result.get("ROE%", 0))
    revenue_growth = _to_float(result.get("營收成長%", 0))
    atr_pct = _to_float(result.get("ATR%", 0))

    trend_pass = str(result.get("Trend通過", "")).strip().lower() in ["yes", "true", "1", "通過"]
    vcp_pass = str(result.get("VCP通過", "")).strip().lower() in ["yes", "true", "1", "通過"]

    # =====================================================
    # 五大燈號
    # =====================================================

    finance_light = "🟢"
    if eps <= 0:
        finance_light = "🔴"
    elif roe < 10:
        finance_light = "🟡"

    growth_light = "🟢"
    if revenue_growth < 10:
        growth_light = "🟡"
    if revenue_growth < 0:
        growth_light = "🔴"

    trend_light = "🟢" if trend_pass else "🔴"

    chip_light = "🟢"
    if chip_score < 15:
        chip_light = "🟡"
    if chip_score < 5:
        chip_light = "🔴"

    risk_light = "🟢"
    if score < 75:
        risk_light = "🟡"
    if score < 60:
        risk_light = "🔴"

    # =====================================================
    # 評級與建議
    # =====================================================

    if score >= 90:
        stars = "★★★★★"
        rating = "S級｜冠軍股候選"
        action = "強烈追蹤"
        suggestion = "強烈買進觀察"
    elif score >= 80:
        stars = "★★★★☆"
        rating = "A級｜強勢股"
        action = "偏多觀察"
        suggestion = "偏多買進觀察"
    elif score >= 70:
        stars = "★★★☆☆"
        rating = "B級｜觀察股"
        action = "觀察布局"
        suggestion = "觀察布局"
    elif score >= 60:
        stars = "★★☆☆☆"
        rating = "C級｜保守觀察"
        action = "保守觀察"
        suggestion = "保守觀察"
    else:
        stars = "★☆☆☆☆"
        rating = "D級｜暫不建議"
        action = "暫不進場"
        suggestion = "暫不建議"

    # =====================================================
    # 優缺點分析
    # =====================================================

    positives = []
    negatives = []

    if trend_pass:
        positives.append("股價維持多頭趨勢排列")
    else:
        negatives.append("均線結構尚未形成完整多頭")

    if vcp_pass:
        positives.append("具備 VCP 收縮整理結構")
    else:
        negatives.append("尚未形成明確 VCP 整理型態")

    if rs > 1:
        positives.append("相對大盤具備領先強度")
    else:
        negatives.append("相對強度仍偏弱")

    if chip_score >= 15:
        positives.append("法人籌碼偏多")
    else:
        negatives.append("法人資金尚未明顯進駐")

    if eps > 0:
        positives.append("公司仍維持獲利")
    else:
        negatives.append("EPS 偏弱或目前資料不足")

    if roe >= 15:
        positives.append("ROE 表現良好")
    elif roe > 0:
        negatives.append("ROE 尚未達高品質成長股水準")

    if revenue_growth >= 10:
        positives.append("營收成長維持正向")
    elif revenue_growth < 0:
        negatives.append("營收成長為負，需留意基本面動能")

    # =====================================================
    # 操作區間
    # =====================================================

    if price > 0:
        entry_low = round(price * 0.97, 2)
        entry_high = round(price * 1.02, 2)

        # ATR% 若有值，停損可略參考波動；沒有就用 8%
        if atr_pct > 0:
            stop_pct = max(0.06, min(0.12, atr_pct / 100 * 2.5))
        else:
            stop_pct = 0.08

        stop_price = round(price * (1 - stop_pct), 2)
        target1 = round(price * 1.15, 2)
        target2 = round(price * 1.30, 2)

        entry = f"{entry_low}～{entry_high} 元附近觀察，最好等待量縮回測或放量突破後再進場。"
        stop_loss_text = f"{stop_price} 元附近，或跌破關鍵均線且無法快速站回時停損。"
        take_profit = f"第一目標 {target1} 元，第二目標 {target2} 元；若爆量長黑或跌破短期均線，應先降風險。"
    else:
        entry_low = entry_high = stop_price = target1 = target2 = 0
        entry = "目前沒有有效收盤價，暫時不建議制定進場區間。"
        stop_loss_text = "目前沒有有效收盤價，無法計算停損價。"
        take_profit = "目前沒有有效收盤價，無法計算停利目標。"

    # =====================================================
    # 白話總結
    # =====================================================

    if score >= 85:
        comment = (
            "這檔股票的趨勢、籌碼與基本面條件相對完整，具備強勢股追蹤價值。"
            "但仍不建議無腦追高，較好的做法是等待突破確認，或回測不破時分批布局。"
        )
    elif score >= 70:
        comment = (
            "整體條件屬於中上，已經具備部分 SEPA 強勢股條件，"
            "但型態或籌碼仍需進一步確認，適合放入觀察名單。"
        )
    elif score >= 60:
        comment = (
            "目前分數尚可，但還沒有達到強勢股的完整標準。"
            "建議先觀察趨勢是否轉強、法人是否持續買超，再考慮進場。"
        )
    else:
        comment = (
            "目前條件尚未達到強勢股標準，趨勢、籌碼或財務可能仍有明顯弱點，"
            "建議先觀察，不急著進場。"
        )

    if positives:
        comment += " 優點：" + "、".join(positives[:3]) + "。"
    if negatives:
        comment += " 風險：" + "、".join(negatives[:3]) + "。"

    return {
        # app.py 目前使用的欄位
        "stars": stars,
        "rating": rating,
        "action": action,
        "comment": comment,
        "financial": _light_text(finance_light, "財務良好", "財務普通", "財務偏弱"),
        "growth": _light_text(growth_light, "成長良好", "成長普通", "成長偏弱"),
        "trend": _light_text(trend_light, "趨勢偏多", "趨勢觀察", "趨勢未過"),
        "chip": _light_text(chip_light, "法人偏多", "法人普通", "法人偏弱"),
        "risk": _light_text(risk_light, "風險較低", "風險中等", "風險偏高"),
        "entry": entry,
        "stop_loss": stop_loss_text,
        "take_profit": take_profit,

        # 舊版/其他模組可能使用的欄位
        "suggestion": suggestion,
        "summary": comment,
        "finance_light": finance_light,
        "growth_light": growth_light,
        "trend_light": trend_light,
        "chip_light": chip_light,
        "risk_light": risk_light,
        "positives": positives,
        "negatives": negatives,
        "entry_low": entry_low,
        "entry_high": entry_high,
        "target1": target1,
        "target2": target2,
        "tech_score": tech_score,
        "chip_score": chip_score,
    }


def generate_advisor_summary(result):
    """
    app.py 會使用這個函式：
        from advisor import generate_advisor_summary

    所以一定要保留。
    """
    return build_advisor_report(result)
