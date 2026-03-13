"""
OnDepor - Bot de Reserva Automática de Canchas de Pádel
=======================================================
Automatiza la reserva de canchas en CISSAB a través de ondepor.com

SISTEMA DE REINTENTOS:
- El bot arranca 2 minutos antes de que se habilite la reserva
- Intenta cada 5 segundos hasta conseguir la reserva
- Timeout máximo de 10 minutos

Variables de entorno requeridas:
    ONDEPOR_USER: Email de login
    ONDEPOR_PASS: Contraseña
    ONDEPOR_SOCIOS: (opcional) Lista de socios separados por coma

Uso:
    python ondepor_bot.py
    python ondepor_bot.py --visible    # Ver navegador
    python ondepor_bot.py --dry-run    # Simular sin reservar
"""

import argparse
import os
import sys
import time
from datetime import datetime, timedelta
from playwright.sync_api import sync_playwright, TimeoutError as PlaywrightTimeout


# =============================================================================
# CONFIGURACIÓN
# =============================================================================

# Configuración del sistema de reintentos
RETRY_INTERVAL_SECONDS = 3      # Intentar cada 3 segundos (más agresivo)
MAX_RETRY_MINUTES = 15          # Máximo 15 minutos de intentos
START_MINUTES_BEFORE = 5        # Arrancar 5 minutos antes


def get_config():
    """Obtiene configuración desde variables de entorno."""
    usuario = os.environ.get("ONDEPOR_USER")
    password = os.environ.get("ONDEPOR_PASS")
    
    if not usuario or not password:
        print("❌ Error: Variables de entorno no configuradas")
        print("   Configurar ONDEPOR_USER y ONDEPOR_PASS")
        sys.exit(1)
    
    # Los socios se pueden configurar desde variable de entorno
    # Formato: "Alan Garbo,Gabriel Topor,Damian Potap"
    socios_env = os.environ.get("ONDEPOR_SOCIOS", "")
    if socios_env:
        socios = [s.strip() for s in socios_env.split(",")]
    else:
        # Socios por defecto
        socios = [
            "Alan Garbo",
            "Gabriel Topor",
            "Damian Potap"
        ]
    
    return {
        "url": "https://www.ondepor.com/",
        "url_login": "https://www.ondepor.com/site/login",
        "url_favoritos": "https://www.ondepor.com/user/_favorites",
        "usuario": usuario,
        "password": password,
        
        # Preferencias de reserva
        "actividad": "PÁDEL DIURNO",  # o "PÁDEL NOCTURNO"
        "horarios_preferidos": ["10:00", "11:00"],  # En orden de prioridad
        
        # Canchas preferidas (en orden de prioridad)
        # Las KINERET son las canchas 05-08
        "canchas_preferidas": ["KINERET", "05-", "06-", "07-", "08-"],
        
        # Socios a agregar (configurable via ONDEPOR_SOCIOS)
        "socios": socios,
        
        # Timeouts
        "timeout_navegacion": 30000,
        "timeout_elemento": 10000,
        "delay_entre_acciones": 1000,  # Reducido para ser más rápido
    }


# =============================================================================
# FUNCIONES DE LOGIN
# =============================================================================

def login(page, config):
    """Realiza el login en OnDepor."""
    print("🔐 Iniciando sesión...")
    
    # Ir a la página principal
    page.goto(config["url"], timeout=config["timeout_navegacion"])
    page.wait_for_load_state("networkidle")
    time.sleep(2)
    
    # Click en "Iniciar Sesión"
    try:
        page.click('text="INICIAR SESIÓN"', timeout=5000)
        time.sleep(2)
        page.wait_for_load_state("networkidle")
    except:
        pass
    
    # Esperar a que aparezca el formulario de login
    try:
        page.wait_for_selector('#loginform-email', timeout=10000)
    except:
        print("   ❌ No se encontró el formulario de login")
        return False
    
    # Completar credenciales con los IDs correctos
    try:
        # Campo email
        page.fill('#loginform-email', config["usuario"])
        time.sleep(0.5)
        
        # Campo contraseña
        page.fill('#loginform-password', config["password"])
        time.sleep(0.5)
        
        # Click en INGRESAR
        page.click('#login')
        
    except Exception as e:
        print(f"   ⚠️ Error en formulario: {e}")
        return False
    
    # Esperar a que cargue
    page.wait_for_load_state("networkidle")
    time.sleep(3)
    
    # Verificar login exitoso
    if page.locator('text="CERRAR SESIÓN"').count() > 0 or page.locator('text="Amir Prync"').count() > 0:
        print("✅ Login exitoso")
        return True
    else:
        print("❌ Error en login - verificar credenciales")
        return False


