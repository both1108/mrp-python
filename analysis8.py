import os
from datetime import date, timedelta
from flask import Flask, jsonify
from dotenv import load_dotenv
import pymysql
import psycopg2
import pandas as pd
import numpy as np

load_dotenv()
app = Flask(__name__)

LOOKBACK_DAYS = 30
FORECAST_DAYS = 7
DEFAULT_LEADTIME_DAYS = 3
IOT_LOOKBACK_HOURS = 24

# IoT scoring baseline
TEMP_BASE = 75.0
TEMP_WORST = 95.0
VIB_BASE = 0.05
VIB_WORST = 0.12
RPM_TARGET = 1500.0
RPM_TOLERANCE = 300.0


def get_pg_conn():
    return psycopg2.connect(
        host=os.getenv("PG_HOST"),
        database=os.getenv("PG_DB"),
        user=os.getenv("PG_USER"),
        password=os.getenv("PG_PASSWORD"),
        port=int(os.getenv("PG_PORT", "5432")),
    )


def get_mysql_conn():
    return pymysql.connect(
        host=os.getenv("MYSQL_HOST", "mysql"),
        port=int(os.getenv("MYSQL_PORT", "3306")),
        user=os.getenv("MYSQL_USER", "root"),
        password=os.getenv("MYSQL_PASSWORD", "root"),
        database=os.getenv("MYSQL_DB", "erp"),
        charset="utf8mb4",
        use_unicode=True,
        init_command="SET NAMES utf8mb4",
    )


def safe_float(v, default=0.0):
    try:
        if pd.isna(v):
            return default
        return float(v)
    except Exception:
        return default


def normalize_score(series, base, worst):
    """
    base 以下視為正常 -> 0 penalty
    worst 以上視為最差 -> 1 penalty
    中間線性插值
    """
    if worst <= base:
        return pd.Series(np.zeros(len(series)), index=series.index)
    penalty = (series - base) / (worst - base)
    return penalty.clip(lower=0.0, upper=1.0)


def compute_health_score(iot_df):
    """
    連續式設備健康度:
    - 溫度越高越差
    - 震動越高越差
    - rpm 偏離 target 越多越差
    """
    df = iot_df.copy()

    temp_penalty = normalize_score(df["temperature"], TEMP_BASE, TEMP_WORST) * 0.35
    vib_penalty = normalize_score(df["vibration"], VIB_BASE, VIB_WORST) * 0.45
    rpm_penalty = (
        (df["rpm"] - RPM_TARGET).abs() / RPM_TOLERANCE
    ).clip(lower=0.0, upper=1.0) * 0.20

    df["health_score"] = 1.0 - temp_penalty - vib_penalty - rpm_penalty
    df["health_score"] = df["health_score"].clip(lower=0.0, upper=1.0)

    return df


def build_complete_history(hist_df, lookback_days):
    """
    補齊每個 product_id 在每一天的需求。
    沒有訂單的日期補 0，避免 weekday mean 被高估。
    """
    if hist_df.empty:
        return hist_df.copy()

    hist_df = hist_df.copy()
    hist_df["order_date"] = pd.to_datetime(hist_df["order_date"]).dt.normalize()
    hist_df["product_id"] = hist_df["product_id"].astype(int)
    hist_df["qty"] = hist_df["qty"].astype(float)

    end_date = pd.Timestamp(date.today()).normalize() - pd.Timedelta(days=1)
    start_date = end_date - pd.Timedelta(days=lookback_days - 1)

    date_range = pd.date_range(start=start_date, end=end_date, freq="D")
    products = sorted(hist_df["product_id"].unique())

    full_grid = (
        pd.DataFrame({"order_date": date_range})
        .assign(key=1)
        .merge(pd.DataFrame({"product_id": products, "key": 1}), on="key")
        .drop(columns=["key"])
    )

    hist_full = full_grid.merge(
        hist_df.groupby(["order_date", "product_id"], as_index=False)["qty"].sum(),
        on=["order_date", "product_id"],
        how="left",
    )
    hist_full["qty"] = hist_full["qty"].fillna(0.0)
    hist_full["dow"] = hist_full["order_date"].dt.dayofweek

    return hist_full


def build_forecast(hist_full, forecast_days):
    """
    用完整歷史資料做 weekday mean + overall mean fallback。
    """
    weekday_mean = (
        hist_full.groupby(["product_id", "dow"], as_index=False)["qty"]
        .mean()
        .rename(columns={"qty": "weekday_mean_qty"})
    )

    overall_mean = (
        hist_full.groupby("product_id", as_index=False)["qty"]
        .mean()
        .rename(columns={"qty": "overall_mean_qty"})
    )

    today = pd.Timestamp(date.today()).normalize()
    future_dates = pd.date_range(
        start=today + pd.Timedelta(days=1),
        periods=forecast_days,
        freq="D"
    )

    future_df = pd.DataFrame({"forecast_date": future_dates})
    future_df["dow"] = future_df["forecast_date"].dt.dayofweek

    products = sorted(hist_full["product_id"].unique())
    grid = (
        future_df.assign(key=1)
        .merge(pd.DataFrame({"product_id": products, "key": 1}), on="key")
        .drop(columns=["key"])
    )

    forecast_df = (
        grid.merge(weekday_mean, on=["product_id", "dow"], how="left")
        .merge(overall_mean, on="product_id", how="left")
    )

    forecast_df["forecast_demand_qty"] = (
        forecast_df["weekday_mean_qty"]
        .fillna(forecast_df["overall_mean_qty"])
        .fillna(0.0)
        .round()
        .astype(int)
    )

    return forecast_df


