import streamlit as st
import pandas as pd
import xmlrpc.client
import os
from datetime import datetime
from dotenv import load_dotenv
import io
import pytz
import time
import re

# Importar configuración de navegación
from app_config import setup_page_navigation, get_current_page

# Importar componente del formateador IPS
from components.formateador_ips.streamlit_component import render_ips_formatter

# Cargar variables de entorno
load_dotenv()

def show_login_form():
    """Muestra el formulario de login y retorna las credenciales"""
    # Obtener URL y DB desde variables de entorno (solo lectura)
    url = os.getenv('ODOO_URL', '')
    db = os.getenv('ODOO_DB', '')
    
    if not url or not db:
        st.error("⚠️ Configuración de Odoo incompleta. Defina ODOO_URL y ODOO_DB en el archivo .env.")
        return None, None, None, None
    
    # Obtener credenciales de usuario desde session_state
    default_username = st.session_state.get('odoo_username', '')
    default_password = st.session_state.get('odoo_password', '')
    
    return url, db, default_username, default_password

def connect_to_odoo():
    """Conecta a Odoo usando las credenciales almacenadas"""
    try:
        url = st.session_state.get('odoo_url', '')
        db = st.session_state.get('odoo_db', '')
        username = st.session_state.get('odoo_username', '')
        password = st.session_state.get('odoo_password', '')
        
        if not all([url, db, username, password]):
            return None, None, None, None
        
        # Conectar a Odoo
        common = xmlrpc.client.ServerProxy(f'{url}/xmlrpc/2/common')
        uid = common.authenticate(db, username, password, {})
        
        if uid:
            models = xmlrpc.client.ServerProxy(f'{url}/xmlrpc/2/object')
            return models, db, uid, password
        else:
            return None, None, None, None
            
    except Exception as e:
        st.error(f"Error al conectar con Odoo: {str(e)}")
        return None, None, None, None

def generate_excel_template():
    """Genera un archivo Excel de ejemplo con el formato correcto"""
    # Datos de ejemplo
    data = {
        'Fecha Pago': ['01/01/2024', '02/01/2024', '03/01/2024'],
        'Reserva': ['S12345', 'S12346', 'S12347'],
        'Pago': [1, 0, 1],
        'Forma de Pago': ['TRANSF', 'WEBPAY', 'EFECT'],
        'Monto Abono': [150000, 75000, 200000]
    }
    
    df = pd.DataFrame(data)
    
    # Crear archivo Excel en memoria
    output = io.BytesIO()
    with pd.ExcelWriter(output, engine='openpyxl') as writer:
        df.to_excel(writer, index=False, sheet_name='Pagos')
    
    return output.getvalue()

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

        # Validar Fecha Pago
        if pd.isna(row['Fecha Pago']):
            row_errors.append("Fecha Pago vacía")
        elif not isinstance(row['Fecha Pago'], (datetime, pd.Timestamp)):
            row_errors.append("Fecha Pago no es una fecha válida")

        # Validar Reserva
        if pd.isna(row['Reserva']):
            row_errors.append("Reserva vacía")
        else:
            reserva_str = str(row['Reserva']).strip()
            if len(reserva_str) == 0:
                row_errors.append("Reserva vacía")
            elif len(reserva_str) > 6:
                row_errors.append("Reserva excede 6 caracteres")

        # Validar Pago (debe ser 0 o 1)
        if pd.isna(row['Pago']):
            row_errors.append("Campo Pago vacío")
        elif row['Pago'] not in [0, 1]:
            row_errors.append("Campo Pago debe ser 0 (parcial) o 1 (total)")

        # Validar Monto Abono
        if pd.isna(row['Monto Abono']):
            row_errors.append("Monto Abono vacío")
        else:
            try:
                monto = float(row['Monto Abono'])
                if monto <= 0:
                    row_errors.append("Monto Abono debe ser mayor a 0")
            except (ValueError, TypeError):
                row_errors.append("Monto Abono no es un número válido")

        # Validar Forma de Pago
        if pd.isna(row['Forma de Pago']):
            row_errors.append("Forma de Pago vacía")
        else:
            forma_pago = str(row['Forma de Pago']).strip().upper()
            if forma_pago not in valid_payment_methods:
                row_errors.append(f"Forma de Pago '{forma_pago}' no válida. Valores permitidos: {', '.join(sorted(valid_payment_methods))}")

        # Si hay errores en esta fila, agregarlos al registro de errores
        if row_errors:
            is_valid = False
            for error in row_errors:
                error_records.append({
                    'Fila': index + 2,  # +2 porque Excel empieza en 1 y tiene header
                    'Reserva': str(row.get('Reserva', 'N/A')),
                    'Error': error
                })

    # Crear DataFrame con los errores
    if error_records:
        errors_df = pd.DataFrame(error_records)
    else:
        errors_df = pd.DataFrame()

    return is_valid, errors_df

def validate_orders_status(models, db, uid, password, df):
    """Valida el estado de las órdenes en Odoo con lógica completa de conciliación"""
    orders_info = []
    
    # Crear barra de progreso
    progress_bar = st.progress(0)
    status_container = st.empty()
    
    total_orders = len(df)
    
    # Crear columna limpia de reserva para comparaciones
    df['Reserva_Clean'] = df['Reserva'].astype(str).str.strip()
    
    for order_num, (index, row) in enumerate(df.iterrows(), start=1):
        # Actualizar progreso usando contador secuencial
        progress = order_num / total_orders
        progress_bar.progress(progress)
        status_container.info(f"Validando orden {order_num} de {total_orders}: {row['Reserva']}")
        
        reserva = str(row['Reserva']).strip()
        monto_abono = float(row['Monto Abono'])
        es_pago_total = row['Pago'] == 1
        
        # Buscar la orden de venta en Odoo
        domain = [('name', '=', reserva)]
        sale_order_ids = models.execute_kw(db, uid, password, 'sale.order', 'search', [domain])
        
        if not sale_order_ids:
            # La orden no existe
            orders_info.append({
                'Reserva': reserva,
                'Reserva_Str': reserva,  # Para comparaciones
                'Existe': False,
                'Estado': 'N/A',
                'Estado_Factura': 'N/A',
                'Monto_Total': 'N/A',
                'Monto_Abono': f"${monto_abono:,.0f}",
                'Es_Pago_Total': 'Sí' if es_pago_total else 'No',
                'Procesable': False,
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
                'Reserva_Str': reserva,  # Para comparaciones
                'Existe': True,
                'Estado': sale_order.get('state', 'N/A'),
                'Estado_Factura': sale_order.get('invoice_status', 'N/A'),
                'Monto_Total': monto_total_formato,  # Formato para visualización
                'Monto_Abono': monto_abono_formato,  # Formato para visualización
                'Es_Pago_Total': 'Sí' if es_pago_total else 'No',
                'Procesable': can_process,
                'Motivo': motivo if not can_process else "OK"
            })

    status_container.success("✅ Validación de órdenes completada")
    progress_bar.empty()

    return pd.DataFrame(orders_info)