# =============================================================================
# FUNCIONES DE NAVEGACIÓN
# =============================================================================

def ir_a_padel_diurno(page, config):
    """Navega a la sección de PÁDEL DIURNO."""
    print("\n📍 Navegando a PÁDEL DIURNO...")
    
    # Ir a favoritos/clubes
    page.goto(config["url_favoritos"], timeout=config["timeout_navegacion"])
    page.wait_for_load_state("networkidle")
    time.sleep(3)
    
    # Click en CLUBES si es necesario
    try:
        page.click('text="CLUBES"', timeout=3000)
        time.sleep(2)
        page.wait_for_load_state("networkidle")
    except:
        pass
    
    # Buscar y clickear en PÁDEL DIURNO
    try:
        selectores = [
            'h4:has-text("PÁDEL DIURNO")',
            'div[id*="club_id"]:has-text("PÁDEL DIURNO")',
            'div.open_calendar_board:has-text("PÁDEL DIURNO")',
            'text="CISSAB | PÁDEL DIURNO"',
        ]
        
        for selector in selectores:
            try:
                elemento = page.locator(selector).first
                if elemento.is_visible():
                    elemento.click()
                    time.sleep(2)
                    page.wait_for_load_state("networkidle")
                    print("✅ En sección PÁDEL DIURNO")
                    return True
            except:
                continue
        
        print("❌ No se encontró PÁDEL DIURNO")
        return False
        
    except Exception as e:
        print(f"❌ Error navegando: {e}")
        return False


def navegar_a_dia(page, dia_objetivo):
    """Navega en el calendario hasta el día objetivo."""
    print(f"\n📅 Navegando al día {dia_objetivo.strftime('%d/%m/%Y')}...")
    
    max_intentos = 10
    for intento in range(max_intentos):
        dia_num = dia_objetivo.day
        celdas_dia = page.locator(f'td:has-text("{dia_num}")').all()
        
        for celda in celdas_dia:
            texto = celda.inner_text()
            if str(dia_num) in texto:
                print(f"   ✅ Día {dia_num} encontrado en el calendario")
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
    
    print(f"   ⚠️ No se pudo navegar al día {dia_num}")
    return True


# =============================================================================
# FUNCIONES DE RESERVA
# =============================================================================

def buscar_horario_disponible(page, config, fecha_objetivo):
    """Busca un horario disponible según las preferencias PARA EL DÍA CORRECTO."""
    
    # Calcular el timestamp Unix para el día objetivo (a las 00:00)
    # El timestamp en el data-id representa la fecha/hora del turno
    fecha_inicio_dia = fecha_objetivo.replace(hour=0, minute=0, second=0, microsecond=0)
    fecha_fin_dia = fecha_objetivo.replace(hour=23, minute=59, second=59, microsecond=0)
    
    timestamp_inicio = int(fecha_inicio_dia.timestamp())
    timestamp_fin = int(fecha_fin_dia.timestamp())
    
    print(f"   📅 Buscando para fecha: {fecha_objetivo.strftime('%d/%m/%Y')}")
    print(f"   🔢 Rango timestamps: {timestamp_inicio} - {timestamp_fin}")
    
    for horario in config["horarios_preferidos"]:
        print(f"   Buscando horario {horario}...")
        selector = f'td[data-id*="time-{horario}"]:not(.disabled)'
        celdas = page.locator(selector).all()
        
        for celda in celdas:
            try:
                texto = celda.inner_text()
                clase = celda.get_attribute("class") or ""
                data_id = celda.get_attribute("data-id") or ""
                
                if "disabled" in clase:
                    continue
                
                # Extraer el timestamp del data-id
                # Formato: time-HH:MM-club-CLUBID-TIMESTAMP
                partes = data_id.split("-")
                if len(partes) >= 5:
                    try:
                        timestamp_celda = int(partes[-1])
                        
                        # Verificar si el timestamp corresponde al día objetivo
                        if timestamp_inicio <= timestamp_celda <= timestamp_fin:
                            if "libres" in texto.lower() or texto.strip().isdigit():
                                print(f"   ✅ Encontrado: {horario} (timestamp: {timestamp_celda})")
                                return celda, horario
                        else:
                            # Es de otro día, ignorar
                            continue
                    except ValueError:
                        continue
                    
            except Exception as e:
                continue
    
    return None, None


