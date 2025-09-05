import streamlit as st
import pandas as pd
import xmlrpc.client
from datetime import datetime
import pytz
import time
import re
import os
import base64
import io
import openpyxl
from dotenv import load_dotenv

# Cargar variables de entorno desde .env si existe
load_dotenv()

def show_login_form():
    """Muestra el formulario de login y retorna las credenciales"""
    st.sidebar.title("Inicio de Sesión")

    # Obtener URL y DB desde variables de entorno
    url = os.environ.get("ODOO_URL", "")
    db = os.environ.get("ODOO_DB", "")
    if not url or not db:
        st.sidebar.error("⚠️ Configuración de Odoo incompleta. Defina ODOO_URL y ODOO_DB en el entorno o en el archivo .env.")
        return None, None, None, None

    
    # Formulario de login en el sidebar
    with st.sidebar.form("login_form"):
        st.write("Ingrese sus credenciales de Odoo")

        # Mostrar la URL y DB como información pero no como entrada
        st.info(f"Servidor: {url}")
        
        # Campos del formulario
        username = st.text_input("Usuario")
        password = st.text_input("Contraseña", type="password")

        # Botón de login
        submit_button = st.form_submit_button("Iniciar Sesión")

    # Verificar si se ha pulsado el botón de login
    if submit_button:
        if not username or not password:
            st.sidebar.error("❌ Usuario y contraseña son requeridos")
            return None, None, None, None

        # Guardar credenciales en sesión
        st.session_state['odoo_url'] = url
        st.session_state['odoo_db'] = db
        st.session_state['odoo_username'] = username
        st.session_state['odoo_password'] = password
        st.session_state['is_logged_in'] = True

        return url, db, username, password

    # Si hay credenciales guardadas, devolverlas
    if st.session_state.get('is_logged_in', False):
        # Asegurarse de que url y db estén en la sesión, si no, usar los valores del entorno
        session_url = st.session_state.get('odoo_url', url)
        session_db = st.session_state.get('odoo_db', db)
        
        # Si no hay url o db en la sesión ni en el entorno, mostrar error
        if not session_url or not session_db:
            st.sidebar.error("⚠️ Configuración de Odoo incompleta. Defina ODOO_URL y ODOO_DB.")
            return None, None, None, None
            
        return (
            session_url,
            session_db,
            st.session_state.get('odoo_username', ''),
            st.session_state.get('odoo_password', '')
        )

    return None, None, None, None

def validate_excel_format(df):
    """
    Valida el formato del Excel según los requisitos

    Retorna:
    - is_valid: booleano indicando si el formato es válido
    - errors: DataFrame con los errores encontrados
    """
    is_valid = True
    error_records = []

    # Obtener los valores válidos para Forma de Pago del mapping
    valid_payment_methods = {
        'TRANSF', 'DEP', 'BEX', 'CV', 'IN', 'SBE', 'EFECT OF', 'MAQ/TD', 'MAQ/TC', 'WEBPAY', 'IPS'
    }

    # Recorrer cada fila y validar
    for index, row in df.iterrows():
        row_errors = []

        # 1. Validar formato de fecha
        try:
            if pd.isna(row['Fecha Pago']):
                row_errors.append("Fecha de pago vacía")
            elif not isinstance(row['Fecha Pago'], pd.Timestamp):
                row_errors.append("Formato de fecha inválido")
        except Exception:
            row_errors.append("Error en columna Fecha Pago")

        # 2. Validar código de reserva (6 caracteres máximo)
        try:
            reserva = str(row['Reserva']).strip()
            if pd.isna(row['Reserva']) or not reserva:
                row_errors.append("Código de reserva vacío")
            elif len(reserva) > 6:
                row_errors.append(f"Código de reserva ({reserva}) excede 6 caracteres")
        except Exception:
            row_errors.append("Error en columna Reserva")

        # 3. Validar valor de pago (0 o 1)
        try:
            pago = row['Pago']
            if pd.isna(pago):
                row_errors.append("Valor de pago vacío")
            elif pago not in [0, 1]:
                row_errors.append(f"Valor de pago ({pago}) debe ser 0 o 1")
        except Exception:
            row_errors.append("Error en columna Pago")

        # 4. Validar forma de pago (debe coincidir con los códigos del mapping)
        try:
            forma_pago = str(row['Forma de Pago']).strip()
            if pd.isna(row['Forma de Pago']) or not forma_pago:
                row_errors.append("Forma de pago vacía")
            elif forma_pago not in valid_payment_methods:
                row_errors.append(f"Forma de pago ({forma_pago}) no válida. Valores permitidos: {', '.join(valid_payment_methods)}")
        except Exception:
            row_errors.append("Error en columna Forma de Pago")

        # 5. Validar Monto Abono
        try:
            monto = row['Monto Abono']
            if pd.isna(monto):
                row_errors.append("Monto de abono vacío")
            elif not isinstance(monto, (int, float)) or monto <= 0:
                row_errors.append(f"Monto de abono ({monto}) debe ser un número positivo")
        except Exception:
            row_errors.append("Error en columna Monto Abono")

        # Si hay errores, el formato no es válido
        if row_errors:
            is_valid = False

            # Agregar los errores a la lista de registros con error
            for error in row_errors:
                error_records.append({
                    'Fila': index + 2,  # +2 para considerar el encabezado y base 1
                    'Reserva': str(row.get('Reserva', '')),
                    'Error': error
                })

    # Crear DataFrame con los errores
    errors_df = pd.DataFrame(error_records)

    return is_valid, errors_df