def convert_to_odoo_date(date_value):
    """Convierte una fecha a formato Odoo (YYYY-MM-DD)"""
    if isinstance(date_value, str):
        # Intentar parsear diferentes formatos de fecha
        for fmt in ('%d/%m/%Y', '%Y-%m-%d', '%d-%m-%Y'):
            try:
                parsed_date = datetime.strptime(date_value, fmt)
                return parsed_date.strftime('%Y-%m-%d')
            except ValueError:
                continue
        raise ValueError(f"Formato de fecha no reconocido: {date_value}")
    elif isinstance(date_value, (datetime, pd.Timestamp)):
        return date_value.strftime('%Y-%m-%d')
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

def format_date(date_value):
    """Formatea una fecha para mostrar en el memo"""
    if isinstance(date_value, str):
        try:
            parsed_date = datetime.strptime(date_value, '%d/%m/%Y')
            return parsed_date.strftime('%d/%m/%Y')
        except ValueError:
            return str(date_value)
    elif isinstance(date_value, (datetime, pd.Timestamp)):
        return date_value.strftime('%d/%m/%Y')
    else:
        return str(date_value)

def register_payment_from_invoice(models, db, uid, password, invoice_id, payment_data, update_step):
    """Registra el pago usando el wizard nativo de Odoo"""
    try:
        update_step("Preparando registro de pago...")
        # Verificar que la factura existe
        try:
            invoice_check = models.execute_kw(db, uid, password, 'account.move', 'read', [[invoice_id]], {'fields': ['name', 'state']})
            update_step(f"Factura encontrada: {invoice_check[0]['name']} (Estado: {invoice_check[0]['state']})")
        except Exception as e:
            update_step(f"⚠️ No se pudo verificar la factura: {str(e)}")
            
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
        start_time = time.time()
        
        try:
            payment_register = models.execute_kw(db, uid, password,
                'account.payment.register', 'create',
                [wizard_vals],
                {'context': context})
            elapsed = time.time() - start_time
            update_step(f"Wizard creado en {elapsed:.2f} segundos, ID: {payment_register}")
        except Exception as e:
            update_step(f"❌ Error al crear el wizard de pago: {str(e)}")
            return False

        if not payment_register:
            update_step("❌ Error al crear el wizard de pago: No se obtuvo ID")
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
            update_step(f"❌ Error al ejecutar el pago: {str(e)}")
            return False

        if not result:
            update_step("⚠️ Advertencia: El pago se ejecutó pero no retornó resultado")
            
        update_step("✅ Pago registrado exitosamente")
        
        # Intentar obtener el ID del pago creado desde el resultado
        payment_id = None
        if result and isinstance(result, dict):
            if 'res_id' in result:
                payment_id = result['res_id']
            elif 'domain' in result:
                # Buscar en el dominio si hay información del pago
                domain = result.get('domain', [])
                for condition in domain:
                    if isinstance(condition, list) and len(condition) == 3 and condition[0] == 'id':
                        if condition[1] == '=' and isinstance(condition[2], int):
                            payment_id = condition[2]
                        elif condition[1] == 'in' and isinstance(condition[2], list) and condition[2]:
                            payment_id = condition[2][0]
        
        # Si no pudimos obtener el ID del resultado, buscar el pago más reciente para esta factura
        if not payment_id:
            try:
                # Buscar pagos relacionados con esta factura
                payment_domain = [
                    ('reconciled_invoice_ids', 'in', [invoice_id]),
                    ('state', 'in', ['posted', 'sent', 'reconciled'])
                ]
                payment_ids = models.execute_kw(db, uid, password, 'account.payment', 'search', 
                                              [payment_domain], {'order': 'create_date desc', 'limit': 1})
                if payment_ids:
                    payment_id = payment_ids[0]
                    update_step(f"ID del pago encontrado: {payment_id}")
            except Exception as e:
                update_step(f"⚠️ No se pudo obtener ID del pago: {str(e)}")
        
        return payment_id if payment_id else True

    except Exception as e:
        import traceback
        error_trace = traceback.format_exc()
        update_step(f"❌ Error al registrar pago: {str(e)}")
        update_step(f"Detalles del error: {error_trace}")
        return False

