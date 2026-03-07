# 🎾 OnDepor - Bot de Reserva de Pádel

Bot automático para reservar canchas de pádel en CISSAB a través de ondepor.com.

## Configuración actual

| Parámetro | Valor |
|-----------|-------|
| **Días** | Sábados y Domingos |
| **Horarios** | 10:00 o 11:00 (prioridad 10:00) |
| **Cancha** | Preferencia KINERET (05-08) |
| **Socios** | Alan Garbo, Gabriel Topor, Damian Potap |
| **Actividad** | PÁDEL DIURNO |

## Ejecución automática

El bot corre automáticamente 24 horas antes:

- **Viernes 10:00** → Reserva para Sábado 10:00
- **Sábado 10:00** → Reserva para Domingo 10:00

## Configuración en GitHub

### 1. Crear repositorio

1. Ir a [github.com](https://github.com) 
2. Crear nuevo repositorio **privado** (ej: `ondepor-bot`)

### 2. Subir archivos

Subir estos archivos manteniendo la estructura:

```
ondepor-bot/
├── .github/
│   └── workflows/
│       └── ondepor.yml
├── ondepor_bot.py
└── README.md
```

### 3. Configurar credenciales (Secrets)

1. En el repositorio → **Settings** → **Secrets and variables** → **Actions**
2. Click **"New repository secret"**
3. Crear:

   | Name | Value |
   |------|-------|
   | `ONDEPOR_USER` | `aprync@gmail.com` |
   | `ONDEPOR_PASS` | `tu_contraseña` |

### 4. Probar

1. Ir a **Actions** → **OnDepor - Reserva Pádel**
2. Click **"Run workflow"** → **"Run workflow"**
3. Ver el resultado

## Modificar preferencias

Editar `ondepor_bot.py`, sección de configuración:

```python
# Horarios preferidos (en orden de prioridad)
"horarios_preferidos": ["10:00", "11:00"],

# Socios a agregar
"socios": [
    "Alan Garbo",
    "Gabriel Topor",
    "Damian Potap"
],
```

## Cambiar horario de ejecución

Editar `.github/workflows/ondepor.yml`:

```yaml
schedule:
  # Formato: minuto hora * * día_semana
  # Viernes 10:00 ARG = 13:00 UTC
  - cron: '0 13 * * 5'
  # Sábado 10:00 ARG = 13:00 UTC
  - cron: '0 13 * * 6'
```

**Ejemplos de horarios:**
- `'0 14 * * 5'` → Viernes 11:00 ARG (para reservar Sábado 11:00)
- `'0 20 * * 5'` → Viernes 17:00 ARG (para reservar Sábado 17:00 - NOCTURNO)

## Troubleshooting

### El login falla
Verificar credenciales en GitHub Secrets.

### No encuentra horarios
El horario puede ya estar tomado. El bot corre justo cuando se habilita, pero si alguien es más rápido...

### No encuentra socios
Verificar que los nombres coincidan exactamente con cómo aparecen en OnDepor.

### Para PÁDEL NOCTURNO
Cambiar en `ondepor_bot.py`:
```python
"actividad": "PÁDEL NOCTURNO",
"horarios_preferidos": ["19:00", "20:00", "21:00"],
```
