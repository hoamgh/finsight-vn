import re
from io import StringIO

import requests
import pandas as pd


def build_income_statement_url(ticker, year, quarter):
    ticker = ticker.lower()

    return (
        f"https://cafef.vn/du-lieu/bao-cao-tai-chinh/"
        f"{ticker}/incsta/{year}/{quarter}/0/0/"
        f"ket-qua-hoat-dong-kinh-doanh-cong-ty-co-phan-{ticker}.chn"
    )


def find_financial_table(tables):
    for table in tables:
        text = " ".join(map(str, table.to_numpy().ravel()))

        if (
            "Doanh thu thuần" in text
            and "Lợi nhuận sau thuế" in text
        ):
            return table

    raise ValueError("Financial statement table not found")


def find_quarter_columns(tables):
    for table in tables:
        text = " ".join(map(str, table.to_numpy().ravel()))
        matches = re.findall(r"Quý\s*(\d)\s*-?\s*(\d{4})", text)

        if len(matches) == 4:
            return [f"{year}Q{quarter}" for quarter, year in matches]

    raise ValueError("Quarter columns not found")


def fetch_income_statement(ticker, year, quarter):
    url = build_income_statement_url(
        ticker=ticker,
        year=year,
        quarter=quarter
    )

    response = requests.get(url, timeout=30)
    response.raise_for_status()

    return parse_income_statement_html(response.text)


def parse_income_statement_html(html):
    """Parse a CafeF Income Statement from a replayable raw HTML snapshot."""
    tables = pd.read_html(StringIO(html))

    financial_table = find_financial_table(tables)
    quarter_columns = find_quarter_columns(tables)

    # CafeF returns: metric, four quarters, and an empty growth column.
    financial_table = financial_table.iloc[:, : len(quarter_columns) + 1].copy()
    financial_table.columns = ["metric_raw", *quarter_columns]
    financial_table["metric_raw"] = financial_table["metric_raw"].str.strip()

    return financial_table


def combine_income_statement_windows(ticker, dataframes):
    frames = []

    for wide in dataframes:
        long = wide.melt(
            id_vars="metric_raw",
            var_name="period",
            value_name="value",
        )
        long.insert(0, "ticker", ticker.upper())
        frames.append(long)

    history = pd.concat(frames, ignore_index=True)
    history = history.dropna(subset=["value"])
    history = history.drop_duplicates(
        subset=["ticker", "period", "metric_raw"],
        keep="last",
    )

    return history.sort_values(
        ["period", "metric_raw"],
        ignore_index=True,
    )


def fetch_income_statement_history(ticker, windows):
    dataframes = [
        fetch_income_statement(ticker, year, quarter)
        for year, quarter in windows
    ]
    return combine_income_statement_windows(ticker, dataframes)


if __name__ == "__main__":
    windows = [(2024, 2), (2025, 2), (2026, 2)]
    dataframes = [
        fetch_income_statement("FPT", year, quarter)
        for year, quarter in windows
    ]

    for window, dataframe in zip(windows, dataframes):
        print(f"FPT {window[0]}Q{window[1]}:")
        print("Columns:", dataframe.columns.tolist())
        print("Shape:", dataframe.shape)

    history = combine_income_statement_windows("FPT", dataframes)

    print("\nCombined history:")
    print(history.head())
    print("Shape:", history.shape)
