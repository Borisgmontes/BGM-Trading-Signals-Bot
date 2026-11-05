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
Variables necesarias: `BOT_TOKEN` y `DATABASE_URL` (PostgreSQL persistente de Render). Opcionales: `POLL_SECONDS` (mínimo 60; default 300) y `LOG_LEVEL`. Ejecuta `python web_worker.py`. Crea PostgreSQL persistente y añade su URL interna como `DATABASE_URL` al servicio en la misma región. El esquema se crea automáticamente al iniciar el worker. Si `DATABASE_URL` no está disponible, el bot permite pruebas en memoria, pero las configuraciones se pierden al reiniciar; esa modalidad no es adecuada para uso estable.

## Límites
La configuración funciona en chats privados. Cada usuario solo puede cambiar sus propias estrategias; las alertas se deduplican por estrategia y vela cerrada. Usa datos públicos spot de Binance.US; la disponibilidad regional puede variar. El riesgo es nominal, no una pérdida máxima garantizada. El bot no ejecuta órdenes ni garantiza rentabilidad. Prueba en simulación antes de arriesgar capital.


## BTC RADAR (nuevo módulo en rama feature/btc-radar)

En Telegram, pulsa **📡 Configurar BTC RADAR** desde `/start`. El asistente permite seleccionar temporalidad (5m/15m/1h/4h), activar módulos EMA/tendencia, RSI, MACD, volumen, ATR, Bollinger, barrido de liquidez y BOS, fijar el mínimo de confirmaciones y elegir objetivo teórico de 1.5R/2R/3R.

El radar utiliza velas cerradas de BTCUSDT desde el endpoint público spot de Binance.US. Cada configuración se guarda como estrategia individual en la tabla existente y se deduplica por estrategia y vela. Alertas informativas LONG/SHORT; no ejecuta órdenes. Los indicadores son reglas transparentes iniciales, no probabilidades ni señales con rentabilidad demostrada. Validar mediante backtest y paper trading antes de utilizarlas en real.

## Dashboard móvil privado (en pruebas)

La rama `feature/btc-radar` incluye una PWA para Android servida desde la raíz del servicio `web_worker.py`. El acceso está protegido por `DASHBOARD_PIN`. Para almacenamiento persistente se requiere `DATABASE_URL`. Para notificaciones Push se requieren `VAPID_PUBLIC_KEY`, `VAPID_PRIVATE_KEY` y opcionalmente `VAPID_CLAIMS_EMAIL`. Instala la PWA desde Chrome y concede permiso de notificaciones. El botón de compartir abre el menú nativo de Android; el usuario elige WhatsApp y el grupo.

**Probabilidad:** porcentaje histórico de configuraciones idénticas y misma dirección que alcanzaron TP antes de SL dentro de las siguientes 20 velas cerradas. Se calcula con hasta 1.000 velas; solo se muestra cuando existen al menos 30 ejemplos. Si la muestra es menor, se indica “en calibración”. No garantiza el resultado de la próxima señal. El dashboard no ejecuta órdenes.
