# Swing trading en Python

## Datos
- `descargar_datos.py`: descarga velas diarias OHLCV (ajustadas por splits/dividendos) de Yahoo Finance con yfinance y las guarda en `data/<TICKER>.csv`.
- Lista por defecto: SPY, QQQ, IWM, DIA, AAPL, MSFT, NVDA, AMZN, GOOGL, META, TSLA, JPM, V, XOM (10 años).
- Instalar: `pip install -r requirements.txt`
- Descargar: `python descargar_datos.py` · Actualizar: `python descargar_datos.py --actualizar`
- Usar desde otro script: `from descargar_datos import cargar; df = cargar("SPY")`
  (índice `Date`, columnas `Open High Low Close Volume`)

## Backtest
- `backtest.py`: estrategia swing de cruce de medias (SMA 20/50) con filtro RSI(14), stop del 8 %, solo largos, orden en la apertura siguiente, 0,05 % de coste por operación. Compara con comprar y mantener.
- `python backtest.py` (todos) · `python backtest.py SPY --rapida 10 --lenta 30 --grafico` · `--desde 2023-01-01`
- Salida en `resultados/`: `resumen.csv`, `operaciones_<TICKER>.csv` y, con `--grafico`, `<TICKER>.png`.

## Escáner diario
- `escaner.py`: actualiza los datos y busca señales con el último cierre en los 14 activos.
  - Cruce de medias (SMA 20/50 + RSI14, igual que el backtest): COMPRA / VENTA.
  - Retroceso en tendencia: COMPRA si cierre > SMA200 y RSI(2) < 10; VIGILAR si RSI(2) < 25; VENTA cuando el cierre vuelve sobre la SMA5.
- `python escaner.py` · `--sin-actualizar` · `python escaner.py AAPL NVDA` · `--fecha 2026-03-10` (revisar un día pasado)
- Salida en `resultados/escaner/`: `informe_<FECHA>.md` (informe del día) y `senales.csv` (histórico).

## Paper trading (Alpaca, dinero simulado)
- `paper_trading.py`: lee las señales del último día en `resultados/escaner/senales.csv` y las manda a una cuenta **paper** de Alpaca. Nunca usa la cuenta real (cliente con `paper=True` y comprobación de la URL).
  - COMPRA: orden a mercado para la apertura siguiente con stop adjunto (OTO, GTC). Tamaño: arriesga el 1 % del capital hasta un stop del 8 %, máx. 10 % del capital por posición y 8 posiciones.
  - VENTA: cierra la posición si la abrió esa estrategia y cancela su stop. VIGILAR: nada.
  - Registro de lo enviado en `resultados/paper/diario.csv`.
- Claves en variables de entorno, nunca en archivos: `export ALPACA_API_KEY=...` y `export ALPACA_SECRET_KEY=...`
- En el entorno de Claude las claves van como secreto de red en el proxy: ejecutar con `ALPACA_CLAVES_EN_PROXY=1`.
- `python paper_trading.py` (simulacro sin claves) · `--cuenta` (lee la cuenta, no envía) · `--enviar` · `--estado` · `--estrategias cruce_medias`
- Flujo diario, tras el cierre: `python escaner.py && python paper_trading.py --enviar`
- La estrategia `retroceso_ma200` no está validada con backtest.
