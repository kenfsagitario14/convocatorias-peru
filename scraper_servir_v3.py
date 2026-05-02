"""
ConvocatoriasPerúHoy — Scraper SERVIR Mejorado v3
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
✅ Solo descarga convocatorias NUEVAS (evita duplicados)
✅ Guarda historial de números de convocatoria ya descargados
✅ Salida en convocatorias.json lista para tu web
✅ Compatible con GitHub Actions (modo headless)
✅ Control de cantidad de páginas
"""

from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.common.exceptions import TimeoutException
from selenium.webdriver.chrome.service import Service
import json
import os
import re
import time
from datetime import datetime, timedelta

# ─── INTENTAR IMPORTAR DEPENDENCIAS OPCIONALES ───────────────
try:
    from webdriver_manager.chrome import ChromeDriverManager
    USE_WEBDRIVER_MANAGER = True
except ImportError:
    USE_WEBDRIVER_MANAGER = False

# ─── ARCHIVOS DE DATOS ────────────────────────────────────────
ARCHIVO_JSON      = "convocatorias.json"        # Tu web lee este archivo
ARCHIVO_HISTORIAL = "historial_ids.json"        # IDs ya descargados
ARCHIVO_LOG       = "scraper_log.txt"           # Log de ejecuciones

# ─── CONFIGURACIÓN ────────────────────────────────────────────
URL_SERVIR = "https://app.servir.gob.pe/DifusionOfertasExterno/faces/consultas/ofertas_laborales.xhtml"
MAX_CONVOCATORIAS_TOTAL = 300   # Máximo a guardar en el JSON
MAX_PAGINAS_POR_DEFECTO = 5     # Páginas a revisar cada vez


# ═══════════════════════════════════════════════════════════════
# HISTORIAL — Evita duplicados
# ═══════════════════════════════════════════════════════════════

def cargar_historial():
    """Carga el set de números de convocatoria ya descargados"""
    if os.path.exists(ARCHIVO_HISTORIAL):
        try:
            with open(ARCHIVO_HISTORIAL, 'r', encoding='utf-8') as f:
                data = json.load(f)
                ids = set(data.get('ids', []))
                print(f"📋 Historial cargado: {len(ids)} convocatorias ya conocidas")
                return ids
        except Exception as e:
            print(f"⚠ Error cargando historial: {e}")
    print("📋 Sin historial previo — primera ejecución")
    return set()

def guardar_historial(ids):
    """Guarda el historial actualizado"""
    try:
        with open(ARCHIVO_HISTORIAL, 'w', encoding='utf-8') as f:
            json.dump({
                'ids': list(ids),
                'ultima_actualizacion': datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
                'total': len(ids)
            }, f, ensure_ascii=False, indent=2)
    except Exception as e:
        print(f"⚠ Error guardando historial: {e}")

def cargar_json_actual():
    """Carga las convocatorias actuales del JSON de la web"""
    if os.path.exists(ARCHIVO_JSON):
        try:
            with open(ARCHIVO_JSON, 'r', encoding='utf-8') as f:
                data = json.load(f)
                convs = data.get('convocatorias', [])
                print(f"📂 JSON actual: {len(convs)} convocatorias")
                return convs
        except Exception as e:
            print(f"⚠ Error cargando JSON: {e}")
    return []

def limpiar_vencidas(convocatorias):
    """Elimina convocatorias cuya fecha fin ya pasó"""
    hoy = datetime.now().date()
    activas = []
    vencidas = 0
    for c in convocatorias:
        cierre = c.get('cierre', '')
        if cierre:
            try:
                fecha = datetime.strptime(cierre, '%Y-%m-%d').date()
                if fecha >= hoy:
                    activas.append(c)
                else:
                    vencidas += 1
            except:
                activas.append(c)
        else:
            activas.append(c)
    if vencidas:
        print(f"🗑 {vencidas} convocatorias vencidas eliminadas")
    return activas


# ═══════════════════════════════════════════════════════════════
# CONVERSIÓN DE DATOS — SERVIR → Formato web
# ═══════════════════════════════════════════════════════════════

def parsear_sueldo(texto):
    """Extrae el número de sueldo del texto"""
    if not texto:
        return 0
    numeros = re.findall(r'[\d,]+\.?\d*', texto.replace(',', ''))
    for n in numeros:
        try:
            val = float(n)
            if 500 < val < 50000:
                return int(val)
        except:
            pass
    return 0

