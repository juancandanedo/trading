"""Backtest de la estrategia de retrocesos (retroceso_ma200) tal como la usa la rutina diaria.

Reglas, copiadas de escaner.py y paper_trading.py:
    Entrada: cierre por encima de la SMA 200 y RSI(2) < 10  -> compra en la apertura siguiente.
    Salida:  el cierre vuelve por encima de la SMA 5, viniendo de debajo, con el RSI(2) de ayer
             < 25 -> venta en la apertura siguiente (es la señal VENTA del escáner).
    Stop:    orden stop al 8 % bajo el cierre de la señal, activa desde la apertura de entrada.
             Si el precio abre por debajo del stop, se vende a la apertura (hueco).
    Costes:  0,05 % por operación, igual que backtest.py.

Variante "salida_simple": vende con el primer cierre sobre la SMA 5, sin exigir RSI(2) < 25 ayer
(la versión de libro de la estrategia), para ver si la regla del escáner deja posiciones colgadas.

Dos vistas:
    1) Por activo, todo el capital dentro cuando hay posición (comparable con resultados/resumen.csv).
    2) Cartera como la cuenta paper: los 14 activos, ~10 % del capital por posición, máx. 8 a la vez,
       comparada con comprar y mantener los 14 a partes iguales y con SPY.

Uso:
    python backtest_retrocesos.py                 # todo el histórico
    python backtest_retrocesos.py --desde 2021-10-01

Salida en resultados/retrocesos/.
"""
import argparse
from pathlib import Path

import numpy as np
import pandas as pd

from backtest import backtest as backtest_cruce, metricas, rsi
from descargar_datos import TICKERS, cargar

OUT = Path(__file__).resolve().parent / "resultados" / "retrocesos"


def senales(df: pd.DataFrame, salida_simple=False) -> pd.DataFrame:
    c = df["Close"]
    sma5, sma200, r2 = c.rolling(5).mean(), c.rolling(200).mean(), rsi(c, 2)
    compra = (c > sma200) & (r2 < 10)
    sobre5 = c > sma5
    if salida_simple:
        venta = sobre5
    else:
        venta = sobre5 & ~sobre5.shift(1, fill_value=True) & (r2.shift(1) < 25)
    return pd.DataFrame({"compra": compra, "venta": venta})


def backtest_ret(df: pd.DataFrame, stop=0.08, coste=0.0005, salida_simple=False):
    """Igual que backtest.backtest: curva de capital (parte de 1) y tabla de operaciones."""
    s = senales(df, salida_simple)
    abre, alto, bajo, cierra = (df[k].to_numpy() for k in ("Open", "High", "Low", "Close"))
    compra, venta = s["compra"].to_numpy(), s["venta"].to_numpy()
    capital, ops = np.ones(len(df)), []
    eq, en_pos, orden, ref = 1.0, False, None, None
    for i in range(len(df)):
        if orden == "comprar":
            en_pos, p_ent, f_ent, ref = True, abre[i], df.index[i], abre[i]
            nivel_stop = cierre_senal * (1 - stop)
            eq *= 1 - coste
        elif orden == "vender":
            eq *= abre[i] / ref * (1 - coste)
            ops.append((f_ent, df.index[i], p_ent, abre[i], abre[i] / p_ent - 1, motivo))
            en_pos = False
        orden = None
        if en_pos and bajo[i] <= nivel_stop:  # stop dentro del día
            precio = min(abre[i], nivel_stop)
            eq *= precio / ref * (1 - coste)
            ops.append((f_ent, df.index[i], p_ent, precio, precio / p_ent - 1, "stop"))
            en_pos = False
        elif en_pos:
            eq *= cierra[i] / ref
            ref = cierra[i]
        capital[i] = eq
        if i == len(df) - 1:
            break
        if not en_pos and compra[i]:
            orden, cierre_senal = "comprar", cierra[i]
        elif en_pos and venta[i]:
            orden, motivo = "vender", "sma5"
    if en_pos:
        ops.append((f_ent, df.index[-1], p_ent, cierra[-1], cierra[-1] / p_ent - 1, "abierta"))
    ops = pd.DataFrame(ops, columns=["entrada", "salida", "precio_ent", "precio_sal", "retorno", "motivo"])
    return pd.Series(capital, index=df.index), ops


def recortar(cap, ops, bh, desde):
    cap = cap.loc[desde:] / cap.loc[desde:].iloc[0]
    bh = bh.loc[desde:] / bh.loc[desde:].iloc[0]
    ops = ops[ops["entrada"] >= cap.index[0]]
    return cap, ops, bh