def validate_orders_status(models, db, uid, password, df):
    """
    Valida el estado de las órdenes de venta antes de procesar pagos

    Retorna:
    - orders_status: DataFrame con el estado de cada orden
    """
    orders_info = []
    status_container = st.empty()
    progress_bar = st.progress(0)

    for index, row in df.iterrows():
        # Actualizar la barra de progreso
        progress_bar.progress((index + 1) / len(df))

        reserva = str(row['Reserva']).strip()
        status_container.info(f"Validando orden {reserva} ({index + 1}/{len(df)})...")

        # Obtener información del pago
        es_pago_total = int(row.get('Pago', 0)) == 1
        monto_abono = float(row.get('Monto Abono', 0))

        # Buscar la orden en Odoo
        domain = [('name', '=', reserva)]
        sale_order_ids = models.execute_kw(db, uid, password, 'sale.order', 'search', [domain])

        if not sale_order_ids:
            # La orden no existe
            orders_info.append({
                'Reserva': reserva,
                'Existe': False,
                'Estado': 'N/A',
                'Estado_Factura': 'N/A',
                'Puede_Procesar': False,
                'Motivo': "Orden no encontrada en Odoo"
            })
        else:
            # La orden existe, verificar su estado
            sale_order = models.execute_kw(db, uid, password, 'sale.order', 'read',
                [sale_order_ids[0]], {'fields': ['state', 'invoice_status', 'amount_total']})[0]

            # Verificar si el estado de facturación es 'to invoice' o si es un pago parcial con factura ya creada
            invoice_status = sale_order.get('invoice_status')
            monto_total_orden = float(sale_order.get('amount_total', 0))
            
            # Caso especial: Pago parcial (Pago=0) y la orden ya tiene factura (invoice_status='invoiced')
            es_caso_especial = not es_pago_total and invoice_status == 'invoiced'
            
            # Puede procesar si: (estado normal para facturar) O (caso especial de pago parcial con factura)
            can_process = (invoice_status == 'to invoice') or es_caso_especial

            motivo = ""
            if not can_process:
                if invoice_status == 'invoiced' and es_pago_total:
                    motivo = "Orden ya facturada y se intenta hacer un pago total"
                elif invoice_status == 'no':
                    motivo = "Orden no requiere facturación"
                elif invoice_status == 'upselling':
                    motivo = "Orden en estado de venta adicional"
                else:
                    motivo = f"Estado de facturación no válido: {invoice_status}"
            # Validar que si es pago total, el monto coincida con el total de la orden
            elif es_pago_total and abs(monto_abono - monto_total_orden) > 0.01:  # Tolerancia de 0.01 para errores de redondeo
                can_process = False
                motivo = f"El monto del pago total ({monto_abono}) no coincide con el total de la orden ({monto_total_orden})"
            
            # Agregar información adicional para el caso especial
            if es_caso_especial and can_process:
                motivo = "Pago parcial para orden ya facturada - Se asociará a la factura existente"

            # Formatear montos para visualización (solo para mostrar en la tabla)
            monto_total_formato = f"${monto_total_orden:,.0f}"
            monto_abono_formato = f"${monto_abono:,.0f}"
            
            orders_info.append({
                'Reserva': reserva,
                'Existe': True,
                'Estado': sale_order.get('state', 'N/A'),
                'Estado_Factura': sale_order.get('invoice_status', 'N/A'),
                'Monto_Total': monto_total_formato,  # Formato para visualización
                'Monto_Abono': monto_abono_formato,  # Formato para visualización
                'Es_Pago_Total': 'Sí' if es_pago_total else 'No',
                'Puede_Procesar': can_process,
                'Motivo': motivo if not can_process else "OK"
            })

    status_container.success("✅ Validación de órdenes completada")
    progress_bar.empty()

    return pd.DataFrame(orders_info)

def connect_to_odoo():
    """Establece conexión con Odoo usando las credenciales de la sesión"""
    # Crear indicador de estado para la conexión
    status_container = st.empty()

    # Verificar si hay credenciales almacenadas
    if not all(k in st.session_state for k in ['odoo_url', 'odoo_db', 'odoo_username', 'odoo_password']):
        status_container.error("❌ No hay credenciales de acceso. Por favor inicie sesión.")
        return None, None, None, None

    status_container.info("Intentando conectar con Odoo...")

    try:
        url = st.session_state['odoo_url']
        db = st.session_state['odoo_db']
        username = st.session_state['odoo_username']
        password = st.session_state['odoo_password']

        # Mostrar intentando conectar con servidor
        status_container.info(f"Estableciendo conexión con {url}...")
        # Crear conexión sin timeout (compatible con todas las versiones de Python)
        common = xmlrpc.client.ServerProxy(f'{url}/xmlrpc/2/common', allow_none=True, use_datetime=True)

        # Mostrar intentando autenticar
        status_container.info("Autenticando...")
        uid = common.authenticate(db, username, password, {})
        if not uid:
            status_container.error("❌ Error de autenticación. Verifique sus credenciales.")
            # Limpiar credenciales incorrectas
            for key in ['odoo_url', 'odoo_db', 'odoo_username', 'odoo_password']:
                if key in st.session_state:
                    del st.session_state[key]
            return None, None, None, None

        # Conexión exitosa, mostrar indicador de éxito
        models = xmlrpc.client.ServerProxy(f'{url}/xmlrpc/2/object', allow_none=True, use_datetime=True)
        status_container.success(f"✅ Conexión exitosa a Odoo ({url})")
        return models, db, uid, password
    except Exception as e:
        status_container.error(f"❌ Error de conexión: {str(e)}")
        # Limpiar credenciales en caso de error
        for key in ['odoo_url', 'odoo_db', 'odoo_username', 'odoo_password']:
            if key in st.session_state:
                del st.session_state[key]
        return None, None, None, None


def format_date(date_value):
    """Convierte la fecha al formato requerido dd-mm-aaaa"""
    if isinstance(date_value, pd.Timestamp):
        return date_value.strftime('%d-%m-%Y')
    elif isinstance(date_value, str):
        try:
            date_obj = datetime.strptime(date_value, '%Y-%m-%d')
            return date_obj.strftime('%d-%m-%Y')
        except ValueError:
            try:
                date_obj = datetime.strptime(date_value, '%d-%m-%Y')
                return date_value
            except ValueError:
                raise ValueError(f"Formato de fecha no reconocido: {date_value}")
    else:
        raise ValueError(f"Tipo de fecha no soportado: {type(date_value)}")

def convert_to_odoo_date(date_value):
    """Convierte la fecha a formato Odoo (YYYY-MM-DD)"""
    if isinstance(date_value, pd.Timestamp):
        return date_value.strftime('%Y-%m-%d')
    elif isinstance(date_value, str):
        try:
            date_obj = datetime.strptime(date_value, '%Y-%m-%d')
            return date_value
        except ValueError:
            date_obj = datetime.strptime(date_value, '%d-%m-%Y')
            return date_obj.strftime('%Y-%m-%d')
    else:
        raise ValueError(f"Tipo de fecha no soportado: {type(date_value)}")

def get_journal_id(payment_method):
    """Determina el diario según el método de pago"""
    journal_mapping = {
        'TRANSF': 7,  # ID del diario de transferencias
        'DEP': 7,     # ID del diario de depósitos
        'BEX': 7,     # ID del diario de Banco Estado Express
        'CV': 7,      # ID del diario de Caja Vecina
        'IN': 7,      # ID del diario de Internet
        'SBE': 7,     # ID del diario de Sucursal Banco Estado
        'EFECT OF': 6,# ID del diario de Efectivo
        'MAQ/TD': 7,  # ID del diario de Transbank Débito
        'MAQ/TC': 7,   # ID del diario de Transbank Crédito
        'WEBPAY': 7,   # ID del diario de Webpay
        'IPS': 7   # ID del diario de IPS
    }
    return journal_mapping.get(payment_method, 7)

def get_order_lines(models, db, uid, password, order_id):
    """Obtiene las líneas de la orden de venta"""
    fields = [
        'id',  # Necesario para vincular con las líneas de factura
        'product_id',
        'name',
        'product_uom_qty',  # Cantidad en la unidad de medida del producto
        'product_uom',      # Unidad de medida
        'price_unit',
        'price_subtotal',
        'tax_id'
    ]

    return models.execute_kw(db, uid, password, 'sale.order.line', 'search_read',
        [[('order_id', '=', order_id)]], 
        {'fields': fields})

