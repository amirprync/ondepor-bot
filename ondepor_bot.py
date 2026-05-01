"""
OnDepor - Bot de Reserva Automática de Canchas de Pádel
=======================================================
Automatiza la reserva de canchas en CISSAB a través de ondepor.com

MODOS DE EJECUCIÓN:
1. Inmediato: El bot arranca a buscar la reserva apenas se ejecuta
2. Programado: Si se define ONDEPOR_HORA_OBJETIVO, sigue esta línea de tiempo:

    t - 2 min        →  💤 Pre-carga: levanta browser, login, navega al día
                        (cuando termina, queda esperando)
    t - 5 segundos   →  🔍 Empieza a refrescar agresivamente (cada 0.5s)
    t (ej. 16:00:00) →  🎯 El club habilita la celda, click instantáneo
    t + 60 segundos  →  📉 Si no consiguió, baja a polling normal (cada 3s)
    t + 5 min        →  🛑 Abandona

OBJETIVO: estar logueado y posicionado en el calendario antes de la hora exacta,
para reaccionar inmediatamente cuando el club habilita el turno y competir
contra otros usuarios que también están intentando reservar.

Variables de entorno requeridas:
    ONDEPOR_USER:           Email de login
    ONDEPOR_PASS:           Contraseña

Variables de entorno opcionales (configurables desde la web):
    ONDEPOR_SOCIOS:         Lista de socios separados por coma
    ONDEPOR_HORARIOS:       Horarios preferidos en orden de prioridad
    ONDEPOR_FECHA:          Fecha del turno YYYY-MM-DD (default: mañana)
    ONDEPOR_ACTIVIDAD:      "DIURNO" o "NOCTURNO" (default: DIURNO)
    ONDEPOR_HORA_OBJETIVO:  Hora ARG HH:MM en la que el club habilita.
                            Si no se indica, ejecuta inmediato.
    ONDEPOR_FECHA_OBJETIVO: Fecha del momento del disparo YYYY-MM-DD (default: hoy)

Uso:
    python ondepor_bot.py
    python ondepor_bot.py --visible    # Ver navegador
    python ondepor_bot.py --dry-run    # Simular sin reservar
"""

import argparse
import os
import sys
import time
from datetime import datetime, timedelta, timezone
from playwright.sync_api import sync_playwright, TimeoutError as PlaywrightTimeout

# CRÍTICO: forzar que stdout sea line-buffered (cada print() se ve al toque
# en los logs de GitHub Actions, no atrapado en buffer hasta que termine el job).
# Refuerzo de PYTHONUNBUFFERED=1 que está en el workflow YAML.
try:
    sys.stdout.reconfigure(line_buffering=True)
    sys.stderr.reconfigure(line_buffering=True)
except (AttributeError, OSError):
    pass


# =============================================================================
# CONFIGURACIÓN
# =============================================================================

# =============================================================================
# Configuración de tiempos del modo PROGRAMADO
# =============================================================================
# Línea de tiempo:
#
#   t - PRELOAD_MINUTES_BEFORE       →  Levanta browser, login, navega al día
#   t - INICIO_BUSQUEDA_SEG_ANTES    →  Empieza a refrescar agresivamente
#   t (hora objetivo, ej. 16:00)     →  El club habilita la celda
#   t + END_MINUTES_AFTER            →  Abandona si no consiguió
#

PRELOAD_MINUTES_BEFORE = 3          # Pre-carga (login + navegación) antes de la hora — subido a 3min
INICIO_BUSQUEDA_SEG_ANTES = 10      # Empezar a refrescar X segundos antes — subido a 10s
END_MINUTES_AFTER = 5               # Cortar intentos X min después de la hora objetivo

RETRY_INTERVAL_RAPIDO = 0.8         # Intervalo durante ventana crítica (con reload completo)
RETRY_INTERVAL_NORMAL = 3.0         # Intervalo después de la ventana crítica
VENTANA_CRITICA_DESPUES_SEG = 90    # Cuántos seg después de t seguir con polling rápido

# Variable global para guardar URL del XHR del calendario una vez detectada
CALENDAR_XHR_URL = None
CALENDAR_XHR_HEADERS = None
CALENDAR_XHR_METHOD = "GET"
CALENDAR_PAGE_URL = None  # URL de la página del calendario (post click en DIURNO)

# Modo inmediato (sin hora objetivo): ventana max de intentos
MAX_RETRY_MINUTES_INMEDIATO = 15

# Argentina: UTC-3 fijo (no usa horario de verano desde 2009)
ARGENTINA_TZ = timezone(timedelta(hours=-3))


