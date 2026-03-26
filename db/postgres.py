import psycopg2

from config.settings import (
    PG_HOST,
    PG_DB,
    PG_USER,
    PG_PASSWORD,
    PG_PORT,
)


def get_pg_conn():
    return psycopg2.connect(
        host=PG_HOST,
        database=PG_DB,
        user=PG_USER,
        password=PG_PASSWORD,
        port=PG_PORT,
    )