# BGM Trading Signals Bot

Bot educativo de señales para Binance USDⓈ-M Futures usando únicamente datos públicos. No coloca órdenes.

## Estrategia inicial
- Activos por defecto: BTCUSDT, ETHUSDT, SOLUSDT y BNBUSDT.
- Contexto H4: precio frente a EMA200 y relación EMA20/EMA50.
- Confirmación H1: EMA20/50/200 alineadas, barrido de liquidez reciente, ruptura estructural y volumen mínimo.
- Solo velas H1 cerradas.
- Entrada de referencia al cierre de la vela de confirmación.
- Stop detrás del extremo del barrido, con margen de 0.2 ATR.
- Objetivo mínimo 2R.
- Riesgo nominal configurado al 1% por operación.
- Solo envía LONG/SHORT válidos; las demás condiciones quedan como NO TRADE en logs.
- Deduplicación por vela H1 y registro local en signal_state.json.

## Variables de entorno obligatorias
- BOT_TOKEN: token del bot de Telegram.
- CHAT_ID: chat o canal al que el bot puede enviar mensajes.

## Variables opcionales
- SYMBOLS: lista separada por comas. Default: BTCUSDT,ETHUSDT,SOLUSDT,BNBUSDT
- RISK_PCT: riesgo nominal por operación. Default: 0.01 (1%).
- MIN_RR: relación mínima riesgo/beneficio. Default: 2.0.
- ACCOUNT_EQUITY_USDT: equity de referencia para estimar cantidad. Default: 0 (no muestra tamaño calculado).
- POLL_SECONDS: intervalo de revisión en segundos. Default: 300.
- LOG_LEVEL: nivel de logs. Default: INFO.

## Ejecución
Instala dependencias con: pip install -r requirements.txt
Inicia con: python worker.py

Configura las variables de entorno en el servicio de despliegue. Nunca guardes el token de Telegram en el repositorio.

## Importante
Es una primera versión de reglas, no una estrategia validada ni una garantía de rentabilidad. Probar en paper trading y hacer backtesting antes de usar capital real. El límite diario de pérdida no puede controlarse con fiabilidad hasta que el sistema registre y liquide los resultados de cada señal.
