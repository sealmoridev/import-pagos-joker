"""
Página de visualización de transacciones electrónicas desde Odoo
Modelo: payment.transaction con state='done'
"""

import streamlit as st
import pandas as pd
from datetime import datetime, timedelta
import xmlrpc.client
import io
import os
from dotenv import load_dotenv

# Cargar variables de entorno
load_dotenv()


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


def fetch_payment_transactions(models, db, uid, password, fecha_inicio=None, fecha_fin=None, estados=None):
    """Obtiene las transacciones de pago desde Odoo con filtros de fecha y estado"""
    try:
        # Construir dominio de búsqueda
        domain = []
        
        # Filtrar por estados (por defecto 'done')
        if estados:
            if len(estados) == 1:
                domain.append(('state', '=', estados[0]))
            else:
                domain.append(('state', 'in', estados))
        else:
            domain.append(('state', '=', 'done'))
        
        # Aplicar filtros de fecha si se proporcionan
        if fecha_inicio:
            fecha_inicio_str = fecha_inicio.strftime('%Y-%m-%d 00:00:00')
            domain.append(('create_date', '>=', fecha_inicio_str))
        
        if fecha_fin:
            # Incluir todo el día seleccionado
            fecha_fin_str = (fecha_fin + timedelta(days=1)).strftime('%Y-%m-%d 00:00:00')
            domain.append(('create_date', '<', fecha_fin_str))
        
        # Campos a obtener (basados en el esquema real de payment_transaction)
        fields = [
            'id',
            'reference',
            'amount',
            'fees',
            'currency_id',
            'partner_id',
            'partner_name',
            'partner_email',
            'partner_phone',
            'partner_address',
            'partner_city',
            'partner_zip',
            'partner_country_id',
            'acquirer_id',
            'acquirer_reference',
            'type',
            'state',
            'state_message',
            'date',
            'create_date',
            'write_date',
            'payment_id',
            'payment_token_id',
            'is_processed',
            'callback_model_id',
            'callback_res_id',
            'return_url',
            'webpay_txn_type',
            'webpay_token'
        ]
        
        # Buscar transacciones
        transaction_ids = models.execute_kw(
            db, uid, password,
            'payment.transaction', 'search',
            [domain],
            {'order': 'create_date desc'}
        )
        
        if not transaction_ids:
            return pd.DataFrame()
        
        # Leer datos de las transacciones
        transactions = models.execute_kw(
            db, uid, password,
            'payment.transaction', 'read',
            [transaction_ids],
            {'fields': fields}
        )
        
        # Convertir a DataFrame
        df = pd.DataFrame(transactions)
        
        # Procesar campos relacionales (que vienen como [id, name])
        relational_fields = ['currency_id', 'partner_id', 'acquirer_id', 'partner_country_id', 'payment_id', 'payment_token_id', 'callback_model_id']
        for field in relational_fields:
            if field in df.columns:
                df[field] = df[field].apply(lambda x: x[1] if x and isinstance(x, list) and len(x) > 1 else x)
        
        return df
        
    except Exception as e:
        st.error(f"❌ Error al obtener transacciones: {str(e)}")
        return pd.DataFrame()


def format_dataframe(df):
    """Formatea el DataFrame para visualización"""
    if df.empty:
        return df
    
    df_display = df.copy()
    
    # Formatear fechas
    date_columns = ['date', 'create_date', 'write_date']
    for col in date_columns:
        if col in df_display.columns:
            df_display[col] = pd.to_datetime(df_display[col], errors='coerce').dt.strftime('%d-%m-%Y %H:%M:%S')
    
    # Formatear monto con separador de miles
    if 'amount' in df_display.columns:
        df_display['amount'] = pd.to_numeric(df_display['amount'], errors='coerce')
        df_display['amount'] = df_display['amount'].apply(
            lambda x: f"${x:,.0f}" if pd.notna(x) else "N/A"
        )
    
    # Formatear fees con separador de miles
    if 'fees' in df_display.columns:
        df_display['fees'] = pd.to_numeric(df_display['fees'], errors='coerce')
        df_display['fees'] = df_display['fees'].apply(
            lambda x: f"${x:,.2f}" if pd.notna(x) and x > 0 else "$0"
        )
    
    # Renombrar columnas para mejor visualización
    column_mapping = {
        'id': 'ID',
        'reference': 'Referencia',
        'amount': 'Monto',
        'fees': 'Comisiones',
        'currency_id': 'Moneda',
        'partner_id': 'Cliente ID',
        'partner_name': 'Nombre Cliente',
        'partner_email': 'Email',
        'partner_phone': 'Teléfono',
        'partner_address': 'Dirección',
        'partner_city': 'Ciudad',
        'partner_zip': 'Código Postal',
        'partner_country_id': 'País',
        'acquirer_id': 'Proveedor Pago',
        'acquirer_reference': 'Ref. Proveedor',
        'type': 'Tipo',
        'state': 'Estado',
        'state_message': 'Mensaje',
        'date': 'Fecha Transacción',
        'create_date': 'Creado',
        'write_date': 'Modificado',
        'payment_id': 'Pago ID',
        'payment_token_id': 'Token ID',
        'is_processed': 'Procesado',
        'callback_model_id': 'Modelo Callback',
        'callback_res_id': 'Recurso Callback',
        'return_url': 'URL Retorno',
        'webpay_txn_type': 'Tipo Txn Webpay',
        'webpay_token': 'Token Webpay'
    }
    
    df_display = df_display.rename(columns=column_mapping)
    
    return df_display


