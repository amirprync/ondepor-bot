# 🎾 OnDepor - Reserva Web de Pádel

Interfaz web para disparar el bot de reserva en CISSAB. Soporta dos modos:
- **⚡ Reservar ahora**: ejecuta el bot inmediatamente (modo original)
- **⏰ Programar**: el bot espera en GitHub Actions hasta el momento exacto que vos elijas, y arranca a intentar 2 min antes

## 📁 Archivos

- `ondepor_bot.py` → Bot con modo programado (ventana de -2min a +5min)
- `ondepor.yml` → Workflow con timeout extendido a 6 horas. Va en `.github/workflows/`
- `index.html` → Web con toggle entre los dos modos

## 🚀 Setup (si ya tenías la versión anterior, solo reemplazá los 3 archivos)

### 1. Reemplazar archivos en tu repo

- Reemplazá `ondepor_bot.py`
- Reemplazá `.github/workflows/ondepor.yml` (el timeout pasó a 6 horas)
- Commit + push

### 2. La web

Misma URL que ya usabas (sea local o GitHub Pages). Solo bajate el nuevo `index.html` y abrilo.

> ⚙️ La configuración de GitHub (token, owner, repo) y la lista de jugadores se mantienen — están en `localStorage`.

## 🎯 Cómo usar el modo programado

1. Llená el formulario como siempre (actividad, fecha del turno, jugadores, horarios)
2. En **Modo de ejecución**, click en **⏰ Programar**
3. Aparecen 2 nuevos campos:
   - **Fecha del disparo**: el día EN QUE EL CLUB HABILITA la reserva (no el día del turno)
   - **Hora del disparo**: la hora EXACTA en que el sistema habilita (HH:MM)
4. Click en **⏰ PROGRAMAR RESERVA**
5. Listo — podés cerrar la pestaña, el bot espera en GitHub Actions

### Ejemplo concreto

Querés jugar el **sábado 3 de mayo a las 10:00**. El club habilita las reservas con 24hs de anticipación, o sea **viernes 2 de mayo a las 10:00**.

| Campo | Valor |
|---|---|
| Fecha del turno | 2026-05-03 |
| Horarios del turno | 10:00, 09:00 |
| Modo | ⏰ Programar |
| Fecha del disparo | 2026-05-02 |
| Hora del disparo | 10:00 |

El bot va a:
1. Quedarse esperando en GitHub Actions hasta el viernes 09:58 ARG
2. Empezar a intentar a las 09:58
3. Seguir intentando cada 3 segundos hasta lograr la reserva
4. Si a las 10:05 no lo logró, abandona

## ⏱️ Ventana de intentos

```
hora_objetivo - 2 min  ──→  empieza a intentar
hora_objetivo          ──→  el club habilita
hora_objetivo + 5 min  ──→  abandona si no consiguió
```

Total: **7 minutos** de intentos cada 3 segundos.

## ⚠️ Límites a tener en cuenta

- **GitHub Actions tiene un límite de 6 horas por job.** Si programás más de 6h adelante, el job se va a matar antes de la hora. La web te avisa si estás cerca del límite.
- **Tiempo de cómputo gratis**: 2.000 min/mes en repos privados. Si programás 5h adelante, eso "consume" 5h. Hacelo cuenta si vas a programar muchas reservas.
- **La hora se interpreta como Argentina (UTC-3)**, sin importar desde qué dispositivo dispares. Si viajás y querés programar desde otro país, igual pensá en hora ARG.

## 🐛 Troubleshooting

**"El workflow se disparó pero no encuentra el día del turno"**
- Probablemente la fecha del turno está mal. La fecha del **turno** es el día que querés jugar, no el día que disparás.

**"Pasaron las 10:05 y nada"**
- Revisá los logs en GitHub Actions. Lo más común: la lista de horarios estaba vacía, o todos los horarios estaban tomados al momento del disparo.

**"Quiero cancelar una reserva programada"**
- Andá a la pestaña Actions de tu repo en GitHub, abrí el run que está corriendo, y hacé click en "Cancel workflow" arriba a la derecha.

**"El bot no esperó y arrancó al toque"**
- Verificá que pusiste fecha Y hora del disparo en la web (en modo programado). Si alguno está vacío, cae en modo inmediato.

## 📝 Notas técnicas (cambios vs la versión anterior)

### Bot
- Nueva variable `ONDEPOR_HORA_OBJETIVO` (HH:MM, hora ARG)
- Nueva variable `ONDEPOR_FECHA_OBJETIVO` (YYYY-MM-DD, opcional, default = hoy)
- Si están definidas, el bot espera con `time.sleep` antes de levantar el browser
- La ventana de reintentos ahora es atada al momento objetivo, no al inicio

### Workflow
- `timeout-minutes: 360` (era 20) — necesario para soportar la espera
- Dos inputs nuevos: `hora_objetivo` y `fecha_objetivo`

### Web
- Tabs "Reservar ahora" / "Programar"
- Selector de fecha+hora en modo programado
- Conversión de hora local ARG a UTC manejada en JS (siempre interpreta como UTC-3)
- Polling más espaciado (cada 30s) en modo programado para ahorrar rate limit