def parsear_fecha(texto):
    """Convierte fecha de SERVIR (DD/MM/YYYY) a formato web (YYYY-MM-DD)"""
    if not texto:
        return (datetime.now() + timedelta(days=30)).strftime('%Y-%m-%d')
    formatos = ['%d/%m/%Y', '%d-%m-%Y', '%Y-%m-%d']
    for fmt in formatos:
        try:
            return datetime.strptime(texto.strip(), fmt).strftime('%Y-%m-%d')
        except:
            pass
    return (datetime.now() + timedelta(days=30)).strftime('%Y-%m-%d')

def detectar_modalidad(texto_completo):
    """Detecta la modalidad del puesto"""
    texto = texto_completo.upper()
    if 'CAS' in texto or 'CONTRATO ADMINISTRATIVO' in texto:
        return 'CAS'
    elif '728' in texto or 'PLANILLA' in texto or 'DL 728' in texto:
        return '728'
    elif 'PRÁCTICA' in texto or 'PRACTICANTE' in texto or 'PRACTICAN' in texto:
        return 'Prácticas'
    return 'CAS'  # Por defecto en SERVIR es CAS

def detectar_carrera(formacion, puesto):
    """Detecta la carrera basándose en la formación y el puesto"""
    texto = (formacion + ' ' + puesto).upper()
    mapa = {
        'Administración':  ['ADMINISTRACIÓN', 'ADMINISTRACION', 'GESTIÓN', 'GESTION'],
        'Contabilidad':    ['CONTABILIDAD', 'CONTADOR', 'CONTABLE', 'SIAF'],
        'Derecho':         ['DERECHO', 'ABOGADO', 'JURÍDIC', 'JURIDIC', 'LEGAL'],
        'Ingeniería':      ['INGENIERÍA', 'INGENIERIA', 'INGENIERO', 'CIVIL', 'SISTEMAS', 'INDUSTRIAL'],
        'Salud':           ['ENFERMERÍA', 'ENFERMERIA', 'MÉDICO', 'MEDICO', 'SALUD', 'OBSTETR', 'FARMAC', 'NUTRICI'],
        'Educación':       ['EDUCACIÓN', 'EDUCACION', 'DOCENTE', 'PEDAGOG', 'MAGIST'],
        'Economía':        ['ECONOMÍA', 'ECONOMIA', 'ECONOMISTA', 'FINANZAS', 'PRESUPUESTO'],
        'Sistemas':        ['INFORMÁTICA', 'INFORMATICA', 'SISTEMAS', 'COMPUTACI', 'TECNOLOGÍA', 'TI ', 'IT '],
        'Psicología':      ['PSICOLOGÍA', 'PSICOLOGIA', 'PSICÓLOGO', 'PSICOLOGO'],
        'Trabajo Social':  ['TRABAJO SOCIAL', 'ASISTENTE SOCIAL'],
    }
    for carrera, palabras in mapa.items():
        if any(p in texto for p in palabras):
            return carrera
    return 'Administración'

def detectar_region(ubicacion):
    """Detecta la región de la ubicación"""
    if not ubicacion:
        return 'Lima'
    ub = ubicacion.upper()
    regiones = [
        'AMAZONAS','ÁNCASH','ANCASH','APURÍMAC','APURIMAC','AREQUIPA',
        'AYACUCHO','CAJAMARCA','CALLAO','CUSCO','CUZCO','HUANCAVELICA',
        'HUÁNUCO','HUANUCO','ICA','JUNÍN','JUNIN','LA LIBERTAD',
        'LAMBAYEQUE','LIMA','LORETO','MADRE DE DIOS','MOQUEGUA',
        'PASCO','PIURA','PUNO','SAN MARTÍN','SAN MARTIN','TACNA',
        'TUMBES','UCAYALI'
    ]
    for r in regiones:
        if r in ub:
            r_clean = r.title().replace('Á','á').replace('É','é').replace('Í','í').replace('Ó','ó').replace('Ú','ú')
            if r == 'ÁNCASH': r_clean = 'Áncash'
            if r == 'APURÍMAC': r_clean = 'Apurímac'
            if r == 'CUSCO' or r == 'CUZCO': r_clean = 'Cusco'
            if r == 'HUÁNUCO': r_clean = 'Huánuco'
            if r == 'JUNÍN': r_clean = 'Junín'
            if r == 'SAN MARTÍN' or r == 'SAN MARTIN': r_clean = 'San Martín'
            return r_clean
    return 'Lima'

