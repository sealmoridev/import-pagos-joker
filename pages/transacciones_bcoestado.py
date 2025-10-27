"""
Página de visualización de transacciones de Supabase
"""

import streamlit as st
import pandas as pd
from datetime import datetime, timedelta
import os
from dotenv import load_dotenv
import io
import requests
from auth_utils import check_internal_auth, show_auth_form

# Cargar variables de entorno
load_dotenv()

def get_supabase_client():
    """Obtiene el cliente de Supabase"""
    try:
        from supabase import create_client, Client
        
        url = os.getenv('SUPABASE_URL')
        key = os.getenv('SUPABASE_KEY')
        
        if not url or not key:
            st.error("⚠️ Configuración de Supabase incompleta. Defina SUPABASE_URL y SUPABASE_KEY en el archivo .env.")
            return None
        
        supabase: Client = create_client(url, key)
        return supabase
    except ImportError:
        st.error("⚠️ La librería 'supabase' no está instalada. Por favor instale: pip install supabase")
        return None
    except Exception as e:
        st.error(f"❌ Error al conectar con Supabase: {str(e)}")
        return None

def fetch_payments_data(supabase, fecha_inicio=None, fecha_fin=None, campo_fecha='fecha_pago'):
    """Obtiene los datos de la tabla payments con filtros de fecha"""
    try:
        query = supabase.table('payments').select('*')
        
        # Aplicar filtros de fecha si se proporcionan
        if fecha_inicio:
            query = query.gte(campo_fecha, fecha_inicio.strftime('%Y-%m-%d'))
        if fecha_fin:
            # Agregar un día a la fecha_fin para incluir todo el día seleccionado
            fecha_fin_inclusive = fecha_fin + timedelta(days=1)
            query = query.lt(campo_fecha, fecha_fin_inclusive.strftime('%Y-%m-%d'))
        
        # Ordenar por created_at descendente
        query = query.order('created_at', desc=True)
        
        response = query.execute()
        
        if response.data:
            return pd.DataFrame(response.data)
        else:
            return pd.DataFrame()
    except Exception as e:
        st.error(f"❌ Error al obtener datos: {str(e)}")
        return pd.DataFrame()

def convert_df_to_excel(df):
    """Convierte un DataFrame a Excel en memoria"""
    output = io.BytesIO()
    with pd.ExcelWriter(output, engine='openpyxl') as writer:
        df.to_excel(writer, index=False, sheet_name='Transacciones')
    return output.getvalue()

def prepare_df_for_excel(df):
    """Prepara el DataFrame para Excel con formatos apropiados"""
    df_excel = df.copy()
    
    # Formatear fechas tipo dd-mm-aaaa (fecha_pago, fecha_contable)
    date_columns_short = ['fecha_pago', 'fecha_contable']
    for col in date_columns_short:
        if col in df_excel.columns:
            df_excel[col] = pd.to_datetime(df_excel[col], errors='coerce').dt.strftime('%d-%m-%Y')
    
    # Formatear fechas tipo dd-mm-aaaaThh:mm:ss (created_at, last_reconciliation_attempt, reconciled_at)
    datetime_columns = ['created_at', 'last_reconciliation_attempt', 'reconciled_at']
    for col in datetime_columns:
        if col in df_excel.columns:
            df_excel[col] = pd.to_datetime(df_excel[col], errors='coerce').dt.strftime('%d-%m-%YT%H:%M:%S')
    
    # Formatear IDs sin separador de miles (odoo_invoice_id, odoo_payment_id)
    id_columns = ['odoo_invoice_id', 'odoo_payment_id']
    for col in id_columns:
        if col in df_excel.columns:
            df_excel[col] = df_excel[col].apply(lambda x: str(int(x)) if pd.notna(x) and x != '' else '')
    
    # Mantener monto_pagado como numérico para Excel (sin formato de moneda)
    if 'monto_pagado' in df_excel.columns:
        df_excel['monto_pagado'] = pd.to_numeric(df_excel['monto_pagado'], errors='coerce')
    
    return df_excel