def register_payment_from_invoice(models, db, uid, password, invoice_id, payment_data, update_step):
    """Registra el pago usando el wizard nativo de Odoo"""
    try:
        update_step("Preparando registro de pago...")
        # Verificar que la factura existe
        try:
            invoice_check = models.execute_kw(db, uid, password, 'account.move', 'read', [[invoice_id]], {'fields': ['name', 'state']})
            update_step(f"Factura encontrada: {invoice_check[0]['name']} (Estado: {invoice_check[0]['state']})")
        except Exception as e:
            update_step(f"\u26a0\ufe0f No se pudo verificar la factura: {str(e)}")
            
        context = {
            'active_model': 'account.move',
            'active_ids': [invoice_id],
            'active_id': invoice_id,
        }

        wizard_vals = {
            'payment_date': payment_data['date'],
            'journal_id': payment_data['journal_id'],
            'payment_method_id': 1,
            'amount': payment_data['amount'],
            'communication': payment_data['memo'],
            'partner_type': 'customer',
            'payment_type': 'inbound'
        }

        update_step(f"Creando wizard de pago con valores: {wizard_vals}")
        
        # Agregar manejo de tiempo para detectar operaciones lentas
        import time
        start_time = time.time()
        
        try:
            payment_register = models.execute_kw(db, uid, password,
                'account.payment.register', 'create',
                [wizard_vals],
                {'context': context})
            elapsed = time.time() - start_time
            update_step(f"Wizard creado en {elapsed:.2f} segundos, ID: {payment_register}")
        except Exception as e:
            update_step(f"\u274c Error al crear el wizard de pago: {str(e)}")
            return False

        if not payment_register:
            update_step("\u274c Error al crear el wizard de pago: No se obtuvo ID")
            return False

        update_step("Ejecutando pago...")
        start_time = time.time()
        
        try:
            result = models.execute_kw(db, uid, password,
                'account.payment.register', 'action_create_payments',
                [[payment_register]],
                {'context': context})
            elapsed = time.time() - start_time
            update_step(f"Pago ejecutado en {elapsed:.2f} segundos, Resultado: {result}")
        except Exception as e:
            update_step(f"\u274c Error al ejecutar el pago: {str(e)}")
            return False

        if not result:
            update_step("\u26a0\ufe0f Advertencia: El pago se ejecutó pero no retornó resultado")
            
        update_step("\u2705 Pago registrado exitosamente")
        return True

    except Exception as e:
        import traceback
        error_trace = traceback.format_exc()
        update_step(f"\u274c Error al registrar pago: {str(e)}")
        update_step(f"Detalles del error: {error_trace}")
        return False

