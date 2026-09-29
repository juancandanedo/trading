"""Descarga históricos diarios (OHLCV) de Yahoo Finance y los guarda en data/<TICKER>.csv.

Uso:
    python descargar_datos.py                      # lista por defecto, 10 años
    python descargar_datos.py AAPL MSFT --anios 5  # tickers concretos
    python descargar_datos.py --actualizar         # solo añade las velas nuevas

Leer luego desde otro script:
    from descargar_datos import cargar
    df = cargar("SPY")
"""
import argparse
from pathlib import Path

import pandas as pd
import yfinance as yf

DATA_DIR = Path(__file__).resolve().parent / "data"

TICKERS = [
    # ETFs de índices
    "SPY", "QQQ", "IWM", "DIA",
    # Acciones grandes de EE. UU.
    "AAPL", "MSFT", "NVDA", "AMZN", "GOOGL", "META", "TSLA", "JPM", "V", "XOM",
]


def descargar(ticker: str, inicio: str | None = None, anios: int = 10) -> pd.DataFrame:
    """Velas diarias ajustadas por splits y dividendos (auto_adjust)."""
    kwargs = {"start": inicio} if inicio else {"period": f"{anios}y"}
    df = yf.Ticker(ticker).history(interval="1d", auto_adjust=True, **kwargs)
    if df.empty:
        return df
    df = df[["Open", "High", "Low", "Close", "Volume"]]
    df.index = df.index.tz_localize(None).normalize()
    df.index.name = "Date"
    return df


def cargar(ticker: str) -> pd.DataFrame:
    return pd.read_csv(DATA_DIR / f"{ticker}.csv", index_col="Date", parse_dates=True)


def guardar(ticker: str, anios: int, actualizar: bool) -> None:
    ruta = DATA_DIR / f"{ticker}.csv"
    if actualizar and ruta.exists():
        viejo = cargar(ticker)
        nuevo = descargar(ticker, inicio=viejo.index[-1].strftime("%Y-%m-%d"))
        df = pd.concat([viejo, nuevo])
        df = df[~df.index.duplicated(keep="last")].sort_index()
    else:
        df = descargar(ticker, anios=anios)
    if df.empty:
        print(f"{ticker}: sin datos")
        return
    df.round(4).to_csv(ruta)
    print(f"{ticker}: {len(df)} velas, {df.index[0].date()} a {df.index[-1].date()}")


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("tickers", nargs="*", default=TICKERS)
    p.add_argument("--anios", type=int, default=10)
    p.add_argument("--actualizar", action="store_true", help="añade solo las velas nuevas")
    a = p.parse_args()
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    for t in a.tickers:
        try:
            guardar(t.upper(), a.anios, a.actualizar)
        except Exception as e:  # un ticker malo no debe parar el resto
            print(f"{t}: error {e}")


if __name__ == "__main__":
    main()
