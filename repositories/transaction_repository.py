import pandas as pd
from config.settings import LOOKBACK_DAYS


def get_order_history_df(pg_conn):
    sql = f"""
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
    return pd.read_sql(sql, pg_conn)