def format_dataframe(df):
    """Formatea el DataFrame para visualización con colores y formatos"""
    df_display = df.copy()
    
    # Formatear fechas tipo dd-mm-aaaa (fecha_pago, fecha_contable)
    date_columns_short = ['fecha_pago', 'fecha_contable']
    for col in date_columns_short:
        if col in df_display.columns:
            df_display[col] = pd.to_datetime(df_display[col], errors='coerce').dt.strftime('%d-%m-%Y')
    
    # Formatear fechas tipo dd-mm-aaaaThh:mm:ss (created_at, last_reconciliation_attempt, reconciled_at)
    datetime_columns = ['created_at', 'last_reconciliation_attempt', 'reconciled_at']
    for col in datetime_columns:
        if col in df_display.columns:
            df_display[col] = pd.to_datetime(df_display[col], errors='coerce').dt.strftime('%d-%m-%YT%H:%M:%S')
    
    # Formatear IDs sin separador de miles (odoo_invoice_id, odoo_payment_id)
    id_columns = ['odoo_invoice_id', 'odoo_payment_id']
    for col in id_columns:
        if col in df_display.columns:
            df_display[col] = df_display[col].apply(lambda x: str(int(x)) if pd.notna(x) and x != '' else '')
    
    # Formatear monto_pagado con separador de miles sin decimales
    if 'monto_pagado' in df_display.columns:
        # Convertir a numérico primero, luego formatear
        df_display['monto_pagado'] = pd.to_numeric(df_display['monto_pagado'], errors='coerce')
        df_display['monto_pagado'] = df_display['monto_pagado'].apply(
            lambda x: f"${x:,.0f}" if pd.notna(x) else "N/A"
        )
    
    return df_display

def apply_status_colors(df_display):
    """Aplica colores a las columnas de estado usando Styler"""
    def color_status(val):
        if pd.isna(val) or val == '':
            return ''
        val_lower = str(val).lower()
        if val_lower == 'success':
            return 'background-color: #90EE90; color: black'  # Verde claro
        elif val_lower == 'pending':
            return 'background-color: #FFFF99; color: black'  # Amarillo claro
        return ''
    
    def color_reconciliation_status(val):
        if pd.isna(val) or val == '':
            return ''
        val_lower = str(val).lower()
        if val_lower == 'reconciled':
            return 'background-color: #90EE90; color: black'  # Verde claro
        elif val_lower == 'pending':
            return 'background-color: #FFFF99; color: black'  # Amarillo claro
        elif val_lower == 'failed':
            return 'background-color: #FFB6C1; color: black'  # Rojo claro
        return ''
    
    # Aplicar estilos
    styled_df = df_display.style
    
    if 'status' in df_display.columns:
        styled_df = styled_df.applymap(color_status, subset=['status'])
    
    if 'reconciliation_status' in df_display.columns:
        styled_df = styled_df.applymap(color_reconciliation_status, subset=['reconciliation_status'])
    
    return styled_df

def get_payment_by_id(supabase, payment_id):
    """Obtiene un pago específico por su ID de Supabase"""
    try:
        response = supabase.table('payments').select('*').eq('id', payment_id).execute()
        if response.data and len(response.data) > 0:
            return response.data[0]
        return None
    except Exception as e:
        st.error(f"❌ Error al obtener pago: {str(e)}")
        return None

def can_retry_reconciliation(payment_data):
    """Valida si un pago puede ser re-conciliado"""
    if not payment_data:
        return False, "Pago no encontrado"
    
    status = payment_data.get('status', '').lower()
    recon_status = payment_data.get('reconciliation_status', '').lower()
    
    if status != 'pending':
        return False, f"Status debe ser 'pending', actual: '{status}'"
    
    if recon_status != 'failed':
        return False, f"Reconciliation status debe ser 'failed', actual: '{recon_status}'"
    
    return True, "OK"

