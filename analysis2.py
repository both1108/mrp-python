import os
from datetime import date, timedelta

from dotenv import load_dotenv
import pymysql
import psycopg2
import pandas as pd
import matplotlib.pyplot as plt

# =========================
# 0) Settings
# =========================
LOOKBACK_DAYS = 30
FORECAST_DAYS = 7

load_dotenv()

# =========================
# 1) Connect DBs (ENV)
# =========================
pg_conn = psycopg2.connect(
    host=os.getenv("PG_HOST"),
    database=os.getenv("PG_DB"),
    user=os.getenv("PG_USER"),
    password=os.getenv("PG_PASSWORD"),
    port=int(os.getenv("PG_PORT", "5432")),
)

mysql_conn = pymysql.connect(
    host=os.getenv("MYSQL_HOST", "localhost"),
    port=int(os.getenv("MYSQL_PORT", "3306")),
    user=os.getenv("MYSQL_USER", "root"),
    password=os.getenv("MYSQL_PASSWORD", ""),
    database=os.getenv("MYSQL_DB", "test"),
)

# =========================
# 2) Load BOM (MySQL)
# =========================
bom_sql = """
SELECT 
    CAST(TRIM(b.`英文編碼`) AS UNSIGNED) AS product_id,
    d.`圖號` AS part_no,
    d.`需求數量` AS bom_qty
FROM bom主檔 b
JOIN bom明細 d ON b.bom_id = d.bom_id;
"""
bom_df = pd.read_sql(bom_sql, mysql_conn)
bom_df["product_id"] = pd.to_numeric(bom_df["product_id"], errors="coerce").astype("Int64")
bom_df = bom_df.dropna(subset=["product_id"])
bom_df["product_id"] = bom_df["product_id"].astype(int)

# =========================
# 3) Load Parts Stock/Safety (MySQL)
# =========================
parts_sql = """
SELECT `圖號` AS part_no, `數量` AS stock_qty, `安全量` AS safety_qty
FROM 零件;
"""
parts_df = pd.read_sql(parts_sql, mysql_conn)

# =========================
# 4) Load Incoming by ETA date (MySQL)
#    只算 未到貨 且 交貨日期有值
# =========================
purchase_sql = """
SELECT 
    `圖號` AS part_no,
    DATE(`交貨日期`) AS eta_date,
    SUM(`叫貨數量`) AS incoming_qty
FROM purchase
WHERE `到貨狀態` = '未到貨'
  AND `交貨日期` IS NOT NULL
GROUP BY `圖號`, DATE(`交貨日期`);
"""
incoming_df = pd.read_sql(purchase_sql, mysql_conn)
if not incoming_df.empty:
    incoming_df["eta_date"] = pd.to_datetime(incoming_df["eta_date"])


# =========================
# 5) Historical daily demand per product (PostgreSQL)
#    用 orders.created_at 做近 LOOKBACK_DAYS 天的日需求
#    排除 cancelled
# =========================
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
    raise RuntimeError("近 LOOKBACK_DAYS 天沒有訂單資料（hist_df 為空）。請確認 orders.created_at 是否有資料。")

hist_df["order_date"] = pd.to_datetime(hist_df["order_date"])
hist_df["dow"] = hist_df["order_date"].dt.dayofweek

hist_df["product_id"] = hist_df["product_id"].astype(int)
hist_df["dow"] = pd.to_datetime(hist_df["order_date"]).dt.dayofweek  # Mon=0..Sun=6

# =========================
# 6) Forecast next 7 days (weekday average)
#    每個 product_id × (星期幾) 的平均需求
# =========================
weekday_mean = (
    hist_df.groupby(["product_id", "dow"])["qty"]
    .mean()
    .reset_index()
    .rename(columns={"qty": "forecast_qty"})
)

overall_mean = (
    hist_df.groupby("product_id")["qty"]
    .mean()
    .reset_index()
    .rename(columns={"qty": "overall_forecast_qty"})
)

today = date.today()
future_dates = [today + timedelta(days=i) for i in range(1, FORECAST_DAYS + 1)]
future_df = pd.DataFrame({"forecast_date": pd.to_datetime(future_dates)})
future_df["dow"] = future_df["forecast_date"].dt.dayofweek



# 做出所有產品 × 未來日期的組合
products = hist_df["product_id"].unique()
grid = future_df.assign(key=1).merge(pd.DataFrame({"product_id": products, "key": 1}), on="key").drop(columns=["key"])

# 先用星期幾平均，沒有就 fallback 用 overall 平均，再沒有就 0
forecast_df = (
    grid.merge(weekday_mean, on=["product_id", "dow"], how="left")
        .merge(overall_mean, on="product_id", how="left")
)
forecast_df["forecast_qty"] = forecast_df["forecast_qty"].fillna(forecast_df["overall_forecast_qty"]).fillna(0)
forecast_df["forecast_qty"] = forecast_df["forecast_qty"].round().astype(int)

# 若你想避免「整天 0」，可以設定最小值，例如至少 1：
# forecast_df["forecast_qty"] = forecast_df["forecast_qty"].clip(lower=1)

