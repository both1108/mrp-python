from datetime import date
import pandas as pd


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
        freq="D",
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