"""Envía las señales del escáner a una cuenta de paper trading de Alpaca (dinero simulado).

Lee resultados/escaner/senales.csv (lo genera escaner.py), toma las señales del último día
y decide qué órdenes mandar:

    COMPRA  orden a mercado para la apertura siguiente, con un stop de pérdidas adjunto
            (orden OTO de Alpaca). Se omite si ya tienes el activo, si hay una orden pendiente,
            si ya hay demasiadas posiciones o si no alcanza el efectivo.
    VENTA   cierra la posición si la abrió esa misma estrategia (o si no hay registro de quién
            la abrió) y cancela antes su stop pendiente.
    VIGILAR no hace nada.

Tamaño de posición: se arriesga un % del capital hasta el stop.
    acciones = capital * riesgo / (precio * stop), con un máximo de max_peso del capital por posición.
    Con los valores por defecto (riesgo 1 %, stop 8 %, máx. 10 %) cada compra ocupa ~10 % del capital.

SOLO PAPER TRADING: el cliente se crea con paper=True y el script se niega a seguir si la URL
no es la de la cuenta simulada. No hay opción para dinero real.

Claves: variables de entorno ALPACA_API_KEY y ALPACA_SECRET_KEY (las de la cuenta paper).
Nunca las escribas en este archivo ni en ningún otro que se guarde en el proyecto.

Uso:
    python paper_trading.py                   # simulacro sin claves: capital ficticio de 100 000 $
    python paper_trading.py --capital 25000   # simulacro con otro capital
    python paper_trading.py --cuenta          # lee tu cuenta paper y muestra el plan, sin enviar
    python paper_trading.py --enviar          # lee la cuenta paper y ENVÍA las órdenes (simuladas)
    python paper_trading.py --estado          # posiciones y órdenes abiertas de la cuenta paper
    python paper_trading.py --estrategias cruce_medias   # solo una estrategia

Aviso: la estrategia de retrocesos (retroceso_ma200) no está validada con backtest; el cruce de
medias sí, y rindió menos que comprar y mantener. Esto es para practicar, no una recomendación.
"""
import argparse
import math
import os
import sys
import time
from datetime import date, datetime
from pathlib import Path

import pandas as pd

BASE = Path(__file__).resolve().parent
SENALES = BASE / "resultados" / "escaner" / "senales.csv"
DIARIO = BASE / "resultados" / "paper" / "diario.csv"
ESTRATEGIAS = ["cruce_medias", "retroceso_ma200"]


# ---------------------------------------------------------------- planificación (sin red)

def senales_del_dia(ruta: Path = SENALES, fecha: str | None = None) -> tuple[str, pd.DataFrame]:
    df = pd.read_csv(ruta, dtype={"fecha": str})
    if df.empty:
        raise SystemExit("senales.csv está vacío: ejecuta antes python escaner.py")
    fecha = fecha or df["fecha"].max()
    return fecha, df[df["fecha"] == fecha].reset_index(drop=True)


def estrategia_de_apertura(diario: Path = DIARIO) -> dict[str, str]:
    """Qué estrategia abrió cada posición, según la última compra enviada."""
    if not diario.exists():
        return {}
    d = pd.read_csv(diario)
    d = d[(d["accion"] == "COMPRA") & (d["estado"] == "enviada")]
    return d.groupby("ticker")["estrategia"].last().to_dict()


