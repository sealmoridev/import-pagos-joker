"""
Página de visualización de transacciones de Supabase
"""

import streamlit as st
import pandas as pd
from datetime import datetime, timedelta
import os
from dotenv import load_dotenv
import io
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

def main():
    """Función principal de la página"""
    
    # Verificar autenticación
    if not check_internal_auth():
        show_auth_form()
        return
    
    st.title("💳 Transacciones de Pagos - Banco Estado")
    st.markdown("---")
    
    # Descripción
    st.markdown("""
    Esta página muestra las transacciones de pagos de Bco. Estado recibidos para los canales BEX, CVE e INT.
    Puede filtrar por rango de fechas y descargar los datos en formato Excel.
    """)
    
    # Obtener cliente de Supabase
    supabase = get_supabase_client()
    
    if not supabase:
        st.stop()
    
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

if __name__ == "__main__":
    main()
