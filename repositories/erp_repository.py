import pandas as pd


def get_bom_df(mysql_conn):
    sql = """
    SELECT 
        CAST(TRIM(b.product_code) AS UNSIGNED) AS product_id,
        d.part_no AS part_no,
        d.qty AS bom_qty
    FROM bom_header b
    JOIN bom_detail d ON b.bom_id = d.bom_id;
    """
    return pd.read_sql(sql, mysql_conn)


def get_parts_df(mysql_conn):
    sql = """
    SELECT part_no, stock_qty, safety_stock AS safety_qty
    FROM parts;
    """
    return pd.read_sql(sql, mysql_conn)


def get_incoming_purchase_df(mysql_conn):
    sql = """
    SELECT 
        part_no,
        DATE(delivery_date) AS eta_date,
        SUM(order_qty) AS incoming_qty
    FROM purchase
    WHERE status = 'pending'
      AND delivery_date IS NOT NULL
    GROUP BY part_no, DATE(delivery_date);
    """
    return pd.read_sql(sql, mysql_conn)