"""Escáner diario de señales swing sobre la lista de activos.

Evalúa dos estrategias con el cierre del último día disponible:

1. Cruce de medias (la del backtest.py):
       COMPRA  la SMA 20 cruza por encima de la SMA 50 y el RSI(14) < 70
       VENTA   la SMA 20 cruza por debajo de la SMA 50, o RSI(14) > 80
2. Retroceso en tendencia alcista:
       COMPRA  cierre por encima de la SMA 200 y RSI(2) < 10 (caída fuerte de corto plazo)
       VENTA   cierre por encima de la SMA 5 (el rebote ya se produjo)
       VIGILAR sobre la SMA 200 y RSI(2) < 25 (cerca de dar señal)

Las órdenes se pensarían para la apertura de la siguiente sesión, igual que en el backtest.
Esto no es una recomendación de inversión: son señales mecánicas para revisar a mano.

Uso:
    python escaner.py                 # actualiza datos, escanea los 14 activos y guarda el informe
    python escaner.py --sin-actualizar
    python escaner.py AAPL NVDA       # solo algunos activos
    python escaner.py --fecha 2026-03-10   # escanea como si fuera ese día (para revisar el pasado)

Salida:
    resultados/escaner/informe_<FECHA>.md   informe legible del día
    resultados/escaner/senales.csv          histórico de señales (una fila por señal)
"""
import argparse
from pathlib import Path

import pandas as pd

from backtest import rsi
from descargar_datos import TICKERS, cargar, guardar

OUT_DIR = Path(__file__).resolve().parent / "resultados" / "escaner"


def indicadores(df: pd.DataFrame) -> pd.DataFrame:
    c = df["Close"]
    out = pd.DataFrame({"close": c})
    for n in (5, 20, 50, 200):
        out[f"sma{n}"] = c.rolling(n).mean()
    out["rsi14"] = rsi(c, 14)
    out["rsi2"] = rsi(c, 2)
    return out


def evaluar(ticker: str, df: pd.DataFrame) -> tuple[dict, list[dict]]:
    """Devuelve (fila con el estado del activo, lista de señales del día)."""
    ind = indicadores(df)
    hoy, ayer = ind.iloc[-1], ind.iloc[-2]
    fecha = ind.index[-1].date()
    arriba_hoy, arriba_ayer = hoy.sma20 > hoy.sma50, ayer.sma20 > ayer.sma50
    sobre_200 = hoy.close > hoy.sma200

    senales = []

    def senal(estrategia, tipo, motivo):
        senales.append({"fecha": fecha, "ticker": ticker, "estrategia": estrategia,
                        "senal": tipo, "cierre": round(hoy.close, 2), "motivo": motivo})

    # 1) cruce de medias
    if arriba_hoy and not arriba_ayer:
        if hoy.rsi14 < 70:
            senal("cruce_medias", "COMPRA", f"SMA20 cruza sobre SMA50, RSI14 {hoy.rsi14:.0f}")
        else:
            senal("cruce_medias", "VIGILAR", f"cruce alcista pero RSI14 {hoy.rsi14:.0f} >= 70")
    elif arriba_ayer and not arriba_hoy:
        senal("cruce_medias", "VENTA", "SMA20 cruza bajo SMA50")
    elif arriba_hoy and hoy.rsi14 > 80:
        senal("cruce_medias", "VENTA", f"RSI14 {hoy.rsi14:.0f} > 80, recoger beneficios")

    # 2) retroceso sobre la SMA 200
    if sobre_200 and hoy.rsi2 < 10:
        senal("retroceso_ma200", "COMPRA", f"sobre SMA200, RSI2 {hoy.rsi2:.0f} < 10")
    elif sobre_200 and hoy.rsi2 < 25:
        senal("retroceso_ma200", "VIGILAR", f"sobre SMA200, RSI2 {hoy.rsi2:.0f} (compra si < 10)")
    if hoy.close > hoy.sma5 and ayer.close <= ayer.sma5 and ayer.rsi2 < 25:
        senal("retroceso_ma200", "VENTA", "cierre vuelve sobre SMA5 tras retroceso (salida si estás dentro)")

    estado = {
        "ticker": ticker,
        "fecha": fecha,
        "cierre": hoy.close,
        "var_dia_%": 100 * (hoy.close / ayer.close - 1),
        "tendencia": "alcista" if sobre_200 else "bajista",
        "sma20>50": "sí" if arriba_hoy else "no",
        "dist_sma200_%": 100 * (hoy.close / hoy.sma200 - 1),
        "rsi14": hoy.rsi14,
        "rsi2": hoy.rsi2,
    }
    return estado, senales


def informe(tabla: pd.DataFrame, senales: pd.DataFrame, fecha) -> str:
    lineas = [f"# Escáner swing, {fecha}", ""]
    orden = {"COMPRA": 0, "VENTA": 1, "VIGILAR": 2}
    if senales.empty:
        lineas += ["Sin señales hoy.", ""]
    else:
        for tipo in orden:
            sub = senales[senales["senal"] == tipo]
            if sub.empty:
                continue
            lineas.append(f"## {tipo} ({len(sub)})")
            for s in sub.itertuples():
                lineas.append(f"- **{s.ticker}** ({s.estrategia}) a {s.cierre}: {s.motivo}")
            lineas.append("")
    lineas += ["## Estado de todos los activos", "", "```",
               tabla.round(2).to_string(), "```", "",
               "_Señales mecánicas calculadas con el cierre; se operarían en la apertura siguiente. "
               "No es una recomendación de inversión._"]
    return "\n".join(lineas)


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("tickers", nargs="*", default=TICKERS)
    p.add_argument("--sin-actualizar", action="store_true", help="no descarga velas nuevas")
    p.add_argument("--fecha", help="escanear como si hoy fuera AAAA-MM-DD")
    a = p.parse_args()
    tickers = [t.upper() for t in a.tickers]

    if not a.sin_actualizar and not a.fecha:
        for t in tickers:
            try:
                guardar(t, anios=10, actualizar=True)
            except Exception as e:  # sin red se escanea con lo que haya
                print(f"{t}: no se pudo actualizar ({e})")

    estados, todas = [], []
    for t in tickers:
        df = cargar(t)
        if a.fecha:
            df = df.loc[:a.fecha]
        if len(df) < 201:
            print(f"{t}: histórico insuficiente ({len(df)} velas)")
            continue
        e, s = evaluar(t, df)
        estados.append(e)
        todas += s

    tabla = pd.DataFrame(estados).set_index("ticker")
    fecha = tabla["fecha"].max()
    tabla = tabla.drop(columns="fecha")
    cols = ["fecha", "ticker", "estrategia", "senal", "cierre", "motivo"]
    senales = pd.DataFrame(todas, columns=cols)

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    texto = informe(tabla, senales, fecha)
    (OUT_DIR / f"informe_{fecha}.md").write_text(texto, encoding="utf-8")

    hist = OUT_DIR / "senales.csv"
    if not senales.empty:
        if hist.exists():
            previo = pd.read_csv(hist, dtype={"fecha": str})
            senales_str = senales.assign(fecha=senales["fecha"].astype(str))
            combinado = pd.concat([previo, senales_str])
            combinado = combinado.drop_duplicates(subset=["fecha", "ticker", "estrategia", "senal"], keep="last")
        else:
            combinado = senales
        combinado.sort_values(["fecha", "ticker"]).to_csv(hist, index=False)

    pd.set_option("display.width", 200)
    print(texto)
    print(f"\nInforme guardado en {OUT_DIR / f'informe_{fecha}.md'}")


if __name__ == "__main__":
    main()