def servir_a_web(oferta_servir, numero_conv):
    """Convierte una oferta de SERVIR al formato de tu web"""
    formacion = oferta_servir.get('formacion_academica', '')
    puesto    = oferta_servir.get('puesto', 'Sin título')
    ubicacion = oferta_servir.get('ubicacion', '')
    remuner   = oferta_servir.get('remuneracion', oferta_servir.get('remuneracion_detalle', ''))
    fecha_fin = oferta_servir.get('fecha_fin_publicacion', '')
    entidad   = oferta_servir.get('entidad', 'Entidad del Estado')
    experiencia   = oferta_servir.get('experiencia', '')
    especializacion = oferta_servir.get('especializacion', '')
    conocimientos   = oferta_servir.get('conocimientos', '')
    competencias    = oferta_servir.get('competencias', '')

    # Construir requisitos
    requisitos = []
    if formacion:
        requisitos.append(f"Formación: {formacion[:120]}")
    if experiencia:
        requisitos.append(f"Experiencia: {experiencia[:120]}")
    if especializacion:
        requisitos.append(f"Especialización: {especializacion[:100]}")
    if conocimientos:
        requisitos.append(f"Conocimientos: {conocimientos[:100]}")
    if competencias:
        requisitos.append(f"Competencias: {competencias[:100]}")
    if not requisitos:
        requisitos = ['Según perfil de la convocatoria — ver enlace oficial']

    # Descripción
    descripcion = f"Convocatoria N° {numero_conv} — {puesto} en {entidad}."
    if experiencia:
        descripcion += f" Se requiere: {experiencia[:200]}."

    # Link de postulación
    link = oferta_servir.get('detalle_web', URL_SERVIR)
    if not link or link.strip() == '':
        link = URL_SERVIR

    vacantes_txt = oferta_servir.get('cantidad_vacantes', oferta_servir.get('cantidad_vacantes_detalle', '1'))
    try:
        vacantes = int(re.search(r'\d+', str(vacantes_txt)).group())
    except:
        vacantes = 1

    return {
        'id':           abs(hash(numero_conv)) % (10**9),
        'numero_conv':  numero_conv,
        'cargo':        puesto,
        'entidad':      entidad,
        'modalidad':    detectar_modalidad(puesto + ' ' + formacion),
        'region':       detectar_region(ubicacion),
        'carrera':      detectar_carrera(formacion, puesto),
        'sueldo':       parsear_sueldo(remuner),
        'cierre':       parsear_fecha(fecha_fin),
        'vacantes':     vacantes,
        'nuevo':        'auto',
        'link':         link,
        'imagen':       '',
        'fuente':       'SERVIR',
        'fecha_scraping': datetime.now().strftime('%Y-%m-%d %H:%M'),
        'requisitos':   requisitos,
        'descripcion':  descripcion,
        # Campos extra de SERVIR (útiles para tu panel de edición)
        '_ubicacion_original': ubicacion,
        '_remuneracion_original': remuner,
        '_formacion_original': formacion,
        '_experiencia_original': experiencia,
    }


# ═══════════════════════════════════════════════════════════════
# SCRAPER PRINCIPAL
# ═══════════════════════════════════════════════════════════════