def get_config():
    """Obtiene configuración desde variables de entorno."""
    usuario = os.environ.get("ONDEPOR_USER")
    password = os.environ.get("ONDEPOR_PASS")
    
    if not usuario or not password:
        print("❌ Error: Variables de entorno no configuradas")
        print("   Configurar ONDEPOR_USER y ONDEPOR_PASS")
        sys.exit(1)
    
    # Los socios se pueden configurar desde variable de entorno
    socios_env = os.environ.get("ONDEPOR_SOCIOS", "")
    if socios_env:
        socios = [s.strip() for s in socios_env.split(",") if s.strip()]
    else:
        socios = ["Alan Garbo", "Gabriel Topor", "Damian Potap"]
    
    # Horarios preferidos
    horarios_env = os.environ.get("ONDEPOR_HORARIOS", "")
    if horarios_env:
        horarios_preferidos = [h.strip() for h in horarios_env.split(",") if h.strip()]
    else:
        horarios_preferidos = ["09:00", "10:00"]
    
    # Actividad
    actividad_env = os.environ.get("ONDEPOR_ACTIVIDAD", "DIURNO").upper().strip()
    if actividad_env not in ("DIURNO", "NOCTURNO"):
        actividad_env = "DIURNO"
    actividad = f"PÁDEL {actividad_env}"
    
    return {
        "url": "https://www.ondepor.com/",
        "url_login": "https://www.ondepor.com/site/login",
        "url_favoritos": "https://www.ondepor.com/user/_favorites",
        "usuario": usuario,
        "password": password,
        "actividad": actividad,
        "horarios_preferidos": horarios_preferidos,
        "canchas_preferidas": ["KINERET", "05-", "06-", "07-", "08-"],
        "socios": socios,
        "timeout_navegacion": 30000,
        "timeout_elemento": 10000,
        "delay_entre_acciones": 1000,
    }


def get_fecha_objetivo():
    """Calcula la fecha A RESERVAR (la del turno de pádel)."""
    fecha_env = os.environ.get("ONDEPOR_FECHA", "").strip()
    if fecha_env:
        try:
            fecha = datetime.strptime(fecha_env, "%Y-%m-%d")
            fecha = fecha.replace(hour=12, minute=0, second=0, microsecond=0)
            print(f"📅 Usando fecha desde ONDEPOR_FECHA: {fecha.strftime('%d/%m/%Y')}")
            return fecha
        except ValueError:
            print(f"⚠️ ONDEPOR_FECHA inválida ('{fecha_env}'), usando mañana por defecto")
    
    # Default: mañana (en hora Argentina)
    return datetime.now(ARGENTINA_TZ).replace(tzinfo=None) + timedelta(days=1)


def get_momento_disparo():
    """
    Calcula el datetime EXACTO en hora Argentina en el que la reserva debe habilitarse.
    
    Usa ONDEPOR_HORA_OBJETIVO (HH:MM) y opcionalmente ONDEPOR_FECHA_OBJETIVO (YYYY-MM-DD).
    Si no hay hora objetivo, retorna None (= modo inmediato).
    """
    hora_env = os.environ.get("ONDEPOR_HORA_OBJETIVO", "").strip()
    if not hora_env:
        return None
    
    try:
        hora, minuto = hora_env.split(":")
        hora = int(hora)
        minuto = int(minuto)
    except (ValueError, IndexError):
        print(f"⚠️ ONDEPOR_HORA_OBJETIVO inválida ('{hora_env}'), modo inmediato")
        return None
    
    # Fecha del momento del disparo (no la fecha del turno)
    fecha_disparo_env = os.environ.get("ONDEPOR_FECHA_OBJETIVO", "").strip()
    if fecha_disparo_env:
        try:
            fecha_base = datetime.strptime(fecha_disparo_env, "%Y-%m-%d").date()
        except ValueError:
            print(f"⚠️ ONDEPOR_FECHA_OBJETIVO inválida, usando hoy")
            fecha_base = datetime.now(ARGENTINA_TZ).date()
    else:
        fecha_base = datetime.now(ARGENTINA_TZ).date()
    
    # Combinar fecha + hora en zona Argentina
    momento = datetime.combine(
        fecha_base,
        datetime.min.time().replace(hour=hora, minute=minuto)
    ).replace(tzinfo=ARGENTINA_TZ)
    
    return momento


def esperar_hasta(momento_target, etiqueta="momento objetivo"):
    """
    Helper genérico para dormir hasta un datetime específico (en zona ARG).
    Imprime progreso cada 60s mientras espera.
    """
    # Mensaje inicial flusheado para que se vea en los logs en vivo
    sys.stdout.flush()
    
    while True:
        ahora = datetime.now(ARGENTINA_TZ)
        if ahora >= momento_target:
            return
        
        restante = (momento_target - ahora).total_seconds()
        
        if restante > 65:
            # Dormir en chunks de 60s para poder loggear progreso
            time.sleep(60)
            nuevo = datetime.now(ARGENTINA_TZ)
            r2 = (momento_target - nuevo).total_seconds()
            if r2 > 0:
                print(f"   ⏳ {nuevo.strftime('%H:%M:%S')} — faltan {int(r2)}s ({r2/60:.1f} min) hasta {etiqueta}", flush=True)
        elif restante > 1:
            # Espera precisa para los últimos segundos
            time.sleep(restante - 0.5)
        else:
            # Espera final precisa
            time.sleep(max(0, restante))
            return