def process_record(models, db, uid, password, row, orders_status_df, progress_bar, progress_step, update_step):
    """Procesa un registro del Excel con actualización de pasos completa"""
    # Inicializar el avance
    current_step = 0
    progress_bar.progress(current_step * progress_step)

    # Preparar datos básicos
    reserva = str(row['Reserva']).strip()
    reserva_clean = str(row['Reserva_Clean']).strip() if 'Reserva_Clean' in row else reserva
    
    # Obtener la fila correspondiente en el DataFrame de validación
    order_status_rows = orders_status_df[orders_status_df['Reserva_Str'].astype(str).str.strip() == reserva_clean]
    if len(order_status_rows) > 0:
        order_status = order_status_rows.iloc[0]
    else:
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
    if not es_pago_parcial and abs(monto - total_orden) > 0.01:
        update_step(f"⚠️ Advertencia: Pago marcado como total pero el monto ({monto}) no coincide con el total de la orden ({total_orden})")

    # Verificar si es un caso especial: pago parcial para orden ya facturada
    es_caso_especial = es_pago_parcial and sale_order.get('invoice_status') == 'invoiced'
    invoice_id = None
    payment_data = None
    memo = ""

    if es_caso_especial:
        # Manejar caso especial: buscar factura existente para pago parcial en orden ya facturada
        update_step("🔍 Buscando factura existente para la orden...")
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
                'sale_line_ids': [(6, 0, [line['id']])]
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
            'ref': reserva,
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

        # Confirmar factura
        update_step("✅ Confirmando factura...")
        models.execute_kw(db, uid, password, 'account.move', 'action_post', [[invoice_id]])

        current_step += 1
        progress_bar.progress(current_step * progress_step)

        # Preparar datos del pago
        payment_data = {
            'amount': monto,
            'date': invoice_date,
            'journal_id': journal_id,
            'memo': memo
        }

    # Registrar el pago
    update_step("💳 Registrando pago...")
    payment_success = register_payment_from_invoice(models, db, uid, password, invoice_id, payment_data, update_step)

    current_step += 1
    progress_bar.progress(current_step * progress_step)

    if payment_success:
        update_step("🎉 Registro completado exitosamente")
        return {
            'Reserva': reserva,
            'Status': 'Éxito',
            'Mensaje': 'Procesado correctamente',
            'Estado_Orden': order_status['Estado'],
            'Estado_Factura': order_status['Estado_Factura'],
            'Factura': 'Sí',
            'Pago': 'Sí',
            'Conciliación': 'Sí',
            'order_id': sale_order_ids[0] if sale_order_ids else None,
            'invoice_id': invoice_id,
            'payment_id': payment_success if isinstance(payment_success, int) else None
        }
    else:
        update_step("❌ Error en el registro del pago")
        return {
            'Reserva': reserva,
            'Status': 'Error',
            'Mensaje': 'Error al registrar pago',
            'Estado_Orden': order_status['Estado'],
            'Estado_Factura': order_status['Estado_Factura'],
            'Factura': 'Sí' if not es_caso_especial else 'Existente',
            'Pago': 'No',
            'Conciliación': 'No',
            'order_id': sale_order_ids[0] if sale_order_ids else None,
            'invoice_id': invoice_id,
            'payment_id': None
        }

class ProcessingStage:
    ORDER_FOUND = "order_found"
    INVOICE_CREATED = "invoice_created" 
    INVOICE_CONFIRMED = "invoice_confirmed"
    PAYMENT_REGISTERED = "payment_registered"
    PAYMENT_RECONCILED = "payment_reconciled"

class RecordProcessor:
    def __init__(self):
        self.audit_log = []
        
    def create_audit_entry(self, reserva):
        """Crea una entrada de auditoría para un registro"""
        audit_entry = {
            'reserva': reserva,
            'stages': {
                'order_found': {'status': 'pending', 'data': None, 'error': None},
                'invoice_created': {'status': 'pending', 'data': None, 'error': None},
                'invoice_confirmed': {'status': 'pending', 'data': None, 'error': None},
                'payment_registered': {'status': 'pending', 'data': None, 'error': None},
                'payment_reconciled': {'status': 'pending', 'data': None, 'error': None}
            },
            'final_status': 'processing',
            'timestamp': datetime.now(),
            'error_summary': None
        }
        self.audit_log.append(audit_entry)
        return audit_entry
    
    def get_stage_icon(self, stage_data):
        """Retorna icono según el estado de la etapa"""
        if stage_data['status'] == 'success':
            return '✅'
        elif stage_data['status'] == 'failed':
            return '❌'
        elif stage_data['status'] == 'warning':
            return '⚠️'
        elif stage_data['status'] == 'skipped':
            return '⏭️'
        elif stage_data['status'] == 'processing':
            return '🔄'
        else:
            return '⏳'
    
    def get_final_status_icon(self, final_status):
        """Retorna icono según el estado final"""
        if final_status == 'completed':
            return '🎉'
        elif final_status == 'failed':
            return '💥'
        elif final_status == 'partial':
            return '⚠️'
        else:
            return '🔄'
    
    def render_progress_table(self, placeholder):
        """Renderiza tabla de progreso en tiempo real"""
        if not self.audit_log:
            return
            
        progress_data = []
        for entry in self.audit_log:
            row = {
                'Reserva': entry['reserva'],
                '🔍 Orden': self.get_stage_icon(entry['stages']['order_found']),
                '📄 Factura': self.get_stage_icon(entry['stages']['invoice_created']),
                '✅ Confirmada': self.get_stage_icon(entry['stages']['invoice_confirmed']),
                '💳 Pago': self.get_stage_icon(entry['stages']['payment_registered']),
                '🔗 Conciliada': self.get_stage_icon(entry['stages']['payment_reconciled']),
                'Estado': self.get_final_status_icon(entry['final_status']),
                'Error': entry['error_summary'] or ''
            }
            progress_data.append(row)
        
        df_progress = pd.DataFrame(progress_data)
        with placeholder.container():
            st.subheader("📊 Progreso del Procesamiento")
            st.dataframe(df_progress, use_container_width=True)

def validate_stage_in_odoo(models, db, uid, password, stage, data):
    """Valida que una etapa realmente se completó en Odoo"""
    try:
        if stage == 'order_found' and data:
            # Verificar que la orden existe
            result = models.execute_kw(db, uid, password, 'sale.order', 'read', 
                                     [[data]], {'fields': ['id', 'name']})
            return len(result) > 0
            
        elif stage == 'invoice_created' and data:
            # Verificar que la factura existe y está en estado correcto
            result = models.execute_kw(db, uid, password, 'account.move', 'read',
                                     [[data]], {'fields': ['id', 'name', 'state']})
            return len(result) > 0 and result[0]['state'] in ['draft', 'posted']
            
        elif stage == 'invoice_confirmed' and data:
            # Verificar que la factura está confirmada (posted)
            result = models.execute_kw(db, uid, password, 'account.move', 'read',
                                     [[data]], {'fields': ['state']})
            return len(result) > 0 and result[0]['state'] == 'posted'
            
        elif stage == 'payment_registered' and data:
            # Verificar que el pago existe
            result = models.execute_kw(db, uid, password, 'account.payment', 'read',
                                     [[data]], {'fields': ['id', 'name', 'state']})
            return len(result) > 0 and result[0]['state'] in ['draft', 'posted']
            
        elif stage == 'payment_reconciled' and data:
            # Verificar que el pago está reconciliado
            result = models.execute_kw(db, uid, password, 'account.payment', 'read',
                                     [[data]], {'fields': ['state', 'is_reconciled']})
            return len(result) > 0 and result[0].get('is_reconciled', False)
            
        return False
    except Exception:
        return False

