import pandas as pd
import numpy as np

from config.settings import (
    TEMP_BASE,
    TEMP_WORST,
    VIB_BASE,
    VIB_WORST,
    RPM_TARGET,
    RPM_TOLERANCE,
)


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