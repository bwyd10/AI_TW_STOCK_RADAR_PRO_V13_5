# -*- coding: utf-8 -*-
import pandas as pd

def calc_consecutive_positive(values):
    count = 0
    for v in values:
        try:
            if float(v) > 0:
                count += 1
            else:
                break
        except Exception:
            break
    return count

def summarize_institutional(inst_df, stock_id):
    base = {
        "foreign_today": 0.0, "trust_today": 0.0, "dealer_today": 0.0,
        "foreign_buy_days_5": 0, "trust_buy_days_5": 0, "dealer_buy_days_5": 0,
        "foreign_consecutive": 0, "trust_consecutive": 0, "dealer_consecutive": 0,
        "foreign_trust_sync": "No", "three_institution_sync": "No",
        "institutional_score": 0, "chip_score": 0, "chip_signal": "無法人資料",
        "latest_inst_date": "",
    }
    if inst_df is None or inst_df.empty:
        return base
    df = inst_df[inst_df["stock_id"].astype(str) == str(stock_id)].copy()
    if df.empty:
        return base
    df["date"] = df["date"].astype(str)
    df = df.sort_values("date", ascending=False)
    latest = df.iloc[0]
    recent = df.head(5)
    foreign_today = float(latest.get("foreign_net", 0) or 0)
    trust_today = float(latest.get("trust_net", 0) or 0)
    dealer_today = float(latest.get("dealer_net", 0) or 0)
    foreign_cons = calc_consecutive_positive(df["foreign_net"].head(10).tolist())
    trust_cons = calc_consecutive_positive(df["trust_net"].head(10).tolist())
    dealer_cons = calc_consecutive_positive(df["dealer_net"].head(10).tolist())
    foreign_trust_sync = foreign_today > 0 and trust_today > 0
    three_sync = foreign_today > 0 and trust_today > 0 and dealer_today > 0
    score = 0
    if foreign_today > 0: score += 4
    if trust_today > 0: score += 5
    if dealer_today > 0: score += 2
    if foreign_cons >= 2: score += 3
    if foreign_cons >= 3: score += 3
    if trust_cons >= 2: score += 4
    if trust_cons >= 3: score += 4
    if foreign_trust_sync: score += 3
    if three_sync: score += 2
    score = min(25, score)
    signals = []
    if score >= 22: signals.append("S級籌碼")
    elif score >= 18: signals.append("A級籌碼")
    elif score >= 13: signals.append("B級籌碼")
    else: signals.append("籌碼觀察")
    if foreign_cons >= 3: signals.append(f"外資連買{foreign_cons}天")
    if trust_cons >= 3: signals.append(f"投信連買{trust_cons}天")
    if three_sync: signals.append("三大法人同步")
    elif foreign_trust_sync: signals.append("外資投信同步")
    base.update({
        "foreign_today": round(foreign_today, 2),
        "trust_today": round(trust_today, 2),
        "dealer_today": round(dealer_today, 2),
        "foreign_buy_days_5": int((recent["foreign_net"] > 0).sum()),
        "trust_buy_days_5": int((recent["trust_net"] > 0).sum()),
        "dealer_buy_days_5": int((recent["dealer_net"] > 0).sum()),
        "foreign_consecutive": foreign_cons,
        "trust_consecutive": trust_cons,
        "dealer_consecutive": dealer_cons,
        "foreign_trust_sync": "Yes" if foreign_trust_sync else "No",
        "three_institution_sync": "Yes" if three_sync else "No",
        "institutional_score": score,
        "chip_score": score,
        "chip_signal": "、".join(signals),
        "latest_inst_date": str(latest.get("date", "")),
    })
    return base