def process_record(models, db, uid, password, row, orders_status_df, progress_bar, progress_step, update_step):
    """Procesa un registro del Excel con actualización de pasos

    Args:
        update_step: Función para actualizar el paso actual en el log
        
    Nota:
        Si row['Pago'] = 1: Se valida que el monto del abono coincida con el total de la orden
        Si row['Pago'] = 0: Se permite un pago parcial (monto del abono puede ser menor al total)
        
    Caso especial:
        Si row['Pago'] = 0 y la orden ya está facturada (invoice_status='invoiced'):
        Se busca la factura existente y se asocia el pago a ella sin crear una nueva factura
    """
    # Inicializar el avance
    current_step = 0
    progress_bar.progress(current_step * progress_step)

    # Preparar datos básicos
    reserva = str(row['Reserva']).strip()
    reserva_clean = str(row['Reserva_Clean']).strip() if 'Reserva_Clean' in row else reserva
    
    # Obtener la fila correspondiente en el DataFrame de validación (solo para información)
    order_status_rows = orders_status_df[orders_status_df['Reserva_Str'].astype(str).str.strip() == reserva_clean]
    if len(order_status_rows) > 0:
        order_status = order_status_rows.iloc[0]
    else:
        # Esto no debería ocurrir nunca con la nueva implementación
        order_status = {'Estado': 'Desconocido', 'Estado_Factura': 'Desconocido'}

    # Buscar la orden de venta
    update_step(f"🔍 Buscando orden de venta: {reserva}")
    domain = [('name', '=', reserva)]
    sale_order_ids = models.execute_kw(db, uid, password, 'sale.order', 'search', [domain])

    current_step += 1
    progress_bar.progress(current_step * progress_step)

    # Obtener detalles de la orden
    update_step("📋 Obteniendo detalles de la orden...")
    sale_order = models.execute_kw(db, uid, password, 'sale.order', 'read',
        [sale_order_ids[0]], {'fields': ['partner_id', 'amount_total', 'invoice_status']})[0]

    current_step += 1
    progress_bar.progress(current_step * progress_step)

    if not sale_order.get('partner_id'):
        update_step("❌ Orden sin cliente asociado")
        return {
            'Reserva': reserva,
            'Status': 'Error',
            'Mensaje': 'Orden sin cliente asociado',
            'Estado_Orden': order_status['Estado'],
            'Estado_Factura': order_status['Estado_Factura'],
            'Factura': 'No',
            'Pago': 'No',
            'Conciliación': 'No'
        }

    # Obtener líneas de la orden
    update_step("📊 Obteniendo líneas de la orden...")
    order_lines = get_order_lines(models, db, uid, password, sale_order_ids[0])

    current_step += 1
    progress_bar.progress(current_step * progress_step)

    # Preparar datos básicos
    partner_id = sale_order['partner_id'][0]
    invoice_date = convert_to_odoo_date(row['Fecha Pago'])
    monto = float(row['Monto Abono'])
    payment_method = str(row['Forma de Pago']).strip()
    journal_id = get_journal_id(payment_method)
    formatted_date = format_date(row['Fecha Pago'])
        
    # Verificar si es pago total o parcial
    es_pago_parcial = row['Pago'] == 0
    total_orden = float(sale_order['amount_total'])
    
    # Validar monto si es pago total (Pago=1)
    if not es_pago_parcial and abs(monto - total_orden) > 0.01:  # Tolerancia de 0.01 para errores de redondeo
        update_step(f"⚠️ Advertencia: Pago marcado como total pero el monto ({monto}) no coincide con el total de la orden ({total_orden})")
        # Continuamos de todas formas, pero dejamos la advertencia en el log

    # Verificar si es un caso especial: pago parcial para orden ya facturada
    es_caso_especial = es_pago_parcial and sale_order.get('invoice_status') == 'invoiced'
    invoice_id = None
    payment_data = None
    memo = ""

    if es_caso_especial:
        # Manejar caso especial: buscar factura existente para pago parcial en orden ya facturada
        update_step("🔍 Buscando factura existente para la orden...")
        # Buscar facturas relacionadas con la orden
        domain = [
            ('invoice_origin', '=', reserva),
            ('move_type', '=', 'out_invoice'),
            ('state', '=', 'posted')
        ]
        existing_invoice_ids = models.execute_kw(db, uid, password, 'account.move', 'search', [domain])
        
        if not existing_invoice_ids:
            update_step("⚠️ No se encontraron facturas existentes para la orden")
            return {
                'Reserva': reserva,
                'Status': 'Error',
                'Mensaje': 'No se encontraron facturas existentes para la orden',
                'Estado_Orden': order_status['Estado'],
                'Estado_Factura': order_status['Estado_Factura'],
                'Factura': 'No',
                'Pago': 'No',
                'Conciliación': 'No'
            }
        
        # Usar la primera factura encontrada
        invoice_id = existing_invoice_ids[0]
        invoice_data = models.execute_kw(db, uid, password, 'account.move', 'read', 
                                      [invoice_id], {'fields': ['name', 'amount_total', 'amount_residual']})[0]
        
        update_step(f"✅ Factura existente encontrada: {invoice_data['name']}")
        update_step(f"Total factura: ${invoice_data['amount_total']}, Pendiente: ${invoice_data['amount_residual']}")
        
        # Preparar memo para el pago
        memo = f"{reserva} / {payment_method}/{formatted_date} (PAGO PARCIAL ADICIONAL)"
        update_step(f"💰 Procesando pago PARCIAL ADICIONAL por ${monto} para factura existente")
        
        # Avanzar los pasos para mantener la barra de progreso
        current_step += 3
        progress_bar.progress(current_step * progress_step)
        update_step("✅ Usando factura existente, no es necesario crear una nueva")
        
        # Preparar payment_data para el caso especial
        payment_data = {
            'amount': monto,
            'date': invoice_date,
            'journal_id': journal_id,
            'memo': memo
        }
    else:
        # Caso normal: crear factura y registrar pago
        # Preparar datos para el memo
        if es_pago_parcial:
            memo = f"{reserva} / {payment_method}/{formatted_date} (PAGO PARCIAL)"
            update_step(f"💰 Procesando pago PARCIAL por ${monto} de un total de ${total_orden}")
        else:
            memo = f"{reserva} / {payment_method}/{formatted_date}"
            update_step(f"💰 Procesando pago TOTAL por ${monto}")
        
        # Crear líneas de factura
        update_step("📝 Preparando líneas de factura...")
        invoice_lines = []
        for line in order_lines:
            invoice_line = {
                'product_id': line['product_id'][0],
                'name': line['name'],
                'quantity': line['product_uom_qty'],
                'product_uom_id': line['product_uom'][0],
                'price_unit': line['price_unit'],
                'tax_ids': [(6, 0, line['tax_id'])],
                'sale_line_ids': [(6, 0, [line['id']])]  # Vinculación directa con la línea de venta
            }
            invoice_lines.append((0, 0, invoice_line))

        current_step += 1
        progress_bar.progress(current_step * progress_step)

        # Crear factura
        update_step("📄 Creando factura...")
        invoice_vals = {
            'partner_id': partner_id,
            'move_type': 'out_invoice',
            'invoice_date': invoice_date,
            'date': invoice_date,
            'journal_id': 1,  # Diario de ventas
            'invoice_origin': reserva,
            'ref': reserva,  # Referencia a la orden
            'invoice_line_ids': invoice_lines
        }

        invoice_id = models.execute_kw(db, uid, password, 'account.move', 'create', [invoice_vals])
        if not invoice_id:
            update_step("❌ Error al crear factura")
            return {
                'Reserva': reserva,
                'Status': 'Error',
                'Mensaje': 'Error al crear factura',
                'Estado_Orden': order_status['Estado'],
                'Estado_Factura': order_status['Estado_Factura'],
                'Factura': 'No',
                'Pago': 'No',
                'Conciliación': 'No'
            }

        current_step += 1
        progress_bar.progress(current_step * progress_step)

        # Publicar factura
        update_step("📣 Publicando factura...")
        models.execute_kw(db, uid, password, 'account.move', 'action_post', [[invoice_id]])
        update_step(f"✅ Factura creada y publicada con ID: {invoice_id}")

        current_step += 1
        progress_bar.progress(current_step * progress_step)

        # Actualizar la orden de venta
        update_step("🔄 Actualizando orden de venta...")
        try:
            # Actualizar el estado de facturación de la orden
            models.execute_kw(db, uid, password, 'sale.order', 'write', [
                [sale_order_ids[0]], 
                {'invoice_status': 'invoiced'}
            ])

            # Establecer relación directa entre orden y factura
            try:
                models.execute_kw(db, uid, password, 'sale.order', 'write', [
                    [sale_order_ids[0]], 
                    {'invoice_ids': [(4, invoice_id, 0)]}
                ])
                update_step("✅ Orden de venta vinculada con factura")
            except Exception as e:
                update_step(f"⚠️ No se pudo establecer relación orden-factura: {str(e)}")
        except Exception as e:
            update_step(f"⚠️ Error al actualizar la orden de venta: {str(e)}")

        # Registrar el pago para la factura (sea existente o recién creada)
        current_step += 1
        progress_bar.progress(current_step * progress_step)

        payment_data = {
            'amount': monto,
            'date': invoice_date,
            'journal_id': journal_id,
            'memo': memo
        }

    # Registrar el pago para la factura (sea existente o recién creada)
    update_step("💰 Registrando pago...")

    current_step += 1
    progress_bar.progress(current_step * progress_step)

    if register_payment_from_invoice(models, db, uid, password, invoice_id, payment_data, update_step):
        current_step += 1
        progress_bar.progress(1.0)  # Completar la barra
        update_step("✅ Proceso completado exitosamente")
        # Determinar estado del pago
        estado_pago = 'Parcial' if es_pago_parcial else 'Total'
        
        return {
            'Reserva': reserva,
            'Status': 'Éxito',
            'Mensaje': f'Proceso completado exitosamente (Pago {estado_pago})',
            'Estado_Orden': order_status['Estado'],
            'Estado_Factura': 'invoiced',  # Ahora está facturado
            'Factura': str(invoice_id),
            'Pago': estado_pago,
            'Conciliación': 'Si'
        }
    else:
        current_step += 1
        progress_bar.progress(current_step * progress_step)
        update_step("⚠️ Factura creada, error al registrar pago")
        return {
            'Reserva': reserva,
            'Status': 'Parcial',
            'Mensaje': 'Factura creada, error al registrar pago',
            'Estado_Orden': order_status['Estado'],
            'Estado_Factura': 'invoiced',  # Parcialmente facturado
            'Factura': str(invoice_id),
            'Pago': 'No',
            'Conciliación': 'No'
        }

def generate_excel_template():
    """Genera un template de Excel con datos de ejemplo"""
    # Crear un DataFrame con las columnas requeridas y un registro de ejemplo
    df = pd.DataFrame([
        {
            'Fecha Pago': '01/09/2025',
            'Reserva': 'S12345',
            'Pago': 1,  # 1 = Pago total, 0 = Pago parcial
            'Forma de Pago': 'TRANSF',
            'Monto Abono': 150000
        },
        {
            'Fecha Pago': '02/09/2025',
            'Reserva': 'S12346',
            'Pago': 0,  # Ejemplo de pago parcial
            'Forma de Pago': 'DEP',
            'Monto Abono': 75000
        }
    ])
    
    # Crear un archivo temporal
    temp_file = 'template_pagos_temp.xlsx'
    
    # Guardar el DataFrame como Excel
    df.to_excel(temp_file, index=False)
    
    # Leer el archivo como bytes
    with open(temp_file, 'rb') as f:
        data = f.read()
    
    # Eliminar el archivo temporal
    if os.path.exists(temp_file):
        os.remove(temp_file)
    
    return data

