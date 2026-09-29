"""Backtest de una estrategia swing: cruce de medias + filtro RSI (solo largos).

Reglas (por defecto):
    Entrada: la media rápida (SMA 20) cruza por encima de la lenta (SMA 50)
             y el RSI(14) está por debajo de 70 (no comprar sobrecomprado).
    Salida:  la media rápida cruza por debajo de la lenta,
             o el RSI(14) supera 80 (recoger beneficios),
             o el precio cae un 8 % desde la entrada (stop loss).
    Ejecución: la señal se calcula con el cierre del día y se opera en la
               apertura del día siguiente (sin mirar al futuro).
    Costes: 0,05 % por operación (comisión + deslizamiento).

Uso:
    python backtest.py                          # los 14 activos, parámetros por defecto
    python backtest.py SPY AAPL --rapida 10 --lenta 30
    python backtest.py --grafico SPY            # guarda resultados/SPY.png
    python backtest.py --desde 2023-01-01       # solo un tramo de fechas
"""
import argparse
from pathlib import Path

import numpy as np
import pandas as pd

from descargar_datos import TICKERS, cargar

RES_DIR = Path(__file__).resolve().parent / "resultados"
DIAS_ANIO = 252


def rsi(close: pd.Series, n: int = 14) -> pd.Series:
    """RSI de Wilder."""
    delta = close.diff()
    sube = delta.clip(lower=0).ewm(alpha=1 / n, adjust=False).mean()
    baja = (-delta.clip(upper=0)).ewm(alpha=1 / n, adjust=False).mean()
    return 100 - 100 / (1 + sube / baja)


def backtest(df: pd.DataFrame, rapida=20, lenta=50, rsi_n=14, rsi_entrada=70,
             rsi_salida=80, stop=0.08, coste=0.0005) -> tuple[pd.Series, pd.DataFrame]:
    """Devuelve (curva de capital diaria partiendo de 1, tabla de operaciones)."""
    c = df["Close"]
    sma_r, sma_l, r = c.rolling(rapida).mean(), c.rolling(lenta).mean(), rsi(c, rsi_n)
    arriba = sma_r > sma_l
    cruce_alza = arriba & ~arriba.shift(1, fill_value=False)
    cruce_baja = ~arriba & arriba.shift(1, fill_value=False)

    abre, cierra = df["Open"].to_numpy(), c.to_numpy()
    capital = np.ones(len(df))
    operaciones = []
    en_pos, precio_ent, fecha_ent, orden = False, 0.0, None, None  # orden: "comprar"/"vender" para la apertura siguiente
    eq = 1.0
    for i in range(len(df)):
        # 1) ejecutar la orden pendiente en la apertura de hoy
        if orden == "comprar":
            en_pos, precio_ent, fecha_ent = True, abre[i], df.index[i]
            eq *= 1 - coste
            ref = abre[i]
        elif orden == "vender":
            eq *= abre[i] / ref * (1 - coste)
            operaciones.append((fecha_ent, df.index[i], precio_ent, abre[i], abre[i] / precio_ent - 1, motivo))
            en_pos, ref = False, None
        orden = None
        # 2) marcar a mercado con el cierre
        if en_pos:
            eq *= cierra[i] / ref
            ref = cierra[i]
        capital[i] = eq
        # 3) generar la orden para mañana con los datos de hoy
        if i == len(df) - 1:
            break
        if not en_pos and cruce_alza.iloc[i] and r.iloc[i] < rsi_entrada:
            orden = "comprar"
        elif en_pos:
            if cruce_baja.iloc[i]:
                orden, motivo = "vender", "cruce"
            elif r.iloc[i] > rsi_salida:
                orden, motivo = "vender", "rsi"
            elif cierra[i] <= precio_ent * (1 - stop):
                orden, motivo = "vender", "stop"
    if en_pos:  # cerrar al final para contabilizar la operación abierta
        operaciones.append((fecha_ent, df.index[-1], precio_ent, cierra[-1], cierra[-1] / precio_ent - 1, "abierta"))
    ops = pd.DataFrame(operaciones, columns=["entrada", "salida", "precio_ent", "precio_sal", "retorno", "motivo"])
    return pd.Series(capital, index=df.index), ops


