"""Gráficos de velas interactivos al estilo TradingView para los activos de data/.

Genera resultados/graficos.html, una página que se abre en el navegador (necesita internet para
cargar la librería Lightweight Charts, la de código abierto de TradingView):
    - velas diarias o semanales, con zoom (rueda) y desplazamiento (arrastrar)
    - medias SMA 20 / 50 / 200, volumen y RSI(14) en panel aparte
    - señales del escáner (resultados/escaner/senales.csv), órdenes paper (resultados/paper/diario.csv)
      y, opcional, las operaciones del backtest de retrocesos (resultados/retrocesos/operaciones.csv)

Uso:
    python graficos.py                  # todos los activos de data/
    python graficos.py NVDA AAPL        # solo esos
    python graficos.py --salida otro.html
Para tener la última vela, antes: python descargar_datos.py --actualizar
"""
import argparse
import json
import sys
from pathlib import Path

import pandas as pd

BASE = Path(__file__).resolve().parent
DATOS = BASE / "data"
SENALES = BASE / "resultados" / "escaner" / "senales.csv"
DIARIO = BASE / "resultados" / "paper" / "diario.csv"
OPERACIONES = BASE / "resultados" / "retrocesos" / "operaciones.csv"
SALIDA = BASE / "resultados" / "graficos.html"
LIBRERIA = "https://unpkg.com/lightweight-charts@4.1.3/dist/lightweight-charts.standalone.production.js"


def leer_csv(ruta: Path) -> pd.DataFrame:
    return pd.read_csv(ruta, dtype=str).fillna("") if ruta.exists() else pd.DataFrame()


def recopilar(tickers: list[str]) -> dict:
    velas = {}
    for t in tickers:
        df = pd.read_csv(DATOS / f"{t}.csv")
        velas[t] = [[r.Date, round(r.Open, 4), round(r.High, 4), round(r.Low, 4), round(r.Close, 4), int(r.Volume)]
                    for r in df.itertuples()]

    marcas = {t: [] for t in tickers}
    s = leer_csv(SENALES)
    for r in s[s.get("senal", pd.Series(dtype=str)).isin(["COMPRA", "VENTA"])].itertuples() if not s.empty else []:
        if r.ticker in marcas:
            marcas[r.ticker].append({"t": r.fecha, "tipo": "senal", "lado": r.senal,
                                     "texto": f"{r.senal.capitalize()} · {r.estrategia}", "info": r.motivo})
    d = leer_csv(DIARIO)
    for r in d.itertuples() if not d.empty else []:
        if r.ticker in marcas:
            marcas[r.ticker].append({"t": r.fecha_senal, "tipo": "paper", "lado": r.accion,
                                     "texto": f"Paper {r.accion.lower()} {r.qty}", "info": r.estado})
    o = leer_csv(OPERACIONES)
    for r in o.itertuples() if not o.empty else []:
        if r.ticker in marcas:
            ret = float(r.retorno) * 100
            marcas[r.ticker].append({"t": r.entrada, "tipo": "backtest", "lado": "COMPRA", "texto": "BT", "info": ""})
            marcas[r.ticker].append({"t": r.salida, "tipo": "backtest", "lado": "VENTA",
                                     "texto": f"{ret:+.1f}%", "info": r.motivo})
    return {"velas": velas, "marcas": marcas}


def main() -> None:
    a = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    a.add_argument("tickers", nargs="*", help="activos (por defecto, todos los de data/)")
    a.add_argument("--salida", type=Path, default=SALIDA)
    args = a.parse_args()

    tickers = [t.upper() for t in args.tickers] or sorted(p.stem for p in DATOS.glob("*.csv"))
    faltan = [t for t in tickers if not (DATOS / f"{t}.csv").exists()]
    if faltan:
        raise SystemExit(f"No hay datos de {', '.join(faltan)}: ejecuta python descargar_datos.py {' '.join(faltan)}")
    datos = json.dumps(recopilar(tickers), separators=(",", ":"), ensure_ascii=False).replace("</", "<\\/")
    args.salida.parent.mkdir(parents=True, exist_ok=True)
    args.salida.write_text(PLANTILLA.replace("__LIBRERIA__", LIBRERIA).replace("__DATOS__", datos), encoding="utf-8")
    print(f"Gráficos de {len(tickers)} activos en {args.salida}")