def planificar(senales: pd.DataFrame, capital: float, efectivo: float,
               posiciones: dict[str, float], pendientes: set[str], abiertas_por: dict[str, str],
               estrategias=ESTRATEGIAS, riesgo=0.01, stop=0.08, max_peso=0.10,
               max_posiciones=8) -> list[dict]:
    """Convierte las señales en acciones. No toca la red, así se puede probar sin cuenta."""
    senales = senales[senales["estrategia"].isin(estrategias)]
    plan = []
    vendidos = set()

    for s in senales[senales["senal"] == "VENTA"].itertuples():
        if s.ticker not in posiciones or s.ticker in vendidos:
            continue
        duena = abiertas_por.get(s.ticker)
        if duena and duena != s.estrategia:
            plan.append({"accion": "OMITIR", "ticker": s.ticker, "estrategia": s.estrategia,
                         "motivo": f"venta de {s.estrategia}, pero la posición la abrió {duena}"})
            continue
        vendidos.add(s.ticker)
        plan.append({"accion": "VENTA", "ticker": s.ticker, "estrategia": s.estrategia,
                     "qty": posiciones[s.ticker], "motivo": s.motivo})

    n_pos = len(set(posiciones) - vendidos) + len(pendientes - set(posiciones))
    comprados = set()
    for s in senales[senales["senal"] == "COMPRA"].itertuples():
        def omitir(motivo):
            plan.append({"accion": "OMITIR", "ticker": s.ticker, "estrategia": s.estrategia, "motivo": motivo})

        if s.ticker in comprados:
            continue
        if s.ticker in posiciones:
            omitir("ya hay posición abierta"); continue
        if s.ticker in pendientes:
            omitir("ya hay una orden de compra pendiente"); continue
        if s.ticker in vendidos:
            omitir("hay venta del mismo activo hoy"); continue
        if n_pos >= max_posiciones:
            omitir(f"máximo de {max_posiciones} posiciones alcanzado"); continue
        precio = float(s.cierre)
        qty = math.floor(min(capital * riesgo / (precio * stop), capital * max_peso / precio))
        coste = qty * precio
        if qty < 1:
            omitir("el capital no llega para 1 acción con este riesgo"); continue
        if coste > efectivo:
            omitir(f"efectivo insuficiente ({efectivo:,.0f} $ < {coste:,.0f} $)"); continue
        efectivo -= coste
        n_pos += 1
        comprados.add(s.ticker)
        plan.append({"accion": "COMPRA", "ticker": s.ticker, "estrategia": s.estrategia, "qty": qty,
                     "precio_ref": precio, "stop": round(precio * (1 - stop), 2),
                     "importe": round(coste, 2), "motivo": s.motivo})
    return plan


def mostrar(plan: list[dict], fecha: str, capital: float) -> None:
    print(f"Señales del {fecha} · capital {capital:,.0f} $")
    if not plan:
        print("Nada que hacer (sin COMPRA ni VENTA aplicables).")
    for p in plan:
        if p["accion"] == "COMPRA":
            print(f"  COMPRA {p['qty']:>5} {p['ticker']:<5} ~{p['importe']:>10,.0f} $  "
                  f"stop {p['stop']}  ({p['estrategia']}: {p['motivo']})")
        elif p["accion"] == "VENTA":
            print(f"  VENTA  {p['qty']:>5} {p['ticker']:<5} ({p['estrategia']}: {p['motivo']})")
        else:
            print(f"  omitir {p['ticker']:<5} {p['motivo']}")


# ---------------------------------------------------------------- Alpaca (solo paper)

def cliente():
    from alpaca.trading.client import TradingClient

    key, secret = os.environ.get("ALPACA_API_KEY"), os.environ.get("ALPACA_SECRET_KEY")
    if not key or not secret:
        raise SystemExit("Faltan ALPACA_API_KEY y ALPACA_SECRET_KEY en el entorno (claves de la cuenta paper).")
    c = TradingClient(key, secret, paper=True)
    if "paper" not in str(getattr(c, "_base_url", "")).lower():
        raise SystemExit("Seguridad: el cliente no apunta a la cuenta paper. No se envía nada.")
    return c


def leer_cuenta(c):
    from alpaca.trading.enums import OrderSide, QueryOrderStatus
    from alpaca.trading.requests import GetOrdersRequest

    cuenta = c.get_account()
    posiciones = {p.symbol: float(p.qty) for p in c.get_all_positions()}
    abiertas = c.get_orders(GetOrdersRequest(status=QueryOrderStatus.OPEN, limit=500))
    pendientes = {o.symbol for o in abiertas if o.side == OrderSide.BUY}
    efectivo = min(float(cuenta.cash), float(cuenta.buying_power))
    return float(cuenta.equity), efectivo, posiciones, pendientes, abiertas


def anotar(filas: list[dict]) -> None:
    DIARIO.parent.mkdir(parents=True, exist_ok=True)
    nuevo = pd.DataFrame(filas)
    if DIARIO.exists():
        nuevo = pd.concat([pd.read_csv(DIARIO), nuevo])
    nuevo.to_csv(DIARIO, index=False)


