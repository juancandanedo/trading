"""Panel de la cuenta paper de Alpaca: saldo, posiciones, ganancias y evolución del capital.

Lee la cuenta paper (solo lectura, no envía ni cancela órdenes) y el diario
resultados/paper/diario.csv, y genera una página HTML autónoma en
resultados/paper/panel.html que se abre con cualquier navegador.

Claves: igual que paper_trading.py, variables de entorno ALPACA_API_KEY y ALPACA_SECRET_KEY
(cuenta paper). En el entorno de Claude las añade el proxy: ejecutar con ALPACA_CLAVES_EN_PROXY=1.

Uso:
    python panel.py                      # genera resultados/paper/panel.html
    python panel.py --salida otro.html
    python panel.py --periodo 3M         # periodo del gráfico (1M, 3M, 6M, 1A, all)
"""
import argparse
import html
import json
import math
import os
import sys
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

import pandas as pd

BASE = Path(__file__).resolve().parent
DIARIO = BASE / "resultados" / "paper" / "diario.csv"
SALIDA = BASE / "resultados" / "paper" / "panel.html"
API = "https://paper-api.alpaca.markets/v2"  # solo la cuenta simulada
NY = ZoneInfo("America/New_York")

ESTADOS = {
    "new": "pendiente", "accepted": "pendiente", "pending_new": "pendiente",
    "held": "en espera de la compra", "partially_filled": "ejecutada en parte",
    "filled": "ejecutada", "canceled": "cancelada", "expired": "caducada",
    "rejected": "rechazada", "replaced": "sustituida", "done_for_day": "cerrada hoy",
}
TIPOS = {"market": "a mercado", "stop": "stop", "limit": "limitada", "stop_limit": "stop limitada",
         "trailing_stop": "stop dinámico"}
LADOS = {"buy": "Compra", "sell": "Venta"}


# ---------------------------------------------------------------- datos

def pedir(ruta: str):
    if not API.startswith("https://paper-api."):
        raise SystemExit("Seguridad: el panel solo lee la cuenta paper.")
    cabeceras = {"Accept": "application/json"}
    key, secret = os.environ.get("ALPACA_API_KEY"), os.environ.get("ALPACA_SECRET_KEY")
    if key and secret:
        cabeceras.update({"APCA-API-KEY-ID": key, "APCA-API-SECRET-KEY": secret})
    elif not os.environ.get("ALPACA_CLAVES_EN_PROXY"):
        raise SystemExit("Faltan ALPACA_API_KEY y ALPACA_SECRET_KEY en el entorno (claves de la cuenta paper).")
    req = urllib.request.Request(f"{API}/{ruta}", headers=cabeceras)
    with urllib.request.urlopen(req, timeout=30) as r:
        return json.load(r)


def leer_todo(periodo: str) -> dict:
    return {
        "cuenta": pedir("account"),
        "posiciones": pedir("positions"),
        "abiertas": aplanar(pedir("orders?status=open&limit=200&nested=true")),
        "cerradas": pedir("orders?status=closed&limit=100&direction=desc"),
        "historia": pedir(f"account/portfolio/history?period={periodo}&timeframe=1D"),
    }


def aplanar(ordenes: list[dict]) -> list[dict]:
    """Saca las patas de las órdenes OTO (el stop que espera a la compra) como órdenes propias."""
    plana = []
    for o in ordenes:
        plana.append(o)
        plana.extend(o.get("legs") or [])
    return plana


def leer_diario() -> pd.DataFrame:
    if not DIARIO.exists():
        return pd.DataFrame(columns=["enviado", "fecha_senal", "ticker", "estrategia", "accion",
                                     "qty", "stop", "order_id", "estado"])
    return pd.read_csv(DIARIO, dtype=str).fillna("")


