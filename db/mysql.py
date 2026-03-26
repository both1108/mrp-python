import time
import pymysql

from config.settings import (
    MYSQL_HOST,
    MYSQL_PORT,
    MYSQL_USER,
    MYSQL_PASSWORD,
    MYSQL_DB,
)


def get_mysql_conn():
    return pymysql.connect(
        host=MYSQL_HOST,
        port=MYSQL_PORT,
        user=MYSQL_USER,
        password=MYSQL_PASSWORD,
        database=MYSQL_DB,
        charset="utf8mb4",
        use_unicode=True,
        init_command="SET NAMES utf8mb4",
    )


def get_mysql_conn_autocommit():
    return pymysql.connect(
        host=MYSQL_HOST,
        port=MYSQL_PORT,
        user=MYSQL_USER,
        password=MYSQL_PASSWORD,
        database=MYSQL_DB,
        charset="utf8mb4",
        autocommit=True,
    )


def get_mysql_conn_with_retry(retries=20, delay=3):
    last_error = None

    for i in range(retries):
        try:
            conn = get_mysql_conn_autocommit()
            print(f"✅ Connected to MySQL on attempt {i + 1}", flush=True)
            return conn
        except Exception as e:
            last_error = e
            print(f"⏳ MySQL not ready yet ({i + 1}/{retries}): {e}", flush=True)
            time.sleep(delay)

    raise last_error