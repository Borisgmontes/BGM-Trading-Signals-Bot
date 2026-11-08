# BGM Quant Lab — BTC Strategy Research

Estado: laboratorio de investigación en la rama `feature/bgm-quant-lab-btc`. No conecta con brokers, no envía órdenes y no modifica BTC Radar.

## Flujo recomendado desde el dashboard

1. Abre el constructor BTC y describe las reglas usando las condiciones compatibles.
2. Ajusta temporalidad, velas, capital, comisión, slippage, Stop ATR, objetivo R, riesgo y máximo de velas.
3. Pulsa **Guardar configuración**. Si modificas un campo después, vuelve a guardarlo.
4. Pulsa **Interpretar reglas** y revisa las condiciones LONG/SHORT y los avisos. Si solo defines una dirección, la opuesta se genera invirtiendo operadores; revisa esa hipótesis.
5. Guarda la estrategia si quieres reutilizarla, exporta el JSON o ejecuta el backtest.
6. Compara el resultado OUT-OF-SAMPLE con las pruebas anteriores. El historial de estrategias y comparaciones queda en el almacenamiento local del navegador.

El parser de lenguaje natural sigue siendo deliberadamente limitado y solo reconoce las reglas indicadas por su diagnóstico. El constructor visual añade reglas de entrada y salida LONG/SHORT con comparaciones de precio e indicadores, eventos de cruce EMA 10/20, 20/50 y 50/200, y aperturas de Tokio, Londres y Nueva York. Los cruces se activan únicamente en la vela donde cambia la relación entre medias. Las aperturas se calculan en la zona horaria local de cada mercado (con DST) y requieren una vela cuya marca de tiempo coincida con la apertura; en temporalidades mayores puede no existir una vela alineada. Los indicadores usan estos parámetros fijos en esta versión: EMA 10/20/50/100/200; RSI 14; ATR 14; Bollinger 20 con 2 desviaciones; MACD 12/26/9; volumen relativo sobre SMA 20. El usuario selecciona la variante EMA desde el catálogo; los periodos de RSI/ATR/Bollinger/MACD todavía no son editables. VWAP, Fibonacci, CHoCH/BOS y patrones no se deben considerar implementados.

## Datos y motor

- El dashboard llama a `https://bgm-quant-lab-api.onrender.com`. El constructor visual está en `quant_lab/dashboard/builder-v2.js` y la biblioteca se conserva en `localStorage` del navegador (no es una biblioteca compartida entre dispositivos).
- `GET /health`: estado del API.
- `POST /api/interpret`: convierte una descripción compatible en el esquema de `quant_lab.strategy`.
- `POST /api/backtest`: descarga velas cerradas de BTCUSDT desde Binance.US, calcula indicadores y devuelve muestra completa, TRAIN y OUT-OF-SAMPLE cronológico.
- La entrada se simula en la apertura de la vela siguiente a la señal. Las salidas por condición se evalúan al cierre de cada vela; el Stop y el Target tienen prioridad y, si ambos se tocan en una misma vela, se asume primero el Stop.
- El sizing es spot sin apalancamiento, limita el nocional al 100% del capital y busca no superar el riesgo configurado en el Stop. Las operaciones SHORT son simulaciones direccionales; no modelan margen, funding, borrow, liquidación, gaps, profundidad ni latencia.
- Comisiones y slippage se expresan en bps por lado y se descuentan como coste de ida y vuelta. Los resultados dependen de la disponibilidad y calidad del proveedor gratuito.
- El dashboard muestra métricas calculadas por el motor, no cifras de muestra. Si la API no responde, no presenta resultados como si fueran reales.

## JSON y CLI reproducible

El botón **Exportar JSON** descarga un objeto con `strategy` compatible con `strategy_from_dict`, además de temporalidad, velas, capital y costes. Desde la raíz del repositorio:

```bash
pip install -r requirements.txt
python -m quant_lab.cli --strategy-json bgm_quant_lab_strategy.json
```

El CLI usa los parámetros guardados en el JSON. Los argumentos de línea de comandos los pueden sobrescribir:

```bash
python -m quant_lab.cli --strategy-json bgm_quant_lab_strategy.json --timeframe 1h --candles 5000 --fee-bps 5 --slippage-bps 2 --initial-equity 10000
```

El reporte se escribe en `quant_lab/results/btc_candidates.json`. También se puede ejecutar la batería local con:

```bash
python -m unittest discover -s tests -v
python -m compileall -q quant_lab
```

## Interpretación de métricas y limitaciones

- Las métricas de muestra completa sirven para inspección; no sustituyen la validación fuera de muestra.
- TRAIN ocupa el primer 70% de velas; OUT-OF-SAMPLE usa el 30% final con velas previas solo para calentar indicadores. No se deben optimizar parámetros mirando repetidamente el OOS.
- El profit factor se calcula con retornos netos de cada operación; si no hay pérdidas, puede aparecer como `null` (sin denominador).
- El drawdown se calcula sobre la curva de capital al cierre de cada operación, no sobre cada fluctuación intrabar.
- El simulador no incorpora impuestos, spread variable, funding, liquidación, latencia, market impact ni fallos de ejecución.
- El score OOS es un filtro transparente de investigación, no una predicción ni una aprobación para operar.
- La página multi-activo anterior se conserva en `multi-asset.html`; usa un motor distinto y datos de Yahoo Finance. Para estrategias BTC exportables al CLI se debe usar el constructor principal de esta página.
