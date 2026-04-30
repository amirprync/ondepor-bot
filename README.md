# 🎾 OnDepor - Reserva Web de Pádel

Interfaz web para disparar el bot de reserva de canchas en CISSAB. La web dispara un workflow de GitHub Actions vía la API de GitHub, así que el bot sigue corriendo en GitHub (gratis, sin necesidad de tener tu PC prendida).

## 📁 Archivos

- `ondepor_bot.py` → Bot modificado, ahora lee horario/fecha/socios desde variables de entorno
- `ondepor.yml` → Workflow de GitHub Actions (sin schedule, solo manual con inputs). Va en `.github/workflows/`
- `index.html` → Página web. Podés abrirla local (doble click) o subirla a GitHub Pages

## 🚀 Setup paso a paso

### 1. Reemplazar archivos en tu repo

En tu repositorio de GitHub:
- Reemplazá `ondepor_bot.py` por el nuevo
- Reemplazá `.github/workflows/ondepor.yml` por el nuevo
- Hacé commit y push

### 2. Crear el Personal Access Token de GitHub

1. Andá a https://github.com/settings/tokens?type=beta (Fine-grained tokens)
2. Click en **Generate new token**
3. Configurá:
   - **Token name**: `ondepor-bot-trigger`
   - **Expiration**: 1 año (o lo que prefieras)
   - **Repository access**: Only select repositories → elegí tu repo del bot
   - **Permissions** → Repository permissions:
     - **Actions**: Read and write
     - **Metadata**: Read-only (se marca solo)
4. Click en **Generate token** y copiá el token (empieza con `github_pat_...`)
5. ⚠️ Guardalo bien, GitHub solo te lo muestra una vez

> 💡 Si preferís un token clásico, también funciona con scope `workflow`, pero los fine-grained son más seguros.

### 3. Abrir la web

**Opción A: Local (más fácil)**
- Hacé doble click en `index.html` y se abre en el navegador
- Listo

**Opción B: GitHub Pages (accesible desde cualquier lado)**
1. Creá un repo nuevo (puede ser privado): `ondepor-web`
2. Subí el `index.html`
3. Settings → Pages → Source: `Deploy from a branch` → `main` / `/(root)`
4. Te da una URL tipo `https://tu-usuario.github.io/ondepor-web/`

### 4. Configurar la web (la primera vez)

1. Abrí la web
2. Click en **⚙️ Configuración GitHub**
3. Pegá:
   - **Token**: el que creaste antes
   - **Owner**: tu usuario de GitHub
   - **Repo**: el nombre del repo donde está el bot
   - **Workflow file**: `ondepor.yml` (default, no cambies si no es necesario)
4. Click en **💾 Guardar configuración**

> 🔒 Todo se guarda en `localStorage` de tu navegador. No se manda a ningún servidor externo.

### 5. Reservar 🎾

1. Elegí actividad (DIURNO/NOCTURNO)
2. Elegí fecha (default: mañana)
3. Click en 3 socios (vos sos el cuarto jugador, no te selecciones a vos)
4. Click en los horarios en orden de prioridad (el primer click = prioridad 1, etc.)
5. Click en **🚀 RESERVAR**
6. La web va a:
   - Disparar el workflow
   - Hacer polling cada 5 segundos
   - Mostrarte el resultado cuando termine (éxito/error con link a los logs)

## ⏱️ Tiempos esperables

- ~5-10 segundos para que arranque el runner de GitHub
- ~30-60 segundos instalando dependencias (Playwright + Chromium)
- ~10-15 minutos máximo del bot intentando la reserva
- **Total**: 1-2 minutos en el caso bueno (cancha disponible al toque)

## 🔧 Agregar/quitar jugadores

La lista de jugadores la podés editar directo desde la web (botón "+" para agregar). Se guarda en el navegador.

Si querés resetear a la lista default, hay un link "Resetear lista a la default".

## 🐛 Troubleshooting

**Error 401 / 403 al disparar**
- Token expirado o sin permisos. Generá uno nuevo y guardalo en config.

**Error 404 "Not Found"**
- Owner/Repo mal escritos, o el workflow no está en `main`.
- Verificá que `ondepor.yml` esté en `.github/workflows/` y haya hecho push.

**El workflow corre pero falla**
- Click en "Ver en GitHub Actions" desde la web para ver los logs.
- Lo más común: que `ONDEPOR_USER` o `ONDEPOR_PASS` no estén configurados como Secrets del repo (Settings → Secrets and variables → Actions).

**No encuentra el horario / la cancha**
- El bot busca en CISSAB con la actividad que elegiste. Si elegiste NOCTURNO pero el club no la tiene habilitada para esa fecha, no va a encontrar nada.

## 📝 Notas técnicas

- El bot ahora acepta 4 variables de entorno nuevas (todas opcionales):
  - `ONDEPOR_HORARIOS` (ej: `"10:00,09:00"`)
  - `ONDEPOR_FECHA` (ej: `"2026-05-15"`, vacío = mañana)
  - `ONDEPOR_ACTIVIDAD` (`DIURNO` o `NOCTURNO`)
  - `ONDEPOR_SOCIOS` (igual que antes)
- Si no se pasan, usa los defaults originales (compatible hacia atrás)
- El schedule automático fue eliminado del YAML. Si lo querés restaurar, copiá las líneas `schedule:` del YAML viejo.