def main():
    st.title("Importación de Pagos a Odoo")
    
    # Crear una sección para el template
    st.sidebar.markdown("---")
    st.sidebar.subheader("Formato de Archivo")
    st.sidebar.info("""
    Para importar pagos, necesitas un archivo Excel con las siguientes columnas:
    - **Fecha Pago**: Fecha en formato DD/MM/AAAA
    - **Reserva**: Código de reserva Ej: S12345 (máx. 6 caracteres)
    - **Pago**: 1 = Pago total, 0 = Pago parcial
    - **Forma de Pago**: TRANSF, DEP, BEX, CV, IN, SBE, EFECT OF, MAQ/TD, MAQ/TC, WEBPAY, IPS
    - **Monto Abono**: Valor numérico del pago
    """)
    
    # Añadir botón para descargar template en el sidebar
    excel_data = generate_excel_template()
    st.sidebar.download_button(
        label="📥 Descargar Template Excel",
        data=excel_data,
        file_name="template_pagos.xlsx",
        mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        help="Descarga un archivo Excel con el formato correcto y ejemplos para importar pagos"
    )
    
    # Mostrar formulario de login y obtener credenciales
    url, db, username, password = show_login_form()

    # Verificar si el usuario está logueado
    is_logged_in = all([url, db, username, password])

    if not is_logged_in:
        st.warning("Por favor inicie sesión para acceder a la herramienta.")
        return

    # Mostrar nombre de usuario en la barra lateral
    st.sidebar.success(f"✅ Conectado como: {username}")

    # Botón para cerrar sesión
    if st.sidebar.button("Cerrar Sesión"):
        # Eliminar todas las credenciales y el estado de login
        for key in ['odoo_url', 'odoo_db', 'odoo_username', 'odoo_password', 'is_logged_in', 'processing_complete']:
            if key in st.session_state:
                del st.session_state[key]
        st.experimental_rerun()
    
    st.write("Esta herramienta permite importar pagos a Odoo desde un archivo Excel.")
    
    # Inicializar la variable de estado si no existe
    if 'processing_complete' not in st.session_state:
        st.session_state['processing_complete'] = False

    # Crear contenedor para estado general
    status_container = st.empty()
    progress_container = st.empty()
    details_container = st.empty()
    
    # Mostrar el formulario de carga solo si no hay un procesamiento completo
    if not st.session_state['processing_complete']:
        uploaded_file = st.file_uploader("Cargar archivo Excel", type=['xlsx'])
    else:
        uploaded_file = None

    # Procesar el archivo subido o mostrar los resultados anteriores
    if st.session_state['processing_complete']:
        # Mostrar los resultados guardados en la sesión
        if 'processing_results' in st.session_state and 'results_df' in st.session_state:
            results = st.session_state['processing_results']
            results_df = st.session_state['results_df']
            
            # Mostrar el mensaje de éxito
            st.success(f"✅ Procesamiento completado: {results['total_processed']} registros")
            
            # Botón de descarga del log
            st.download_button(
                label="Descargar Log Completo",
                data=st.session_state['log_file'].encode('utf-8'),
                file_name="log_procesamiento.txt",
                mime="text/plain",
                key="persistent_download_log"
            )
            
            # Mostrar resultados
            st.write("### Resultados del Procesamiento:")
            
            # Función para colorear las filas según el resultado
            def highlight_status(row):
                if row['Status'] == 'Éxito':
                    # Diferenciar entre pagos totales y parciales
                    if row['Pago'] == 'Parcial':
                        return ['background-color: #E6FFCC'] * len(row)  # Verde más claro para pagos parciales
                    else:
                        return ['background-color: #CCFFCC'] * len(row)  # Verde estándar para pagos totales
                elif row['Status'] == 'Parcial':
                    return ['background-color: #FFFFCC'] * len(row)  # Amarillo para éxito parcial (factura sin pago)
                elif row['Status'] == 'Omitido':
                    return ['background-color: #EFEFEF'] * len(row)  # Gris para omitidos
                else:
                    return ['background-color: #FFCCCC'] * len(row)  # Rojo para errores
            
            # Mostrar el dataframe con los resultados
            if isinstance(results_df, pd.DataFrame) and not results_df.empty:
                st.dataframe(results_df.style.apply(highlight_status, axis=1))
            
                # Mostrar resumen
                st.write("Resumen:")
                col1, col2, col3 = st.columns(3)
                with col1:
                    st.metric("Total procesados", results['total_processed'])
                with col2:
                    st.metric("Facturas creadas", results['facturas_creadas'])
                with col3:
                    st.metric("Pagos registrados", results['pagos_registrados'])
                
                col1, col2, col3 = st.columns(3)
                with col1:
                    st.metric("Conciliaciones exitosas", results['conciliaciones_exitosas'])
                with col2:
                    st.metric("Órdenes omitidas", results['ordenes_omitidas'])
                with col3:
                    st.metric("Tasa de éxito", f"{results['success_rate']}%")
            
            # Descargar resultados
            st.download_button(
                label="Descargar Resultados",
                data=results_df.to_csv(index=False).encode('utf-8'),
                file_name="resultados_importacion.csv",
                mime="text/csv",
                key="persistent_download_results"
            )
            
            # Botón para iniciar una nueva carga de datos
            st.write("")
            st.write("")
            if st.button("Iniciar una nueva carga de datos", key="persistent_new_upload"):
                # Reiniciar el estado pero mantener las credenciales de sesión
                for key in ['orders_status_df', 'validation_complete', 'show_process_button', 
                          'processing_complete', 'processing_results', 'log_file', 'results_df']:
                    if key in st.session_state:
                        del st.session_state[key]
                st.experimental_rerun()
    elif uploaded_file is not None:
        try:
            # Cargar el Excel pero sin procesar las fechas aún
            df = pd.read_excel(uploaded_file)

            # Mostrar vista previa de los datos
            st.write("Vista previa de los datos:")
            st.dataframe(df.head())

            # Validar las columnas requeridas primero
            required_columns = ['Fecha Pago', 'Reserva', 'Pago', 'Monto Abono', 'Forma de Pago']
            missing_columns = [col for col in required_columns if col not in df.columns]

            if missing_columns:
                st.error(f"El archivo no contiene todas las columnas requeridas. Faltan: {', '.join(missing_columns)}")
                return

            # Convertir la columna de fecha una vez que sabemos que existe
            df['Fecha Pago'] = pd.to_datetime(df['Fecha Pago'], errors='coerce')

            # Validar el formato completo del Excel
            is_valid_format, errors_df = validate_excel_format(df)

            if not is_valid_format:
                st.error("⚠️ El archivo Excel contiene errores de formato que deben corregirse antes de procesar.")

                # Mostrar los errores en una tabla con colores
                st.write("Errores encontrados:")
                st.dataframe(errors_df.style.apply(lambda _: ['background-color: #FFCCCC'] * len(errors_df.columns), axis=1))

                # Opción para descargar los errores
                st.download_button(
                    label="Descargar Errores",
                    data=errors_df.to_csv(index=False).encode('utf-8'),
                    file_name="errores_formato.csv",
                    mime="text/csv"
                )
                return

            # Si el formato es válido, mostrar mensaje de éxito y habilitar botón para validar órdenes
            st.success("✅ Formato del archivo Excel validado correctamente.")

            # Crear un botón para validar el estado de las órdenes
            if st.button("Validar Estado de Órdenes"):
                # Conectar a Odoo para validar órdenes
                models, db, uid, password = connect_to_odoo()
                if not all([models, db, uid, password]):
                    status_container.error("❌ No se pudo conectar a Odoo")
                    return

                # Validar el estado de las órdenes
                status_container.info("Validando estado de las órdenes...")
                orders_status_df = validate_orders_status(models, db, uid, password, df)

                # Mostrar los resultados de la validación
                st.write("Estado de las órdenes:")

                # Aplicar colores según el estado
                def highlight_rows(row):
                    if not row['Existe']:
                        return ['background-color: #FFCCCC'] * len(row)
                    elif not row['Puede_Procesar']:
                        return ['background-color: #FFFFCC'] * len(row)
                    else:
                        return ['background-color: #CCFFCC'] * len(row)

                st.dataframe(orders_status_df.style.apply(highlight_rows, axis=1))

                # Calcular estadísticas
                total_orders = len(orders_status_df)
                valid_orders = len(orders_status_df[orders_status_df['Puede_Procesar']])
                invalid_orders = total_orders - valid_orders

                # Mostrar resumen
                st.write("Resumen de validación:")
                col1, col2, col3 = st.columns(3)
                with col1:
                    st.metric("Total de órdenes", total_orders)
                with col2:
                    st.metric("Órdenes válidas", valid_orders)
                with col3:
                    st.metric("Órdenes no procesables", invalid_orders)

                # Opción para descargar los resultados de la validación
                st.download_button(
                    label="Descargar Resultados de Validación",
                    data=orders_status_df.to_csv(index=False).encode('utf-8'),
                    file_name="validacion_ordenes.csv",
                    mime="text/csv"
                )

                # Solo mostrar el botón de procesar cuando TODAS las órdenes sean válidas (100%)
                if valid_orders > 0 and valid_orders == total_orders and invalid_orders == 0:
                    st.session_state['orders_status_df'] = orders_status_df
                    st.session_state['validation_complete'] = True
                    st.success(f"✅ Todas las {total_orders} órdenes están listas para procesar.")
                    st.info("💡 **Recomendación**: Puede limpiar la base de datos antes de procesar si lo desea.")
                    st.session_state['show_process_button'] = True  # Mostrar botón solo cuando 100% están aptos
                elif valid_orders > 0:
                    st.session_state['orders_status_df'] = orders_status_df
                    st.session_state['validation_complete'] = True
                    st.warning(f"⚠️ Solo {valid_orders} de {total_orders} órdenes están listas para procesar. Corrija los {invalid_orders} registros con problemas antes de continuar.")
                    st.session_state['show_process_button'] = False  # Ocultar botón cuando hay registros mixtos
                else:
                    st.warning("⚠️ No hay órdenes válidas para procesar. Corrija los problemas identificados e intente nuevamente.")
                    st.session_state['show_process_button'] = False

            # Botón para procesar pagos (solo se muestra si la validación está completa)
            if st.session_state.get('show_process_button', False):
                if st.button("Procesar Pagos"):
                    # Recuperar datos validados
                    orders_status_df = st.session_state['orders_status_df']

                    # Conectar a Odoo si es necesario
                    if 'models' not in locals():
                        models, db, uid, password = connect_to_odoo()
                        if not all([models, db, uid, password]):
                            status_container.error("❌ No se pudo conectar a Odoo")
                            return

                    # Crear contenedores para el seguimiento del progreso
                    st.write("### Progreso del Procesamiento")
                    col1, col2 = st.columns([2, 1])

                    with col1:
                        st.write("#### Progreso General:")
                        overall_progress = st.progress(0)
                        overall_status = st.empty()

                    with col2:
                        st.write("#### Estadísticas:")
                        processed_counter = st.empty()
                        success_counter = st.empty()
                        error_counter = st.empty()

                    # Crear contenedor para el log de actividad
                    st.write("#### Log de Actividad:")
                    log_container = st.container()
                    with log_container:
                        log_placeholder = st.empty()

                    # Crear contenedor para el registro actual
                    st.write("#### Registro Actual:")
                    current_record_container = st.container()
                    with current_record_container:
                        current_record_info = st.empty()
                        record_progress = st.progress(0)
                        current_step_info = st.empty()

                    
                    # Preparar variables para el procesamiento
                    results = []
                    log_entries = []
                    processed = 0
                    successful = 0
                    errors = 0
                    
                    # Número de pasos en el proceso
                    total_steps = 10
                    progress_step = 1.0 / total_steps
                    
                    # Validar el formato del archivo
                    validation_errors = validate_excel_format(df)
                    if validation_errors and isinstance(validation_errors, list) and validation_errors:
                        st.error("\n".join([str(error) for error in validation_errors]))
                        return
                    
                    # Conectar a Odoo
                    models, db, uid, password = connect_to_odoo()
                    if not models:
                        st.error("No se pudo conectar a Odoo. Verifique sus credenciales.")
                        return
                        
                    # Preparar DataFrame para el estado de las órdenes
                    # Esto reemplaza la función check_orders_status que no está implementada
                    orders_data = []
                    for _, row in df.iterrows():
                        reserva = "Desconocido"
                        try:
                            reserva = str(row['Reserva']).strip()
                            # Buscar la orden en Odoo
                            domain = [('name', '=', reserva)]
                            sale_order_ids = models.execute_kw(db, uid, password, 'sale.order', 'search', [domain])
                            
                            if not sale_order_ids:
                                orders_data.append({
                                    'Reserva': reserva,
                                    'Puede_Procesar': False,
                                    'Motivo': 'Orden no encontrada en Odoo',
                                    'Estado': 'No encontrado',
                                    'Estado_Factura': 'N/A'
                                })
                                continue
                                
                            # Obtener detalles de la orden
                            # Usamos try-except para manejar posibles errores de tipo
                            try:
                                order_id = sale_order_ids[0] if isinstance(sale_order_ids, list) and len(sale_order_ids) > 0 else 0
                                sale_order = models.execute_kw(db, uid, password, 'sale.order', 'read',
                                    [order_id], {'fields': ['state', 'invoice_status']})
                            except (TypeError, IndexError) as e:
                                st.error(f"Error al obtener detalles de la orden {reserva}: {str(e)}")
                                sale_order = []
                            
                            if not sale_order or not isinstance(sale_order, list) or len(sale_order) == 0:
                                orders_data.append({
                                    'Reserva': reserva,
                                    'Puede_Procesar': False,
                                    'Motivo': 'No se pudieron obtener detalles de la orden',
                                    'Estado': 'Error',
                                    'Estado_Factura': 'N/A'
                                })
                                continue
                                
                            sale_order_data = sale_order[0]
                            
                            # Verificar si la orden puede ser procesada
                            puede_procesar = True  # Por defecto, asumimos que es procesable
                            motivo = ''
                            
                            state = sale_order_data.get('state', '')
                            invoice_status = sale_order_data.get('invoice_status', '')
                            
                            # Verificar estado de la orden
                            if state not in ['sale', 'done']:
                                puede_procesar = False
                                motivo = f"Estado de orden inválido: {state}"
                            
                            # Verificar si hay un monto de abono válido
                            try:
                                # Asegurar que el valor existe y es convertible a float
                                if 'Monto Abono' in row and row['Monto Abono'] is not None:
                                    monto_abono = float(row['Monto Abono'])
                                    if monto_abono <= 0:
                                        puede_procesar = False
                                        motivo = "Monto de abono inválido o cero"
                                else:
                                    puede_procesar = False
                                    motivo = "No se encontró monto de abono"
                            except (ValueError, TypeError):
                                puede_procesar = False
                                motivo = "Monto de abono no es un número válido"
                                
                            # Verificar si la orden ya está pagada completamente
                            if invoice_status == 'invoiced':
                                # Verificar si es pago total
                                es_pago_total = False
                                if isinstance(row, dict) and 'Pago' in row:
                                    try:
                                        if int(row['Pago']) == 1:
                                            es_pago_total = True
                                    except (ValueError, TypeError):
                                        pass
                                
                                if es_pago_total:
                                    # Obtener facturas de la orden
                                    try:
                                        invoice_ids = models.execute_kw(db, uid, password, 'account.move', 'search',
                                                                    [[('invoice_origin', '=', reserva), ('move_type', '=', 'out_invoice')]])
                                        if invoice_ids:
                                            invoice_data = models.execute_kw(db, uid, password, 'account.move', 'read',
                                                                        [invoice_ids[0]], {'fields': ['payment_state']})
                                            if invoice_data and isinstance(invoice_data, list) and len(invoice_data) > 0:
                                                invoice_info = invoice_data[0]
                                                if isinstance(invoice_info, dict) and 'payment_state' in invoice_info:
                                                    if invoice_info['payment_state'] == 'paid':
                                                        puede_procesar = False
                                                        motivo = "La orden ya está completamente pagada"
                                    except Exception as e:
                                        # Si hay error al verificar, permitimos procesar pero lo registramos
                                        st.warning(f"Advertencia al verificar pagos de {reserva}: {str(e)}")
                            
                                
                            orders_data.append({
                                'Reserva': reserva,
                                'Puede_Procesar': puede_procesar,
                                'Motivo': motivo,
                                'Estado': state,
                                'Estado_Factura': invoice_status
                            })
                        except Exception as e:
                            st.error(f"Error al verificar estado de orden {reserva}: {str(e)}")
                            orders_data.append({
                                'Reserva': reserva,
                                'Puede_Procesar': False,
                                'Motivo': f"Error: {str(e)}",
                                'Estado': 'Error',
                                'Estado_Factura': 'Error'
                            })
                    
                    # Crear DataFrame con los estados de las órdenes
                    orders_status_df = pd.DataFrame(orders_data)

                    # Filtrar solo las órdenes que pueden ser procesadas
                    # Asegurar que todas las reservas están en formato string limpio para comparación
                    orders_status_df['Reserva_Str'] = orders_status_df['Reserva'].astype(str).str.strip()
                    
                    # Verificar explícitamente que Puede_Procesar sea True (no solo truthy)
                    # Esto evita problemas con valores que podrían evaluarse como True pero no son exactamente True
                    procesable_df = orders_status_df[orders_status_df['Puede_Procesar'].apply(lambda x: x is True)]
                    procesable_orders = procesable_df['Reserva_Str'].tolist()
                    
                    # Log de depuración - Órdenes procesables (eliminado - ya no necesario)
                    # Solo procesar órdenes validadas
                    
                    # Filtrar el DataFrame original para incluir solo órdenes procesables
                    # Convertir las reservas a string y eliminar espacios para comparación exacta
                    df['Reserva_Clean'] = df['Reserva'].astype(str).str.strip()
                    df_procesable = df[df['Reserva_Clean'].isin(procesable_orders)].copy()
                    
                    # Guardar el DataFrame de validación en la sesión para usarlo en el paso de procesamiento
                    st.session_state['orders_status_df'] = orders_status_df
                    
                    # Guardar el DataFrame filtrado en la sesión
                    st.session_state['df_procesable'] = df_procesable
                    
                    # Calcular estadísticas
                    total_registros = len(df)
                    registros_procesables = len(df_procesable)
                    registros_filtrados = total_registros - registros_procesables
                    
                    if registros_procesables == 0:
                        st.error("\u274c No hay registros procesables. Por favor, revise los datos y vuelva a intentarlo.")
                        return
                    
                    # NUEVO: Impedir procesar si hay registros no procesables
                    if registros_filtrados > 0:
                        st.error(f"⛔ No se puede continuar. Hay {registros_filtrados} registros que no son procesables.")
                        st.warning("Para continuar, todos los registros deben ser procesables. Por favor, corrija los errores o elimine los registros con problemas del archivo Excel.")
                        
                        # Mostrar qué registros fueron filtrados con sus motivos
                        registros_no_procesables = df[~df['Reserva_Clean'].isin(procesable_orders)]
                        st.write("### Registros no procesables:")
                        
                        # Unir con el DataFrame de validación para mostrar los motivos
                        registros_no_procesables['Reserva_Str'] = registros_no_procesables['Reserva_Clean']
                        merged_df = pd.merge(
                            registros_no_procesables[['Reserva', 'Reserva_Str', 'Monto Abono']], 
                            orders_status_df[['Reserva_Str', 'Motivo']], 
                            on='Reserva_Str',
                            how='left'
                        )
                        
                        st.dataframe(merged_df[['Reserva', 'Monto Abono', 'Motivo']])
                        return
                    
                    # NO modificar el DataFrame orders_status_df original, ya que contiene la información completa de validación
                    # En su lugar, usar el DataFrame filtrado procesable_df para el procesamiento
                    
                    # Confirmar que solo se procesarán los registros correctos
                    st.success(f"Se procesarán únicamente {registros_procesables} registros válidos.")
                    
                    # Reiniciar contadores y variables para el procesamiento
                    results = []
                    log_entries = []
                    processed = 0
                    successful = 0
                    errors = 0
                    
                    for index, row in df_procesable.iterrows():
                        # Actualizar progreso general
                        try:
                            # Convertir explícitamente a tipos numéricos para evitar errores de tipo
                            df_len = len(df_procesable) if hasattr(df_procesable, '__len__') else 0
                            if df_len > 0:
                                # Asegurar que index sea un número
                                idx_num = index if isinstance(index, (int, float)) else 0
                                progress_percent = float(idx_num) / float(df_len)
                                # Calcular el índice para mostrar (1-based)
                                idx_display = int(idx_num) + 1 if isinstance(idx_num, (int, float)) else 1
                                # Calcular el porcentaje para mostrar
                                percent_display = int(progress_percent * 100)
                            else:
                                progress_percent = 0.0
                                idx_display = 1
                                percent_display = 0
                            overall_progress.progress(progress_percent)
                            overall_status.info(f"Procesando registro {idx_display} de {df_len} ({percent_display}%)")

                        except Exception as e:
                            st.warning(f"Error al actualizar progreso: {str(e)}")
                            overall_progress.progress(0)
                            overall_status.info("Procesando registros...")

                        
                        # Formatear la fecha
                        fecha_pago = None
                        try:
                            # Verificar si el valor existe y no es NaN
                            if 'Fecha Pago' in row and pd.notna(row['Fecha Pago']):
                                # Intentar formatear la fecha
                                if hasattr(row['Fecha Pago'], 'strftime'):
                                    fecha_pago = row['Fecha Pago'].strftime('%Y-%m-%d')
                                else:
                                    fecha_pago = str(row['Fecha Pago'])
                        except Exception as e:
                            st.warning(f"Error al formatear fecha: {str(e)}")
                            fecha_pago = "Fecha no válida"
                        
                        # Mostrar información del registro actual
                        try:
                            reserva = str(row.get('Reserva', 'N/A')) if hasattr(row, 'get') else str(row['Reserva'] if 'Reserva' in row else 'N/A')
                            forma_pago = str(row.get('Forma de Pago', 'N/A')) if hasattr(row, 'get') else str(row['Forma de Pago'] if 'Forma de Pago' in row else 'N/A')
                            monto = str(row.get('Monto Abono', 0)) if hasattr(row, 'get') else str(row['Monto Abono'] if 'Monto Abono' in row else 0)
                            current_record_info.info(f"Procesando: Reserva {reserva} - {fecha_pago} - {forma_pago} - ${monto}")
                        except Exception as e:
                            st.warning(f"Error al mostrar información del registro: {str(e)}")
                            current_record_info.info("Procesando registro...")
                        
                        
                        # Resetear progreso del registro
                        record_progress.progress(0)
                        current_step_info.info("Iniciando procesamiento...")

                        # Definir una función para actualizar el paso actual
                        def update_step_info(message):
                            current_step_info.info(message)
                            # Añadir al log
                            timestamp = datetime.now().strftime("%H:%M:%S")
                            log_entries.append(f"[{timestamp}] [{row['Reserva']}] {message}")
                            # Mostrar log actualizado (últimas 10 entradas)
                            log_placeholder.code("\n".join(log_entries[-10:]))

                        # Log de depuración antes de procesar
                        update_step_info(f"Procesando registro con reserva: {row['Reserva']} (Reserva_Clean: {row['Reserva_Clean']})")
                        
                        # Procesar registro con función de actualización
                        result = process_record(models, db, uid, password, row, orders_status_df, 
                                             record_progress, progress_step, update_step_info)
                        
                        # Log del resultado
                        update_step_info(f"Resultado del procesamiento: {result['Status']} - {result['Mensaje']}")
                        results.append(result)

                        # Actualizar contadores
                        processed += 1
                        if result['Status'] == 'Éxito':
                            successful += 1
                        elif result['Status'] == 'Error':
                            errors += 1

                        # Actualizar estadísticas
                        processed_counter.metric("Procesados", f"{processed}/{len(df_procesable)}")
                        success_counter.metric("Exitosos", successful)
                        error_counter.metric("Errores", errors)

                        # Pequeña pausa para visualizar
                        time.sleep(0.5)

                    # Completar progreso general
                    overall_progress.progress(1.0)
                    overall_status.success(f"✅ Procesamiento completado: {len(df_procesable)} registros procesables de {len(df)} totales")
                    
                    # Guardar log completo y resultados en la sesión
                    log_file = "\n".join(log_entries)
                    st.session_state['log_file'] = log_file
                    
                    # Crear DataFrame con los resultados
                    results_df = pd.DataFrame(results)
                    
                    # Guardar en session_state antes de calcular métricas para evitar errores de lint
                    st.session_state['results_df'] = results_df
                    
                    # Calcular las métricas
                    if isinstance(results_df, pd.DataFrame) and not results_df.empty:
                        total_processed = len(results_df)
                        facturas_creadas = len(results_df[results_df['Factura'] != 'No'])
                        pagos_registrados = len(results_df[results_df['Pago'] == 'Registrado'])
                        conciliaciones_exitosas = len(results_df[results_df['Conciliación'] == 'Si'])
                        ordenes_omitidas = len(results_df[results_df['Status'] == 'Omitido'])
                        processed_orders = len(results_df[results_df['Status'] != 'Omitido'])
                        success_rate = round(len(results_df[results_df['Status'] == 'Éxito']) / max(processed_orders, 1) * 100, 2)
                        
                        # Guardar todos los datos necesarios para mantener la vista de resultados
                        st.session_state['processing_results'] = {
                            'log_file': log_file,
                            'total_processed': total_processed,
                            'facturas_creadas': facturas_creadas,
                            'pagos_registrados': pagos_registrados,
                            'conciliaciones_exitosas': conciliaciones_exitosas,
                            'ordenes_omitidas': ordenes_omitidas,
                            'success_rate': success_rate
                        }
                        
                        # Marcar que el procesamiento está completo
                        st.session_state['processing_complete'] = True
                    
                    # Botón de descarga que usa los datos guardados en la sesión
                    st.download_button(
                        label="Descargar Log Completo",
                        data=log_file.encode('utf-8'),
                        file_name="log_procesamiento.txt",
                        mime="text/plain",
                        key="download_log"
                    )

                    # Mostrar resultados
                    st.write("### Resultados del Procesamiento:")
                    results_df = pd.DataFrame(results)
                    column_order = ['Reserva', 'Status', 'Estado_Orden', 'Estado_Factura', 'Factura', 'Pago', 'Conciliación', 'Mensaje']
                    results_df = results_df[column_order]

                    # Función para colorear las filas según el resultado
                    def highlight_status(row):
                        if row['Status'] == 'Éxito':
                            # Diferenciar entre pagos totales y parciales
                            if row['Pago'] == 'Parcial':
                                return ['background-color: #E6FFCC'] * len(row)  # Verde más claro para pagos parciales
                            else:
                                return ['background-color: #CCFFCC'] * len(row)  # Verde estándar para pagos totales
                        elif row['Status'] == 'Parcial':
                            return ['background-color: #FFFFCC'] * len(row)  # Amarillo para éxito parcial (factura sin pago)
                        elif row['Status'] == 'Omitido':
                            return ['background-color: #EFEFEF'] * len(row)  # Gris para omitidos
                        else:
                            return ['background-color: #FFCCCC'] * len(row)  # Rojo para errores

                    st.dataframe(results_df.style.apply(highlight_status, axis=1))

                    # Mostrar resumen
                    st.write("Resumen:")
                    col1, col2, col3 = st.columns(3)
                    with col1:
                        st.metric("Total procesados", len(results_df))
                    with col2:
                        st.metric("Facturas creadas", len(results_df[results_df['Factura'] != 'No']))
                    with col3:
                        st.metric("Pagos registrados", len(results_df[results_df['Pago'] == 'Registrado']))

                    col1, col2, col3 = st.columns(3)
                    with col1:
                        st.metric("Conciliaciones exitosas", len(results_df[results_df['Conciliación'] == 'Si']))
                    with col2:
                        st.metric("Órdenes omitidas", len(results_df[results_df['Status'] == 'Omitido']))
                    with col3:
                        processed_orders = len(results_df[results_df['Status'] != 'Omitido'])
                        if processed_orders > 0:
                            success_rate = round(len(results_df[results_df['Status'] == 'Éxito']) / processed_orders * 100, 2)
                        else:
                            success_rate = 0
                        st.metric("Tasa de éxito", f"{success_rate}%")

                    # Descargar resultados
                    st.download_button(
                        label="Descargar Resultados",
                        data=results_df.to_csv(index=False).encode('utf-8'),
                        file_name="resultados_importacion.csv",
                        mime="text/csv",
                        key="download_results"
                    )
                    
                    # Marcar el procesamiento como completo para mantener los resultados visibles
                    st.session_state['processing_complete'] = True
                    
                    # Botón para iniciar una nueva carga de datos
                    st.write("")
                    st.write("")
                    if st.button("Iniciar una nueva carga de datos", key="new_upload"):
                        # Reiniciar el estado pero mantener las credenciales de sesión
                        for key in ['orders_status_df', 'validation_complete', 'show_process_button', 
                                  'processing_complete', 'processing_results', 'log_file', 'results_df']:
                            if key in st.session_state:
                                del st.session_state[key]
                        st.experimental_rerun()

        except Exception as e:
            st.error(f"Error al procesar el archivo: {str(e)}")
            import traceback
            st.error(traceback.format_exc())

main()