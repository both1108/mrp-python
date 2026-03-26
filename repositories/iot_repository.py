import pandas as pd
from config.settings import IOT_LOOKBACK_HOURS


def get_recent_iot_df(mysql_conn):
    sql = f"""
    SELECT machine_id, temperature, vibration, rpm, created_at
    FROM machine_data
    WHERE created_at >= NOW() - INTERVAL {IOT_LOOKBACK_HOURS} HOUR
    ORDER BY machine_id, created_at ASC;
    """
    return pd.read_sql(sql, mysql_conn)