def process_payments(models, db, uid, password, df, orders_status_df, progress_container, details_container):
    """Procesa los pagos en Odoo con sistema de auditoría robusto y validación granular"""
    # Inicializar procesador con auditoría
    processor = RecordProcessor()
    
    # Ya no necesitamos filtrar - df viene 100% validado
    total_records = len(df)
    
    if total_records == 0:
        st.warning("⚠️ No hay registros para procesar.")
        return {
            'total_processed': 0,
            'facturas_creadas': 0,
            'pagos_registrados': 0,
            'conciliaciones_exitosas': 0,
            'ordenes_omitidas': 0,
            'success_rate': 0,
            'results_df': pd.DataFrame(),
            'log_file': "No hay registros para procesar"
        }
    
    # Crear placeholders para progreso
    progress_placeholder = st.empty()
    general_progress_placeholder = st.empty()
    current_order_placeholder = st.empty()
    
    progress_step = 1.0 / (total_records * 8)  # 8 pasos por registro
    
    # Contadores
    facturas_creadas = 0
    pagos_registrados = 0
    conciliaciones_exitosas = 0
    
    for record_num, (idx, row) in enumerate(df.iterrows(), start=1):
        reserva = str(row['Reserva']).strip()
        
        # Crear entrada de auditoría
        audit_entry = processor.create_audit_entry(reserva)
        
        # Mostrar progreso general usando contador secuencial
        general_progress = record_num / total_records
        with general_progress_placeholder.container():
            st.subheader(f"📊 Progreso General: {record_num}/{total_records} registros procesados")
            st.progress(general_progress)
        
        # Mostrar orden actual
        with current_order_placeholder.container():
            st.info(f"🔄 Procesando orden {record_num} de {total_records}: **{reserva}**")
            current_phase = st.empty()
        
        # Crear barra de progreso individual
        progress_bar = st.progress(0)
        
        try:
            progress_container.info(f"Procesando {record_num}/{total_records}: {reserva}")
            
            # Procesar el registro usando la función existente pero con auditoría
            def update_step(message):
                details_container.write(f"**{reserva}:** {message}")
                # Actualizar fase actual
                current_phase.write(f"📍 **Fase actual:** {message}")
            
            # Usar la función existente process_record pero capturar errores por etapa
            try:
                result = process_record(models, db, uid, password, row, orders_status_df, 
                                      progress_bar, progress_step, update_step)
                
                # Validación granular mejorada con verificación real en Odoo
                if result['Status'] == 'Éxito':
                    # Extraer IDs de los datos del resultado si están disponibles
                    order_id = result.get('order_id')
                    invoice_id = result.get('invoice_id')
                    payment_id = result.get('payment_id')
                    
                    # Validar cada etapa individualmente en Odoo
                    stages_validation = {
                        'order_found': validate_stage_in_odoo(models, db, uid, password, 'order_found', order_id),
                        'invoice_created': validate_stage_in_odoo(models, db, uid, password, 'invoice_created', invoice_id),
                        'invoice_confirmed': validate_stage_in_odoo(models, db, uid, password, 'invoice_confirmed', invoice_id),
                        'payment_registered': validate_stage_in_odoo(models, db, uid, password, 'payment_registered', payment_id),
                        'payment_reconciled': validate_stage_in_odoo(models, db, uid, password, 'payment_reconciled', payment_id)
                    }
                    
                    # Actualizar estados basado en validación real
                    all_stages_valid = True
                    for stage, is_valid in stages_validation.items():
                        if is_valid:
                            audit_entry['stages'][stage]['status'] = 'success'
                            audit_entry['stages'][stage]['data'] = locals().get(f"{stage.split('_')[0]}_id")
                        else:
                            audit_entry['stages'][stage]['status'] = 'warning'
                            audit_entry['stages'][stage]['error'] = 'No se pudo verificar en Odoo'
                            all_stages_valid = False
                    
                    # Estado final basado en validación granular
                    if all_stages_valid:
                        audit_entry['final_status'] = 'completed'
                    else:
                        audit_entry['final_status'] = 'partial'
                        audit_entry['error_summary'] = 'Algunas etapas no pudieron ser verificadas en Odoo'
                else:
                    # Marcar como fallido
                    audit_entry['final_status'] = 'failed'
                    audit_entry['error_summary'] = result['Mensaje']
                    
            except Exception as process_error:
                audit_entry['final_status'] = 'failed'
                audit_entry['error_summary'] = str(process_error)
                raise process_error
            
            # Actualizar contadores según auditoría
            if audit_entry['final_status'] == 'completed':
                if audit_entry['stages']['invoice_created']['status'] == 'success':
                    facturas_creadas += 1
                if audit_entry['stages']['payment_registered']['status'] == 'success':
                    pagos_registrados += 1
                if audit_entry['stages']['payment_reconciled']['status'] == 'success':
                    conciliaciones_exitosas += 1
            
            # Actualizar tabla de progreso en tiempo real
            processor.render_progress_table(progress_placeholder)
            
            progress_bar.empty()
            current_phase.empty()
            
        except Exception as e:
            # Error crítico - marcar como fallido y continuar
            audit_entry['final_status'] = 'failed'
            audit_entry['error_summary'] = f"Error crítico: {str(e)}"
            details_container.error(f"**{reserva}:** ❌ Error crítico: {str(e)}")
            
            # Actualizar tabla de progreso
            processor.render_progress_table(progress_placeholder)
            
            progress_bar.empty()
            current_phase.empty()
            continue  # Continuar con el siguiente registro
    
    # Generar resultados finales desde auditoría
    results = []
    for entry in processor.audit_log:
        result = {
            'Reserva': entry['reserva'],
            'Status': 'Éxito' if entry['final_status'] == 'completed' else 'Error',
            'Mensaje': entry['error_summary'] or 'Procesado correctamente',
            'Estado_Orden': 'Procesado',
            'Estado_Factura': 'Procesado',
            'Factura': 'Sí' if entry['stages']['invoice_created']['status'] == 'success' else 'No',
            'Pago': 'Sí' if entry['stages']['payment_registered']['status'] == 'success' else 'No',
            'Conciliación': 'Sí' if entry['stages']['payment_reconciled']['status'] == 'success' else 'No'
        }
        results.append(result)
    
    # Calcular estadísticas finales
    completed_count = len([e for e in processor.audit_log if e['final_status'] == 'completed'])
    success_rate = (completed_count / total_records * 100) if total_records > 0 else 0
    
    # Crear log completo desde auditoría
    log_entries = []
    for entry in processor.audit_log:
        log_entries.append(f"[{entry['reserva']}] Estado final: {entry['final_status']}")
        if entry['error_summary']:
            log_entries.append(f"[{entry['reserva']}] Error: {entry['error_summary']}")
    log_file = "\n".join(log_entries)
    
    # Limpiar placeholders de progreso
    general_progress_placeholder.empty()
    current_order_placeholder.empty()
    
    progress_container.success(f"✅ Procesamiento completado: {completed_count}/{total_records} registros exitosos")
    
    # Crear tabla de resumen para descarga
    summary_data = []
    for entry in processor.audit_log:
        summary_row = {
            'Reserva': entry['reserva'],
            'Estado_Final': 'Completado' if entry['final_status'] == 'completed' else 'Fallido',
            'Orden_Encontrada': '✅' if entry['stages']['order_found']['status'] == 'success' else '❌',
            'Factura_Creada': '✅' if entry['stages']['invoice_created']['status'] == 'success' else '❌',
            'Factura_Confirmada': '✅' if entry['stages']['invoice_confirmed']['status'] == 'success' else '❌',
            'Pago_Registrado': '✅' if entry['stages']['payment_registered']['status'] == 'success' else '❌',
            'Pago_Conciliado': '✅' if entry['stages']['payment_reconciled']['status'] == 'success' else '❌',
            'Error': entry['error_summary'] or 'Sin errores',
            'Timestamp': entry['timestamp'].strftime('%Y-%m-%d %H:%M:%S')
        }
        summary_data.append(summary_row)
    
    summary_df = pd.DataFrame(summary_data)
    
    # Crear archivo Excel de resumen
    output = io.BytesIO()
    with pd.ExcelWriter(output, engine='openpyxl') as writer:
        summary_df.to_excel(writer, index=False, sheet_name='Resumen_Procesamiento')
    
    # Mostrar botón de descarga
    st.download_button(
        label="📥 Descargar Resumen de Procesamiento",
        data=output.getvalue(),
        file_name=f"resumen_procesamiento_{datetime.now().strftime('%Y%m%d_%H%M%S')}.xlsx",
        mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        help="Descarga un resumen detallado del procesamiento realizado"
    )
    
    # Botón para re-auditar manualmente después del procesamiento
    if st.button("🔍 Re-auditar Registros", help="Vuelve a verificar el estado real de todos los registros en Odoo"):
        st.info("🔄 Iniciando re-auditoría manual...")
        
        # Re-auditar cada registro
        for entry in processor.audit_log:
            reserva = entry['reserva']
            
            # Buscar IDs reales en Odoo para esta reserva
            try:
                # Buscar orden
                order_domain = [('name', '=', reserva)]
                order_ids = models.execute_kw(db, uid, password, 'sale.order', 'search', [order_domain])
                order_id = order_ids[0] if order_ids else None
                
                # Buscar factura relacionada
                invoice_id = None
                if order_id:
                    invoice_domain = [('invoice_origin', '=', reserva)]
                    invoice_ids = models.execute_kw(db, uid, password, 'account.move', 'search', [invoice_domain])
                    invoice_id = invoice_ids[0] if invoice_ids else None
                
                # Buscar pago relacionado
                payment_id = None
                if invoice_id:
                    payment_domain = [('reconciled_invoice_ids', 'in', [invoice_id])]
                    payment_ids = models.execute_kw(db, uid, password, 'account.payment', 'search', [payment_domain])
                    payment_id = payment_ids[0] if payment_ids else None
                
                # Re-validar cada etapa con los IDs encontrados
                stages_validation = {
                    'order_found': validate_stage_in_odoo(models, db, uid, password, 'order_found', order_id),
                    'invoice_created': validate_stage_in_odoo(models, db, uid, password, 'invoice_created', invoice_id),
                    'invoice_confirmed': validate_stage_in_odoo(models, db, uid, password, 'invoice_confirmed', invoice_id),
                    'payment_registered': validate_stage_in_odoo(models, db, uid, password, 'payment_registered', payment_id),
                    'payment_reconciled': validate_stage_in_odoo(models, db, uid, password, 'payment_reconciled', payment_id)
                }
                
                # Actualizar estados basado en re-validación
                all_stages_valid = True
                for stage, is_valid in stages_validation.items():
                    if is_valid:
                        entry['stages'][stage]['status'] = 'success'
                        entry['stages'][stage]['data'] = locals().get(f"{stage.split('_')[0]}_id")
                    else:
                        entry['stages'][stage]['status'] = 'failed'
                        entry['stages'][stage]['error'] = 'No encontrado en Odoo durante re-auditoría'
                        all_stages_valid = False
                
                # Actualizar estado final
                if all_stages_valid:
                    entry['final_status'] = 'completed'
                    entry['error_summary'] = None
                else:
                    entry['final_status'] = 'failed'
                    entry['error_summary'] = 'Algunas etapas no se encontraron en Odoo'
                    
            except Exception as e:
                entry['final_status'] = 'failed'
                entry['error_summary'] = f'Error durante re-auditoría: {str(e)}'
        
        # Actualizar tabla de progreso con nuevos resultados
        processor.render_progress_table(progress_placeholder)
        
        # Mostrar estadísticas actualizadas
        completed_count = len([e for e in processor.audit_log if e['final_status'] == 'completed'])
        success_rate = (completed_count / total_records * 100) if total_records > 0 else 0
        
        st.success(f"✅ Re-auditoría completada: {completed_count}/{total_records} registros verificados como exitosos ({success_rate:.1f}%)")
        
        # Generar nuevo resumen con datos actualizados
        updated_summary_data = []
        for entry in processor.audit_log:
            summary_row = {
                'Reserva': entry['reserva'],
                'Estado_Final': 'Completado' if entry['final_status'] == 'completed' else 'Fallido',
                'Orden_Encontrada': '✅' if entry['stages']['order_found']['status'] == 'success' else '❌',
                'Factura_Creada': '✅' if entry['stages']['invoice_created']['status'] == 'success' else '❌',
                'Factura_Confirmada': '✅' if entry['stages']['invoice_confirmed']['status'] == 'success' else '❌',
                'Pago_Registrado': '✅' if entry['stages']['payment_registered']['status'] == 'success' else '❌',
                'Pago_Conciliado': '✅' if entry['stages']['payment_reconciled']['status'] == 'success' else '❌',
                'Error': entry['error_summary'] or 'Sin errores',
                'Timestamp_Reauditoria': datetime.now().strftime('%Y-%m-%d %H:%M:%S')
            }
            updated_summary_data.append(summary_row)
        
        updated_summary_df = pd.DataFrame(updated_summary_data)
        
        # Crear nuevo archivo Excel con datos actualizados
        updated_output = io.BytesIO()
        with pd.ExcelWriter(updated_output, engine='openpyxl') as writer:
            updated_summary_df.to_excel(writer, index=False, sheet_name='Resumen_Reauditoria')
        
        # Botón de descarga actualizado
        st.download_button(
            label="📥 Descargar Resumen Re-auditado",
            data=updated_output.getvalue(),
            file_name=f"resumen_reauditado_{datetime.now().strftime('%Y%m%d_%H%M%S')}.xlsx",
            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            help="Descarga el resumen actualizado después de la re-auditoría manual"
        )
    
    return {
        'total_processed': total_records,
        'facturas_creadas': facturas_creadas,
        'pagos_registrados': pagos_registrados,
        'conciliaciones_exitosas': conciliaciones_exitosas,
        'ordenes_omitidas': 0,  # Ya no hay filtrado
        'success_rate': round(success_rate, 1),
        'results_df': pd.DataFrame(results),
        'log_file': log_file,
        'audit_log': processor.audit_log,  # Incluir auditoría completa
        'summary_df': summary_df  # Incluir resumen para descarga
    }