def retry_reconciliation_api(payment_id):
    """Llama a la API para reintentar la conciliación de un pago"""
    try:
        api_key = os.getenv('API_KEY_PAYMENT')
        base_url = os.getenv('URL_API_PAYMENT')
        
        if not api_key:
            return {'error': 'API_KEY_PAYMENT no configurada en .env'}, 500
        
        if not base_url:
            return {'error': 'URL_API_PAYMENT no configurada en .env'}, 500
        
        # Construir URL completa
        url = f"{base_url}{payment_id}/retry-reconciliation"
        
        headers = {
            'accept': 'application/json',
            'X-API-Key': api_key
        }
        
        response = requests.post(url, headers=headers, timeout=30)
        
        return response.json(), response.status_code
        
    except requests.exceptions.Timeout:
        return {'error': 'Timeout al llamar a la API'}, 408
    except requests.exceptions.RequestException as e:
        return {'error': f'Error de conexión: {str(e)}'}, 500
    except Exception as e:
        return {'error': f'Error inesperado: {str(e)}'}, 500

def get_failed_payments(supabase):
    """Obtiene pagos con conciliación fallida"""
    try:
        response = supabase.table('payments')\
            .select('*')\
            .eq('status', 'pending')\
            .eq('reconciliation_status', 'failed')\
            .order('created_at', desc=True)\
            .execute()
        
        if response.data:
            return pd.DataFrame(response.data)
        return pd.DataFrame()
    except Exception as e:
        st.error(f"❌ Error al obtener pagos fallidos: {str(e)}")
        return pd.DataFrame()

