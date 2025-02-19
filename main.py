import streamlit as st
import pandas as pd
import xmlrpc.client
from datetime import datetime
import pytz

# Configuración de la conexión Odoo
def connect_to_odoo():
    url = st.secrets["odoo_url"]
    db = st.secrets["odoo_db"]
    username = st.secrets["odoo_username"]
    password = st.secrets["odoo_password"]

    common = xmlrpc.client.ServerProxy(f'{url}/xmlrpc/2/common')
    uid = common.authenticate(db, username, password, {})
    models = xmlrpc.client.ServerProxy(f'{url}/xmlrpc/2/object')

    return models, db, uid, password

def format_date(date_val):
    """Convierte la fecha al formato requerido dd-mm-aaaa"""
    if isinstance(date_val, pd.Timestamp):
        date_obj = date_val.to_pydatetime()
    elif isinstance(date_val, str):
        date_obj = datetime.strptime(date_val, '%Y-%m-%d')
    else:
        date_obj = date_val
    return date_obj.strftime('%d-%m-%Y')

def create_invoice_and_payment(models, db, uid, password, row):
    """Crea la factura y el pago en Odoo"""
    try:
        # Buscar la orden de venta por número de reserva
        sale_order = models.execute_kw(db, uid, password,
            'sale.order', 'search_read',
            [[('name', '=', row['Reserva'])]], 
            {'fields': ['partner_id', 'amount_total']})

        if not sale_order:
            return False, f"No se encontró la orden de venta {row['Reserva']}"

        # Crear factura
        invoice_vals = {
            'partner_id': sale_order[0]['partner_id'][0],
            'move_type': 'out_invoice',
            'invoice_origin': row['Reserva'],
            'invoice_line_ids': [(0, 0, {
                'name': f'Pago reserva {row["Reserva"]}',
                'quantity': 1,
                'price_unit': row['Monto Abono']
            })]
        }

        invoice_id = models.execute_kw(db, uid, password,
            'account.move', 'create', [invoice_vals])

        # Confirmar factura
        models.execute_kw(db, uid, password,
            'account.move', 'action_post', [invoice_id])

        # Crear pago
        payment_date = datetime.strptime(row['Fecha Pago'], '%Y-%m-%d')
        payment_method = row['Forma de Pago']
        memo = f"{row['Reserva']} / {payment_method}/{format_date(payment_date)}"

        payment_vals = {
            'partner_id': sale_order[0]['partner_id'][0],
            'amount': row['Monto Abono'],
            'date': payment_date,
            'ref': memo,
            'payment_type': 'inbound',
            'partner_type': 'customer',
            'journal_id': get_journal_id(payment_method),  # Función para determinar el diario según forma de pago
            'payment_method_id': 1,  # ID del método de pago manual
        }

        payment_id = models.execute_kw(db, uid, password,
            'account.payment', 'create', [payment_vals])

        # Confirmar pago
        models.execute_kw(db, uid, password,
            'account.payment', 'action_post', [payment_id])

        # Conciliar pago con factura
        invoice = models.execute_kw(db, uid, password,
            'account.move', 'search_read',
            [[('id', '=', invoice_id)]], 
            {'fields': ['line_ids']})

        payment = models.execute_kw(db, uid, password,
            'account.payment', 'search_read',
            [[('id', '=', payment_id)]], 
            {'fields': ['line_ids']})

        lines_to_reconcile = models.execute_kw(db, uid, password,
            'account.move.line', 'search_read',
            [[('id', 'in', invoice[0]['line_ids'] + payment[0]['line_ids']),
              ('account_id.reconcile', '=', True),
              ('reconciled', '=', False)]], 
            {'fields': ['id']})

        models.execute_kw(db, uid, password,
            'account.move.line', 'reconcile',
            [list(map(lambda x: x['id'], lines_to_reconcile))])

        return True, f"Factura y pago creados exitosamente para {row['Reserva']}"

    except Exception as e:
        return False, f"Error al procesar {row['Reserva']}: {str(e)}"

def get_journal_id(payment_method):
    """Determina el diario según el método de pago"""
    journal_mapping = {
        'TRANSF': 1,  # ID del diario de transferencias
        'DEP': 2,     # ID del diario de depósitos
        'BEX': 3,     # ID del diario de Banco Estado Express
        'CV': 4,      # ID del diario de Caja Vecina
        'IN': 5,      # ID del diario de Internet
        'SBE': 6,     # ID del diario de Sucursal Banco Estado
        'EFECT OF': 7,# ID del diario de Efectivo
        'MAQ/TD': 8,  # ID del diario de Transbank Débito
        'MAQ/TC': 9   # ID del diario de Transbank Crédito
    }
    return journal_mapping.get(payment_method, 1)  # Default a transferencia si no se encuentra

def main():
    st.title("Importación de Pagos a Odoo")

    # Archivo Excel
    uploaded_file = st.file_uploader("Cargar archivo Excel", type=['xlsx'])

    if uploaded_file is not None:
        try:
            df = pd.read_excel(uploaded_file)
            st.write("Vista previa de los datos:")
            st.dataframe(df.head())

            # Validar columnas requeridas
            required_columns = ['Fecha Pago', 'Reserva', 'Pago', 'Monto Abono', 'Forma de Pago']
            if not all(col in df.columns for col in required_columns):
                st.error("El archivo no contiene todas las columnas requeridas")
                return

            # Botón para procesar
            if st.button("Procesar Pagos"):
                models, db, uid, password = connect_to_odoo()

                progress_bar = st.progress(0)
                status_text = st.empty()

                results = []
                for index, row in df.iterrows():
                    status_text.text(f"Procesando {row['Reserva']}...")
                    success, message = create_invoice_and_payment(models, db, uid, password, row)
                    results.append({'Reserva': row['Reserva'], 'Status': 'Éxito' if success else 'Error', 'Mensaje': message})
                    progress_bar.progress((index + 1) / len(df))

                # Mostrar resultados
                results_df = pd.DataFrame(results)
                st.write("Resultados del procesamiento:")
                st.dataframe(results_df)

                # Descargar resultados
                st.download_button(
                    label="Descargar Resultados",
                    data=results_df.to_csv(index=False).encode('utf-8'),
                    file_name="resultados_importacion.csv",
                    mime="text/csv"
                )

        except Exception as e:
            st.error(f"Error al procesar el archivo: {str(e)}")

if __name__ == "__main__":
    main()