PLANTILLA = r"""<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1, viewport-fit=cover">
<title>Gráficos swing</title>
<link rel="stylesheet" href="https://fonts.googleapis.com/css2?family=Public+Sans:wght@400;600;700&family=IBM+Plex+Mono:wght@400;500&display=swap">
<style>
/* Mesa de gráficos: barra de activos arriba, controles, gráfico de velas y RSI debajo */
:root {
  --fondo: #f3f5f4; --hoja: #ffffff; --tinta: #17201d; --suave: #5b6863; --linea: #dfe5e2;
  --acento: #1f5f74; --acento-velo: rgba(31,95,116,.12);
  --sube: #17794a; --baja: #c2412f; --m20: #d18a00; --m50: #2f6fd0; --m200: #8a4fc0; --bt: #7a8580;
  --texto: "Public Sans", "Segoe UI", system-ui, sans-serif;
  --cifras: "IBM Plex Mono", ui-monospace, Menlo, monospace;
}
@media (prefers-color-scheme: dark) { :root:not([data-theme="light"]) {
  --fondo: #0f1513; --hoja: #151c19; --tinta: #e6ece9; --suave: #95a39d; --linea: #26302c;
  --acento: #6bb7cf; --acento-velo: rgba(107,183,207,.16);
  --sube: #3fbf7f; --baja: #ef6f63; --m20: #f0b03c; --m50: #6aa2f5; --m200: #b88ae6; --bt: #8d9893; color-scheme: dark; } }
:root[data-theme="dark"] {
  --fondo: #0f1513; --hoja: #151c19; --tinta: #e6ece9; --suave: #95a39d; --linea: #26302c;
  --acento: #6bb7cf; --acento-velo: rgba(107,183,207,.16);
  --sube: #3fbf7f; --baja: #ef6f63; --m20: #f0b03c; --m50: #6aa2f5; --m200: #b88ae6; --bt: #8d9893; color-scheme: dark; }
* { box-sizing: border-box; }
body { margin: 0; background: var(--fondo); color: var(--tinta); font: 14px/1.45 var(--texto); }
main { max-width: 1280px; margin: 0 auto; padding: 20px 16px 36px; display: grid; gap: 12px; }
h1 { margin: 0; font-size: 1.35rem; }
.fila { display: flex; flex-wrap: wrap; gap: 6px; align-items: center; }
.activos { overflow-x: auto; flex-wrap: nowrap; padding-bottom: 2px; }
button { font: 600 .82rem var(--texto); color: var(--tinta); background: var(--hoja); border: 1px solid var(--linea);
  border-radius: 6px; padding: 5px 10px; cursor: pointer; white-space: nowrap; }
button:hover { border-color: var(--acento); }
button:focus-visible { outline: 2px solid var(--acento); outline-offset: 1px; }
button[aria-pressed="true"] { background: var(--acento); border-color: var(--acento); color: var(--hoja); }
.sep { width: 1px; height: 22px; background: var(--linea); margin: 0 4px; }
.mueble { background: var(--hoja); border: 1px solid var(--linea); border-radius: 8px; overflow: hidden; position: relative; }
#principal { height: min(62vh, 560px); min-height: 340px; }
#rsi { height: 140px; border-top: 1px solid var(--linea); }
.leyenda { position: absolute; top: 8px; left: 12px; z-index: 3; pointer-events: none; display: grid; gap: 2px;
  font: 12px/1.4 var(--cifras); font-variant-numeric: tabular-nums; }
.leyenda b { font: 700 15px var(--texto); margin-right: 8px; }
.leyenda .sube { color: var(--sube); } .leyenda .baja { color: var(--baja); }
.medias span { margin-right: 10px; }
.chip { display: inline-block; width: 10px; height: 3px; border-radius: 2px; vertical-align: middle; margin-right: 4px; }
.nota { color: var(--suave); font-size: .8rem; max-width: 80ch; }
#info { min-height: 1.4em; color: var(--suave); font-size: .85rem; }
</style>
<main>
  <div class="fila" style="justify-content: space-between">
    <h1>Gráficos swing</h1>
    <span class="nota">Rueda: zoom · arrastrar: mover · doble clic en el eje: reajustar</span>
  </div>
  <div class="fila activos" id="activos" role="group" aria-label="Activo"></div>
  <div class="fila" role="group" aria-label="Opciones">
    <button id="tf-D" aria-pressed="true">Diario</button><button id="tf-S" aria-pressed="false">Semanal</button>
    <span class="sep"></span>
    <button id="op-m20" aria-pressed="true"><span class="chip" style="background:var(--m20)"></span>SMA 20</button>
    <button id="op-m50" aria-pressed="true"><span class="chip" style="background:var(--m50)"></span>SMA 50</button>
    <button id="op-m200" aria-pressed="true"><span class="chip" style="background:var(--m200)"></span>SMA 200</button>
    <button id="op-vol" aria-pressed="true">Volumen</button>
    <span class="sep"></span>
    <button id="op-senal" aria-pressed="true">Señales y paper</button>
    <button id="op-bt" aria-pressed="false">Operaciones backtest</button>
    <span class="sep"></span>
    <button id="r-6M">6 M</button><button id="r-1A">1 A</button><button id="r-3A">3 A</button><button id="r-T">Todo</button>
  </div>
  <div class="mueble">
    <div class="leyenda"><div id="ohlc"></div><div class="medias" id="medias"></div></div>
    <div id="principal"></div>
    <div id="rsi"></div>
  </div>
  <div id="info"></div>
  <p class="nota">Velas ajustadas por splits y dividendos (Yahoo Finance). Flechas: señales del escáner y órdenes de la
    cuenta paper; «BT»: operaciones del backtest de retrocesos. El RSI(14) marca 70 y 30. La última vela puede estar
    en curso si se generó con el mercado abierto. Se regenera con <code>python graficos.py</code>.</p>
</main>
<script src="__LIBRERIA__"></script>
<script>
const D = __DATOS__;
const css = n => getComputedStyle(document.documentElement).getPropertyValue(n).trim();
const est = { tk: Object.keys(D.velas).includes("NVDA") ? "NVDA" : Object.keys(D.velas)[0], tf: "D",
  m20: true, m50: true, m200: true, vol: true, senal: true, bt: false };
try { Object.assign(est, JSON.parse(localStorage.getItem("graficos") || "{}")); } catch (e) {}
if (!D.velas[est.tk]) est.tk = Object.keys(D.velas)[0];
const guardar = () => { try { localStorage.setItem("graficos", JSON.stringify(est)); } catch (e) {} };

function semanal(v) {  // agrupa velas diarias en semanas (fecha = lunes de la semana)
  const out = [];
  for (const [t, o, h, l, c, vol] of v) {
    const d = new Date(t + "T00:00:00Z"); d.setUTCDate(d.getUTCDate() - ((d.getUTCDay() + 6) % 7));
    const k = d.toISOString().slice(0, 10), u = out[out.length - 1];
    if (u && u[0] === k) { u[2] = Math.max(u[2], h); u[3] = Math.min(u[3], l); u[4] = c; u[5] += vol; }
    else out.push([k, o, h, l, c, vol]);
  }
  return out;
}
const lunes = t => { const d = new Date(t + "T00:00:00Z"); d.setUTCDate(d.getUTCDate() - ((d.getUTCDay() + 6) % 7)); return d.toISOString().slice(0, 10); };
function sma(v, n) { const r = []; let s = 0;
  v.forEach((x, i) => { s += x[4]; if (i >= n) s -= v[i - n][4]; if (i >= n - 1) r.push({ time: x[0], value: s / n }); }); return r; }
function rsi(v, n = 14) {  // RSI de Wilder, como backtest.py
  const r = v.length ? [{ time: v[0][0] }] : []; let su = null, ba = null;  // huecos al inicio: así el RSI queda alineado con las velas
  for (let i = 1; i < v.length; i++) {
    const d = v[i][4] - v[i - 1][4], up = Math.max(d, 0), dn = Math.max(-d, 0);
    su = su === null ? up : su + (up - su) / n; ba = ba === null ? dn : ba + (dn - ba) / n;
    r.push(i >= n ? { time: v[i][0], value: ba === 0 ? 100 : 100 - 100 / (1 + su / ba) } : { time: v[i][0] });
  }
  return r;
}

const base = () => ({ layout: { background: { color: css("--hoja") }, textColor: css("--suave"), fontFamily: css("--cifras") },
  grid: { vertLines: { color: css("--linea") }, horzLines: { color: css("--linea") } },
  rightPriceScale: { borderColor: css("--linea") }, timeScale: { borderColor: css("--linea") },
  crosshair: { mode: 0 }, autoSize: true, localization: { locale: "es-ES" } });
const LW = LightweightCharts;
const g = LW.createChart(document.getElementById("principal"), base());
const fijo = { timeScale: { visible: false }, handleScroll: false, handleScale: false };
const gr = LW.createChart(document.getElementById("rsi"), { ...base(), ...fijo });
const velas = g.addCandlestickSeries({ borderVisible: false });
const vol = g.addHistogramSeries({ priceScaleId: "vol", priceFormat: { type: "volume" }, lastValueVisible: false, priceLineVisible: false });
g.priceScale("vol").applyOptions({ scaleMargins: { top: 0.82, bottom: 0 } });
g.priceScale("right").applyOptions({ scaleMargins: { top: 0.12, bottom: 0.2 } });
const med = { m20: g.addLineSeries({ lineWidth: 1, priceLineVisible: false, lastValueVisible: false, crosshairMarkerVisible: false }),
  m50: g.addLineSeries({ lineWidth: 1, priceLineVisible: false, lastValueVisible: false, crosshairMarkerVisible: false }),
  m200: g.addLineSeries({ lineWidth: 2, priceLineVisible: false, lastValueVisible: false, crosshairMarkerVisible: false }) };
const lrsi = gr.addLineSeries({ lineWidth: 1.5, priceLineVisible: false });
let lineas = [];

function colores() {
  g.applyOptions(base()); gr.applyOptions({ ...base(), ...fijo });
  velas.applyOptions({ upColor: css("--sube"), downColor: css("--baja"), wickUpColor: css("--sube"), wickDownColor: css("--baja") });
  for (const k in med) med[k].applyOptions({ color: css("--" + k) });
  lrsi.applyOptions({ color: css("--acento") });
  lineas.forEach(l => lrsi.removePriceLine(l));
  lineas = [70, 30].map(p => lrsi.createPriceLine({ price: p, color: css("--suave"), lineWidth: 1, lineStyle: 2, axisLabelVisible: true }));
}

let actual = [];
function dibujar() {  // cambia de activo o de marco temporal
  const v = est.tf === "S" ? semanal(D.velas[est.tk]) : D.velas[est.tk];
  actual = v;
  velas.setData(v.map(x => ({ time: x[0], open: x[1], high: x[2], low: x[3], close: x[4] })));
  lrsi.setData(rsi(v));
  capas();
  rangoBarras(est.tf === "S" ? 52 : 250);
  const ult = D.marcas[est.tk]?.filter(m => m.tipo !== "backtest").slice(-1)[0];
  document.getElementById("info").textContent = ult ? `Última marca de ${est.tk}: ${ult.texto} el ${ult.t}${ult.info ? " (" + ult.info + ")" : ""}` : "";
}
function capas() {  // medias, volumen y marcas, sin tocar las velas ni el zoom
  const v = actual;
  vol.setData(est.vol ? v.map(x => ({ time: x[0], value: x[5], color: (x[4] >= x[1] ? css("--sube") : css("--baja")) + "55" })) : []);
  for (const [k, n] of [["m20", 20], ["m50", 50], ["m200", 200]]) med[k].setData(est[k] ? sma(v, n) : []);
  const fechas = new Set(v.map(x => x[0]));
  const ms = (D.marcas[est.tk] || []).filter(m => (m.tipo === "backtest" ? est.bt : est.senal))
    .map(m => ({ ...m, t: est.tf === "S" ? lunes(m.t) : m.t })).filter(m => fechas.has(m.t))
    .sort((a, b) => a.t < b.t ? -1 : 1)
    .map(m => { const c = m.lado === "COMPRA";
      return { time: m.t, position: c ? "belowBar" : "aboveBar", shape: m.tipo === "backtest" ? "circle" : (c ? "arrowUp" : "arrowDown"),
        color: m.tipo === "backtest" ? css("--bt") : m.tipo === "paper" ? css("--acento") : (c ? css("--sube") : css("--baja")),
        text: m.texto, size: m.tipo === "backtest" ? 0.6 : 1.2 }; });
  velas.setMarkers(ms);
  leyenda(null); botones(); guardar();
}
function rangoBarras(n) { const L = actual.length; g.timeScale().setVisibleLogicalRange({ from: Math.max(0, L - n), to: L + 3 }); }

const fmt = (x, d = 2) => x.toLocaleString("es-ES", { minimumFractionDigits: d, maximumFractionDigits: d });
function leyenda(p) {
  const i = p && p.time ? actual.findIndex(x => x[0] === (typeof p.time === "string" ? p.time :
    `${p.time.year}-${String(p.time.month).padStart(2, "0")}-${String(p.time.day).padStart(2, "0")}`)) : actual.length - 1;
  const x = actual[i < 0 ? actual.length - 1 : i], prev = actual[(i < 0 ? actual.length - 1 : i) - 1];
  const ch = prev ? (x[4] / prev[4] - 1) * 100 : 0, cl = ch >= 0 ? "sube" : "baja";
  document.getElementById("ohlc").innerHTML = `<b>${est.tk}</b>${x[0]} · A ${fmt(x[1])} · M ${fmt(x[2])} · m ${fmt(x[3])} · C ${fmt(x[4])} <span class="${cl}">${ch >= 0 ? "+" : ""}${fmt(ch)} %</span>`;
  const val = (s) => { const d = s.find(y => y.time === x[0]); return d ? fmt(d.value) : "—"; };
  const partes = [];
  for (const [k, n] of [["m20", 20], ["m50", 50], ["m200", 200]]) if (est[k]) partes.push(`<span><span class="chip" style="background:var(--${k})"></span>SMA${n} ${val(sma(actual.slice(Math.max(0, (i < 0 ? actual.length - 1 : i) - n + 1), (i < 0 ? actual.length : i + 1)), n))}</span>`);
  document.getElementById("medias").innerHTML = partes.join("");
}

function botones() {
  document.querySelectorAll("#activos button").forEach(b => b.setAttribute("aria-pressed", b.dataset.tk === est.tk));
  document.getElementById("tf-D").setAttribute("aria-pressed", est.tf === "D");
  document.getElementById("tf-S").setAttribute("aria-pressed", est.tf === "S");
  for (const k of ["m20", "m50", "m200", "vol", "senal", "bt"]) document.getElementById("op-" + k).setAttribute("aria-pressed", est[k]);
}
const caja = document.getElementById("activos");
for (const tk of Object.keys(D.velas)) {
  const b = document.createElement("button"); b.textContent = tk; b.dataset.tk = tk;
  b.onclick = () => { est.tk = tk; dibujar(); }; caja.appendChild(b);
}
document.getElementById("tf-D").onclick = () => { est.tf = "D"; dibujar(); };
document.getElementById("tf-S").onclick = () => { est.tf = "S"; dibujar(); };
for (const k of ["m20", "m50", "m200", "vol", "senal", "bt"]) document.getElementById("op-" + k).onclick = () => { est[k] = !est[k]; capas(); };
const porRango = { "6M": [126, 26], "1A": [252, 52], "3A": [756, 156] };
for (const r in porRango) document.getElementById("r-" + r).onclick = () => rangoBarras(porRango[r][est.tf === "S" ? 1 : 0]);
document.getElementById("r-T").onclick = () => g.timeScale().fitContent();

// el RSI sigue al gráfico principal (solo en ese sentido; el zoom se maneja arriba)
g.timeScale().subscribeVisibleLogicalRangeChange(r => { if (r) gr.timeScale().setVisibleLogicalRange(r); });
g.subscribeCrosshairMove(leyenda);

colores(); dibujar();
const recolorear = () => { colores(); capas(); };
matchMedia("(prefers-color-scheme: dark)").addEventListener("change", recolorear);
new MutationObserver(recolorear).observe(document.documentElement, { attributes: true, attributeFilter: ["data-theme"] });
</script>
"""

if __name__ == "__main__":
    sys.exit(main())