def imprimir_plan_programado(momento_disparo):
    """Imprime el plan de ejecución del modo programado."""
    momento_preload = momento_disparo - timedelta(minutes=PRELOAD_MINUTES_BEFORE)
    momento_busqueda = momento_disparo - timedelta(seconds=INICIO_BUSQUEDA_SEG_ANTES)
    momento_corte = momento_disparo + timedelta(minutes=END_MINUTES_AFTER)
    
    ahora = datetime.now(ARGENTINA_TZ)
    print(f"\n⏰ MODO PROGRAMADO ACTIVADO")
    print(f"   🕐 Hora actual (ARG):           {ahora.strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"   🎯 Hora objetivo (habilita):    {momento_disparo.strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"   📥 Pre-carga (login + nav):     {momento_preload.strftime('%H:%M:%S')}")
    print(f"   🔍 Empezar a buscar:            {momento_busqueda.strftime('%H:%M:%S')} ({INICIO_BUSQUEDA_SEG_ANTES}s antes)")
    print(f"   🛑 Cortar si no consigue:       {momento_corte.strftime('%H:%M:%S')}")


# =============================================================================
# FUNCIONES DE LOGIN
# =============================================================================

def login(page, config):
    """Realiza el login en OnDepor."""
    print("🔐 Iniciando sesión...")
    
    page.goto(config["url"], timeout=config["timeout_navegacion"])
    page.wait_for_load_state("networkidle")
    time.sleep(2)
    
    try:
        page.click('text="INICIAR SESIÓN"', timeout=5000)
        time.sleep(2)
        page.wait_for_load_state("networkidle")
    except:
        pass
    
    try:
        page.wait_for_selector('#loginform-email', timeout=10000)
    except:
        print("   ❌ No se encontró el formulario de login")
        return False
    
    try:
        page.fill('#loginform-email', config["usuario"])
        time.sleep(0.5)
        page.fill('#loginform-password', config["password"])
        time.sleep(0.5)
        page.click('#login')
    except Exception as e:
        print(f"   ⚠️ Error en formulario: {e}")
        return False
    
    page.wait_for_load_state("networkidle")
    time.sleep(3)
    
    if page.locator('text="CERRAR SESIÓN"').count() > 0 or page.locator('text="Amir Prync"').count() > 0:
        print("✅ Login exitoso")
        return True
    else:
        print("❌ Error en login - verificar credenciales")
        return False


# =============================================================================
# FUNCIONES DE NAVEGACIÓN
# =============================================================================

def ir_a_actividad(page, config):
    """Navega a la sección de la actividad configurada."""
    actividad = config["actividad"]
    print(f"\n📍 Navegando a {actividad}...")
    
    # Sniffer: capturar URLs de XHR que parezcan ser del calendario
    # (las guardamos para usarlas como refresh rápido durante la ventana crítica)
    global CALENDAR_XHR_URL, CALENDAR_XHR_HEADERS, CALENDAR_XHR_METHOD
    capturadas = []
    
    def on_request(request):
        url = request.url.lower()
        # Heurística: el endpoint del calendario probablemente contiene una de estas palabras
        if any(k in url for k in ["calendar", "schedule", "horario", "turno", "week", "day", "board"]):
            if request.method in ("GET", "POST"):
                capturadas.append({
                    "url": request.url,
                    "method": request.method,
                    "headers": request.headers,
                })
    
    page.on("request", on_request)
    
    page.goto(config["url_favoritos"], timeout=config["timeout_navegacion"])
    page.wait_for_load_state("networkidle")
    time.sleep(3)
    
    try:
        page.click('text="CLUBES"', timeout=3000)
        time.sleep(2)
        page.wait_for_load_state("networkidle")
    except:
        pass
    
    try:
        selectores = [
            f'h4:has-text("{actividad}")',
            f'div[id*="club_id"]:has-text("{actividad}")',
            f'div.open_calendar_board:has-text("{actividad}")',
            f'text="CISSAB | {actividad}"',
        ]
        
        encontrado = False
        for selector in selectores:
            try:
                elemento = page.locator(selector).first
                if elemento.is_visible():
                    elemento.click()
                    time.sleep(2)
                    page.wait_for_load_state("networkidle")
                    print(f"✅ En sección {actividad}")
                    encontrado = True
                    break
            except:
                continue
        
        # Quitar el listener
        page.remove_listener("request", on_request)
        
        if not encontrado:
            print(f"❌ No se encontró {actividad}")
            return False
        
        # Capturar la URL ACTUAL de la página: después de hacer click en DIURNO,
        # estamos en la página del calendario. Esa URL es la que usaremos para
        # los refreshes (en vez de page.reload() que vuelve a favoritos).
        global CALENDAR_PAGE_URL
        CALENDAR_PAGE_URL = page.url
        print(f"   📍 URL del calendario: {CALENDAR_PAGE_URL[:100]}", flush=True)
        
        # Analizar XHRs capturados — buscar el más probable
        if capturadas:
            print(f"   🔍 Detectados {len(capturadas)} XHR(s) del calendario")
            # Tomamos el último que coincida con calendar/board/horario (suele ser el correcto)
            for cap in reversed(capturadas):
                u = cap["url"].lower()
                if any(k in u for k in ["calendar", "board", "schedule"]):
                    CALENDAR_XHR_URL = cap["url"]
                    CALENDAR_XHR_METHOD = cap["method"]
                    CALENDAR_XHR_HEADERS = cap["headers"]
                    print(f"   ✅ XHR refresh: {CALENDAR_XHR_METHOD} {CALENDAR_XHR_URL[:80]}...")
                    break
            if CALENDAR_XHR_URL is None:
                print(f"   ⚠️ No se identificó XHR del calendario, usaremos goto normal")
        else:
            print(f"   ⚠️ No se capturaron XHRs, usaremos goto normal")
        
        return True
        
    except Exception as e:
        print(f"❌ Error navegando: {e}")
        try:
            page.remove_listener("request", on_request)
        except:
            pass
        return False


def _dia_correcto_visible(page, fecha_objetivo):
    """
    Verifica rápidamente si las celdas del día objetivo están presentes en el DOM.
    
    Mira si hay al menos una celda <td> cuyo data-id contenga un timestamp dentro
    del rango del día objetivo. Si la hay, no necesitamos re-navegar.
    """
    fecha_inicio_dia = fecha_objetivo.replace(hour=0, minute=0, second=0, microsecond=0)
    fecha_fin_dia = fecha_objetivo.replace(hour=23, minute=59, second=59, microsecond=0)
    timestamp_inicio = int(fecha_inicio_dia.timestamp())
    timestamp_fin = int(fecha_fin_dia.timestamp())
    
    try:
        # Tomar todas las celdas con data-id que tengan formato time-HH:MM-club-X-TIMESTAMP
        # y ver si alguna cae en el día objetivo
        celdas = page.locator('td[data-id*="time-"]').all()
        for celda in celdas[:30]:  # Limitamos para no gastar tiempo
            try:
                data_id = celda.get_attribute("data-id") or ""
                partes = data_id.split("-")
                if len(partes) < 5:
                    continue
                ts = int(partes[-1])
                if timestamp_inicio <= ts <= timestamp_fin:
                    return True
            except (ValueError, AttributeError):
                continue
        return False
    except Exception:
        # Si algo falla en la verificación, asumimos que sí (no queremos re-navegar al pedo)
        return True


def navegar_a_dia(page, dia_objetivo):
    """Navega en el calendario hasta el día objetivo."""
    print(f"\n📅 Navegando al día {dia_objetivo.strftime('%d/%m/%Y')}...", flush=True)
    
    # Optimización: si el día ya está visible, no hacemos nada
    if _dia_correcto_visible(page, dia_objetivo):
        print(f"   ✅ Día {dia_objetivo.day} ya visible en el calendario", flush=True)
        return True
    
    max_intentos = 10
    for intento in range(max_intentos):
        dia_num = dia_objetivo.day
        # Verificar si el día objetivo aparece en el DOM por timestamp
        if _dia_correcto_visible(page, dia_objetivo):
            print(f"   ✅ Día {dia_num} encontrado en el calendario", flush=True)
            return True
        
        try:
            page.click('xpath=//div[contains(@class,"calendar-month")]//following-sibling::*[contains(@class,"next")] | //a[contains(@class,"next")]', timeout=2000)
            time.sleep(1)
        except:
            try:
                page.click('[class*="next"], [class*="arrow-right"]', timeout=2000)
                time.sleep(1)
            except:
                break
    
    print(f"   ⚠️ No se pudo navegar al día {dia_num}", flush=True)
    return True


# =============================================================================
# FUNCIONES DE RESERVA
# =============================================================================

def buscar_horario_disponible(page, config, fecha_objetivo, verbose=False):
    """
    Busca un horario disponible PARA EL DÍA CORRECTO.
    Retorna (locator_celda, horario_str) o (None, None).
    
    Optimización: ejecuta UNA sola llamada JS que evalúa todas las celdas relevantes
    y devuelve un resumen (4-10x más rápido que hacer múltiples get_attribute desde Python).
    """
    fecha_inicio_dia = fecha_objetivo.replace(hour=0, minute=0, second=0, microsecond=0)
    fecha_fin_dia = fecha_objetivo.replace(hour=23, minute=59, second=59, microsecond=0)
    timestamp_inicio = int(fecha_inicio_dia.timestamp())
    timestamp_fin = int(fecha_fin_dia.timestamp())
    
    horarios = config["horarios_preferidos"]
    
    # Una sola llamada JS para evaluar todas las celdas relevantes
    js = """
    (args) => {
        const [horarios, tsIni, tsFin] = args;
        const result = [];
        let totalCeldasEnDia = 0;
        for (const h of horarios) {
            const celdas = document.querySelectorAll(`td[data-id*="time-${h}"]`);
            for (const c of celdas) {
                const dataId = c.getAttribute('data-id') || '';
                const partes = dataId.split('-');
                if (partes.length < 5) continue;
                const ts = parseInt(partes[partes.length - 1]);
                if (isNaN(ts) || ts < tsIni || ts > tsFin) continue;
                totalCeldasEnDia++;
                const clase = c.className || '';
                const texto = (c.innerText || '').trim();
                const disabled = clase.includes('disabled');
                const libre = !disabled && (texto.toLowerCase().includes('libres') || /^\\d+$/.test(texto));
                result.push({ horario: h, dataId, disabled, libre, texto });
            }
        }
        return { celdas: result, totalCeldasEnDia };
    }
    """
    
    try:
        evaluacion = page.evaluate(js, [horarios, timestamp_inicio, timestamp_fin])
    except Exception as e:
        if verbose:
            print(f"   ⚠️ Error evaluando DOM: {e}", flush=True)
        return None, None
    
    celdas_info = evaluacion.get("celdas", [])
    total = evaluacion.get("totalCeldasEnDia", 0)
    
    # Reportar estado si verbose o si no encontramos NADA del día
    if verbose:
        if total == 0:
            print(f"   ❓ Sin celdas del día {fecha_objetivo.strftime('%d/%m/%Y')} en el DOM (calendario no cargado?)", flush=True)
        else:
            for c in celdas_info:
                if c['libre']:
                    estado = "🔓 LIBRE"
                elif c['disabled']:
                    estado = "🔒 disabled"
                else:
                    estado = f"❌ sin lugares ('{c['texto'][:25]}')"
                print(f"   [{c['horario']}] {estado}", flush=True)
    
    # Buscar primera celda libre (en orden de prioridad)
    for c in celdas_info:
        if c['libre']:
            print(f"   ✅ ¡LIBRE DETECTADA! {c['horario']}", flush=True)
            locator = page.locator(f'td[data-id="{c["dataId"]}"]').first
            return locator, c['horario']
    
    return None, None


def refrescar_calendario_rapido(page, config, fecha_objetivo):
    """
    Refresco AGRESIVO usado en la ventana crítica.
    
    Estrategia:
    1. Si tenemos URL del calendario capturada (CALENDAR_PAGE_URL), hacer page.goto()
       a esa URL directamente. Esto evita el bug de page.reload() que vuelve
       a la página de favoritos en lugar de mantenerse en el calendario.
    2. Si no, fallback a reload (probablemente roto, pero peor es nada).
    """
    global CALENDAR_PAGE_URL
    
    if CALENDAR_PAGE_URL:
        try:
            # goto a la URL del calendario directamente. Más rápido que reload
            # porque no espera networkidle, solo el load básico.
            page.goto(CALENDAR_PAGE_URL, wait_until="load", timeout=8000)
            return True
        except Exception:
            return False
    
    # Fallback: reload (probablemente no funciona bien)
    try:
        page.reload(wait_until="load", timeout=8000)
        return True
    except Exception:
        return False


def refrescar_calendario(page, config):
    """Refresco normal usado fuera de ventana crítica. Usa goto si tenemos URL."""
    global CALENDAR_PAGE_URL
    
    if CALENDAR_PAGE_URL:
        try:
            page.goto(CALENDAR_PAGE_URL, wait_until="networkidle", timeout=15000)
            return True
        except:
            return False
    
    # Fallback
    try:
        page.reload(wait_until="networkidle", timeout=15000)
        return True
    except:
        return False


def seleccionar_cancha_preferida(page, config):
    """Selecciona la cancha preferida (KINERET si está disponible)."""
    print("   🎾 Seleccionando cancha...")
    
    try:
        selector = page.locator('#reservationform-court_id')
        opciones = selector.locator('option').all()
        
        for cancha_pref in config["canchas_preferidas"]:
            for opcion in opciones:
                texto = opcion.inner_text().upper()
                if cancha_pref.upper() in texto:
                    valor = opcion.get_attribute("value")
                    selector.select_option(valor)
                    print(f"   ✅ Cancha seleccionada: {opcion.inner_text()}")
                    return True
        
        if len(opciones) > 0:
            primera = opciones[0]
            valor = primera.get_attribute("value")
            if valor:
                selector.select_option(valor)
                print(f"   ✅ Cancha seleccionada: {primera.inner_text()} (alternativa)")
                return True
                
    except Exception as e:
        print(f"   ⚠️ Error seleccionando cancha: {e}")
    
    return False


def agregar_socios(page, config):
    """Agrega los socios a la reserva."""
    print("   👥 Agregando socios...")
    
    input_socios = page.locator('#reservationform-name')
    
    for socio in config["socios"]:
        try:
            print(f"      Agregando: {socio}")
            input_socios.fill("")
            time.sleep(0.3)
            input_socios.type(socio, delay=50)
            time.sleep(1)
            
            try:
                sugerencia = page.locator(f'.tt-suggestion:has-text("{socio}"), .tt-menu div:has-text("{socio}")').first
                sugerencia.click()
                time.sleep(0.3)
                print(f"      ✅ {socio} agregado")
            except:
                input_socios.press("Enter")
                time.sleep(0.3)
                
        except Exception as e:
            print(f"      ⚠️ Error agregando {socio}: {e}")
    
    return True


def aceptar_terminos(page):
    """Marca el checkbox de términos y condiciones."""
    print("   ✓ Aceptando términos...")
    
    try:
        checkbox = page.locator('#reservationform-terms_and_cond')
        if not checkbox.is_checked():
            checkbox.click()
            time.sleep(0.3)
        print("   ✅ Términos aceptados")
        return True
    except Exception as e:
        print(f"   ⚠️ Error con checkbox: {e}")
        return False


def verificar_errores(page):
    """Verifica si hay mensajes de error en el modal."""
    errores = page.locator('.alert-danger, .alert-warning, [class*="error"], [style*="background"][style*="rgb(23"]').all()
    
    for error in errores:
        try:
            if error.is_visible():
                texto = error.inner_text()
                if texto and len(texto) > 5:
                    print(f"   ⚠️ ERROR DETECTADO: {texto[:100]}")
                    return False
        except:
            continue
    
    if page.locator('text=/máximo de reservas/i').count() > 0:
        print("   ⚠️ ERROR: Uno de los socios tiene el máximo de reservas permitidas")
        return False
    
    return True


def confirmar_reserva(page, dry_run=False):
    """Hace click en el botón Reservar."""
    print("   💾 Confirmando reserva...")
    
    if dry_run:
        print("   [DRY RUN] Simulando click en RESERVAR")
        return True
    
    if not verificar_errores(page):
        print("   ❌ No se puede confirmar, hay errores en el formulario")
        return False
    
    try:
        page.click('#btn_submit', timeout=5000)
        time.sleep(3)
        page.wait_for_load_state("networkidle")
        time.sleep(2)
        
        if page.locator('text=/reserva fue realizada/i').count() > 0:
            print("   ✅ Reserva confirmada exitosamente")
            try:
                page.click('text="CERRAR"', timeout=3000)
            except:
                pass
            return True
        else:
            if page.locator('text=/máximo de reservas/i').count() > 0:
                print("   ❌ Error: máximo de reservas alcanzado")
                return False
            print("   ⚠️ No se pudo verificar la confirmación")
            return False
            
    except Exception as e:
        print(f"   ⚠️ Error al confirmar: {e}")
        return False


def cerrar_modal(page):
    """Cierra el modal de reserva si está abierto."""
    try:
        page.click('button[data-dismiss="modal"], .close, text="CERRAR"', timeout=2000)
        time.sleep(1)
    except:
        try:
            page.keyboard.press("Escape")
            time.sleep(1)
        except:
            pass


def realizar_reserva(page, config, celda_horario, horario, dry_run=False):
    """Realiza todo el proceso de reserva."""
    print(f"\n{'='*50}")
    print(f"🎾 Reservando horario {horario}")
    print(f"{'='*50}")
    
    try:
        celda_horario.click()
        time.sleep(2)
        
        page.wait_for_selector('#popupModal.show, #popupModal[style*="display: block"]', timeout=5000)
        time.sleep(1)
        
        seleccionar_cancha_preferida(page, config)
        time.sleep(config["delay_entre_acciones"] / 1000)
        
        agregar_socios(page, config)
        time.sleep(config["delay_entre_acciones"] / 1000)
        
        aceptar_terminos(page)
        time.sleep(config["delay_entre_acciones"] / 1000)
        
        if confirmar_reserva(page, dry_run):
            return True
        else:
            return False
            
    except Exception as e:
        print(f"❌ Error en reserva: {e}")
        return False


# =============================================================================
# SISTEMA DE REINTENTOS
# =============================================================================

def intentar_reserva_con_reintentos(page, config, fecha_objetivo, momento_disparo, dry_run=False):
    """
    Intenta hacer la reserva con polling adaptativo.
    
    Modo programado:
        - Refresca rápido (cada RETRY_INTERVAL_RAPIDO seg) durante la ventana crítica:
          desde t-INICIO_BUSQUEDA_SEG_ANTES hasta t+VENTANA_CRITICA_DESPUES_SEG
        - Refresca normal (cada RETRY_INTERVAL_NORMAL seg) después
        - Corta a t+END_MINUTES_AFTER
    
    Modo inmediato:
        - Refresca siempre con intervalo normal hasta MAX_RETRY_MINUTES_INMEDIATO
    """
    
    if momento_disparo is not None:
        # Modo programado
        momento_disparo_naive = momento_disparo.astimezone(ARGENTINA_TZ).replace(tzinfo=None)
        ventana_critica_fin = momento_disparo_naive + timedelta(seconds=VENTANA_CRITICA_DESPUES_SEG)
        tiempo_maximo = momento_disparo_naive + timedelta(minutes=END_MINUTES_AFTER)
        
        def ahora_ref():
            return datetime.now(ARGENTINA_TZ).replace(tzinfo=None)
        
        modo = "PROGRAMADO"
    else:
        # Modo inmediato
        tiempo_maximo = datetime.now() + timedelta(minutes=MAX_RETRY_MINUTES_INMEDIATO)
        ventana_critica_fin = None
        momento_disparo_naive = None
        
        def ahora_ref():
            return datetime.now()
        
        modo = "INMEDIATO"
    
    intento = 0
    en_ventana_critica = False
    ultimo_log = datetime.min
    
    print(f"\n🔄 BÚSQUEDA DE RESERVA ACTIVADA ({modo})")
    if momento_disparo is not None:
        print(f"   🎯 Hora objetivo: {momento_disparo_naive.strftime('%H:%M:%S')}")
        print(f"   ⚡ Ventana crítica (polling cada {RETRY_INTERVAL_RAPIDO}s): hasta {ventana_critica_fin.strftime('%H:%M:%S')}")
        print(f"   🐢 Después polling cada {RETRY_INTERVAL_NORMAL}s")
        print(f"   🛑 Cortar a las: {tiempo_maximo.strftime('%H:%M:%S')}")
    else:
        print(f"   ⏱️ Timeout máximo: {MAX_RETRY_MINUTES_INMEDIATO} minutos")
    print(f"   🎯 Horarios buscados: {config['horarios_preferidos']}")
    print("="*50)
    
    while ahora_ref() < tiempo_maximo:
        intento += 1
        ahora = ahora_ref()
        
        # ¿Estamos en ventana crítica?
        if momento_disparo is not None and ahora <= ventana_critica_fin:
            estaba_en_critica = en_ventana_critica
            en_ventana_critica = True
            if not estaba_en_critica:
                print(f"\n⚡⚡⚡ VENTANA CRÍTICA — refrescando cada {RETRY_INTERVAL_RAPIDO}s ⚡⚡⚡")
        else:
            if en_ventana_critica:
                print(f"\n📉 Saliendo de ventana crítica → polling normal")
            en_ventana_critica = False
        
        intervalo = RETRY_INTERVAL_RAPIDO if en_ventana_critica else RETRY_INTERVAL_NORMAL
        
        # Loggear cada intento en modo programado (con polling de 0.8s no es tanto spam)
        # En modo inmediato cada cierto tiempo
        if momento_disparo is not None:
            debe_loggear = True  # Siempre loggear en modo programado
        else:
            debe_loggear = (ahora - ultimo_log).total_seconds() >= 3
        
        if debe_loggear:
            restante = int((tiempo_maximo - ahora).total_seconds())
            etiqueta = "⚡" if en_ventana_critica else "🔄"
            print(f"[{ahora.strftime('%H:%M:%S')}] {etiqueta} Intento #{intento} (corta en {restante}s)", flush=True)
            ultimo_log = ahora
        
        # Buscar horario libre
        # Verbose siempre activo en modo programado para tener trazabilidad si falla
        verbose = debe_loggear if momento_disparo is None else True
        celda, horario = buscar_horario_disponible(page, config, fecha_objetivo, verbose=verbose)
        
        if celda is not None:
            print(f"\n🎯 ¡HORARIO DETECTADO! {horario} en intento #{intento} ({ahora.strftime('%H:%M:%S')})", flush=True)
            if realizar_reserva(page, config, celda, horario, dry_run):
                return True
            else:
                print("   ⚠️ Falló la reserva (probablemente alguien la tomó), reintentando...", flush=True)
                cerrar_modal(page)
                # Después de un fallo, refresco completo
                refrescar_calendario(page, config)
        
        if ahora_ref() >= tiempo_maximo:
            break
        
        # Esperar y refrescar
        time.sleep(intervalo)
        
        # Refresh: usa goto a la URL del calendario (NO reload)
        if en_ventana_critica:
            refrescar_calendario_rapido(page, config, fecha_objetivo)
        else:
            refrescar_calendario(page, config)
        
        # Verificación post-refresh: ¿el calendario sigue mostrando el día objetivo?
        # Si por alguna razón se rompió, intentar re-entrar a la actividad completa.
        if not _dia_correcto_visible(page, fecha_objetivo):
            # Solo loggeamos cada 5 intentos para no spamear si está roto
            if intento % 5 == 0:
                print(f"   ⚠️ Calendario perdió el día (intento #{intento}), re-entrando a la actividad...", flush=True)
            # Re-entrar al calendario completo (no solo navegar al día)
            try:
                ir_a_actividad(page, config)
                navegar_a_dia(page, fecha_objetivo)
            except Exception as e:
                if intento % 5 == 0:
                    print(f"   ❌ Error re-entrando: {e}", flush=True)
    
    print(f"\n❌ TIMEOUT: ventana de intentos agotada ({tiempo_maximo.strftime('%H:%M:%S')})", flush=True)
    print(f"   Total de intentos: {intento}", flush=True)
    return False


# =============================================================================
# FUNCIÓN PRINCIPAL
# =============================================================================

def ejecutar_bot(visible=False, dry_run=False):
    """
    Función principal del bot.
    
    Modo PROGRAMADO (con ONDEPOR_HORA_OBJETIVO):
        FASE 1 — Espera inicial: dormir hasta t - PRELOAD_MINUTES_BEFORE
        FASE 2 — Pre-carga: levantar browser, login, navegar al día.
                 (si esto termina antes de t-INICIO_BUSQUEDA_SEG_ANTES, esperamos)
        FASE 3 — Búsqueda: empezar polling rápido a t-INICIO_BUSQUEDA_SEG_ANTES,
                 hasta encontrar la celda libre o llegar a t+END_MINUTES_AFTER.
    
    Modo INMEDIATO (sin hora objetivo):
        Levanta browser y empieza a buscar inmediatamente.
    """
    config = get_config()
    fecha_objetivo = get_fecha_objetivo()
    momento_disparo = get_momento_disparo()
    
    print("\n" + "="*60)
    print("🎾 ONDEPOR - BOT DE RESERVA DE PÁDEL")
    print("="*60)
    ahora_arg = datetime.now(ARGENTINA_TZ)
    print(f"📅 Hora ejecución (ARG): {ahora_arg.strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"👤 Usuario: {config['usuario']}")
    print(f"🎯 Actividad: {config['actividad']}")
    print(f"📆 Día a reservar: {fecha_objetivo.strftime('%A %d/%m/%Y')}")
    print(f"⏰ Horarios preferidos: {config['horarios_preferidos']}")
    print(f"👥 Socios: {', '.join(config['socios'])}")
    
    if momento_disparo is not None:
        imprimir_plan_programado(momento_disparo)
    else:
        print(f"⚡ MODO INMEDIATO: arranca ya")
    
    if dry_run:
        print("⚠️  MODO DRY-RUN: No se harán reservas reales")
    print("="*60)
    
    # =========================================================================
    # FASE 1 (solo modo programado): ESPERA INICIAL
    # Dormimos hasta PRELOAD_MINUTES_BEFORE antes de la hora objetivo.
    # Hacemos esto SIN browser para no consumir RAM/CPU al pedo.
    # =========================================================================
    if momento_disparo is not None:
        # Validar que no estemos demasiado tarde
        ahora = datetime.now(ARGENTINA_TZ)
        limite = momento_disparo + timedelta(minutes=END_MINUTES_AFTER)
        if ahora >= limite:
            print(f"\n❌ Ya pasó la ventana objetivo (límite {limite.strftime('%H:%M:%S')}). Abortando.")
            sys.exit(1)
        
        momento_preload = momento_disparo - timedelta(minutes=PRELOAD_MINUTES_BEFORE)
        ahora_naive = ahora.replace(tzinfo=None)
        preload_naive = momento_preload.replace(tzinfo=None)
        
        if ahora_naive < preload_naive:
            delta = (preload_naive - ahora_naive).total_seconds()
            print(f"\n💤 FASE 1: Esperando {int(delta)}s ({delta/60:.1f} min) hasta el momento de pre-carga ({momento_preload.strftime('%H:%M:%S')})")
            print(f"   📌 El runner queda esperando, no apagar.")
            esperar_hasta(momento_preload, "pre-carga")
            print(f"\n   ✅ Hora pre-carga alcanzada: {datetime.now(ARGENTINA_TZ).strftime('%H:%M:%S')}")
        else:
            print(f"\n⚡ Ya estamos dentro o pasamos el momento de pre-carga, vamos directo")
    
    # =========================================================================
    # FASE 2: LEVANTAR BROWSER + LOGIN + NAVEGACIÓN AL DÍA
    # =========================================================================
    with sync_playwright() as p:
        browser = p.chromium.launch(
            headless=not visible,
            slow_mo=300 if visible else 0
        )
        
        context = browser.new_context(
            viewport={"width": 1280, "height": 800},
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
        )
        
        page = context.new_page()
        page.set_default_timeout(config["timeout_elemento"])
        
        try:
            print(f"\n📥 FASE 2: Pre-carga (login + navegación)")
            
            if not login(page, config):
                print("\n❌ Login fallido. Abortando.")
                sys.exit(1)
            
            if not ir_a_actividad(page, config):
                print(f"\n❌ No se pudo acceder a {config['actividad']}. Abortando.")
                sys.exit(1)
            
            navegar_a_dia(page, fecha_objetivo)
            
            print(f"\n   ✅ Pre-carga lista a las {datetime.now(ARGENTINA_TZ).strftime('%H:%M:%S')}")
            
            # =================================================================
            # FASE 3a (solo modo programado): ESPERAR hasta t - INICIO_BUSQUEDA_SEG_ANTES
            # Si la pre-carga terminó muy rápido y estamos lejos de la hora objetivo,
            # esperamos sin hacer nada para no fatigar al servidor del club.
            # =================================================================
            if momento_disparo is not None:
                momento_busqueda = momento_disparo - timedelta(seconds=INICIO_BUSQUEDA_SEG_ANTES)
                ahora_naive = datetime.now(ARGENTINA_TZ).replace(tzinfo=None)
                busqueda_naive = momento_busqueda.replace(tzinfo=None)
                
                if ahora_naive < busqueda_naive:
                    delta = (busqueda_naive - ahora_naive).total_seconds()
                    print(f"\n⏸️ FASE 3a: Esperando {int(delta)}s hasta empezar a buscar ({momento_busqueda.strftime('%H:%M:%S')})")
                    esperar_hasta(momento_busqueda, "inicio de búsqueda")
                    print(f"\n   ✅ Empezando búsqueda agresiva: {datetime.now(ARGENTINA_TZ).strftime('%H:%M:%S')}")
                else:
                    print(f"\n⚡ Ya pasamos el momento de inicio de búsqueda, vamos directo")
            
            # =================================================================
            # FASE 3b: BÚSQUEDA AGRESIVA
            # =================================================================
            print(f"\n🔍 FASE 3b: Búsqueda y reintentos")
            if intentar_reserva_con_reintentos(page, config, fecha_objetivo, momento_disparo, dry_run):
                print("\n" + "="*60)
                print("✅ RESERVA COMPLETADA EXITOSAMENTE")
                print("="*60)
            else:
                print("\n" + "="*60)
                print("❌ NO SE PUDO COMPLETAR LA RESERVA")
                print("="*60)
                sys.exit(1)
                
        except Exception as e:
            print(f"\n❌ Error general: {e}")
            sys.exit(1)
        finally:
            browser.close()


# =============================================================================
# PUNTO DE ENTRADA
# =============================================================================

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="OnDepor - Bot de Reserva de Pádel")
    parser.add_argument("--visible", action="store_true", help="Mostrar navegador")
    parser.add_argument("--dry-run", action="store_true", help="Simular sin reservar")
    
    args = parser.parse_args()
    ejecutar_bot(visible=args.visible, dry_run=args.dry_run)