def render_import_pagos_page():
    """Renderiza la página de importación de pagos (página principal)"""
    st.title("🏠 Importación de Pagos a Odoo")
    
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
    
    # Obtener credenciales desde session_state (ahora manejadas en el sidebar)
    url, db, username, password = show_login_form()

    # Verificar si el usuario está logueado
    is_logged_in = all([url, db, username, password])

    if not is_logged_in:
        st.warning("Por favor inicie sesión usando el formulario en la barra lateral.")
        return
    
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
        if 'processing_results' in st.session_state:
            results = st.session_state['processing_results']
            results_df = results['results_df']
            
            # Mostrar el mensaje de éxito
            st.success(f"✅ Procesamiento completado: {results['total_processed']} registros")
            
            # Mostrar estadísticas de procesamiento
            col1, col2, col3, col4 = st.columns(4)
            with col1:
                st.metric("Total Procesados", results['total_processed'])
            with col2:
                st.metric("Facturas Creadas", results['facturas_creadas'])
            with col3:
                st.metric("Pagos Registrados", results['pagos_registrados'])
            with col4:
                st.metric("Tasa de Éxito", f"{results['success_rate']}%")
            
            # Mostrar tabla de resumen detallado si existe
            if 'summary_df' in results and not results['summary_df'].empty:
                st.subheader("📊 Resumen Detallado del Procesamiento")
                
                # Aplicar estilo para mejor visualización
                def highlight_status(row):
                    if row['Estado_Final'] == 'Completado':
                        return ['background-color: #e8f5e8; color: #2e7d32'] * len(row)
                    else:
                        return ['background-color: #ffebee; color: #c62828'] * len(row)
                
                styled_summary = results['summary_df'].style.apply(highlight_status, axis=1)
                st.dataframe(styled_summary, use_container_width=True)
                
                # Botón de descarga del resumen detallado
                summary_output = io.BytesIO()
                with pd.ExcelWriter(summary_output, engine='openpyxl') as writer:
                    results['summary_df'].to_excel(writer, index=False, sheet_name='Resumen_Procesamiento')
                
                st.download_button(
                    label="📥 Descargar Resumen Detallado",
                    data=summary_output.getvalue(),
                    file_name=f"resumen_procesamiento_{datetime.now().strftime('%Y%m%d_%H%M%S')}.xlsx",
                    mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                    help="Descarga el resumen completo con todas las etapas del procesamiento"
                )
                
                # Botón para re-auditar manualmente después del procesamiento
                if st.button("🔍 Re-auditar Registros", help="Vuelve a verificar el estado real de todos los registros en Odoo"):
                    # Conectar a Odoo para re-auditar
                    models, db_name, uid, odoo_password = connect_to_odoo()
                    if not all([models, db_name, uid, odoo_password]):
                        st.error("❌ No se pudo conectar a Odoo para re-auditar")
                        return
                    
                    st.info("🔄 Iniciando re-auditoría manual...")
                    
                    # Obtener audit_log desde los resultados
                    if 'audit_log' in results:
                        audit_log = results['audit_log']
                        total_records = len(audit_log)
                        
                        # Re-auditar cada registro
                        for entry in audit_log:
                            reserva = entry['reserva']
                            
                            # Buscar IDs reales en Odoo para esta reserva
                            try:
                                # Buscar orden
                                order_domain = [('name', '=', reserva)]
                                order_ids = models.execute_kw(db_name, uid, odoo_password, 'sale.order', 'search', [order_domain])
                                order_id = order_ids[0] if order_ids else None
                                
                                # Buscar factura relacionada
                                invoice_id = None
                                if order_id:
                                    invoice_domain = [('invoice_origin', '=', reserva)]
                                    invoice_ids = models.execute_kw(db_name, uid, odoo_password, 'account.move', 'search', [invoice_domain])
                                    invoice_id = invoice_ids[0] if invoice_ids else None
                                
                                # Buscar pago relacionado
                                payment_id = None
                                if invoice_id:
                                    payment_domain = [('reconciled_invoice_ids', 'in', [invoice_id])]
                                    payment_ids = models.execute_kw(db_name, uid, odoo_password, 'account.payment', 'search', [payment_domain])
                                    payment_id = payment_ids[0] if payment_ids else None
                                
                                # Re-validar cada etapa con los IDs encontrados
                                stages_validation = {
                                    'order_found': validate_stage_in_odoo(models, db_name, uid, odoo_password, 'order_found', order_id),
                                    'invoice_created': validate_stage_in_odoo(models, db_name, uid, odoo_password, 'invoice_created', invoice_id),
                                    'invoice_confirmed': validate_stage_in_odoo(models, db_name, uid, odoo_password, 'invoice_confirmed', invoice_id),
                                    'payment_registered': validate_stage_in_odoo(models, db_name, uid, odoo_password, 'payment_registered', payment_id),
                                    'payment_reconciled': validate_stage_in_odoo(models, db_name, uid, odoo_password, 'payment_reconciled', payment_id)
                                }
                                
                                # Actualizar estados basado en re-validación
                                all_stages_valid = True
                                for stage, is_valid in stages_validation.items():
                                    if is_valid:
                                        entry['stages'][stage]['status'] = 'success'
                                        entry['stages'][stage]['data'] = locals().get(f"{stage.split('_')[0]}_id")
                                    else:
                                        entry['stages'][stage]['status'] = 'failed'
                                        entry['stages'][stage]['error'] = 'No encontrado en Odoo durante re-auditoría'
                                        all_stages_valid = False
                                
                                # Actualizar estado final
                                if all_stages_valid:
                                    entry['final_status'] = 'completed'
                                    entry['error_summary'] = None
                                else:
                                    entry['final_status'] = 'failed'
                                    entry['error_summary'] = 'Algunas etapas no se encontraron en Odoo'
                                    
                            except Exception as e:
                                entry['final_status'] = 'failed'
                                entry['error_summary'] = f'Error durante re-auditoría: {str(e)}'
                        
                        # Mostrar estadísticas actualizadas
                        completed_count = len([e for e in audit_log if e['final_status'] == 'completed'])
                        success_rate = (completed_count / total_records * 100) if total_records > 0 else 0
                        
                        st.success(f"✅ Re-auditoría completada: {completed_count}/{total_records} registros verificados como exitosos ({success_rate:.1f}%)")
                        
                        # Generar nuevo resumen con datos actualizados
                        updated_summary_data = []
                        for entry in audit_log:
                            summary_row = {
                                'Reserva': entry['reserva'],
                                'Estado_Final': 'Completado' if entry['final_status'] == 'completed' else 'Fallido',
                                'Orden_Encontrada': '✅' if entry['stages']['order_found']['status'] == 'success' else '❌',
                                'Factura_Creada': '✅' if entry['stages']['invoice_created']['status'] == 'success' else '❌',
                                'Factura_Confirmada': '✅' if entry['stages']['invoice_confirmed']['status'] == 'success' else '❌',
                                'Pago_Registrado': '✅' if entry['stages']['payment_registered']['status'] == 'success' else '❌',
                                'Pago_Conciliado': '✅' if entry['stages']['payment_reconciled']['status'] == 'success' else '❌',
                                'Error': entry['error_summary'] or 'Sin errores',
                                'Timestamp_Reauditoria': datetime.now().strftime('%Y-%m-%d %H:%M:%S')
                            }
                            updated_summary_data.append(summary_row)
                        
                        updated_summary_df = pd.DataFrame(updated_summary_data)
                        
                        # Mostrar tabla actualizada
                        st.subheader("📊 Resumen Re-auditado")
                        def highlight_updated_status(row):
                            if row['Estado_Final'] == 'Completado':
                                return ['background-color: #e8f5e8; color: #2e7d32'] * len(row)
                            else:
                                return ['background-color: #ffebee; color: #c62828'] * len(row)
                        
                        styled_updated = updated_summary_df.style.apply(highlight_updated_status, axis=1)
                        st.dataframe(styled_updated, use_container_width=True)
                        
                        # Crear nuevo archivo Excel con datos actualizados
                        updated_output = io.BytesIO()
                        with pd.ExcelWriter(updated_output, engine='openpyxl') as writer:
                            updated_summary_df.to_excel(writer, index=False, sheet_name='Resumen_Reauditoria')
                        
                        # Botón de descarga actualizado
                        st.download_button(
                            label="📥 Descargar Resumen Re-auditado",
                            data=updated_output.getvalue(),
                            file_name=f"resumen_reauditado_{datetime.now().strftime('%Y%m%d_%H%M%S')}.xlsx",
                            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                            help="Descarga el resumen actualizado después de la re-auditoría manual"
                        )
                        
                        # Actualizar los resultados en session_state con los datos re-auditados
                        results['audit_log'] = audit_log
                        results['summary_df'] = updated_summary_df
                        st.session_state['processing_results'] = results
                        
                    else:
                        st.warning("⚠️ No se encontró información de auditoría para re-auditar")
            else:
                # Mostrar tabla básica si no hay resumen detallado
                st.subheader("Resultados del Procesamiento")
                st.dataframe(results_df)
            
            # Botón para procesar un nuevo archivo
            if st.button("Procesar Nuevo Archivo"):
                # Reiniciar el estado pero mantener las credenciales de sesión
                for key in ['orders_status_df', 'validation_complete', 'show_process_button', 
                          'processing_complete', 'processing_results']:
                    if key in st.session_state:
                        del st.session_state[key]
                st.experimental_rerun()

    elif uploaded_file is not None:
        try:
            # Cargar el Excel
            df = pd.read_excel(uploaded_file)

            # Mostrar vista previa de los datos
            st.write("Vista previa de los datos:")
            st.dataframe(df.head())

            # Validar las columnas requeridas
            required_columns = ['Fecha Pago', 'Reserva', 'Pago', 'Monto Abono', 'Forma de Pago']
            missing_columns = [col for col in required_columns if col not in df.columns]

            if missing_columns:
                st.error(f"El archivo no contiene todas las columnas requeridas. Faltan: {', '.join(missing_columns)}")
                return

            # Convertir la columna de fecha
            df['Fecha Pago'] = pd.to_datetime(df['Fecha Pago'], errors='coerce')

            # Validar el formato completo del Excel
            is_valid_format, errors_df = validate_excel_format(df)

            if not is_valid_format:
                st.error("⚠️ El archivo Excel contiene errores de formato que deben corregirse antes de procesar.")
                st.write("Errores encontrados:")
                st.dataframe(errors_df)
                return

            # Si el formato es válido
            st.success("✅ Formato del archivo Excel validado correctamente.")

            # Crear un botón para validar el estado de las órdenes
            if st.button("Validar Estado de Órdenes"):
                # Verificar conexión antes de proceder
                if not st.session_state.get('connection_verified', False):
                    st.error("❌ Primero debe probar y verificar la conexión a Odoo usando el botón '🔌 Probar Conexión a Odoo' en la barra lateral.")
                    return
                
                # Conectar a Odoo para validar órdenes
                models, db_name, uid, odoo_password = connect_to_odoo()
                if not all([models, db_name, uid, odoo_password]):
                    st.error("❌ No se pudo conectar a Odoo")
                    return

                # Validar el estado de las órdenes
                status_container.info("Validando estado de las órdenes...")
                orders_status_df = validate_orders_status(models, db_name, uid, odoo_password, df)
                
                # Guardar el resultado en session_state
                st.session_state['orders_status_df'] = orders_status_df
                st.session_state['validation_complete'] = True
                
                # Determinar si se debe mostrar el botón de procesar
                processable_count = len(orders_status_df[orders_status_df['Procesable'] == True])
                total_count = len(orders_status_df)
                
                st.session_state['show_process_button'] = (processable_count == total_count and processable_count > 0)
                st.experimental_rerun()

            # Mostrar resultados de validación si existen
            if st.session_state.get('validation_complete', False) and 'orders_status_df' in st.session_state:
                orders_status_df = st.session_state['orders_status_df']
                
                # Mostrar estadísticas
                processable_count = len(orders_status_df[orders_status_df['Procesable'] == True])
                total_count = len(orders_status_df)
                
                col1, col2, col3 = st.columns(3)
                with col1:
                    st.metric("Total de registros", total_count)
                with col2:
                    st.metric("Registros procesables", processable_count)
                with col3:
                    success_rate = (processable_count / total_count * 100) if total_count > 0 else 0
                    st.metric("Tasa de éxito", f"{success_rate:.1f}%")

                # Mostrar tabla de resultados
                st.write("### Estado de las Órdenes:")
                
                # Aplicar estilo condicional para marcar filas no procesables en rojo
                def highlight_non_processable(row):
                    if not row['Procesable']:
                        return ['background-color: #ffebee; color: #c62828'] * len(row)
                    else:
                        return [''] * len(row)
                
                # Mostrar tabla con estilo
                styled_df = orders_status_df.style.apply(highlight_non_processable, axis=1)
                st.dataframe(styled_df, use_container_width=True)

                # Mostrar el botón de procesar solo si todos los registros son procesables
                if st.session_state.get('show_process_button', False):
                    st.success("✅ Todos los registros están listos para procesar")
                    
                    if st.button("🚀 Procesar Pagos", type="primary"):
                        # Verificar conexión antes de procesar
                        if not st.session_state.get('connection_verified', False):
                            st.error("❌ Primero debe probar y verificar la conexión a Odoo usando el botón '🔌 Probar Conexión a Odoo' en la barra lateral.")
                            return
                        
                        # Conectar a Odoo para procesar pagos
                        models, db_name, uid, odoo_password = connect_to_odoo()
                        if not all([models, db_name, uid, odoo_password]):
                            st.error("❌ No se pudo conectar a Odoo para procesar pagos")
                            return
                        
                        # Filtrar solo los registros procesables usando columnas limpias
                        # Asegurar que ambos DataFrames tengan la columna limpia
                        if 'Reserva_Clean' not in df.columns:
                            df['Reserva_Clean'] = df['Reserva'].astype(str).str.strip()
                        
                        # Obtener lista de reservas procesables
                        reservas_procesables = orders_status_df[orders_status_df['Procesable']]['Reserva_Str'].astype(str).str.strip().tolist()
                        
                        # Filtrar usando la columna limpia
                        processable_df = df[df['Reserva_Clean'].isin(reservas_procesables)].copy()
                        
                        if len(processable_df) == 0:
                            st.error("No hay registros procesables para procesar.")
                            st.info(f"Debug: Reservas en df: {df['Reserva_Clean'].tolist()}")
                            st.info(f"Debug: Reservas procesables: {reservas_procesables}")
                            return
                        
                        # Procesar los pagos
                        progress_container.info(f"Procesando {len(processable_df)} registros...")
                        
                        results = process_payments(models, db_name, uid, odoo_password, processable_df, 
                                                 orders_status_df, progress_container, details_container)
                        
                        # Guardar resultados en session_state
                        st.session_state['processing_results'] = results
                        st.session_state['processing_complete'] = True
                        
                        st.experimental_rerun()
                else:
                    if processable_count < total_count:
                        st.warning(f"⚠️ Solo {processable_count} de {total_count} registros son procesables. Corrija los errores antes de continuar.")
                    elif processable_count == 0:
                        st.error("❌ No hay registros procesables. Revise los datos y corrija los errores.")

        except Exception as e:
            st.error(f"Error al procesar el archivo: {str(e)}")

def main():
    """Función principal con sistema de navegación multi-página"""
    
    # Configuración de la página
    st.set_page_config(
        page_title="Sistema de Pagos y Formateador IPS",
        page_icon="🏠",
        layout="wide",
        initial_sidebar_state="expanded"
    )
    
    # Configurar navegación
    setup_page_navigation()
    
    # Obtener página actual
    current_page = get_current_page()
    
    # Renderizar página según selección
    if current_page == "🏠 Importar Pagos":
        render_import_pagos_page()
    elif current_page == "🧹 Limpieza de Órdenes":
        # Importar y ejecutar la página de limpieza
        from cleanup_orders import render_cleanup_page
        render_cleanup_page()
    elif current_page == "💳 Transacciones BcoEstado":
        # Importar y ejecutar la página de transacciones
        from pages.transacciones_bcoestado import main as transacciones_main
        transacciones_main()
    elif current_page == "📄 Formateador IPS":
        render_ips_formatter()
    else:
        st.error(f"Página no encontrada: {current_page}")
        render_import_pagos_page()  # Fallback a página principal

if __name__ == "__main__":
    main()