def simulate_inventory_and_mrp(sim_input_df, leadtime_days):
    """
    以「需求日」為核心做 MRP：
    - 當 forecast_date 發生 shortage，代表這天需求無法被滿足
    - 建議下單日 = forecast_date - leadtime_days
    - 建議 ETA = forecast_date
    """
    sim = sim_input_df.copy()
    sim = sim.sort_values(["part_no", "forecast_date"]).reset_index(drop=True)

    sim["start_available"] = 0.0
    sim["end_available"] = 0.0
    sim["below_safety"] = False
    sim["below_zero"] = False
    sim["shortage_qty"] = 0.0

    sim["recommended_po_qty"] = 0.0
    sim["suggested_order_date"] = pd.NaT
    sim["required_eta_date"] = pd.NaT

    for part_no, g in sim.groupby("part_no", sort=False):
        prev_end = None

        for idx, row in g.iterrows():
            current_date = pd.to_datetime(row["forecast_date"]).normalize()
            start_qty = safe_float(row["stock_qty"]) if prev_end is None else safe_float(prev_end)
            incoming_qty = safe_float(row["incoming_qty"])
            demand_qty = safe_float(row["part_demand"])
            safety_qty = safe_float(row["safety_qty"])

            start_plus_incoming = start_qty + incoming_qty
            end_qty = start_plus_incoming - demand_qty
            shortage_qty = max(0.0, -end_qty)

            # 若希望這天結束後至少回到 safety，需補到 safety
            required_qty = max(0.0, safety_qty - end_qty)

            sim.at[idx, "start_available"] = start_plus_incoming
            sim.at[idx, "end_available"] = end_qty
            sim.at[idx, "below_safety"] = end_qty < safety_qty
            sim.at[idx, "below_zero"] = end_qty < 0
            sim.at[idx, "shortage_qty"] = shortage_qty

            if required_qty > 0:
                suggested_order_date = current_date - pd.Timedelta(days=leadtime_days)
                sim.at[idx, "recommended_po_qty"] = required_qty
                sim.at[idx, "suggested_order_date"] = suggested_order_date
                sim.at[idx, "required_eta_date"] = current_date

            prev_end = end_qty

    return sim