def metricas(capital: pd.Series, ops: pd.DataFrame | None = None) -> dict:
    ret = capital.pct_change().dropna()
    anios = len(capital) / DIAS_ANIO
    total = capital.iloc[-1] / capital.iloc[0] - 1
    dd = (capital / capital.cummax() - 1).min()
    m = {
        "retorno_%": 100 * total,
        "cagr_%": 100 * ((1 + total) ** (1 / anios) - 1),
        "max_dd_%": 100 * dd,
        "sharpe": np.sqrt(DIAS_ANIO) * ret.mean() / ret.std() if ret.std() > 0 else 0.0,
    }
    if ops is not None:
        m["operaciones"] = len(ops)
        m["win_rate_%"] = 100 * (ops["retorno"] > 0).mean() if len(ops) else np.nan
        m["exposicion_%"] = 100 * (capital.diff() != 0).mean()
    return m


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("tickers", nargs="*", default=TICKERS)
    p.add_argument("--rapida", type=int, default=20)
    p.add_argument("--lenta", type=int, default=50)
    p.add_argument("--rsi-entrada", type=float, default=70)
    p.add_argument("--rsi-salida", type=float, default=80)
    p.add_argument("--stop", type=float, default=0.08, help="stop loss como fracción (0.08 = 8 %%)")
    p.add_argument("--coste", type=float, default=0.0005)
    p.add_argument("--desde", help="fecha inicial AAAA-MM-DD")
    p.add_argument("--hasta", help="fecha final AAAA-MM-DD")
    p.add_argument("--grafico", action="store_true", help="guarda un PNG por activo en resultados/")
    a = p.parse_args()
    RES_DIR.mkdir(exist_ok=True)

    filas = []
    for t in (x.upper() for x in a.tickers):
        df = cargar(t)
        # los indicadores se calculan con todo el histórico y luego se recorta,
        # así las medias ya están "calientes" al inicio del tramo
        cap, ops = backtest(df, a.rapida, a.lenta, 14, a.rsi_entrada, a.rsi_salida, a.stop, a.coste)
        tramo = slice(a.desde, a.hasta)
        cap = cap.loc[tramo] / cap.loc[tramo].iloc[0]
        ops = ops[(ops["entrada"] >= cap.index[0]) & (ops["entrada"] <= cap.index[-1])]
        bh = df["Close"].loc[tramo] / df["Close"].loc[tramo].iloc[0]
        me, mb = metricas(cap, ops), metricas(bh)
        filas.append({"ticker": t, **me, **{f"bh_{k}": v for k, v in mb.items()}})
        ops.to_csv(RES_DIR / f"operaciones_{t}.csv", index=False, float_format="%.4f")
        if a.grafico:
            import matplotlib
            matplotlib.use("Agg")
            import matplotlib.pyplot as plt
            fig, ax = plt.subplots(figsize=(10, 5))
            ax.plot(cap.index, cap, label="Estrategia")
            ax.plot(bh.index, bh, label="Comprar y mantener", alpha=0.7)
            ax.set_yscale("log")
            ax.set_title(f"{t}: SMA {a.rapida}/{a.lenta} + RSI vs comprar y mantener")
            ax.legend()
            fig.tight_layout()
            fig.savefig(RES_DIR / f"{t}.png", dpi=110)
            plt.close(fig)

    tabla = pd.DataFrame(filas).set_index("ticker")
    tabla.to_csv(RES_DIR / "resumen.csv", float_format="%.2f")
    cols = ["retorno_%", "bh_retorno_%", "cagr_%", "bh_cagr_%", "max_dd_%", "bh_max_dd_%",
            "sharpe", "bh_sharpe", "win_rate_%", "operaciones", "exposicion_%"]
    pd.set_option("display.width", 200)
    print(tabla[cols].round(2).to_string())
    print("\nMedia:", tabla[cols].mean().round(2).to_dict())


if __name__ == "__main__":
    main()