def render_retry_tab(supabase):
    """Renderiza el tab de re-conciliación de pagos"""
    st.subheader("🔄 Re-conciliar Pagos Fallidos")
    
    st.markdown("""
    Esta herramienta permite reintentar la conciliación de pagos que fallaron previamente.
    
    **Condiciones para re-conciliar:**
    - ✅ Status: `pending`
    - ✅ Reconciliation Status: `failed`
    """)
    
    st.markdown("---")
    
    # Opción 1: Tabla con pagos fallidos
    st.markdown("### 📋 Pagos con Conciliación Fallida")
    
    with st.spinner("Cargando pagos fallidos..."):
        failed_df = get_failed_payments(supabase)
    
    if not failed_df.empty:
        st.info(f"📊 Se encontraron **{len(failed_df)}** pago(s) con conciliación fallida")
        
        # Mostrar tabla compacta
        for idx, payment in failed_df.iterrows():
            with st.container():
                col1, col2, col3, col4, col5, col6, col7 = st.columns([1.5, 1.5, 1.5, 1.5, 1.5, 1, 1])
                
                with col1:
                    st.write(f"**ID:** `{str(payment['id'])[:8]}...`")
                
                with col2:
                    cod_reserva = payment.get('cod_reserva', 'N/A')
                    st.write(f"**Reserva:** {cod_reserva}")
                
                with col3:
                    monto = payment.get('monto_pagado', 0)
                    # Convertir a numérico si es string
                    try:
                        monto_num = float(monto) if monto else 0
                        st.write(f"**Monto:** ${monto_num:,.0f}")
                    except (ValueError, TypeError):
                        st.write(f"**Monto:** {monto}")
                
                with col4:
                    fecha_pago = pd.to_datetime(payment.get('fecha_pago'), errors='coerce')
                    if pd.notna(fecha_pago):
                        st.write(f"**F.Pago:** {fecha_pago.strftime('%d-%m-%Y')}")
                    else:
                        st.write(f"**F.Pago:** N/A")
                
                with col5:
                    fecha_contable = pd.to_datetime(payment.get('fecha_contable'), errors='coerce')
                    if pd.notna(fecha_contable):
                        st.write(f"**F.Cont:** {fecha_contable.strftime('%d-%m-%Y')}")
                    else:
                        st.write(f"**F.Cont:** N/A")
                
                with col6:
                    canal = payment.get('canal', 'N/A')
                    st.write(f"**Canal:** {canal}")
                
                with col7:
                    if st.button("🔄", key=f"retry_{payment['id']}", use_container_width=True, help="Reintentar conciliación"):
                        with st.spinner("Reintentando conciliación..."):
                            result, status_code = retry_reconciliation_api(payment['id'])
                        
                        if status_code == 200:
                            st.success(f"✅ {result.get('message', 'Conciliación iniciada')}")
                            st.balloons()
                            # Refrescar datos
                            st.rerun()
                        else:
                            error_msg = result.get('error') or result.get('detail', 'Error desconocido')
                            st.error(f"❌ Error: {error_msg}")
                
                st.markdown("---")
    else:
        st.success("✅ No hay pagos con conciliación fallida")
    
    st.markdown("---")
    
    # Opción 2: Input manual
    st.markdown("### 🔧 Re-conciliar por ID Manual")
    st.markdown("Si conoces el ID del pago de la tabla de transacciones, puedes ingresarlo directamente:")
    
    col1, col2 = st.columns([3, 1])
    
    with col1:
        payment_id = st.text_input(
            "ID de Pago",
            placeholder="Ej: 08e68a56-e000-4a8a-80d5-89328b658d96",
            help="Ingrese el ID completo del pago desde la tabla de transacciones"
        )
    
    with col2:
        st.markdown("<br>", unsafe_allow_html=True)
        retry_button = st.button("🔄 Reintentar", type="primary", use_container_width=True)
    
    if retry_button and payment_id:
        # Validar formato UUID básico
        if len(payment_id) != 36 or payment_id.count('-') != 4:
            st.warning("⚠️ El formato del ID no parece ser un UUID válido")
        else:
            with st.spinner("Validando pago..."):
                payment_data = get_payment_by_id(supabase, payment_id)
            
            if not payment_data:
                st.error("❌ No se encontró un pago con ese ID")
            else:
                # Validar condiciones
                can_retry, message = can_retry_reconciliation(payment_data)
                
                if can_retry:
                    with st.spinner("Reintentando conciliación..."):
                        result, status_code = retry_reconciliation_api(payment_id)
                    
                    if status_code == 200:
                        st.success(f"✅ {result.get('message', 'Conciliación iniciada')}")
                        st.json(result)
                        st.balloons()
                    else:
                        error_msg = result.get('error') or result.get('detail', 'Error desconocido')
                        st.error(f"❌ Error: {error_msg}")
                        st.json(result)
                else:
                    st.warning(f"⚠️ No se puede re-conciliar: {message}")
                    st.info("**Datos del pago:**")
                    st.json({
                        'status': payment_data.get('status'),
                        'reconciliation_status': payment_data.get('reconciliation_status'),
                        'reserva': payment_data.get('reserva')
                    })