def prepare_df_for_excel(df):
    """Prepara el DataFrame para Excel con formatos apropiados"""
    if df.empty:
        return df
    
    df_excel = df.copy()
    
    # Formatear fechas
    date_columns = ['date', 'create_date', 'write_date']
    for col in date_columns:
        if col in df_excel.columns:
            df_excel[col] = pd.to_datetime(df_excel[col], errors='coerce').dt.strftime('%d-%m-%Y %H:%M:%S')
    
    # Mantener montos como numéricos para Excel
    if 'amount' in df_excel.columns:
        df_excel['amount'] = pd.to_numeric(df_excel['amount'], errors='coerce')
    
    if 'fees' in df_excel.columns:
        df_excel['fees'] = pd.to_numeric(df_excel['fees'], errors='coerce')
    
    # Renombrar columnas
    column_mapping = {
        'id': 'ID',
        'reference': 'Referencia',
        'amount': 'Monto',
        'fees': 'Comisiones',
        'currency_id': 'Moneda',
        'partner_id': 'Cliente ID',
        'partner_name': 'Nombre Cliente',
        'partner_email': 'Email',
        'partner_phone': 'Teléfono',
        'partner_address': 'Dirección',
        'partner_city': 'Ciudad',
        'partner_zip': 'Código Postal',
        'partner_country_id': 'País',
        'acquirer_id': 'Proveedor Pago',
        'acquirer_reference': 'Ref. Proveedor',
        'type': 'Tipo',
        'state': 'Estado',
        'state_message': 'Mensaje',
        'date': 'Fecha Transacción',
        'create_date': 'Creado',
        'write_date': 'Modificado',
        'payment_id': 'Pago ID',
        'payment_token_id': 'Token ID',
        'is_processed': 'Procesado',
        'callback_model_id': 'Modelo Callback',
        'callback_res_id': 'Recurso Callback',
        'return_url': 'URL Retorno',
        'webpay_txn_type': 'Tipo Txn Webpay',
        'webpay_token': 'Token Webpay'
    }
    
    df_excel = df_excel.rename(columns=column_mapping)
    
    return df_excel


def convert_df_to_excel(df):
    """Convierte un DataFrame a Excel en memoria"""
    output = io.BytesIO()
    with pd.ExcelWriter(output, engine='openpyxl') as writer:
        df.to_excel(writer, index=False, sheet_name='Transacciones')
    return output.getvalue()


def apply_status_colors(df_display):
    """Aplica colores a la columna de estado usando Styler"""
    def color_state(val):
        if pd.isna(val) or val == '':
            return ''
        val_lower = str(val).lower()
        if val_lower == 'done':
            return 'background-color: #90EE90; color: black'  # Verde claro
        elif val_lower == 'pending':
            return 'background-color: #FFFF99; color: black'  # Amarillo claro
        elif val_lower == 'cancel':
            return 'background-color: #FFB6C1; color: black'  # Rojo claro
        elif val_lower == 'error':
            return 'background-color: #FFA07A; color: black'  # Naranja claro
        return ''
    
    # Aplicar estilos
    styled_df = df_display.style
    
    if 'Estado' in df_display.columns:
        styled_df = styled_df.applymap(color_state, subset=['Estado'])
    
    return styled_df


def get_statistics(df):
    """Calcula estadísticas de las transacciones"""
    if df.empty:
        return {
            'total_transacciones': 0,
            'monto_total': 0,
            'monto_promedio': 0,
            'por_proveedor': {}
        }
    
    # Calcular estadísticas
    stats = {
        'total_transacciones': len(df),
        'monto_total': pd.to_numeric(df['amount'], errors='coerce').sum(),
        'monto_promedio': pd.to_numeric(df['amount'], errors='coerce').mean(),
    }
    
    # Estadísticas por proveedor de pago
    if 'acquirer_id' in df.columns:
        provider_stats = df.groupby('acquirer_id').agg({
            'id': 'count',
            'amount': lambda x: pd.to_numeric(x, errors='coerce').sum()
        }).to_dict('index')
        stats['por_proveedor'] = provider_stats
    else:
        stats['por_proveedor'] = {}
    
    return stats