def build_dashboard_data():
    pg_conn = get_pg_conn()
    mysql_conn = get_mysql_conn()

    try:
        # 1) BOM
        bom_sql = """
        SELECT 
            CAST(TRIM(b.product_code) AS UNSIGNED) AS product_id,
            d.part_no AS part_no,
            d.qty AS bom_qty
        FROM bom_header b
        JOIN bom_detail d ON b.bom_id = d.bom_id;
        """
        bom_df = pd.read_sql(bom_sql, mysql_conn)
        bom_df["product_id"] = pd.to_numeric(bom_df["product_id"], errors="coerce").astype("Int64")
        bom_df = bom_df.dropna(subset=["product_id"]).copy()
        bom_df["product_id"] = bom_df["product_id"].astype(int)
        bom_df["bom_qty"] = pd.to_numeric(bom_df["bom_qty"], errors="coerce").fillna(0.0)

        # 2) Parts
        parts_sql = """
        SELECT part_no, stock_qty, safety_stock AS safety_qty
        FROM parts;
        """
        parts_df = pd.read_sql(parts_sql, mysql_conn)
        if parts_df.empty:
            return {"error": "parts 資料表沒有資料，無法進行庫存模擬。"}
        parts_df["stock_qty"] = pd.to_numeric(parts_df["stock_qty"], errors="coerce").fillna(0.0)
        parts_df["safety_qty"] = pd.to_numeric(parts_df["safety_qty"], errors="coerce").fillna(0.0)

        # 3) Incoming purchase
        purchase_sql = """
        SELECT 
            part_no,
            DATE(delivery_date) AS eta_date,
            SUM(order_qty) AS incoming_qty
        FROM purchase
        WHERE status = 'pending'
          AND delivery_date IS NOT NULL
        GROUP BY part_no, DATE(delivery_date);
        """
        incoming_df = pd.read_sql(purchase_sql, mysql_conn)
        if not incoming_df.empty:
            incoming_df["eta_date"] = pd.to_datetime(incoming_df["eta_date"]).dt.normalize()
            incoming_df["incoming_qty"] = pd.to_numeric(incoming_df["incoming_qty"], errors="coerce").fillna(0.0)

        # 4) IoT
        iot_sql = f"""
        SELECT machine_id, temperature, vibration, rpm, created_at
        FROM machine_data
        WHERE created_at >= NOW() - INTERVAL {IOT_LOOKBACK_HOURS} HOUR
        ORDER BY machine_id, created_at ASC;
        """
        iot_df = pd.read_sql(iot_sql, mysql_conn)

        machine_iot = {}
        machine_health_df = pd.DataFrame(columns=["machine_id", "machine_health"])
        avg_health = 1.0
        min_health = 1.0
        capacity_factor = 1.0

        if not iot_df.empty:
            iot_df["created_at"] = pd.to_datetime(iot_df["created_at"])
            iot_df["temperature"] = pd.to_numeric(iot_df["temperature"], errors="coerce").fillna(TEMP_BASE)
            iot_df["vibration"] = pd.to_numeric(iot_df["vibration"], errors="coerce").fillna(VIB_BASE)
            iot_df["rpm"] = pd.to_numeric(iot_df["rpm"], errors="coerce").fillna(RPM_TARGET)

            iot_df = compute_health_score(iot_df)
            iot_df = iot_df.sort_values(["machine_id", "created_at"]).reset_index(drop=True)

            machine_health_df = (
                iot_df.groupby("machine_id", as_index=False)["health_score"]
                .mean()
                .rename(columns={"health_score": "machine_health"})
            )

            if not machine_health_df.empty:
                avg_health = float(machine_health_df["machine_health"].mean())
                min_health = float(machine_health_df["machine_health"].min())
                capacity_factor = max(0.0, min(1.0, 0.7 * avg_health + 0.3 * min_health))

            for machine_id, g in iot_df.groupby("machine_id"):
                g = g.sort_values("created_at").reset_index(drop=True)
                machine_iot[machine_id] = {
                    "x": g["created_at"].dt.strftime("%Y-%m-%d %H:%M:%S").tolist(),
                    "temperature": g["temperature"].astype(float).round(2).tolist(),
                    "vibration": g["vibration"].astype(float).round(4).tolist(),
                    "rpm": g["rpm"].astype(float).round(0).tolist(),
                    "health_score": g["health_score"].astype(float).round(3).tolist(),
                }

        # 5) Historical orders
        hist_sql = f"""
        SELECT
            DATE(o.created_at) AS order_date,
            oi.product_id AS product_id,
            SUM(oi.quantity) AS qty
        FROM orders o
        JOIN order_items oi ON o.id = oi.order_id
        WHERE o.status != 'cancelled'
          AND o.created_at >= NOW() - INTERVAL '{LOOKBACK_DAYS} days'
        GROUP BY DATE(o.created_at), oi.product_id
        ORDER BY order_date;
        """
        hist_df = pd.read_sql(hist_sql, pg_conn)

        if hist_df.empty:
            return {
                "error": f"近 {LOOKBACK_DAYS} 天沒有訂單資料，請檢查 orders.created_at。"
            }

        hist_df["order_date"] = pd.to_datetime(hist_df["order_date"])
        hist_df["product_id"] = pd.to_numeric(hist_df["product_id"], errors="coerce")
        hist_df["qty"] = pd.to_numeric(hist_df["qty"], errors="coerce")

        hist_df = hist_df.dropna(subset=["product_id", "qty"]).copy()
        hist_df["product_id"] = hist_df["product_id"].astype(int)

        hist_full = build_complete_history(hist_df, LOOKBACK_DAYS)
        forecast_df = build_forecast(hist_full, FORECAST_DAYS)

        # 6) Capacity logic
        forecast_df["capacity_factor"] = capacity_factor
        forecast_df["expected_output_qty"] = (
            forecast_df["forecast_demand_qty"] * forecast_df["capacity_factor"]
        ).round().astype(int)

        forecast_df["gap_qty"] = (
            forecast_df["forecast_demand_qty"] - forecast_df["expected_output_qty"]
        ).clip(lower=0)

        # 7) BOM explode: demand vs executable output 分開
        future_bom = forecast_df.merge(bom_df, on="product_id", how="inner")

        future_bom["part_demand_for_customer_demand"] = (
            future_bom["forecast_demand_qty"] * future_bom["bom_qty"]
        )

        future_bom["part_demand_for_planned_output"] = (
            future_bom["expected_output_qty"] * future_bom["bom_qty"]
        )

        # 這裡做 MRP，採用「為滿足市場需求所需物料」
        # 若你想改成只為可執行產出備料，可以改用 part_demand_for_planned_output
        daily_part_demand = (
            future_bom.groupby(["forecast_date", "part_no"], as_index=False)["part_demand_for_customer_demand"]
            .sum()
            .rename(columns={"part_demand_for_customer_demand": "part_demand"})
        )

        # 額外保留 planned output 對應物料需求，方便摘要說明
        daily_part_output_need = (
            future_bom.groupby(["forecast_date", "part_no"], as_index=False)["part_demand_for_planned_output"]
            .sum()
            .rename(columns={"part_demand_for_planned_output": "planned_output_part_demand"})
        )

        # 8) incoming by day
        if incoming_df.empty:
            daily_incoming = pd.DataFrame(columns=["forecast_date", "part_no", "incoming_qty"])
        else:
            daily_incoming = (
                incoming_df.rename(columns={"eta_date": "forecast_date"})
                .groupby(["forecast_date", "part_no"], as_index=False)["incoming_qty"]
                .sum()
            )

        future_dates_df = pd.DataFrame({
            "forecast_date": pd.date_range(
                start=pd.Timestamp(date.today()).normalize() + pd.Timedelta(days=1),
                periods=FORECAST_DAYS,
                freq="D"
            )
        })

        parts_list = parts_df["part_no"].dropna().astype(str).unique()

        sim_grid = (
            future_dates_df.assign(key=1)
            .merge(pd.DataFrame({"part_no": parts_list, "key": 1}), on="key")
            .drop(columns=["key"])
        )

        sim = (
            sim_grid.merge(daily_part_demand, on=["forecast_date", "part_no"], how="left")
            .merge(daily_part_output_need, on=["forecast_date", "part_no"], how="left")
            .merge(daily_incoming, on=["forecast_date", "part_no"], how="left")
            .merge(parts_df, on="part_no", how="left")
        )

        sim["part_demand"] = pd.to_numeric(sim["part_demand"], errors="coerce").fillna(0.0)
        sim["planned_output_part_demand"] = pd.to_numeric(
            sim["planned_output_part_demand"], errors="coerce"
        ).fillna(0.0)
        sim["incoming_qty"] = pd.to_numeric(sim["incoming_qty"], errors="coerce").fillna(0.0)
        sim["stock_qty"] = pd.to_numeric(sim["stock_qty"], errors="coerce").fillna(0.0)
        sim["safety_qty"] = pd.to_numeric(sim["safety_qty"], errors="coerce").fillna(0.0)

        sim = simulate_inventory_and_mrp(sim, DEFAULT_LEADTIME_DAYS)

        # 9) Risk summary
        part_risk_summary = (
            sim.groupby("part_no", as_index=False)
            .agg(
                days_below_safety=("below_safety", "sum"),
                days_below_zero=("below_zero", "sum"),
                min_available=("end_available", "min"),
                max_shortage_qty=("shortage_qty", "max"),
                total_recommended_qty=("recommended_po_qty", "sum"),
            )
        )

        risk_parts = (
            part_risk_summary[
                (part_risk_summary["days_below_safety"] > 0) |
                (part_risk_summary["days_below_zero"] > 0)
            ]
            .sort_values(
                ["days_below_zero", "days_below_safety", "max_shortage_qty"],
                ascending=False
            )["part_no"]
            .tolist()
        )

        po_summary = (
            sim[sim["recommended_po_qty"] > 0]
            .groupby("part_no", as_index=False)
            .agg(
                total_recommended_qty=("recommended_po_qty", "sum"),
                first_shortage_date=("forecast_date", "min"),
                first_suggested_order_date=("suggested_order_date", "min"),
                first_required_eta=("required_eta_date", "min"),
                max_shortage_qty=("shortage_qty", "max"),
            )
            .sort_values("total_recommended_qty", ascending=False)
        )

        po_summary = po_summary.merge(
            part_risk_summary[["part_no", "days_below_safety", "days_below_zero", "min_available"]],
            on="part_no",
            how="left",
        )

        # 10) Compare chart
        compare = (
            forecast_df.groupby("forecast_date", as_index=False)[
                ["forecast_demand_qty", "expected_output_qty", "gap_qty"]
            ]
            .sum()
        )

        compare_x = compare["forecast_date"].dt.strftime("%Y-%m-%d").tolist()
        compare_demand = compare["forecast_demand_qty"].astype(int).tolist()
        compare_output = compare["expected_output_qty"].astype(int).tolist()
        compare_gap = compare["gap_qty"].astype(int).tolist()

        # 11) PO chart
        po_labels = []
        po_values = []
        if not po_summary.empty:
            top_po = po_summary.head(10).copy()
            po_labels = top_po["part_no"].astype(str).tolist()
            po_values = top_po["total_recommended_qty"].astype(float).round(2).tolist()

        # 12) PO table
        po_table = []
        if not po_summary.empty:
            table_df = po_summary.head(15).copy()
            for col in ["first_shortage_date", "first_suggested_order_date", "first_required_eta"]:
                table_df[col] = pd.to_datetime(table_df[col]).dt.strftime("%Y-%m-%d")

            numeric_cols = [
                "total_recommended_qty",
                "max_shortage_qty",
                "min_available",
            ]
            for col in numeric_cols:
                table_df[col] = table_df[col].astype(float).round(2)

            po_table = table_df.to_dict(orient="records")

        # 13) summary numbers
        total_demand_part_qty = float(future_bom["part_demand_for_customer_demand"].sum()) if not future_bom.empty else 0.0
        total_output_part_qty = float(future_bom["part_demand_for_planned_output"].sum()) if not future_bom.empty else 0.0

        return {
            "updated_at": pd.Timestamp.now().strftime("%Y-%m-%d %H:%M:%S"),
            "kpi": {
                "avg_health": round(avg_health, 3),
                "min_health": round(min_health, 3),
                "capacity_factor": round(capacity_factor, 3),
                "total_forecast_demand": int(forecast_df["forecast_demand_qty"].sum()) if not forecast_df.empty else 0,
                "total_expected_output": int(forecast_df["expected_output_qty"].sum()) if not forecast_df.empty else 0,
                "total_gap_qty": int(forecast_df["gap_qty"].sum()) if not forecast_df.empty else 0,
                "risk_count": int(len(risk_parts)),
                "total_po_qty": int(po_summary["total_recommended_qty"].sum()) if not po_summary.empty else 0,
                "days_below_zero_parts": int((part_risk_summary["days_below_zero"] > 0).sum()) if not part_risk_summary.empty else 0,
            },
            "risk_parts": risk_parts[:20],
            "summary": {
                "lookback_days": LOOKBACK_DAYS,
                "forecast_days": FORECAST_DAYS,
                "po_count": int(len(po_summary)),
                "logic_note": "Demand forecast and executable output are modeled separately. MRP suggestions are backward-scheduled from shortage date using lead time.",
                "total_demand_part_qty": round(total_demand_part_qty, 2),
                "total_output_part_qty": round(total_output_part_qty, 2),
            },
            "charts": {
                "compare": {
                    "x": compare_x,
                    "demand": compare_demand,
                    "output": compare_output,
                    "gap": compare_gap,
                },
                "iot": {
                    "machines": machine_iot,
                    "machine_ids": list(machine_iot.keys()),
                },
                "po": {
                    "labels": po_labels,
                    "values": po_values,
                },
            },
            "po_table": po_table,
        }

    finally:
        pg_conn.close()
        mysql_conn.close()