def main():
    """Función principal de la página"""
    
    # Verificar autenticación
    if not check_internal_auth():
        show_auth_form()
        return
    
    st.title("💳 Transacciones de Pagos - Banco Estado")
    st.markdown("---")
    
    # Obtener cliente de Supabase
    supabase = get_supabase_client()
    
    if not supabase:
        st.stop()
    
    # Crear tabs
    tab1, tab2 = st.tabs(["📋 Ver Transacciones", "🔄 Re-conciliar Pagos"])
    
    with tab1:
        # Descripción
        st.markdown("""
        Esta página muestra las transacciones de pagos de Bco. Estado recibidos para los canales BEX, CVE e INT.
        Puede filtrar por rango de fechas y descargar los datos en formato Excel.
        """)
        
        # Filtros de fecha
        st.subheader("📅 Filtros de Fecha")
        
        # Selector de campo de fecha
        campo_fecha = st.radio(
            "Filtrar por:",
            options=["fecha_pago", "fecha_contable"],
            index=0,  # Por defecto fecha_pago
            horizontal=True,
            help="Seleccione el campo de fecha por el cual filtrar"
        )
        
        col1, col2, col3 = st.columns([2, 2, 1])
        
        with col1:
            # Fecha de inicio (por defecto: hace 7 días)
            fecha_inicio = st.date_input(
                f"Fecha Inicio ({campo_fecha})",
                value=datetime.now() - timedelta(days=7),
                help=f"Seleccione la fecha de inicio del rango según {campo_fecha}"
            )
        
        with col2:
            # Fecha de fin (por defecto: hoy)
            fecha_fin = st.date_input(
                f"Fecha Fin ({campo_fecha})",
                value=datetime.now(),
                help=f"Seleccione la fecha de fin del rango según {campo_fecha}"
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
        if aplicar_filtros or 'payments_df' not in st.session_state:
            with st.spinner("Cargando transacciones..."):
                df = fetch_payments_data(supabase, fecha_inicio, fecha_fin, campo_fecha)
                st.session_state['payments_df'] = df
                st.session_state['fecha_inicio'] = fecha_inicio
                st.session_state['fecha_fin'] = fecha_fin
                st.session_state['campo_fecha'] = campo_fecha
        else:
            df = st.session_state.get('payments_df', pd.DataFrame())
        
        # Mostrar resultados
        if df.empty:
            st.warning("⚠️ No se encontraron transacciones para el rango de fechas seleccionado")
            st.stop()
        
        # Estadísticas generales
        st.subheader("📊 Resumen de Transacciones")
        
        col1, col2, col3 = st.columns(3)
        
        with col1:
            st.metric("Total Transacciones", f"{len(df):,}")
        
        with col2:
            # Calcular monto total usando monto_pagado (convertir a numérico)
            if 'monto_pagado' in df.columns:
                monto_total = pd.to_numeric(df['monto_pagado'], errors='coerce').sum()
                st.metric("Monto Total", f"${monto_total:,.0f}")
            else:
                st.metric("Monto Total", "N/A")
        
        with col3:
            # Promedio usando monto_pagado (convertir a numérico)
            if 'monto_pagado' in df.columns:
                promedio = pd.to_numeric(df['monto_pagado'], errors='coerce').mean()
                st.metric("Monto Promedio", f"${promedio:,.0f}")
            else:
                st.metric("Monto Promedio", "N/A")
        
        st.markdown("---")
        
        # Tabla de datos
        st.subheader("📋 Detalle de Transacciones")
        
        # Configurar columnas para mostrar
        if not df.empty:
            # Formatear el DataFrame
            df_display = format_dataframe(df)
            
            # Aplicar colores a las columnas de estado
            styled_df = apply_status_colors(df_display)
            
            # Mostrar tabla con scroll y estilos
            st.dataframe(
                styled_df,
                use_container_width=True,
                height=400
            )
            
            # Botón de descarga
            st.markdown("---")
            st.subheader("📥 Descargar Datos")
            
            col1, col2 = st.columns([3, 1])
            
            with col1:
                st.info(f"📊 **{len(df)}** transacciones listas para descargar")
            
            with col2:
                # Preparar DataFrame para Excel (con monto_pagado numérico)
                df_excel = prepare_df_for_excel(df)
                excel_data = convert_df_to_excel(df_excel)
                
                # Nombre del archivo con fecha
                fecha_inicio_str = st.session_state.get('fecha_inicio', fecha_inicio).strftime('%Y%m%d')
                fecha_fin_str = st.session_state.get('fecha_fin', fecha_fin).strftime('%Y%m%d')
                filename = f"transacciones_{fecha_inicio_str}_{fecha_fin_str}.xlsx"
                
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
            💡 <strong>Tip:</strong> Use los filtros de fecha para acotar la búsqueda y mejorar el rendimiento
        </div>
        """, unsafe_allow_html=True)
    
    with tab2:
        render_retry_tab(supabase)

if __name__ == "__main__":
    main()