class ServirScraperV3:
    def __init__(self, headless=True):
        self.url = URL_SERVIR
        self.ofertas_nuevas = []

        options = webdriver.ChromeOptions()
        if headless:
            options.add_argument('--headless=new')
        options.add_argument('--no-sandbox')
        options.add_argument('--disable-dev-shm-usage')
        options.add_argument('--disable-gpu')
        options.add_argument('--window-size=1920,1080')
        options.add_argument('--user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36')

        if USE_WEBDRIVER_MANAGER:
            service = Service(ChromeDriverManager().install())
            self.driver = webdriver.Chrome(service=service, options=options)
        else:
            # En GitHub Actions Chrome ya está instalado
            self.driver = webdriver.Chrome(options=options)

        self.wait = WebDriverWait(self.driver, 30)
        print("✅ Navegador iniciado")

    def iniciar(self):
        print(f"\n🌐 Cargando SERVIR...")
        self.driver.get(self.url)
        time.sleep(3)
        try:
            btn = self.wait.until(EC.element_to_be_clickable((By.ID, "frmLstOfertsLabo:btnBuscar")))
            btn.click()
            time.sleep(4)
            print("✅ Resultados cargados")
        except Exception as e:
            print(f"⚠ No se encontró botón Buscar: {e}")

    def extraer_numero_convocatoria(self, tarjeta):
        """Extrae el número de convocatoria de una tarjeta"""
        try:
            elem = tarjeta.find_element(
                By.XPATH,
                ".//span[@class='sub-titulo' and contains(text(), 'Número de Convocatoria')]/following-sibling::span"
            )
            return elem.text.strip()
        except:
            return ''

    def extraer_info_basica(self, tarjeta):
        """Extrae info básica de la tarjeta de la lista"""
        oferta = {}
        campos = {
            'puesto':                   "div.titulo-vacante label",
            'entidad':                  "div.nombre-entidad span.detalle-sp",
        }
        for campo, selector in campos.items():
            try:
                oferta[campo] = tarjeta.find_element(By.CSS_SELECTOR, selector).text.strip()
            except:
                oferta[campo] = ''

        xpaths = {
            'ubicacion':              "Ubicación",
            'numero_convocatoria':    "Número de Convocatoria",
            'cantidad_vacantes':      "Cantidad de Vacantes",
            'remuneracion':           "Remuneración",
            'fecha_inicio_publicacion': "Fecha Inicio de Publicación",
            'fecha_fin_publicacion':  "Fecha Fin de Publicación",
        }
        for campo, texto in xpaths.items():
            try:
                elem = tarjeta.find_element(
                    By.XPATH,
                    f".//span[@class='sub-titulo' and contains(text(), '{texto}')]/following-sibling::span"
                )
                oferta[campo] = elem.text.strip()
            except:
                oferta[campo] = ''
        return oferta

    def extraer_detalles(self):
        """Extrae los detalles de la página de detalle"""
        detalles = {}
        time.sleep(2.5)

        campos_detalle = {
            'detalle_web':              ("sub-titulo", "DETALLE"),
            'cantidad_vacantes_detalle': ("sub-titulo", "CANTIDAD DE VACANTES"),
            'remuneracion_detalle':     ("sub-titulo", "REMUNERACIÓN"),
            'fecha_inicio_publicacion': ("sub-titulo", "FECHA INICIO"),
            'fecha_fin_publicacion':    ("sub-titulo", "FECHA FIN"),
        }
        for campo, (cls, texto) in campos_detalle.items():
            try:
                elem = self.driver.find_element(
                    By.XPATH,
                    f"//span[@class='{cls}' and contains(normalize-space(.), '{texto}')]/following-sibling::span[@class='detalle-sp']"
                )
                detalles[campo] = elem.text.strip()
            except:
                detalles[campo] = ''

        campos_perfil = {
            'experiencia':        "EXPERIENCIA",
            'formacion_academica': "FORMACIÓN",
            'especializacion':    "ESPECIALIZACIÓN",
            'conocimientos':      "CONOCIMIENTO",
            'competencias':       "COMPETENCIAS",
        }
        for campo, texto in campos_perfil.items():
            try:
                elem = self.driver.find_element(
                    By.XPATH,
                    f"//span[@class='sub-titulo-2' and contains(normalize-space(.), '{texto}')]/following-sibling::span[@class='detalle-sp']"
                )
                detalles[campo] = elem.text.strip()
            except:
                detalles[campo] = ''
        return detalles

    def procesar_pagina(self, historial_ids):
        """Procesa una página y retorna (nuevas, hay_nuevas_en_pagina)"""
        nuevas_pagina = []
        try:
            tarjetas = self.wait.until(
                EC.presence_of_all_elements_located((By.CSS_SELECTOR, "div.cuadro-vacantes"))
            )
            total = len(tarjetas)
            print(f"  → {total} ofertas en esta página")

            for idx in range(total):
                try:
                    tarjetas = self.driver.find_elements(By.CSS_SELECTOR, "div.cuadro-vacantes")
                    tarjeta  = tarjetas[idx]

                    num_conv = self.extraer_numero_convocatoria(tarjeta)

                    # ── DEDUPLICACIÓN ──
                    if num_conv and num_conv in historial_ids:
                        print(f"    ⏭ Ya conocida: {num_conv}")
                        continue

                    oferta = self.extraer_info_basica(tarjeta)
                    print(f"    📋 Nueva: {oferta.get('puesto','?')[:45]}...", end=' ')

                    # Entrar al detalle
                    try:
                        btn_ver = tarjeta.find_element(By.CSS_SELECTOR, "button.btn-primary")
                        btn_ver.click()
                        detalles = self.extraer_detalles()
                        oferta.update(detalles)
                        print("✅")

                        # Volver
                        try:
                            btn_volver = self.wait.until(EC.element_to_be_clickable(
                                (By.XPATH, "//button[contains(., 'Volver a la lista') or contains(@id, 'volver')]")
                            ))
                            btn_volver.click()
                        except:
                            self.driver.back()
                        time.sleep(2)

                    except Exception as e:
                        print(f"⚠ Sin detalles")

                    oferta['fecha_extraccion'] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

                    # Convertir al formato web
                    conv_web = servir_a_web(oferta, num_conv or f"CONV-{abs(hash(oferta.get('puesto',''))%99999)}")
                    nuevas_pagina.append(conv_web)

                    if num_conv:
                        historial_ids.add(num_conv)

                except Exception as e:
                    print(f"    ✗ Error oferta {idx}: {e}")
                    continue

        except Exception as e:
            print(f"  ✗ Error en página: {e}")

        return nuevas_pagina

    def navegar_siguiente(self):
        try:
            btn = self.driver.find_element(
                By.XPATH,
                "//button[contains(@class,'ui-button') and .//span[contains(text(),'Sig.')]]"
            )
            if 'ui-state-disabled' in btn.get_attribute('class'):
                return False
            btn.click()
            time.sleep(4)
            return True
        except:
            return False

    def cerrar(self):
        try:
            self.driver.quit()
        except:
            pass


