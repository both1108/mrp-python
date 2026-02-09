# lang.py

TEXT = {
    "zh": {
        # 圖表文字
        "temp": "溫度 (°C)",
        "vib": "震動 (mm/s)",
        "time": "時間",
        "health_title": "設備健康監控趨勢圖（雙軸）",
        "orig_demand": "原始需求",
        "adj_demand": "產能修正後需求",
        "demand_title": "未來需求比較（原始 vs 修正後）",
        "date": "日期",
        "qty": "數量",

        # Console 標題
        "mrp_focus_title": "未來 7 天零件供需模擬（重點）",
        "risk_parts_title": "7 天內有風險的零件",
        "po_summary_title": "7 天採購建議彙總"
    },
    "en": {
        "temp": "Temperature (°C)",
        "vib": "Vibration (mm/s)",
        "time": "Time",
        "health_title": "Machine Health Monitoring Trend (Dual Axis)",
        "orig_demand": "Original Demand",
        "adj_demand": "Capacity Adjusted Demand",
        "demand_title": "Future Demand Comparison (Original vs Adjusted)",
        "date": "Date",
        "qty": "Quantity",

        "mrp_focus_title": "7-Day MRP Simulation (Key Items)",
        "risk_parts_title": "Risk Parts Within 7 Days",
        "po_summary_title": "7-Day Procurement Summary"
    }
}

COLUMN_MAP = {
    "zh": {
        "forecast_date": "日期",
        "part_no": "零件圖號",
        "part_demand": "需求量",
        "incoming_qty": "既有在途到貨量",
        "po_arrival_qty_today": "MRP採購到貨量(今日)",
        "safety_qty": "安全庫存量",
        "start_available": "當日可用量(含到貨)",
        "end_available": "當日結束可用量",
        "recommended_po_qty": "當日建議下單量",
        "po_eta_date": "本日下單預計到貨日",
        "shortage": "低於安全庫存",
        "post_po_available": "採購決策後可供量(期末)"
    },
    "en": {
        "forecast_date": "Date",
        "part_no": "Part No",
        "part_demand": "Demand",
        "incoming_qty": "Existing Incoming",
        "po_arrival_qty_today": "MRP Incoming Today",
        "safety_qty": "Safety Stock",
        "start_available": "Available (Start)",
        "end_available": "Available (End)",
        "recommended_po_qty": "Recommended PO Qty",
        "po_eta_date": "PO ETA",
        "shortage": "Below Safety",
        "post_po_available": "Available After Decision"
    }
}


def get_text(lang="zh"):
    return TEXT[lang]


def get_column_map(lang="zh"):
    return COLUMN_MAP[lang]