def serie_capital(h: dict) -> list[tuple[datetime, float]]:
    """Capital al cierre de cada día, sin los días anteriores a la apertura de la cuenta (capital 0)."""
    puntos = [(datetime.fromtimestamp(t, NY), e) for t, e in zip(h.get("timestamp") or [], h.get("equity") or [])
              if e is not None]
    while puntos and puntos[0][1] == 0:
        puntos.pop(0)
    return puntos


# ---------------------------------------------------------------- formato

def usd(x: float, signo=False) -> str:
    s = f"{abs(x):,.2f}".replace(",", " ").replace(".", ",")
    pre = ("+" if x > 0 else "−" if x < 0 else "") if signo else ("−" if x < 0 else "")
    return f"{pre}{s} $"


def pct(x: float) -> str:
    return f"{'+' if x > 0 else '−' if x < 0 else ''}{abs(x):.2f}".replace(".", ",") + " %"


def tono(x: float) -> str:
    return "sube" if x > 0 else "baja" if x < 0 else "plano"


def hora(iso: str | None) -> str:
    if not iso:
        return ""
    return datetime.fromisoformat(iso.replace("Z", "+00:00")).astimezone(NY).strftime("%d/%m/%Y %H:%M")


def e(x) -> str:
    return html.escape(str(x))