# ═══════════════════════════════════════════════════════════════
# FUNCIÓN PRINCIPAL
# ═══════════════════════════════════════════════════════════════

def main(max_paginas=MAX_PAGINAS_POR_DEFECTO, headless=True):
    print("\n" + "="*60)
    print("🇵🇪 ConvocatoriasPerúHoy — Scraper SERVIR v3")
    print(f"📅 {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"⚙ Modo: {'Headless' if headless else 'Visible'} | Páginas: {max_paginas}")
    print("="*60)

    # Cargar datos previos
    historial_ids    = cargar_historial()
    convs_actuales   = cargar_json_actual()
    convs_actuales   = limpiar_vencidas(convs_actuales)

    scraper = None
    todas_nuevas = []

    try:
        scraper = ServirScraperV3(headless=headless)
        scraper.iniciar()

        for pagina in range(1, max_paginas + 1):
            print(f"\n{'─'*50}")
            print(f"📄 PÁGINA {pagina}/{max_paginas}")
            print(f"{'─'*50}")

            nuevas = scraper.procesar_pagina(historial_ids)
            todas_nuevas.extend(nuevas)
            print(f"  ✅ {len(nuevas)} nuevas en esta página | Total nuevas: {len(todas_nuevas)}")

            if pagina < max_paginas:
                if not scraper.navegar_siguiente():
                    print("  ℹ No hay más páginas")
                    break

    except KeyboardInterrupt:
        print("\n⚠ Interrumpido por el usuario")
    except Exception as e:
        print(f"\n❌ Error: {e}")
        import traceback
        traceback.print_exc()
    finally:
        if scraper:
            scraper.cerrar()

    # ── COMBINAR Y GUARDAR ──
    print(f"\n{'='*60}")
    print(f"📊 RESUMEN FINAL")
    print(f"{'='*60}")
    print(f"  Nuevas descargadas:    {len(todas_nuevas)}")
    print(f"  Existentes previas:    {len(convs_actuales)}")

    # Las nuevas van primero
    todas = todas_nuevas + convs_actuales
    todas = todas[:MAX_CONVOCATORIAS_TOTAL]

    output = {
        "ultima_actualizacion": datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
        "total": len(todas),
        "nuevas_esta_ejecucion": len(todas_nuevas),
        "fuentes": ["SERVIR - app.servir.gob.pe"],
        "convocatorias": todas
    }

    with open(ARCHIVO_JSON, 'w', encoding='utf-8') as f:
        json.dump(output, f, ensure_ascii=False, indent=2)

    guardar_historial(historial_ids)

    # Log
    with open(ARCHIVO_LOG, 'a', encoding='utf-8') as f:
        f.write(f"{datetime.now().strftime('%Y-%m-%d %H:%M')} | "
                f"Nuevas: {len(todas_nuevas)} | Total: {len(todas)} | "
                f"Páginas: {max_paginas}\n")

    print(f"  Total en JSON:         {len(todas)}")
    print(f"\n✅ Guardado en: {ARCHIVO_JSON}")
    print(f"✅ Historial:   {ARCHIVO_HISTORIAL}")
    print(f"✅ Log:         {ARCHIVO_LOG}")
    print("="*60)


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description='Scraper SERVIR v3')
    parser.add_argument('--paginas',  type=int, default=MAX_PAGINAS_POR_DEFECTO,
                        help=f'Número de páginas a scrapear (default: {MAX_PAGINAS_POR_DEFECTO})')
    parser.add_argument('--visible',  action='store_true',
                        help='Mostrar ventana del navegador')
    args = parser.parse_args()

    main(max_paginas=args.paginas, headless=not args.visible)