def refrescar_calendario(page, config):
    """Refresca el calendario para ver nuevos horarios disponibles."""
    try:
        # Refrescar la página actual
        page.reload()
        page.wait_for_load_state("networkidle")
        time.sleep(1)
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
            input_socios.type(socio, delay=50)  # Más rápido
            
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
        # Intentar cerrar con el botón X o CERRAR
        page.click('button[data-dismiss="modal"], .close, text="CERRAR"', timeout=2000)
        time.sleep(1)
    except:
        try:
            # Presionar Escape
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

def intentar_reserva_con_reintentos(page, config, fecha_objetivo, dry_run=False):
    """
    Intenta hacer la reserva con reintentos.
    
    El sistema:
    1. Busca horarios disponibles
    2. Si no hay, espera RETRY_INTERVAL_SECONDS y refresca
    3. Repite hasta conseguir o timeout
    """
    
    tiempo_inicio = datetime.now()
    tiempo_maximo = tiempo_inicio + timedelta(minutes=MAX_RETRY_MINUTES)
    intento = 0
    
    print(f"\n🔄 SISTEMA DE REINTENTOS ACTIVADO")
    print(f"   ⏰ Intervalo entre intentos: {RETRY_INTERVAL_SECONDS} segundos")
    print(f"   ⏱️ Timeout máximo: {MAX_RETRY_MINUTES} minutos")
    print(f"   🎯 Horarios buscados: {config['horarios_preferidos']}")
    print("="*50)
    
    while datetime.now() < tiempo_maximo:
        intento += 1
        ahora = datetime.now()
        tiempo_transcurrido = (ahora - tiempo_inicio).seconds
        
        print(f"\n🔄 Intento #{intento} [{ahora.strftime('%H:%M:%S')}] (transcurrido: {tiempo_transcurrido}s)")
        
        # Buscar horario disponible
        print("   🔍 Buscando horarios disponibles...")
        celda, horario = buscar_horario_disponible(page, config, fecha_objetivo)
        
        if celda is not None:
            print(f"   ✅ ¡HORARIO ENCONTRADO! {horario}")
            
            # Intentar hacer la reserva
            if realizar_reserva(page, config, celda, horario, dry_run):
                return True
            else:
                print("   ⚠️ Falló la reserva, reintentando...")
                cerrar_modal(page)
        else:
            print(f"   ⏳ No hay horarios disponibles aún...")
        
        # Esperar antes del siguiente intento
        print(f"   ⏰ Esperando {RETRY_INTERVAL_SECONDS} segundos...")
        time.sleep(RETRY_INTERVAL_SECONDS)
        
        # Refrescar el calendario
        print("   🔄 Refrescando calendario...")
        refrescar_calendario(page, config)
        
        # Re-navegar al día si es necesario
        navegar_a_dia(page, fecha_objetivo)
    
    print(f"\n❌ TIMEOUT: Se agotaron los {MAX_RETRY_MINUTES} minutos de intentos")
    return False


# =============================================================================
# FUNCIÓN PRINCIPAL
# =============================================================================

def ejecutar_bot(visible=False, dry_run=False):
    """Función principal del bot."""
    config = get_config()
    
    print("\n" + "="*60)
    print("🎾 ONDEPOR - BOT DE RESERVA DE PÁDEL")
    print("="*60)
    print(f"📅 Fecha ejecución: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"👤 Usuario: {config['usuario']}")
    print(f"🎯 Actividad: {config['actividad']}")
    print(f"⏰ Horarios preferidos: {config['horarios_preferidos']}")
    print(f"👥 Socios: {', '.join(config['socios'])}")
    print(f"🔄 Sistema de reintentos: Cada {RETRY_INTERVAL_SECONDS}s por {MAX_RETRY_MINUTES} min")
    if dry_run:
        print("⚠️  MODO DRY-RUN: No se harán reservas reales")
    print("="*60)
    
    # Calcular fecha objetivo (mañana, ya que el bot corre 24hs antes)
    fecha_objetivo = datetime.now() + timedelta(days=1)
    print(f"\n📆 Fecha a reservar: {fecha_objetivo.strftime('%A %d/%m/%Y')}")
    
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
            # Login
            if not login(page, config):
                print("\n❌ Login fallido. Abortando.")
                sys.exit(1)
            
            # Navegar a PÁDEL DIURNO
            if not ir_a_padel_diurno(page, config):
                print("\n❌ No se pudo acceder a PÁDEL DIURNO. Abortando.")
                sys.exit(1)
            
            # Navegar al día objetivo
            navegar_a_dia(page, fecha_objetivo)
            
            # Intentar reserva con reintentos
            if intentar_reserva_con_reintentos(page, config, fecha_objetivo, dry_run):
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