def grafico(puntos: list[tuple[datetime, float]], base: float) -> str:
    if not puntos:
        return '<p class="vacio">Todavía no hay historial de capital.</p>'
    an, al, mi, md, ms, mb = 720, 240, 70, 28, 14, 30
    vals = [v for _, v in puntos] + [base]
    lo, hi = min(vals), max(vals)
    marg = max((hi - lo) * 0.15, base * 0.005)
    lo, hi = lo - marg, hi + marg
    n = len(puntos)
    x = lambda i: mi + (an - mi - md) * (i / (n - 1) if n > 1 else 0.5)
    y = lambda v: ms + (al - ms - mb) * (1 - (v - lo) / (hi - lo))

    partes = []
    paso_y = min((m * 10 ** k for k in range(0, 8) for m in (1, 2, 2.5, 5)), key=lambda s: abs((hi - lo) / s - 4))
    lo, hi = math.floor(lo / paso_y) * paso_y, math.ceil(hi / paso_y) * paso_y
    for k in range(round((hi - lo) / paso_y) + 1):  # rejilla y etiquetas del eje Y en valores redondos
        v = lo + paso_y * k
        partes.append(f'<line class="rej" x1="{mi}" x2="{an - md}" y1="{y(v):.1f}" y2="{y(v):.1f}"/>'
                      f'<text class="eje" x="{mi - 8}" y="{y(v) + 4:.1f}" text-anchor="end">'
                      f'{v:,.0f}'.replace(",", " ") + "</text>")
    paso = max(1, (n - 1) // 5)
    for i in range(0, n, paso):  # fechas del eje X
        partes.append(f'<text class="eje" x="{x(i):.1f}" y="{al - 8}" text-anchor="middle">'
                      f'{puntos[i][0]:%d/%m}</text>')
    partes.append(f'<line class="base" x1="{mi}" x2="{an - md}" y1="{y(base):.1f}" y2="{y(base):.1f}"/>'
                  f'<text class="eje" x="{mi + 6}" y="{y(base) - 6:.1f}">capital inicial</text>')
    linea = " ".join(f"{x(i):.1f},{y(v):.1f}" for i, (_, v) in enumerate(puntos))
    area = f"{x(0):.1f},{al - mb} {linea} {x(n - 1):.1f},{al - mb}"
    partes.append(f'<polygon class="area" points="{area}"/><polyline class="linea" points="{linea}"/>')
    ux, uy = x(n - 1), y(puntos[-1][1])
    partes.append(f'<circle class="punto" cx="{ux:.1f}" cy="{uy:.1f}" r="4"/>')
    return (f'<svg viewBox="0 0 {an} {al}" role="img" aria-label="Evolución del capital de la cuenta paper">'
            + "".join(partes) + "</svg>")


# ---------------------------------------------------------------- página

def construir(d: dict, diario: pd.DataFrame) -> str:
    c = d["cuenta"]
    capital, previo = float(c["equity"]), float(c["last_equity"])
    efectivo, invertido = float(c["cash"]), float(c["long_market_value"]) + float(c["short_market_value"])
    puntos = serie_capital(d["historia"])
    inicial = float(d["historia"].get("base_value") or (puntos[0][1] if puntos else capital)) or capital
    total = capital - inicial
    no_realizada = sum(float(p["unrealized_pl"]) for p in d["posiciones"])
    hoy = capital - previo

    estrategia = {}
    for f in diario[(diario["accion"] == "COMPRA") & (diario["estado"] == "enviada")].itertuples():
        estrategia[f.ticker] = f.estrategia
    stops = {o["symbol"]: float(o["stop_price"]) for o in d["abiertas"]
             if o["side"] == "sell" and o.get("stop_price")}

    # posiciones
    filas_pos = []
    for p in sorted(d["posiciones"], key=lambda p: -float(p["market_value"])):
        pg, pgp = float(p["unrealized_pl"]), float(p["unrealized_plpc"]) * 100
        stop = stops.get(p["symbol"])
        filas_pos.append(
            f'<tr><td class="tk">{e(p["symbol"])}</td><td class="n">{float(p["qty"]):g}</td>'
            f'<td class="n">{usd(float(p["avg_entry_price"]))}</td><td class="n">{usd(float(p["current_price"]))}</td>'
            f'<td class="n">{usd(float(p["market_value"]))}</td>'
            f'<td class="n {tono(pg)}">{usd(pg, True)}</td><td class="n {tono(pg)}">{pct(pgp)}</td>'
            f'<td class="n">{usd(stop) if stop else "—"}</td>'
            f'<td>{e(estrategia.get(p["symbol"], "—"))}</td></tr>')
    compras_pend = [o for o in d["abiertas"] if o["side"] == "buy"]
    if filas_pos:
        tabla_pos = ('<div class="desliza"><table><thead><tr><th>Activo</th><th class="n">Acciones</th>'
                     '<th class="n">Entrada</th><th class="n">Actual</th><th class="n">Valor</th>'
                     '<th class="n">P/G $</th><th class="n">P/G %</th><th class="n">Stop</th><th>Estrategia</th>'
                     '</tr></thead><tbody>' + "".join(filas_pos) + "</tbody></table></div>")
    else:
        extra = ""
        if compras_pend:
            extra = " Hay " + ", ".join(f'{e(o["qty"])} {e(o["symbol"])}' for o in compras_pend) + \
                    " en compra pendiente: aparecerá aquí cuando se ejecute en la apertura."
        tabla_pos = f'<p class="vacio">Sin posiciones abiertas.{extra}</p>'

    # órdenes abiertas
    filas_ab = []
    for o in sorted(d["abiertas"], key=lambda o: (o["symbol"], o["side"] != "buy")):
        estado = o["status"]
        filas_ab.append(
            f'<tr><td>{LADOS.get(o["side"], o["side"])}</td><td class="tk">{e(o["symbol"])}</td>'
            f'<td class="n">{e(o.get("qty") or "")}</td><td>{TIPOS.get(o["type"], o["type"])}</td>'
            f'<td class="n">{usd(float(o["stop_price"])) if o.get("stop_price") else "—"}</td>'
            f'<td><span class="chip {"espera" if estado == "held" else "pend"}">{ESTADOS.get(estado, estado)}</span></td>'
            f'<td class="n">{hora(o.get("submitted_at"))}</td></tr>')
    tabla_ab = ('<div class="desliza"><table><thead><tr><th>Lado</th><th>Activo</th><th class="n">Acciones</th>'
                '<th>Tipo</th><th class="n">Stop</th><th>Estado</th><th class="n">Enviada (NY)</th></tr></thead><tbody>'
                + "".join(filas_ab) + "</tbody></table></div>") if filas_ab else \
        '<p class="vacio">No hay órdenes abiertas.</p>'

    # ejecuciones
    ejec = [o for o in d["cerradas"] if float(o.get("filled_qty") or 0) > 0][:20]
    filas_ej = [
        f'<tr><td class="n">{hora(o["filled_at"])}</td><td>{LADOS.get(o["side"], o["side"])}</td>'
        f'<td class="tk">{e(o["symbol"])}</td><td class="n">{float(o["filled_qty"]):g}</td>'
        f'<td class="n">{usd(float(o["filled_avg_price"]))}</td>'
        f'<td class="n">{usd(float(o["filled_qty"]) * float(o["filled_avg_price"]))}</td></tr>' for o in ejec]
    tabla_ej = ('<div class="desliza"><table><thead><tr><th class="n">Fecha (NY)</th><th>Lado</th><th>Activo</th>'
                '<th class="n">Acciones</th><th class="n">Precio medio</th><th class="n">Importe</th></tr></thead><tbody>'
                + "".join(filas_ej) + "</tbody></table></div>") if filas_ej else \
        '<p class="vacio">Aún no se ha ejecutado ninguna orden.</p>'

    # diario de señales enviadas
    filas_di = [
        f'<tr><td class="n">{e(f.fecha_senal)}</td><td>{"Compra" if f.accion == "COMPRA" else "Venta"}</td>'
        f'<td class="tk">{e(f.ticker)}</td><td class="n">{e(f.qty)}</td>'
        f'<td class="n">{usd(float(f.stop)) if f.stop else "—"}</td><td>{e(f.estrategia)}</td>'
        f'<td><span class="chip {"ok" if f.estado == "enviada" else "mal"}">{e(f.estado)}</span></td></tr>'
        for f in diario.iloc[::-1].head(30).itertuples()]
    tabla_di = ('<div class="desliza"><table><thead><tr><th class="n">Señal del</th><th>Acción</th><th>Activo</th>'
                '<th class="n">Acciones</th><th class="n">Stop</th><th>Estrategia</th><th>Envío</th></tr></thead><tbody>'
                + "".join(filas_di) + "</tbody></table></div>") if filas_di else \
        '<p class="vacio">La rutina diaria aún no ha enviado órdenes.</p>'

    ahora = datetime.now(timezone.utc).astimezone(NY)
    peso = invertido / capital * 100 if capital else 0
    kpis = [
        ("Capital", usd(capital), f"inicial {usd(inicial)}", ""),
        ("Ganancia total", usd(total, True), pct(total / inicial * 100) + " desde el inicio", tono(total)),
        ("Hoy", usd(hoy, True), pct(hoy / previo * 100 if previo else 0) + " frente al cierre anterior", tono(hoy)),
        ("Efectivo", usd(efectivo), f"invertido {usd(invertido)} · {peso:.0f} %".replace(".", ","), ""),
        ("P/G abierta", usd(no_realizada, True), f"{len(d['posiciones'])} {'posición' if len(d['posiciones']) == 1 else 'posiciones'} en cartera",
         tono(no_realizada)),
        ("P/G cerrada", usd(total - no_realizada, True), "operaciones ya vendidas", tono(total - no_realizada)),
    ]
    tarjetas = "".join(f'<div class="kpi"><span class="et">{a}</span><span class="cifra {t}">{b}</span>'
                       f'<span class="sub">{s}</span></div>' for a, b, s, t in kpis)

    return PLANTILLA.format(
        cuenta=e(c["account_number"]), actualizado=f"{ahora:%d/%m/%Y %H:%M}", tarjetas=tarjetas,
        grafico=grafico(puntos, inicial), dias=len(puntos), tabla_pos=tabla_pos, tabla_ab=tabla_ab,
        tabla_ej=tabla_ej, tabla_di=tabla_di, n_pos=len(d["posiciones"]), n_ab=len(d["abiertas"]))


PLANTILLA = """<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1, viewport-fit=cover">
<title>Panel paper Alpaca</title>
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="stylesheet" href="https://fonts.googleapis.com/css2?family=Public+Sans:wght@400;600;700&family=IBM+Plex+Mono:wght@400;500&display=swap">
<style>
/* Libro de cuenta: cabecera con cifras clave, gráfico de capital y tablas de detalle debajo */
:root {{
  --fondo: #f3f5f4; --hoja: #ffffff; --tinta: #17201d; --suave: #5b6863; --linea: #d9e0dc;
  --acento: #1f5f74; --acento-velo: rgba(31,95,116,.12);
  --sube: #17794a; --baja: #b4362f; --espera: #8a5a00; --espera-fondo: #fbefd5;
  --texto: "Public Sans", "Segoe UI", system-ui, sans-serif;
  --cifras: "IBM Plex Mono", ui-monospace, "SFMono-Regular", Menlo, monospace;
}}
@media (prefers-color-scheme: dark) {{ :root:not([data-theme="light"]) {{
  --fondo: #101614; --hoja: #18201d; --tinta: #e6ece9; --suave: #95a39d; --linea: #2b3632;
  --acento: #6bb7cf; --acento-velo: rgba(107,183,207,.16);
  --sube: #4cc287; --baja: #ef7a70; --espera: #f0c063; --espera-fondo: #3a2f17; color-scheme: dark; }} }}
:root[data-theme="dark"] {{
  --fondo: #101614; --hoja: #18201d; --tinta: #e6ece9; --suave: #95a39d; --linea: #2b3632;
  --acento: #6bb7cf; --acento-velo: rgba(107,183,207,.16);
  --sube: #4cc287; --baja: #ef7a70; --espera: #f0c063; --espera-fondo: #3a2f17; color-scheme: dark; }}
* {{ box-sizing: border-box; }}
body {{ margin: 0; background: var(--fondo); color: var(--tinta); font: 15px/1.5 var(--texto); }}
main {{ max-width: 1080px; margin: 0 auto; padding: 28px 16px 48px; display: grid; gap: 28px; }}
header {{ display: flex; flex-wrap: wrap; align-items: baseline; justify-content: space-between; gap: 8px 16px; }}
h1 {{ margin: 0; font-size: 1.6rem; letter-spacing: -.01em; text-wrap: balance; }}
h2 {{ margin: 0 0 10px; font-size: .78rem; text-transform: uppercase; letter-spacing: .08em; color: var(--suave); }}
.meta {{ color: var(--suave); font-size: .85rem; display: flex; flex-wrap: wrap; gap: 6px 12px; align-items: center; }}
.sello {{ border: 1px solid var(--acento); color: var(--acento); border-radius: 4px; padding: 1px 7px;
  font-size: .72rem; font-weight: 700; letter-spacing: .08em; text-transform: uppercase; }}
.kpis {{ display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 1px;
  background: var(--linea); border: 1px solid var(--linea); border-radius: 8px; overflow: hidden; }}
@media (min-width: 640px) {{ .kpis {{ grid-template-columns: repeat(3, minmax(0, 1fr)); }} }}
@media (min-width: 1040px) {{ .kpis {{ grid-template-columns: repeat(6, minmax(0, 1fr)); }} }}
.kpi {{ background: var(--hoja); padding: 14px 16px; display: grid; gap: 2px; min-width: 0; }}
.et {{ font-size: .75rem; text-transform: uppercase; letter-spacing: .07em; color: var(--suave); }}
.cifra {{ font: 500 1.2rem/1.25 var(--cifras); font-variant-numeric: tabular-nums; }}
.sub {{ font-size: .8rem; color: var(--suave); font-variant-numeric: tabular-nums; }}
.sube {{ color: var(--sube); }} .baja {{ color: var(--baja); }}
section {{ min-width: 0; }}
.caja {{ background: var(--hoja); border: 1px solid var(--linea); border-radius: 8px; padding: 12px; }}
svg {{ width: 100%; height: auto; display: block; }}
.rej {{ stroke: var(--linea); stroke-width: 1; }}
.base {{ stroke: var(--suave); stroke-width: 1; stroke-dasharray: 4 4; }}
.eje {{ fill: var(--suave); font: 12px var(--cifras); }}
.linea {{ fill: none; stroke: var(--acento); stroke-width: 2.2; stroke-linejoin: round; }}
.area {{ fill: var(--acento-velo); stroke: none; }}
.punto {{ fill: var(--acento); stroke: var(--hoja); stroke-width: 2; }}
.desliza {{ overflow-x: auto; background: var(--hoja); border: 1px solid var(--linea); border-radius: 8px; }}
table {{ width: 100%; border-collapse: collapse; font-size: .9rem; }}
th, td {{ padding: 9px 12px; text-align: left; white-space: nowrap; border-bottom: 1px solid var(--linea); }}
th {{ font-size: .72rem; text-transform: uppercase; letter-spacing: .06em; color: var(--suave); font-weight: 600; }}
tbody tr:last-child td {{ border-bottom: 0; }}
td.n, th.n {{ text-align: right; font-family: var(--cifras); font-variant-numeric: tabular-nums; }}
th.n {{ font-family: var(--texto); }}
.tk {{ font-weight: 700; }}
.chip {{ display: inline-block; border-radius: 99px; padding: 1px 9px; font-size: .78rem; font-weight: 600; }}
.pend {{ background: var(--acento-velo); color: var(--acento); }}
.espera {{ background: var(--espera-fondo); color: var(--espera); }}
.ok {{ background: var(--acento-velo); color: var(--sube); }}
.mal {{ background: var(--espera-fondo); color: var(--baja); white-space: normal; }}
.vacio {{ margin: 0; padding: 14px 16px; background: var(--hoja); border: 1px dashed var(--linea);
  border-radius: 8px; color: var(--suave); }}
footer {{ color: var(--suave); font-size: .8rem; max-width: 70ch; }}
footer code {{ font-family: var(--cifras); font-size: .78rem; }}
</style>
<main>
  <header>
    <h1>Cuenta paper de Alpaca</h1>
    <div class="meta"><span class="sello">Dinero simulado</span><span>Cuenta {cuenta}</span>
      <span>Actualizado {actualizado} (hora de Nueva York)</span></div>
  </header>
  <div class="kpis">{tarjetas}</div>
  <section><h2>Evolución del capital · {dias} días</h2><div class="caja">{grafico}</div></section>
  <section><h2>Posiciones abiertas · {n_pos}</h2>{tabla_pos}</section>
  <section><h2>Órdenes abiertas · {n_ab}</h2>{tabla_ab}</section>
  <section><h2>Últimas ejecuciones</h2>{tabla_ej}</section>
  <section><h2>Órdenes enviadas por la rutina</h2>{tabla_di}</section>
  <footer>Datos de la API de la cuenta paper de Alpaca (cuenta, posiciones, órdenes e historial diario de capital)
    y de <code>resultados/paper/diario.csv</code>. La ganancia cerrada es la total menos la abierta.
    Se regenera con <code>python panel.py</code>. Es una cuenta de práctica: nada de esto es dinero real.</footer>
</main>
"""


def main() -> None:
    a = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    a.add_argument("--salida", type=Path, default=SALIDA, help="ruta del HTML generado")
    a.add_argument("--periodo", default="1A", help="periodo del gráfico: 1M, 3M, 6M, 1A o all")
    args = a.parse_args()

    pagina = construir(leer_todo(args.periodo), leer_diario())
    args.salida.parent.mkdir(parents=True, exist_ok=True)
    args.salida.write_text(pagina, encoding="utf-8")
    print(f"Panel generado en {args.salida}")


if __name__ == "__main__":
    sys.exit(main())