# =========================
# 7) BOM explode: future product demand -> part demand per day
# =========================
future_bom = forecast_df.merge(bom_df, on="product_id", how="inner")
future_bom["part_demand"] = future_bom["forecast_qty"] * future_bom["bom_qty"]

daily_part_demand = (
    future_bom.groupby(["forecast_date", "part_no"])["part_demand"]
    .sum()
    .reset_index()
)

# =========================
# 8) Build daily incoming per part per day (from purchase ETA)
# =========================
if incoming_df.empty:
    daily_incoming = pd.DataFrame(columns=["forecast_date", "part_no", "incoming_qty"])
else:
    daily_incoming = (
        incoming_df.rename(columns={"eta_date": "forecast_date"})
        .groupby(["forecast_date", "part_no"])["incoming_qty"]
        .sum()
        .reset_index()
    )

# =========================
# 9) Daily simulation for 7 days
#    start_stock -> +incoming_today -> -demand_today -> end_stock
# =========================
# 把 demand / incoming 都補齊成完整 grid（所有日期×所有零件）
parts_list = parts_df["part_no"].unique()
sim_grid = future_df[["forecast_date"]].assign(key=1).merge(pd.DataFrame({"part_no": parts_list, "key": 1}), on="key").drop(columns=["key"])

sim = (
    sim_grid.merge(daily_part_demand, on=["forecast_date", "part_no"], how="left")
            .merge(daily_incoming, on=["forecast_date", "part_no"], how="left")
            .merge(parts_df, on="part_no", how="left")
)

sim["part_demand"] = sim["part_demand"].fillna(0)
sim["incoming_qty"] = sim["incoming_qty"].fillna(0)
sim["stock_qty"] = sim["stock_qty"].fillna(0)
sim["safety_qty"] = sim["safety_qty"].fillna(0)

sim = sim.sort_values(["part_no", "forecast_date"]).reset_index(drop=True)

# 逐零件滾算
sim["start_available"] = 0.0
sim["end_available"] = 0.0
sim["shortage"] = False
sim["recommended_po_qty"] = 0.0
sim["post_po_available"] = 0.0

for part_no, g in sim.groupby("part_no", sort=False):
    prev_end = None
    for idx, row in g.iterrows():
        if prev_end is None:
            start = float(row["stock_qty"])
        else:
            start = float(prev_end)

        start_plus_incoming = start + float(row["incoming_qty"])
        end = start_plus_incoming - float(row["part_demand"])

        # 建議採購：讓「期末」回到安全量
        rec = max(0.0, float(row["safety_qty"]) - end)
        post_po = end + rec

        sim.at[idx, "start_available"] = start_plus_incoming
        sim.at[idx, "end_available"] = end
        sim.at[idx, "shortage"] = end < float(row["safety_qty"])
        sim.at[idx, "recommended_po_qty"] = rec
        sim.at[idx, "post_po_available"] = post_po

        prev_end = end

# =========================
# 10) Output tables (Chinese columns)
# =========================
output = sim.rename(columns={
    "forecast_date": "日期",
    "part_no": "零件圖號",
    "part_demand": "需求量",
    "incoming_qty": "在途到貨量",
    "safety_qty": "安全庫存量",
    "start_available": "當日可用量(含到貨)",
    "end_available": "當日結束可用量",
    "recommended_po_qty": "建議採購量(補到安全)",
    "post_po_available": "採購後可用量(期末)",
    "shortage": "低於安全庫存"
})

# 只看有需求或有在途或有風險的（避免表太大）
focus = output[(output["需求量"] > 0) | (output["在途到貨量"] > 0) | (output["低於安全庫存"])].copy()

print("\n=== 未來 7 天零件供需模擬（重點） ===")
print(focus.sort_values(["低於安全庫存", "日期"], ascending=[False, True]).head(80))

# 風險摘要：7 天內曾低於安全庫存的零件
risk_parts = output.groupby("零件圖號")["低於安全庫存"].any().reset_index()
risk_parts = risk_parts[risk_parts["低於安全庫存"] == True]["零件圖號"].tolist()

print("\n=== 7 天內有風險的零件 ===")
print(risk_parts)

# =========================
# 11) Plot: end_available trend for Top risk parts
# =========================
# 找出「最缺」的幾個零件：期末可用量最小的 Top N
topN = 5
min_end = output.groupby("零件圖號")["當日結束可用量"].min().reset_index().sort_values("當日結束可用量")
top_parts = min_end.head(topN)["零件圖號"].tolist()

plot_df = output[output["零件圖號"].isin(top_parts)].copy()

plt.figure(figsize=(12, 6))
for part in top_parts:
    s = plot_df[plot_df["零件圖號"] == part]
    plt.plot(s["日期"], s["當日結束可用量"], marker="o", label=part)

plt.title("Top Risk Parts - 7 Day Ending Available Trend")
plt.xlabel("Date")
plt.ylabel("Ending Available")
plt.xticks(rotation=45)
plt.legend()
plt.tight_layout()
plt.show()