def cartera(datos: dict, desde, peso=0.10, max_pos=8, stop=0.08, coste=0.0005):
    """Simula la cuenta paper: posiciones de ~peso del capital, máx. max_pos, señales en orden de TICKERS."""
    fechas = sorted(set().union(*[d.loc[desde:].index for d in datos.values()]))
    sen = {t: senales(d) for t, d in datos.items()}
    efectivo, pos, pend, curva = 1.0, {}, {}, []  # pos: t -> [acciones, stop]; pend: t -> "comprar"/"vender"
    for f in fechas:
        # aperturas: primero ventas, luego compras
        for t, o in list(pend.items()):
            d = datos[t]
            if f not in d.index:
                continue
            ab = d.at[f, "Open"]
            if o[0] == "vender" and t in pos:
                efectivo += pos.pop(t)[0] * ab * (1 - coste)
                del pend[t]
        for t, o in list(pend.items()):
            d = datos[t]
            if f not in d.index or o[0] != "comprar":
                continue
            del pend[t]
            ab = d.at[f, "Open"]
            if len(pos) >= max_pos:
                continue
            total = efectivo + sum(n * datos[x].loc[:f, "Close"].iloc[-1] for x, (n, _) in pos.items())
            importe = min(total * peso, efectivo)
            if importe <= 0:
                continue
            pos[t] = [importe * (1 - coste) / ab, o[1] * (1 - stop)]
            efectivo -= importe
        # stops dentro del día
        for t in list(pos):
            d = datos[t]
            if f in d.index and d.at[f, "Low"] <= pos[t][1]:
                n, st = pos.pop(t)
                efectivo += n * min(d.at[f, "Open"], st) * (1 - coste)
                pend.pop(t, None)
        valor = efectivo + sum(n * datos[t].loc[:f, "Close"].iloc[-1] for t, (n, _) in pos.items())
        curva.append(valor)
        # señales con el cierre de hoy
        for t in TICKERS:
            d = datos[t]
            if f not in d.index:
                continue
            if t in pos and sen[t].at[f, "venta"]:
                pend[t] = ("vender",)
            elif t not in pos and t not in pend and sen[t].at[f, "compra"]:
                pend[t] = ("comprar", d.at[f, "Close"])
    return pd.Series(curva, index=pd.DatetimeIndex(fechas))


def main():
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--desde", help="fecha inicial AAAA-MM-DD (por defecto, cuando ya hay SMA 200)")
    a = p.parse_args()
    OUT.mkdir(parents=True, exist_ok=True)
    datos = {t: cargar(t) for t in TICKERS}
    desde = pd.Timestamp(a.desde) if a.desde else max(d.index[200] for d in datos.values())

    filas, todas = [], []
    for t, df in datos.items():
        bh = df["Close"]
        cap, ops, bh_ = recortar(*backtest_ret(df), bh, desde)
        cap2, ops2, _ = recortar(*backtest_ret(df, salida_simple=True), bh, desde)
        cap3, ops3, _ = recortar(*backtest_cruce(df), bh, desde)
        m, m2, m3, mb = metricas(cap, ops), metricas(cap2, ops2), metricas(cap3, ops3), metricas(bh_)
        dias = (pd.to_datetime(ops["salida"]) - pd.to_datetime(ops["entrada"])).dt.days
        filas.append({"ticker": t,
                      "ret_%": m["retorno_%"], "cagr_%": m["cagr_%"], "max_dd_%": m["max_dd_%"],
                      "sharpe": m["sharpe"], "ops": m["operaciones"], "acierto_%": m["win_rate_%"],
                      "media_op_%": 100 * ops["retorno"].mean(), "dias_medios": dias.mean(),
                      "stops": (ops["motivo"] == "stop").sum(), "exposicion_%": m["exposicion_%"],
                      "simple_cagr_%": m2["cagr_%"], "simple_sharpe": m2["sharpe"],
                      "cruce_cagr_%": m3["cagr_%"], "cruce_sharpe": m3["sharpe"],
                      "bh_cagr_%": mb["cagr_%"], "bh_max_dd_%": mb["max_dd_%"], "bh_sharpe": mb["sharpe"]})
        todas.append(ops.assign(ticker=t))
    tabla = pd.DataFrame(filas).set_index("ticker")
    tabla.to_csv(OUT / "resumen_por_activo.csv", float_format="%.2f")
    ops_all = pd.concat(todas)
    ops_all.to_csv(OUT / "operaciones.csv", index=False, float_format="%.4f")

    pd.set_option("display.width", 250)
    print(f"Desde {desde.date()}\n")
    print(tabla.round(2).to_string())
    print("\nMedia:\n" + tabla.mean().round(2).to_string())

    # cartera tipo cuenta paper
    cart = cartera(datos, desde)
    bh_eq = pd.concat([d["Close"].loc[desde:] / d["Close"].loc[desde:].iloc[0] for d in datos.values()], axis=1).mean(axis=1)
    spy = datos["SPY"]["Close"].loc[desde:] / datos["SPY"]["Close"].loc[desde:].iloc[0]
    mc = {"Retrocesos (cartera paper)": metricas(cart),
          "Comprar y mantener 14 activos": metricas(bh_eq),
          "Comprar y mantener SPY": metricas(spy)}
    res = pd.DataFrame(mc).T
    res.to_csv(OUT / "cartera.csv", float_format="%.2f")
    print("\nCartera:\n" + res.round(2).to_string())
    pd.DataFrame({"retrocesos": cart, "bh_14": bh_eq, "spy": spy}).to_csv(OUT / "curvas_cartera.csv", float_format="%.4f")

    # por años, para ver estabilidad
    anual = pd.DataFrame({k: s.resample("YE").last().pct_change().fillna(s.resample("YE").last() - 1) * 100
                          for k, s in {"retrocesos": cart, "bh_14": bh_eq, "spy": spy}.items()})
    anual.index = anual.index.year
    anual.to_csv(OUT / "por_anio.csv", float_format="%.1f")
    print("\nPor año (%):\n" + anual.round(1).to_string())

    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    fig, ax = plt.subplots(figsize=(10, 5))
    ax.plot(cart.index, cart, label="Retrocesos (como la cuenta paper)")
    ax.plot(bh_eq.index, bh_eq, label="Comprar y mantener los 14", alpha=0.8)
    ax.plot(spy.index, spy, label="Comprar y mantener SPY", alpha=0.8)
    ax.set_yscale("log")
    ax.set_title("Estrategia de retrocesos vs comprar y mantener (capital inicial = 1)")
    ax.legend()
    fig.tight_layout()
    fig.savefig(OUT / "cartera.png", dpi=110)
    plt.close(fig)


if __name__ == "__main__":
    main()
