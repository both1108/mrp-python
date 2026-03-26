import random
import time
from datetime import datetime

from db.mysql import get_mysql_conn_with_retry
from config.settings import (
    SIMULATOR_RETRIES,
    SIMULATOR_RETRY_DELAY,
    SIMULATOR_SLEEP_SECONDS,
    SIMULATOR_CLEANUP_EVERY,
    SIMULATOR_CLEANUP_MINUTES,
)


machine_states = {
    "M-01": {"temperature": 74.0, "vibration": 0.0350, "rpm": 1480},
    "M-02": {"temperature": 72.0, "vibration": 0.0320, "rpm": 1450},
}


def clamp(value, min_value, max_value):
    return max(min_value, min(value, max_value))


def update_machine_state(state):
    state["temperature"] = clamp(
        state["temperature"] + random.uniform(-0.6, 0.9), 60, 95
    )
    state["vibration"] = clamp(
        state["vibration"] + random.uniform(-0.0025, 0.0035), 0.01, 0.10
    )
    state["rpm"] = int(clamp(
        state["rpm"] + random.randint(-12, 15), 1000, 1600
    ))

    if random.random() < 0.08:
        state["temperature"] = clamp(
            state["temperature"] + random.uniform(2.0, 5.0), 60, 95
        )
        state["vibration"] = clamp(
            state["vibration"] + random.uniform(0.008, 0.02), 0.01, 0.10
        )
        state["rpm"] = int(clamp(
            state["rpm"] + random.randint(20, 50), 1000, 1600
        ))


def insert_machine_data(cursor, machine_id, state):
    sql = """
    INSERT INTO machine_data
    (machine_id, temperature, vibration, rpm, created_at)
    VALUES (%s, %s, %s, %s, %s)
    """

    data = (
        machine_id,
        round(state["temperature"], 2),
        round(state["vibration"], 4),
        state["rpm"],
        datetime.now(),
    )

    cursor.execute(sql, data)
    print("Inserted:", data, flush=True)


def cleanup_old_data(cursor):
    sql = f"""
    DELETE FROM machine_data
    WHERE created_at < NOW() - INTERVAL {SIMULATOR_CLEANUP_MINUTES} MINUTE
    """
    cursor.execute(sql)
    print(f"🧹 Cleaned records older than {SIMULATOR_CLEANUP_MINUTES} minutes", flush=True)


def run_simulator():
    conn = get_mysql_conn_with_retry(
        retries=SIMULATOR_RETRIES,
        delay=SIMULATOR_RETRY_DELAY,
    )
    cursor = conn.cursor()

    print("🚀 IoT Simulator started...", flush=True)

    loop_count = 0

    try:
        while True:
            for machine_id, state in machine_states.items():
                update_machine_state(state)
                insert_machine_data(cursor, machine_id, state)

            loop_count += 1
            if loop_count % SIMULATOR_CLEANUP_EVERY == 0:
                cleanup_old_data(cursor)

            time.sleep(SIMULATOR_SLEEP_SECONDS)

    except KeyboardInterrupt:
        print("\n🛑 Simulator stopped by user.", flush=True)

    finally:
        cursor.close()
        conn.close()
        print("✅ MySQL connection closed.", flush=True)


if __name__ == "__main__":
    run_simulator()