# BGM Quantum Lab — Analítica de uso

El seguimiento es anónimo y exclusivo de Quantum Lab. No recopila nombres, correos, direcciones IP ni contenido de las estrategias.

## Eventos
- `page_view`: visita a una página.
- `strategy_saved`: estrategia guardada en el navegador.
- `strategy_interpreted`: reglas interpretadas.
- `backtest_completed`: backtest completado.
- `client_error`: reservado para errores de cliente instrumentados.

Se genera un identificador aleatorio de visitante en localStorage y un identificador de sesión en sessionStorage. Esto permite estimar visitantes únicos y sesiones, pero no identificar personas ni dispositivos con certeza absoluta.

## Almacenamiento requerido
La API usa tablas separadas llamadas `quant_lab_analytics_events` en PostgreSQL. No reutilizar la base de datos de BGM BTC Radar sin una decisión explícita del propietario.

Configurar en el servicio Render `bgm-quant-lab-api`:
- `QUANT_ANALYTICS_DATABASE_URL`: URL de una base PostgreSQL dedicada a Quantum Lab.
- `QUANT_ADMIN_TOKEN`: secreto largo y aleatorio para proteger el panel.

No se debe usar una base efímera ni SQLite en el disco temporal del servicio para informes históricos.

## Panel
Después de configurar ambas variables:
- URL: `https://bgm-quant-lab.onrender.com/admin.html`
- API: `GET /api/analytics/report?days=1|7|30`
- Eventos: `POST /api/analytics/event`

El panel solicita el token y lo conserva solo en sessionStorage. El endpoint de informes exige `Authorization: Bearer <token>`.

## Límites
Los datos comienzan a contarse después de publicar y configurar el seguimiento. No reconstruye visitas anteriores. Las métricas de Render por sí solas cuentan solicitudes HTTP, no usuarios únicos. El panel reporta agregados y no almacena IPs ni agentes de usuario.