def main():
    """Función principal de la página"""
    
    st.title("💳 Transacciones Electrónicas - Odoo")
    st.markdown("---")
    
    # Verificar conexión a Odoo
    models, db, uid, password = connect_to_odoo()
    
    if not models:
        st.warning("⚠️ No hay conexión a Odoo. Por favor configure sus credenciales en la barra lateral.")
        st.info("👈 Use la barra lateral para ingresar sus credenciales de Odoo y probar la conexión.")
        st.stop()
    
    # Descripción
    st.markdown("""
    Esta página muestra las transacciones de pagos electrónicos procesadas en Odoo.
    
    **Características:**
    - 📊 Visualización de transacciones por estado
    - 📅 Filtros por período de fecha
    - 📥 Descarga en formato Excel
    - 📈 Estadísticas y resúmenes
    """)
    
    st.markdown("---")
    
    # Filtros
    st.subheader("🔍 Filtros")
    
    # Filtro de estado
    estados_disponibles = {
        'done': '✅ Completado (done)',
        'draft': '📝 Borrador (draft)',
        'cancel': '❌ Cancelado (cancel)'
    }
    
    estados_seleccionados = st.multiselect(
        "Estado de Transacciones",
        options=list(estados_disponibles.keys()),
        default=['done'],
        format_func=lambda x: estados_disponibles[x],
        help="Seleccione uno o más estados para filtrar las transacciones"
    )
    
    if not estados_seleccionados:
        st.warning("⚠️ Debe seleccionar al menos un estado")
        st.stop()
    
    st.markdown("---")
    st.subheader("📅 Filtro de Fechas")
    
    col1, col2, col3 = st.columns([2, 2, 1])
    
    with col1:
        # Fecha de inicio (por defecto: hace 6 días para incluir hoy = 7 días totales)
        fecha_inicio = st.date_input(
            "Fecha Inicio (DD/MM/AAAA)",
            value=datetime.now() - timedelta(days=6),
            format="DD/MM/YYYY",
            help="Seleccione la fecha de inicio del período (últimos 7 días por defecto, incluyendo hoy)"
        )
    
    with col2:
        # Fecha de fin (por defecto: hoy)
        fecha_fin = st.date_input(
            "Fecha Fin (DD/MM/AAAA)",
            value=datetime.now(),
            format="DD/MM/YYYY",
            help="Seleccione la fecha de fin del período"
        )
    
    with col3:
        st.markdown("<br>", unsafe_allow_html=True)
        aplicar_filtros = st.button("🔍 Buscar", use_container_width=True, type="primary")
    
    # Validar fechas
    if fecha_inicio > fecha_fin:
        st.error("⚠️ La fecha de inicio no puede ser mayor que la fecha de fin")
        st.stop()
    
    st.markdown("---")
    
    # Cargar datos
    if aplicar_filtros or 'transactions_df' not in st.session_state:
        with st.spinner("Cargando transacciones desde Odoo..."):
            df = fetch_payment_transactions(models, db, uid, password, fecha_inicio, fecha_fin, estados_seleccionados)
            st.session_state['transactions_df'] = df
            st.session_state['fecha_inicio_trans'] = fecha_inicio
            st.session_state['fecha_fin_trans'] = fecha_fin
            st.session_state['estados_trans'] = estados_seleccionados
    else:
        df = st.session_state.get('transactions_df', pd.DataFrame())
    
    # Mostrar resultados
    if df.empty:
        st.warning("⚠️ No se encontraron transacciones para el período seleccionado")
        st.info("💡 **Sugerencia:** Intente ampliar el rango de fechas o verifique que existan transacciones con estado 'done' en Odoo.")
        st.stop()
    
    # Calcular estadísticas
    stats = get_statistics(df)
    
    # Mostrar estadísticas generales
    st.subheader("📊 Resumen de Transacciones")
    
    col1, col2, col3 = st.columns(3)
    
    with col1:
        st.metric("Total Transacciones", f"{stats['total_transacciones']:,}")
    
    with col2:
        st.metric("Monto Total", f"${stats['monto_total']:,.0f}")
    
    with col3:
        st.metric("Monto Promedio", f"${stats['monto_promedio']:,.0f}")
    
    # Estadísticas por proveedor
    if stats['por_proveedor']:
        st.markdown("---")
        st.subheader("📈 Estadísticas por Proveedor")
        
        provider_data = []
        for provider, data in stats['por_proveedor'].items():
            provider_data.append({
                'Proveedor': provider if provider else 'Sin proveedor',
                'Cantidad': data['id'],
                'Monto Total': f"${data['amount']:,.0f}"
            })
        
        if provider_data:
            df_providers = pd.DataFrame(provider_data)
            st.dataframe(df_providers, use_container_width=True, hide_index=True)
    
    st.markdown("---")
    
    # Tabla de datos
    st.subheader("📋 Detalle de Transacciones")
    
    # Filtro de búsqueda
    col_search1, col_search2 = st.columns([3, 1])
    
    # Inicializar search_term en session_state si no existe
    if 'search_term' not in st.session_state:
        st.session_state.search_term = ""
    
    with col_search1:
        search_term = st.text_input(
            "🔍 Buscar por Referencia o Nombre de Cliente",
            value=st.session_state.search_term,
            placeholder="Ej: REF-12345 o Juan Pérez",
            help="Filtra los resultados por referencia de transacción o nombre del cliente",
            key="search_input"
        )
        # Actualizar session_state con el valor actual
        st.session_state.search_term = search_term
    
    with col_search2:
        st.markdown("<br>", unsafe_allow_html=True)
        if st.button("🗑️ Limpiar", use_container_width=True):
            st.session_state.search_term = ""
            st.rerun()
    
    # Formatear el DataFrame
    df_display = format_dataframe(df)
    
    # Aplicar filtro de búsqueda si hay término
    if search_term:
        # Crear máscara de búsqueda en múltiples columnas
        mask = pd.Series([False] * len(df_display))
        
        # Buscar en Referencia
        if 'Referencia' in df_display.columns:
            mask |= df_display['Referencia'].astype(str).str.contains(search_term, case=False, na=False)
        
        # Buscar en Nombre Cliente
        if 'Nombre Cliente' in df_display.columns:
            mask |= df_display['Nombre Cliente'].astype(str).str.contains(search_term, case=False, na=False)
        
        # Aplicar filtro
        df_display = df_display[mask]
        
        # Mostrar contador de resultados filtrados
        if len(df_display) == 0:
            st.warning(f"⚠️ No se encontraron resultados para: '{search_term}'")
        else:
            st.info(f"📊 Mostrando **{len(df_display)}** de **{len(df)}** transacciones")
    
    # Mostrar tabla solo si hay resultados
    if not df_display.empty:
        # Aplicar colores a la columna de estado
        styled_df = apply_status_colors(df_display)
        
        # Mostrar tabla con scroll y estilos
        st.dataframe(
            styled_df,
            use_container_width=True,
            height=400
        )
    else:
        if search_term:
            st.info("💡 **Sugerencia:** Intente con otro término de búsqueda")
    
    # Botón de descarga
    st.markdown("---")
    st.subheader("📥 Descargar Datos")
    
    col1, col2 = st.columns([3, 1])
    
    # Determinar qué datos descargar (filtrados o todos)
    df_to_download = df_display if search_term and not df_display.empty else df
    
    with col1:
        if search_term and not df_display.empty:
            st.info(f"📊 **{len(df_display)}** transacciones filtradas listas para descargar")
        else:
            st.info(f"📊 **{len(df)}** transacciones listas para descargar")
    
    with col2:
        # Preparar DataFrame para Excel (usar datos originales sin formato para Excel)
        # Necesitamos obtener los datos originales correspondientes a df_display
        if search_term and not df_display.empty:
            # Obtener índices de df_display y filtrar df original
            indices_filtrados = df_display.index
            df_original_filtrado = df.loc[indices_filtrados]
            df_excel = prepare_df_for_excel(df_original_filtrado)
        else:
            df_excel = prepare_df_for_excel(df)
        
        excel_data = convert_df_to_excel(df_excel)
        
        # Nombre del archivo con fecha
        fecha_inicio_str = st.session_state.get('fecha_inicio_trans', fecha_inicio).strftime('%Y%m%d')
        fecha_fin_str = st.session_state.get('fecha_fin_trans', fecha_fin).strftime('%Y%m%d')
        filename = f"transacciones_electronicas_{fecha_inicio_str}_{fecha_fin_str}.xlsx"
        
        st.download_button(
            label="📥 Descargar Excel",
            data=excel_data,
            file_name=filename,
            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            use_container_width=True,
            type="primary"
        )
    
    # Footer
    st.markdown("---")
    st.markdown("""
    <div style='text-align: center; color: #666; font-size: 0.9em;'>
        💡 <strong>Tip:</strong> Las transacciones mostradas tienen estado 'done' en Odoo
    </div>
    """, unsafe_allow_html=True)


if __name__ == "__main__":
    main()