@app.route("/api/dashboard")
def api_dashboard():
    return jsonify(build_dashboard_data())


@app.route("/")
def index():
    return """
    <!DOCTYPE html>
    <html lang="zh-Hant">
    <head>
        <meta charset="UTF-8">
        <title>智慧製造 Dashboard</title>
        <script src="https://cdn.plot.ly/plotly-2.35.2.min.js"></script>
        <style>
            body {
                margin: 0;
                font-family: Arial, "Microsoft JhengHei", sans-serif;
                background: #081224;
                color: #eaf2ff;
            }
            .header {
                padding: 20px 30px;
                background: linear-gradient(90deg, #0c1f3f, #102c57);
                border-bottom: 1px solid #1f4f8a;
                position: relative;
            }
            .container { padding: 20px; }
            .kpi-grid {
                display: grid;
                grid-template-columns: repeat(6, 1fr);
                gap: 16px;
                margin-bottom: 20px;
            }
            .chart-grid {
                display: grid;
                grid-template-columns: 1fr 1fr;
                gap: 20px;
                margin-bottom: 20px;
            }
            .full { grid-column: 1 / -1; }
            .card {
                background: #0f1b33;
                border: 1px solid #17375f;
                border-radius: 14px;
                padding: 18px;
            }
            .value {
                font-size: 28px;
                font-weight: bold;
            }
            .tag {
                display: inline-block;
                padding: 8px 12px;
                margin: 6px 6px 0 0;
                border-radius: 20px;
            }
            .tag.danger {
                background: rgba(255, 80, 80, 0.15);
                border: 1px solid #ff6b6b;
            }
            .tag.ok {
                background: rgba(80, 255, 140, 0.12);
                border: 1px solid #58d68d;
            }
            table.data-table {
                width: 100%;
                border-collapse: collapse;
                color: #fff;
                font-size: 14px;
            }
            table.data-table th, table.data-table td {
                border: 1px solid #1d3f66;
                padding: 8px 10px;
                text-align: center;
            }
            table.data-table th {
                background: #12315a;
            }
            .loading {
                color: #8fb7ff;
                margin-top: 10px;
            }
            .lang-btn {
                font-size: 14px;
                width: 70px;
                height: 30px;
                margin-left: 6px;
                border-radius: 6px;
                border: 1px solid #1f4f8a;
                background: #102c57;
                color: #fff;
                cursor: pointer;
                transition: 0.2s;
            }
            .lang-btn:hover {
                background: #1a3f75;
            }
            .machine-selector {
                background: #102c57;
                color: #fff;
                border: 1px solid #1f4f8a;
                border-radius: 6px;
                padding: 6px 10px;
            }
        </style>
    </head>
    <body>
        <div class="header">
            <div style="position:absolute; right:30px; top:25px;">
                <button class="lang-btn" onclick="setLang('en')">EN</button>
                <button class="lang-btn" onclick="setLang('zh')">中文</button>
            </div>
            <h1 id="title">智慧製造即時監控 Dashboard</h1>
            <p><span id="label_updated_at">更新時間：</span> <span id="updated_at">載入中...</span></p>
        </div>

        <div class="container">
            <div class="kpi-grid">
                <div class="card"><h3 id="label_avg_health">平均設備健康度</h3><div class="value" id="avg_health">-</div></div>
                <div class="card"><h3 id="label_min_health">最低設備健康度</h3><div class="value" id="min_health">-</div></div>
                <div class="card"><h3 id="label_capacity_factor">產能修正係數</h3><div class="value" id="capacity_factor">-</div></div>
                <div class="card"><h3 id="label_original_qty">預測總需求</h3><div class="value" id="total_original_qty">-</div></div>
                <div class="card"><h3 id="label_forecast_qty">預估總產出</h3><div class="value" id="total_forecast_qty">-</div></div>
                <div class="card"><h3 id="label_risk_po">風險零件數 / 建議採購量</h3><div class="value" id="risk_po">-</div></div>
            </div>

            <div class="chart-grid">
                <div class="card"><div id="compare_chart"></div></div>

                <div class="card">
                    <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:10px;">
                        <h3 id="iot_chart_title_text" style="margin:0;">Machine Health Monitoring</h3>
                        <select id="machine_selector" class="machine-selector"></select>
                    </div>
                    <div id="iot_chart"></div>
                </div>

                <div class="card full"><div id="po_chart"></div></div>
            </div>

            <div class="chart-grid">
                <div class="card">
                    <h3 id="label_risk_parts">風險零件</h3>
                    <div id="risk_parts"></div>
                </div>
                <div class="card">
                    <h3 id="label_summary">系統摘要</h3>
                    <div id="summary_block"></div>
                </div>
            </div>

            <div class="card">
                <h3 id="label_po_table">採購建議明細</h3>
                <div id="po_table"></div>
            </div>

            <div class="loading" id="status_text">資料更新中...</div>
        </div>

        <script>
        let LANG = "en";
        let dashboardData = null;
        let selectedMachine = null;

        const TEXT = {
            zh: {
                title: "智慧製造即時監控 Dashboard",
                updated_at: "更新時間：",
                avg_health: "平均設備健康度",
                min_health: "最低設備健康度",
                capacity_factor: "產能修正係數",
                original_demand: "預測總需求",
                adjusted_demand: "預估總產出",
                risk_parts: "風險零件",
                summary: "系統摘要",
                po_table: "採購建議明細",
                risk_po: "風險零件數 / 建議採購量",
                loading: "資料更新中...",
                updated: "資料已更新",
                update_failed: "更新失敗：",
                no_risk_parts: "目前無風險零件",
                no_po_data: "目前無採購建議資料",
                part_no: "圖號",
                suggested_po_qty: "建議採購量",
                first_shortage_date: "最早缺料日",
                first_order_date: "建議下單日",
                first_eta: "需求到貨日",
                days_below_safety: "低於安全庫存天數",
                days_below_zero: "負庫存天數",
                max_shortage_qty: "最大缺口",
                min_available: "最低可用量",
                original_demand_legend: "預測需求",
                adjusted_demand_legend: "預估產出",
                gap_legend: "產能缺口",
                temperature: "溫度",
                vibration: "震動",
                health_score: "健康度",
                suggested_po_legend: "建議採購量",
                compare_chart_title: "未來 7 天需求 / 產出 / 缺口",
                iot_chart_title: "設備健康監控",
                po_chart_title: "Top 10 採購建議零件"
            },
            en: {
                title: "Smart Manufacturing Dashboard",
                updated_at: "Updated at:",
                avg_health: "Average Machine Health",
                min_health: "Minimum Machine Health",
                capacity_factor: "Capacity Adjustment",
                original_demand: "Forecast Demand",
                adjusted_demand: "Expected Output",
                risk_parts: "Risk Parts",
                summary: "System Summary",
                po_table: "Purchase Recommendations",
                risk_po: "Risk Parts / Suggested PO Qty",
                loading: "Updating data...",
                updated: "Updated",
                update_failed: "Update failed: ",
                no_risk_parts: "No risk parts currently",
                no_po_data: "No purchase recommendation data",
                part_no: "Part No.",
                suggested_po_qty: "Suggested PO Qty",
                first_shortage_date: "First Shortage Date",
                first_order_date: "Suggested Order Date",
                first_eta: "Required ETA",
                days_below_safety: "Days Below Safety",
                days_below_zero: "Days Below Zero",
                max_shortage_qty: "Max Shortage",
                min_available: "Min Available",
                original_demand_legend: "Forecast Demand",
                adjusted_demand_legend: "Expected Output",
                gap_legend: "Output Gap",
                temperature: "Temperature",
                vibration: "Vibration",
                health_score: "Health Score",
                suggested_po_legend: "Suggested PO Qty",
                compare_chart_title: "7-Day Demand / Output / Gap",
                iot_chart_title: "Machine Health Monitoring",
                po_chart_title: "Top 10 Recommended Purchase Parts"
            }
        };

        function applyLang() {
            const t = TEXT[LANG];
            document.getElementById("title").textContent = t.title;
            document.getElementById("label_updated_at").textContent = t.updated_at;
            document.getElementById("label_avg_health").textContent = t.avg_health;
            document.getElementById("label_min_health").textContent = t.min_health;
            document.getElementById("label_capacity_factor").textContent = t.capacity_factor;
            document.getElementById("label_original_qty").textContent = t.original_demand;
            document.getElementById("label_forecast_qty").textContent = t.adjusted_demand;
            document.getElementById("label_risk_po").textContent = t.risk_po;
            document.getElementById("label_risk_parts").textContent = t.risk_parts;
            document.getElementById("label_summary").textContent = t.summary;
            document.getElementById("label_po_table").textContent = t.po_table;
            document.getElementById("iot_chart_title_text").textContent = t.iot_chart_title;
        }

        function renderCompareChart() {
            if (!dashboardData) return;

            Plotly.react("compare_chart", [
                {
                    x: dashboardData.charts.compare.x,
                    y: dashboardData.charts.compare.demand,
                    type: "bar",
                    name: TEXT[LANG].original_demand_legend
                },
                {
                    x: dashboardData.charts.compare.x,
                    y: dashboardData.charts.compare.output,
                    type: "bar",
                    name: TEXT[LANG].adjusted_demand_legend
                },
                {
                    x: dashboardData.charts.compare.x,
                    y: dashboardData.charts.compare.gap,
                    type: "scatter",
                    mode: "lines+markers",
                    name: TEXT[LANG].gap_legend
                }
            ], {
                title: TEXT[LANG].compare_chart_title,
                barmode: "group",
                template: "plotly_dark",
                height: 350,
                margin: { t: 50, l: 50, r: 20, b: 50 },
                paper_bgcolor: "#0f1b33",
                plot_bgcolor: "#0f1b33"
            }, { responsive: true });
        }

        function renderIotChart() {
            if (!dashboardData || !dashboardData.charts || !dashboardData.charts.iot) return;

            const machines = dashboardData.charts.iot.machines || {};
            const machineIds = dashboardData.charts.iot.machine_ids || [];

            if (!selectedMachine && machineIds.length > 0) {
                selectedMachine = machineIds[0];
            }

            const current = machines[selectedMachine];
            if (!current) {
                Plotly.react("iot_chart", [], {
                    title: TEXT[LANG].iot_chart_title,
                    template: "plotly_dark",
                    height: 350,
                    paper_bgcolor: "#0f1b33",
                    plot_bgcolor: "#0f1b33"
                }, { responsive: true });
                return;
            }

            Plotly.react("iot_chart", [
                {
                    x: current.x,
                    y: current.temperature,
                    type: "scatter",
                    mode: "lines+markers",
                    name: TEXT[LANG].temperature,
                    yaxis: "y"
                },
                {
                    x: current.x,
                    y: current.vibration,
                    type: "scatter",
                    mode: "lines+markers",
                    name: TEXT[LANG].vibration,
                    yaxis: "y2"
                },
                {
                    x: current.x,
                    y: current.health_score,
                    type: "scatter",
                    mode: "lines+markers",
                    name: TEXT[LANG].health_score,
                    yaxis: "y3"
                }
            ], {
                title: `${TEXT[LANG].iot_chart_title} - ${selectedMachine}`,
                template: "plotly_dark",
                height: 350,
                margin: { t: 50, l: 50, r: 60, b: 50 },
                paper_bgcolor: "#0f1b33",
                plot_bgcolor: "#0f1b33",
                yaxis: { title: TEXT[LANG].temperature },
                yaxis2: {
                    title: TEXT[LANG].vibration,
                    overlaying: "y",
                    side: "right"
                },
                yaxis3: {
                    title: TEXT[LANG].health_score,
                    overlaying: "y",
                    side: "right",
                    position: 0.93,
                    range: [0, 1]
                }
            }, { responsive: true });
        }

        function renderPoChart() {
            if (!dashboardData) return;

            Plotly.react("po_chart", [
                {
                    x: dashboardData.charts.po.labels,
                    y: dashboardData.charts.po.values,
                    type: "bar",
                    name: TEXT[LANG].suggested_po_legend
                }
            ], {
                title: TEXT[LANG].po_chart_title,
                template: "plotly_dark",
                height: 350,
                margin: { t: 50, l: 50, r: 20, b: 50 },
                paper_bgcolor: "#0f1b33",
                plot_bgcolor: "#0f1b33"
            }, { responsive: true });
        }

        function setLang(lang) {
            LANG = lang;
            applyLang();

            if (dashboardData) {
                renderCompareChart();
                renderIotChart();
                renderPoChart();
                renderSummary();
                renderPoTable();
                renderRiskParts();
            }
        }

        function renderRiskParts() {
            const data = dashboardData;
            const riskBox = document.getElementById("risk_parts");
            if (data.risk_parts.length > 0) {
                riskBox.innerHTML = data.risk_parts.map(x => `<span class="tag danger">${x}</span>`).join("");
            } else {
                riskBox.innerHTML = `<span class="tag ok">${TEXT[LANG].no_risk_parts}</span>`;
            }
        }

        function renderSummary() {
            const data = dashboardData;
            if (LANG === "zh") {
                document.getElementById("summary_block").innerHTML = `
                    <p>近 ${data.summary.lookback_days} 天歷史資料已補齊無訂單日後再進行需求預測，降低平均值高估風險。</p>
                    <p>未來 ${data.summary.forecast_days} 天同時保留「預測需求」與「設備健康度修正後可執行產出」兩條邏輯。</p>
                    <p>MRP 建議以下游需求日回推 lead time，避免把缺料日誤當成下單日。</p>
                    <p>需求端零件總量：${data.summary.total_demand_part_qty}；可執行產出對應零件總量：${data.summary.total_output_part_qty}。</p>
                    <p>建議採購品項數：${data.summary.po_count}。</p>
                `;
            } else {
                document.getElementById("summary_block").innerHTML = `
                    <p>Historical demand is forecast after filling zero-order days, reducing upward bias in averages.</p>
                    <p>The model separately keeps forecast demand and executable output adjusted by machine health.</p>
                    <p>MRP suggestions are backward-scheduled from shortage date using lead time.</p>
                    <p>Total parts for demand: ${data.summary.total_demand_part_qty}; total parts for executable output: ${data.summary.total_output_part_qty}.</p>
                    <p>Suggested purchase items: ${data.summary.po_count}.</p>
                `;
            }
        }

        function renderPoTable() {
            const data = dashboardData;
            const tableRows = data.po_table.length > 0
                ? `
                    <table class="data-table">
                        <thead>
                            <tr>
                                <th>${TEXT[LANG].part_no}</th>
                                <th>${TEXT[LANG].suggested_po_qty}</th>
                                <th>${TEXT[LANG].first_shortage_date}</th>
                                <th>${TEXT[LANG].first_order_date}</th>
                                <th>${TEXT[LANG].first_eta}</th>
                                <th>${TEXT[LANG].days_below_safety}</th>
                                <th>${TEXT[LANG].days_below_zero}</th>
                                <th>${TEXT[LANG].max_shortage_qty}</th>
                                <th>${TEXT[LANG].min_available}</th>
                            </tr>
                        </thead>
                        <tbody>
                            ${data.po_table.map(row => `
                                <tr>
                                    <td>${row.part_no}</td>
                                    <td>${row.total_recommended_qty}</td>
                                    <td>${row.first_shortage_date}</td>
                                    <td>${row.first_suggested_order_date}</td>
                                    <td>${row.first_required_eta}</td>
                                    <td>${row.days_below_safety}</td>
                                    <td>${row.days_below_zero}</td>
                                    <td>${row.max_shortage_qty}</td>
                                    <td>${row.min_available}</td>
                                </tr>
                            `).join("")}
                        </tbody>
                    </table>
                `
                : `<p>${TEXT[LANG].no_po_data}</p>`;

            document.getElementById("po_table").innerHTML = tableRows;
        }

        async function loadDashboard() {
            const status = document.getElementById("status_text");
            status.textContent = TEXT[LANG].loading;

            try {
                const res = await fetch("/api/dashboard?t=" + new Date().getTime());
                const data = await res.json();

                if (data.error) {
                    document.body.innerHTML = `
                        <div style="padding:40px;color:white;background:#081224;font-family:Arial;">
                            <h1>智慧製造 Dashboard</h1>
                            <p>${data.error}</p>
                        </div>
                    `;
                    return;
                }

                dashboardData = data;

                document.getElementById("updated_at").textContent = data.updated_at;
                document.getElementById("avg_health").textContent = data.kpi.avg_health.toFixed(3);
                document.getElementById("min_health").textContent = data.kpi.min_health.toFixed(3);
                document.getElementById("capacity_factor").textContent = data.kpi.capacity_factor.toFixed(3);
                document.getElementById("total_original_qty").textContent = data.kpi.total_forecast_demand;
                document.getElementById("total_forecast_qty").textContent = data.kpi.total_expected_output;
                document.getElementById("risk_po").textContent = `${data.kpi.risk_count} / ${data.kpi.total_po_qty}`;

                const selector = document.getElementById("machine_selector");
                const machineIds = data.charts.iot.machine_ids || [];

                selector.innerHTML = machineIds.map(id => `<option value="${id}">${id}</option>`).join("");

                if (!selectedMachine || !machineIds.includes(selectedMachine)) {
                    selectedMachine = machineIds.length > 0 ? machineIds[0] : null;
                }

                selector.value = selectedMachine || "";
                selector.onchange = function () {
                    selectedMachine = this.value;
                    renderIotChart();
                };

                renderRiskParts();
                renderSummary();
                renderPoTable();
                renderCompareChart();
                renderIotChart();
                renderPoChart();

                status.textContent = TEXT[LANG].updated;
            } catch (err) {
                console.error(err);
                status.textContent = TEXT[LANG].update_failed + err;
            }
        }

        applyLang();
        loadDashboard();
        setInterval(loadDashboard, 5000);
        </script>
    </body>
    </html>
    """


if __name__ == "__main__":
    app.run(debug=True, use_reloader=False, host="0.0.0.0", port=5000)