import os
from dotenv import load_dotenv
import pymysql
import psycopg2
import pandas as pd
import matplotlib.pyplot as plt
print("CWD =", os.getcwd())
load_dotenv()  # 讀取 .env
print("PG_PORT =", os.getenv("PG_PORT"))

# === PostgreSQL（電商）===
pg_conn = psycopg2.connect(
    host=os.getenv("PG_HOST"),
    database=os.getenv("PG_DB"),
    user=os.getenv("PG_USER"),
    password=os.getenv("PG_PASSWORD"),
    port=int(os.getenv("PG_PORT"))
)

# === MySQL（ERP）===
mysql_conn = pymysql.connect(
    host=os.getenv("MYSQL_HOST"),
    port=int(os.getenv("MYSQL_PORT")),
    user=os.getenv("MYSQL_USER"),
    password=os.getenv("MYSQL_PASSWORD"),
    database=os.getenv("MYSQL_DB")
)


# === 3. 有效訂單需求（PostgreSQL）===
order_sql = """
SELECT 
    p.id AS product_id,
    p.name AS product_name,
    SUM(oi.quantity) AS demand_qty
FROM orders o
JOIN order_items oi ON o.id = oi.order_id
JOIN products p ON oi.product_id = p.id
WHERE 
    o.status != 'cancelled'
    AND o.is_shipped = false
GROUP BY p.id, p.name;
"""

orders_df = pd.read_sql(order_sql, pg_conn)

print("orders_df 筆數:", len(orders_df))
print(orders_df.head())
print(orders_df["product_id"].unique())

# === 4. BOM 展開（MySQL）===
bom_sql = """
SELECT 
    CAST(TRIM(b.`英文編碼`) AS UNSIGNED) AS product_id,
    d.`圖號` AS part_no,
    d.`需求數量`
FROM bom主檔 b
JOIN bom明細 d ON b.bom_id = d.bom_id;
"""

bom_df = pd.read_sql(bom_sql, mysql_conn)

bom_df["product_id"] = pd.to_numeric(bom_df["product_id"], errors="coerce")
orders_df["product_id"] = orders_df["product_id"].astype(int)
print("bom_df 筆數:", len(bom_df))
print(bom_df.head())
print(bom_df["product_id"].unique())

merged = pd.merge(orders_df, bom_df, on="product_id")

merged["part_demand"] = merged["demand_qty"] * merged["需求數量"]
print("第一次 merge 筆數:", len(merged))
print(merged.head())

# === 5. 加入庫存（MySQL）===
part_sql = """
SELECT `圖號` AS part_no, `數量` AS stock_qty, `安全量`
FROM 零件;
"""
parts_df = pd.read_sql(part_sql, mysql_conn)

merged = pd.merge(merged, parts_df, on="part_no")
print("加庫存後筆數:", len(merged))

# === 6. 加入採購在途（MySQL）===
purchase_sql = """
SELECT 
    `圖號` AS part_no, 
    SUM(`叫貨數量`) AS incoming_qty
FROM purchase
WHERE `到貨狀態` = '未到貨'
GROUP BY `圖號`;
"""

purchase_df = pd.read_sql(purchase_sql, mysql_conn)

merged = pd.merge(merged, purchase_df, on="part_no", how="left")
merged["incoming_qty"] = merged["incoming_qty"].fillna(0)
print("加採購後筆數:", len(merged))

# === 7. 計算缺料 ===
merged["final_available"] = merged["stock_qty"] + merged["incoming_qty"] - merged["part_demand"]
merged["shortage"] = merged["final_available"] < merged["安全量"]

result = merged.groupby("part_no").agg({
    "part_demand": "sum",
    "stock_qty": "first",
    "incoming_qty": "first",
    "安全量": "first",
    "final_available": "first",
    "shortage": "first"
}).reset_index()

# === 建議採購量（為了回到安全量）===
result["recommended_qty"] = (
    result["安全量"] + result["part_demand"]
    - (result["stock_qty"] + result["incoming_qty"])
).clip(lower=0)

# === 採購後可供量（假設依建議量採購）===
result["post_po_available"] = (
    result["final_available"] + result["recommended_qty"]
)
result = result.rename(columns={
    "part_no": "零件圖號",
    "part_demand": "需求量",
    "stock_qty": "現有庫存",
    "incoming_qty": "在途數量",
    "安全量": "安全庫存量",
    "final_available": "可供使用量",
    "recommended_qty": "建議採購量",
    "post_po_available": "採購後可供量"
})


# 只看真的需要叫貨的
po_list = result[result["建議採購量"] > 0].copy()

print("\n=== 建議採購清單（Recommended PO） ===")
print(
    po_list.sort_values("建議採購量", ascending=False)[[
        "零件圖號",
        "需求量",
        "現有庫存",
        "在途數量",
        "安全庫存量",
        "可供使用量",
        "建議採購量",
        "採購後可供量"
    ]]
)


# === 8. 視覺化採購量 ===
shortage_parts = result[result["shortage"] == True]

plt.figure(figsize=(12,6))
plt.bar(po_list["零件圖號"], po_list["建議採購量"])
plt.title("Recommended Purchase Quantity (to meet Safety Stock)")
plt.xlabel("Part No")
plt.ylabel("Recommended Qty")
plt.xticks(rotation=45)
plt.show()
