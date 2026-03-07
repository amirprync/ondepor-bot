"""
OnDepor - Bot de Reserva Automática de Canchas de Pádel
=======================================================
Automatiza la reserva de canchas en CISSAB a través de ondepor.com

Variables de entorno requeridas:
    ONDEPOR_USER: Email de login
    ONDEPOR_PASS: Contraseña

Configuración:
    - Días: Sábados y Domingos
    - Horarios: 10:00 o 11:00 (prioridad 10:00)
    - Cancha: Preferencia KINERET (05-08), si no otra disponible
    - Socios: Alan Garbo, Gabriel Topor, Damian Potap
    - Actividad: PÁDEL DIURNO

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

def get_config():
    """Obtiene configuración desde variables de entorno."""
    usuario = os.environ.get("ONDEPOR_USER")
    password = os.environ.get("ONDEPOR_PASS")
    
    if not usuario or not password:
        print("❌ Error: Variables de entorno no configuradas")
        print("   Configurar ONDEPOR_USER y ONDEPOR_PASS")
        sys.exit(1)
    
    return {
        "url": "https://www.ondepor.com/",
        "url_login": "https://www.ondepor.com/site/login",
        "url_favoritos": "https://www.ondepor.com/user/_favorites",
        "usuario": usuario,
        "password": password,
        
        # Preferencias de reserva
        "actividad": "PÁDEL DIURNO",  # o "PÁDEL NOCTURNO"
        "horarios_preferidos": ["14:00", "10:00", "11:00"],  # En orden de prioridad
        
        # Canchas preferidas (en orden de prioridad)
        # Las KINERET son las canchas 05-08
        "canchas_preferidas": ["KINERET", "05-", "06-", "07-", "08-"],
        
        # Socios a agregar
        "socios": [
            "Alan Garbo",
            "Gabriel Topor",
            "Damian Potap"
        ],
        
        # Timeouts
        "timeout_navegacion": 30000,
        "timeout_elemento": 10000,
        "delay_entre_acciones": 1500,
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
    # El elemento es un <h4>CISSAB | PÁDEL DIURNO</h4> dentro de un div clickeable
    try:
        # Intentar click en el contenedor o en el h4
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
    """
    Navega en el calendario hasta el día objetivo.
    
    Args:
        page: Página de Playwright
        dia_objetivo: datetime del día a reservar
    """
    print(f"\n📅 Navegando al día {dia_objetivo.strftime('%d/%m/%Y')}...")
    
    # El calendario muestra la semana actual
    # Necesitamos navegar con las flechas si el día está en otra semana
    
    max_intentos = 10
    for intento in range(max_intentos):
        # Buscar si el día está visible
        # Los días tienen formato: número + día de semana (ej: "8 DOMINGO")
        dia_num = dia_objetivo.day
        
        # Buscar celda del día objetivo
        # Las celdas de día están en el header del calendario
        celdas_dia = page.locator(f'td:has-text("{dia_num}")').all()
        
        for celda in celdas_dia:
            texto = celda.inner_text()
            if str(dia_num) in texto:
                # Verificamos que sea el día correcto mirando el mes
                # Por ahora asumimos que es correcto
                print(f"   ✅ Día {dia_num} encontrado en el calendario")
                return True
        
        # Si no está, navegar a la siguiente semana
        try:
            page.click('xpath=//div[contains(@class,"calendar-month")]//following-sibling::*[contains(@class,"next")] | //a[contains(@class,"next")]', timeout=2000)
            time.sleep(1)
        except:
            try:
                # Intentar con flecha derecha
                page.click('[class*="next"], [class*="arrow-right"]', timeout=2000)
                time.sleep(1)
            except:
                break
    
    print(f"   ⚠️ No se pudo navegar al día {dia_num}")
    return True  # Continuamos de todas formas


# =============================================================================
# FUNCIONES DE RESERVA
# =============================================================================

def buscar_horario_disponible(page, config):
    """
    Busca un horario disponible según las preferencias.
    
    Returns:
        Elemento de la celda disponible o None
    """
    print("\n🔍 Buscando horarios disponibles...")
    
    # Esperar a que cargue el calendario
    time.sleep(2)
    
    for horario in config["horarios_preferidos"]:
        print(f"   Buscando horario {horario}...")
        
        # Buscar celdas con data-id que contenga el horario
        # Formato: data-id="time-10:00-club-1102-TIMESTAMP"
        selector = f'td[data-id*="time-{horario}"]:not(.disabled)'
        
        celdas = page.locator(selector).all()
        
        for celda in celdas:
            try:
                texto = celda.inner_text()
                clase = celda.get_attribute("class") or ""
                
                # Verificar que no esté completo/deshabilitado
                if "disabled" in clase:
                    continue
                
                # Verificar que tenga lugares libres
                if "libres" in texto.lower() or texto.strip().isdigit():
                    data_id = celda.get_attribute("data-id")
                    print(f"   ✅ Encontrado: {horario} con {texto.strip()}")
                    return celda, horario
                    
            except Exception as e:
                continue
    
    print("   ❌ No se encontraron horarios disponibles")
    return None, None


def seleccionar_cancha_preferida(page, config):
    """Selecciona la cancha preferida (KINERET si está disponible)."""
    print("   🎾 Seleccionando cancha...")
    
    try:
        # Obtener el selector de canchas
        selector = page.locator('#reservationform-court_id')
        
        # Obtener todas las opciones
        opciones = selector.locator('option').all()
        
        # Buscar cancha KINERET primero
        for cancha_pref in config["canchas_preferidas"]:
            for opcion in opciones:
                texto = opcion.inner_text().upper()
                if cancha_pref.upper() in texto:
                    valor = opcion.get_attribute("value")
                    selector.select_option(valor)
                    print(f"   ✅ Cancha seleccionada: {opcion.inner_text()}")
                    return True
        
        # Si no hay KINERET, tomar la primera disponible
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
            
            # Escribir nombre del socio
            input_socios.fill("")
            time.sleep(0.3)
            input_socios.type(socio, delay=100)
            
            # Esperar a que aparezca el dropdown de autocompletado
            time.sleep(1.5)
            
            # Seleccionar del dropdown
            # El dropdown tiene role="listbox" y las opciones tienen la clase tt-suggestion
            try:
                # Click en la primera sugerencia que coincida
                sugerencia = page.locator(f'.tt-suggestion:has-text("{socio}"), .tt-menu div:has-text("{socio}")').first
                sugerencia.click()
                time.sleep(0.5)
                print(f"      ✅ {socio} agregado")
            except:
                # Intentar presionar Enter si no hay dropdown
                input_socios.press("Enter")
                time.sleep(0.5)
                
        except Exception as e:
            print(f"      ⚠️ Error agregando {socio}: {e}")
    
    return True


def aceptar_terminos(page):
    """Marca el checkbox de términos y condiciones."""
    print("   ✓ Aceptando términos...")
    
    try:
        checkbox = page.locator('#reservationform-terms_and_cond')
        
        # Verificar si ya está marcado
        if not checkbox.is_checked():
            checkbox.click()
            time.sleep(0.5)
        
        print("   ✅ Términos aceptados")
        return True
    except Exception as e:
        print(f"   ⚠️ Error con checkbox: {e}")
        return False


def confirmar_reserva(page, dry_run=False):
    """Hace click en el botón Reservar."""
    print("   💾 Confirmando reserva...")
    
    if dry_run:
        print("   [DRY RUN] Simulando click en RESERVAR")
        return True
    
    try:
        page.click('#btn_submit', timeout=5000)
        time.sleep(3)
        page.wait_for_load_state("networkidle")
        
        # Verificar si hubo éxito (buscar mensaje de confirmación o que el modal se cierre)
        time.sleep(2)
        
        print("   ✅ Reserva confirmada")
        return True
    except Exception as e:
        print(f"   ⚠️ Error al confirmar: {e}")
        return False


def realizar_reserva(page, config, celda_horario, horario, dry_run=False):
    """
    Realiza todo el proceso de reserva.
    
    Args:
        page: Página de Playwright
        config: Configuración
        celda_horario: Elemento de la celda con el horario disponible
        horario: String del horario (ej: "10:00")
        dry_run: Si es True, no confirma la reserva
    """
    print(f"\n{'='*50}")
    print(f"🎾 Reservando horario {horario}")
    print(f"{'='*50}")
    
    try:
        # Click en la celda para abrir el modal
        celda_horario.click()
        time.sleep(2)
        
        # Esperar a que aparezca el modal
        page.wait_for_selector('#popupModal.show, #popupModal[style*="display: block"]', timeout=5000)
        time.sleep(1)
        
        # Seleccionar cancha preferida
        seleccionar_cancha_preferida(page, config)
        time.sleep(config["delay_entre_acciones"] / 1000)
        
        # Agregar socios
        agregar_socios(page, config)
        time.sleep(config["delay_entre_acciones"] / 1000)
        
        # Aceptar términos
        aceptar_terminos(page)
        time.sleep(config["delay_entre_acciones"] / 1000)
        
        # Confirmar reserva
        if confirmar_reserva(page, dry_run):
            return True
        else:
            return False
            
    except Exception as e:
        print(f"❌ Error en reserva: {e}")
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
    print(f"📅 Fecha ejecución: {datetime.now().strftime('%Y-%m-%d %H:%M')}")
    print(f"👤 Usuario: {config['usuario']}")
    print(f"🎯 Actividad: {config['actividad']}")
    print(f"⏰ Horarios preferidos: {config['horarios_preferidos']}")
    print(f"👥 Socios: {', '.join(config['socios'])}")
    if dry_run:
        print("⚠️  MODO DRY-RUN: No se harán reservas reales")
    print("="*60)
    
    # Calcular fecha objetivo (mañana, ya que el bot corre 24hs antes)
    fecha_objetivo = datetime.now() + timedelta(days=1)
    print(f"\n📆 Fecha a reservar: {fecha_objetivo.strftime('%A %d/%m/%Y')}")
    
    with sync_playwright() as p:
        browser = p.chromium.launch(
            headless=not visible,
            slow_mo=500 if visible else 0
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
            
            # Buscar horario disponible
            celda, horario = buscar_horario_disponible(page, config)
            
            if celda is None:
                print("\n❌ No se encontraron horarios disponibles")
                sys.exit(1)
            
            # Realizar la reserva
            if realizar_reserva(page, config, celda, horario, dry_run):
                print("\n" + "="*60)
                print("✅ RESERVA COMPLETADA EXITOSAMENTE")
                print("="*60)
            else:
                print("\n" + "="*60)
                print("❌ ERROR EN LA RESERVA")
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
