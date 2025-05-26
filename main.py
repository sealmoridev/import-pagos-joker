import streamlit as st
import pandas as pd
import xmlrpc.client
from datetime import datetime
import pytz
import time
import re
import os
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
        st.session_state['odoo_username'] = username
        st.session_state['odoo_password'] = password
        st.session_state['is_logged_in'] = True

        return url, db, username, password

    # Si hay credenciales guardadas, devolverlas
    if st.session_state.get('is_logged_in', False):
        return (
            url,
            db,
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
        'TRANSF', 'DEP', 'BEX', 'CV', 'IN', 'SBE', 'EFECT OF', 'MAQ/TD', 'MAQ/TC', 'WEBPAY'
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
                [sale_order_ids[0]], {'fields': ['state', 'invoice_status']})[0]

            # Verificar si el estado de facturación es 'to invoice'
            can_process = sale_order.get('invoice_status') == 'to invoice'

            motivo = ""
            if not can_process:
                if sale_order.get('invoice_status') == 'invoiced':
                    motivo = "Orden ya facturada"
                elif sale_order.get('invoice_status') == 'no':
                    motivo = "Orden no requiere facturación"
                elif sale_order.get('invoice_status') == 'upselling':
                    motivo = "Orden en estado de venta adicional"
                else:
                    motivo = f"Estado de facturación no válido: {sale_order.get('invoice_status')}"

            orders_info.append({
                'Reserva': reserva,
                'Existe': True,
                'Estado': sale_order.get('state', 'N/A'),
                'Estado_Factura': sale_order.get('invoice_status', 'N/A'),
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
        # Add timeout to prevent connection hanging
        common = xmlrpc.client.ServerProxy(f'{url}/xmlrpc/2/common', allow_none=True, use_datetime=True, timeout=60)

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
        models = xmlrpc.client.ServerProxy(f'{url}/xmlrpc/2/object', allow_none=True)
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
        'WEBPAY': 7   # ID del diario de Webpay
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

        update_step("Creando wizard de pago...")
        payment_register = models.execute_kw(db, uid, password,
            'account.payment.register', 'create',
            [wizard_vals],
            {'context': context})

        if not payment_register:
            update_step("❌ Error al crear el wizard de pago")
            return False

        update_step("Ejecutando pago...")
        result = models.execute_kw(db, uid, password,
            'account.payment.register', 'action_create_payments',
            [[payment_register]],
            {'context': context})

        update_step("✅ Pago registrado exitosamente")
        return True

    except Exception as e:
        update_step(f"❌ Error al registrar pago: {str(e)}")
        return False

def process_record(models, db, uid, password, row, orders_status_df, progress_bar, progress_step, update_step):
    """Procesa un registro del Excel con actualización de pasos

    Args:
        update_step: Función para actualizar el paso actual en el log
    """
    try:
        # Inicializar el avance
        current_step = 0
        progress_bar.progress(current_step * progress_step)

        # Preparar datos básicos
        reserva = str(row['Reserva']).strip()
        update_step(f"🔍 Validando orden de venta: {reserva}")

        # Verificar si la orden puede ser procesada
        order_status = orders_status_df[orders_status_df['Reserva'] == reserva].iloc[0]

        if not order_status['Puede_Procesar']:
            update_step(f"⚠️ Orden {reserva} no puede ser procesada: {order_status['Motivo']}")
            return {
                'Reserva': reserva,
                'Status': 'Omitido',
                'Mensaje': f"No procesado: {order_status['Motivo']}",
                'Estado_Orden': order_status['Estado'],
                'Estado_Factura': order_status['Estado_Factura'],
                'Factura': 'No',
                'Pago': 'No',
                'Conciliación': 'No'
            }

        current_step += 1
        progress_bar.progress(current_step * progress_step)

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

        current_step += 1
        progress_bar.progress(current_step * progress_step)

        # Preparar datos del pago
        payment_method = str(row['Forma de Pago']).strip()
        journal_id = get_journal_id(payment_method)
        formatted_date = format_date(row['Fecha Pago'])
        memo = f"{reserva} / {payment_method}/{formatted_date}"

        payment_data = {
            'amount': monto,
            'date': invoice_date,
            'journal_id': journal_id,
            'memo': memo
        }

        update_step("💰 Registrando pago...")

        current_step += 1
        progress_bar.progress(current_step * progress_step)

        if register_payment_from_invoice(models, db, uid, password, invoice_id, payment_data, update_step):
            current_step += 1
            progress_bar.progress(1.0)  # Completar la barra
            update_step("✅ Proceso completado exitosamente")
            return {
                'Reserva': reserva,
                'Status': 'Éxito',
                'Mensaje': 'Proceso completado exitosamente',
                'Estado_Orden': order_status['Estado'],
                'Estado_Factura': 'invoiced',  # Ahora está facturado
                'Factura': str(invoice_id),
                'Pago': 'Registrado',
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

    except Exception as e:
        update_step(f"❌ Error general: {str(e)}")
        estado_orden = order_status['Estado'] if 'order_status' in locals() else 'N/A'
        estado_factura = order_status['Estado_Factura'] if 'order_status' in locals() else 'N/A'
        return {
            'Reserva': str(row.get('Reserva', 'Desconocido')),
            'Status': 'Error',
            'Mensaje': str(e),
            'Estado_Orden': estado_orden,
            'Estado_Factura': estado_factura,
            'Factura': 'No',
            'Pago': 'No',
            'Conciliación': 'No'
        }

def main():
    st.title("Importación de Pagos a Odoo")

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
        # Solo eliminamos las credenciales de usuario y el estado de login
        if 'odoo_username' in st.session_state:
            del st.session_state['odoo_username']
        if 'odoo_password' in st.session_state:
            del st.session_state['odoo_password']
        if 'is_logged_in' in st.session_state:
            del st.session_state['is_logged_in']
        st.experimental_rerun()
    
    st.write("Esta herramienta permite importar pagos a Odoo desde un archivo Excel.")

    # Crear contenedor para estado general
    status_container = st.empty()
    progress_container = st.empty()
    details_container = st.empty()

    uploaded_file = st.file_uploader("Cargar archivo Excel", type=['xlsx'])

    if uploaded_file is not None:
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

                # Solo mostrar el botón de procesar si hay órdenes válidas
                if valid_orders > 0:
                    st.session_state['orders_status_df'] = orders_status_df
                    st.session_state['validation_complete'] = True
                    st.success(f"✅ {valid_orders} órdenes están listas para procesar.")
                    st.session_state['show_process_button'] = True
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

                    # Variables para estadísticas
                    processed = 0
                    successful = 0
                    errors = 0

                    # Preparar log de actividad
                    log_entries = []

                    # Número de pasos en el proceso
                    total_steps = 10
                    progress_step = 1.0 / total_steps

                    results = []
                    for index, row in df.iterrows():
                        # Actualizar progreso general
                        progress_percent = (index) / len(df)
                        overall_progress.progress(progress_percent)
                        overall_status.info(f"Procesando registro {index + 1} de {len(df)} ({int(progress_percent * 100)}%)")

                        # Mostrar información del registro actual
                        current_record_info.info(f"Procesando: Reserva {row['Reserva']} - {row['Fecha Pago'].strftime('%d-%m-%Y')} - {row['Forma de Pago']} - ${row['Monto Abono']}")

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

                        # Procesar registro con función de actualización
                        result = process_record(models, db, uid, password, row, orders_status_df, 
                                             record_progress, progress_step, update_step_info)
                        results.append(result)

                        # Actualizar contadores
                        processed += 1
                        if result['Status'] == 'Éxito':
                            successful += 1
                        elif result['Status'] == 'Error':
                            errors += 1

                        # Actualizar estadísticas
                        processed_counter.metric("Procesados", f"{processed}/{len(df)}")
                        success_counter.metric("Exitosos", successful)
                        error_counter.metric("Errores", errors)

                        # Pequeña pausa para visualizar
                        time.sleep(0.5)

                    # Completar progreso general
                    overall_progress.progress(1.0)
                    overall_status.success(f"✅ Procesamiento completado: {len(df)} registros")

                    # Guardar log completo
                    log_file = "\n".join(log_entries)
                    st.download_button(
                        label="Descargar Log Completo",
                        data=log_file.encode('utf-8'),
                        file_name="log_procesamiento.txt",
                        mime="text/plain"
                    )

                    # Mostrar resultados
                    st.write("### Resultados del Procesamiento:")
                    results_df = pd.DataFrame(results)
                    column_order = ['Reserva', 'Status', 'Estado_Orden', 'Estado_Factura', 'Factura', 'Pago', 'Conciliación', 'Mensaje']
                    results_df = results_df[column_order]

                    # Función para colorear las filas según el resultado
                    def highlight_status(row):
                        if row['Status'] == 'Éxito':
                            return ['background-color: #CCFFCC'] * len(row)
                        elif row['Status'] == 'Parcial':
                            return ['background-color: #FFFFCC'] * len(row)
                        elif row['Status'] == 'Omitido':
                            return ['background-color: #EFEFEF'] * len(row)
                        else:
                            return ['background-color: #FFCCCC'] * len(row)

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
                        mime="text/csv"
                    )

        except Exception as e:
            st.error(f"Error al procesar el archivo: {str(e)}")
            import traceback
            st.error(traceback.format_exc())

if __name__ == "__main__":
    # Inicializar variables de estado si no existen
    if 'validation_complete' not in st.session_state:
        st.session_state['validation_complete'] = False

    if 'show_process_button' not in st.session_state:
        st.session_state['show_process_button'] = False

    if 'orders_status_df' not in st.session_state:
        st.session_state['orders_status_df'] = None

    main()