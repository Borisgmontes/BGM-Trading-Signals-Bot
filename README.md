# BGM Trading Signals Bot

Bot educativo multiusuario de alertas de mercado por Telegram. No coloca órdenes.

## Comandos
- `/start`: registra tu chat privado.
- `/help`: muestra ayuda.
- `/new NOMBRE ACTIVO TF ENTRADA TENDENCIA CONFIRMACION STOP OBJETIVO_R RIESGO_PCT`: crea subestrategia.
- `/list`: lista las tuyas.
- `/on ID` y `/off ID`: activar o pausar una subestrategia propia.
- `/delete ID`: borrar una subestrategia propia.
- `/test`: alerta simulada.

Ejemplo: `/new BTC_Ruptura BTCUSDT 5m breakout ema200 volume atr 2 0.5`

Activos: BTCUSDT, ETHUSDT, SOLUSDT, BNBUSDT, XRPUSDT, ADAUSDT, DOGEUSDT. TF: 5m, 15m, 1h, 4h. Entrada: `breakout`, `ema_cross`, `liquidity_sweep`, `bos`. Tendencia: `none`, `ema200`, `ema_alignment`. Confirmación: `none`, `volume`, `atr`. Stop: `atr`, `swing`, `fixed_pct`. Objetivo: 1.5R, 2R o 3R. Riesgo nominal: 0.25%, 0.5%, 1% o 2%.

## Render
Variables necesarias: `BOT_TOKEN` y `DATABASE_URL` (PostgreSQL persistente de Render). Opcionales: `POLL_SECONDS` (mínimo 60; default 300) y `LOG_LEVEL`. Ejecuta `python web_worker.py`. Crea PostgreSQL persistente y añade su URL interna como `DATABASE_URL` al servicio en la misma región. El esquema se crea automáticamente al iniciar el worker.

## Límites
La configuración funciona en chats privados. Cada usuario solo puede cambiar sus propias estrategias; las alertas se deduplican por estrategia y vela cerrada. Usa datos públicos spot de Binance.US; la disponibilidad regional puede variar. El riesgo es nominal, no una pérdida máxima garantizada. El bot no ejecuta órdenes ni garantiza rentabilidad. Prueba en simulación antes de arriesgar capital.