def enviar(c, plan: list[dict], fecha: str, abiertas) -> None:
    from alpaca.trading.enums import OrderClass, OrderSide, TimeInForce
    from alpaca.trading.requests import MarketOrderRequest, StopLossRequest

    ahora = datetime.now().isoformat(timespec="seconds")
    filas = []
    for p in plan:
        if p["accion"] == "OMITIR":
            continue
        fila = {"enviado": ahora, "fecha_senal": fecha, "ticker": p["ticker"], "estrategia": p["estrategia"],
                "accion": p["accion"], "qty": p.get("qty"), "stop": p.get("stop"), "order_id": "", "estado": ""}
        try:
            if p["accion"] == "COMPRA":
                # GTC para que el stop no caduque al cerrar el día; enviada fuera de horario se ejecuta en la apertura.
                orden = c.submit_order(MarketOrderRequest(
                    symbol=p["ticker"], qty=p["qty"], side=OrderSide.BUY, time_in_force=TimeInForce.GTC,
                    order_class=OrderClass.OTO, stop_loss=StopLossRequest(stop_price=p["stop"]),
                    client_order_id=f"esc_{p['estrategia']}_{p['ticker']}_{fecha}"))  # repetir el día falla: evita duplicados
            else:
                for o in abiertas:
                    if o.symbol == p["ticker"] and o.side == OrderSide.SELL:
                        c.cancel_order_by_id(o.id)
                time.sleep(2)  # que Alpaca libere las acciones reservadas por el stop
                orden = c.close_position(p["ticker"])
            fila.update(order_id=str(orden.id), estado="enviada")
            print(f"  ✓ {p['accion']} {p['ticker']} enviada (id {orden.id})")
        except Exception as e:
            fila["estado"] = f"error: {e}"
            print(f"  ✗ {p['accion']} {p['ticker']}: {e}")
        filas.append(fila)
    if filas:
        anotar(filas)
        print(f"Registro en {DIARIO}")


def estado(c) -> None:
    equity, efectivo, posiciones, _, abiertas = leer_cuenta(c)
    print(f"Cuenta paper: capital {equity:,.2f} $ · efectivo disponible {efectivo:,.2f} $")
    for p in c.get_all_positions():
        print(f"  {p.symbol:<5} {p.qty:>6} acc. · entrada {float(p.avg_entry_price):.2f} · "
              f"actual {float(p.current_price):.2f} · P/G {float(p.unrealized_pl):+,.2f} $")
    for o in abiertas:
        print(f"  orden abierta: {o.side.value} {o.qty} {o.symbol} {o.type.value} "
              f"{o.stop_price or ''} ({o.status.value})")


def main() -> None:
    a = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    a.add_argument("--enviar", action="store_true", help="enviar las órdenes a la cuenta paper")
    a.add_argument("--cuenta", action="store_true", help="leer la cuenta paper sin enviar nada")
    a.add_argument("--estado", action="store_true", help="mostrar posiciones y órdenes de la cuenta paper")
    a.add_argument("--fecha", help="usar las señales de ese día (AAAA-MM-DD) en vez del último")
    a.add_argument("--estrategias", nargs="+", default=ESTRATEGIAS, choices=ESTRATEGIAS)
    a.add_argument("--capital", type=float, default=100_000, help="capital ficticio del simulacro sin claves")
    a.add_argument("--riesgo", type=float, default=0.01, help="fracción del capital arriesgada hasta el stop")
    a.add_argument("--stop", type=float, default=0.08, help="distancia del stop bajo el cierre (0.08 = 8 %%)")
    a.add_argument("--max-peso", type=float, default=0.10, help="máximo del capital por posición")
    a.add_argument("--max-posiciones", type=int, default=8)
    args = a.parse_args()

    if args.estado:
        estado(cliente())
        return

    fecha, senales = senales_del_dia(fecha=args.fecha)
    dias = (date.today() - date.fromisoformat(fecha)).days
    if dias > 4:
        print(f"Aviso: las últimas señales son de hace {dias} días; ejecuta python escaner.py primero.")

    c = None
    if args.enviar or args.cuenta:
        c = cliente()
        capital, efectivo, posiciones, pendientes, abiertas = leer_cuenta(c)
    else:
        print("SIMULACRO sin conexión (usa --cuenta o --enviar para la cuenta paper)\n")
        capital, efectivo, posiciones, pendientes, abiertas = args.capital, args.capital, {}, set(), []

    plan = planificar(senales, capital, efectivo, posiciones, pendientes, estrategia_de_apertura(),
                      args.estrategias, args.riesgo, args.stop, args.max_peso, args.max_posiciones)
    mostrar(plan, fecha, capital)
    if any(p["estrategia"] == "retroceso_ma200" and p["accion"] == "COMPRA" for p in plan):
        print("\nOjo: retroceso_ma200 aún no está validada con backtest.")

    if args.enviar:
        print("\nEnviando a la cuenta PAPER (dinero simulado)...")
        enviar(c, plan, fecha, abiertas)
    elif c is not None:
        print("\nNo se ha enviado nada (añade --enviar).")


if __name__ == "__main__":
    sys.exit(main())
