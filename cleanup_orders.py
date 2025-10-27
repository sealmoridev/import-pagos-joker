import streamlit as st
import pandas as pd
import xmlrpc.client
import os
from datetime import datetime
from dotenv import load_dotenv
import io

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

def cleanup_single_order(models, db, uid, password, order_code):
    """Limpia referencias corruptas de una orden específica"""
    log_messages = []
    
    def log(message):
        timestamp = datetime.now().strftime('%H:%M:%S')
        log_messages.append(f"[{timestamp}] {message}")
    
    try:
        log(f"🔍 Buscando orden: {order_code}")
        
        # Buscar la orden
        sale_order_ids = models.execute_kw(db, uid, password, 'sale.order', 'search',
            [[('name', '=', order_code)]], {'limit': 1})
        
        if not sale_order_ids:
            log(f"❌ Orden {order_code} no encontrada")
            return False, log_messages
        
        order_id = sale_order_ids[0]
        log(f"✅ Orden encontrada: ID {order_id}")
        
        # Obtener líneas de la orden
        order_data = models.execute_kw(db, uid, password, 'sale.order', 'read',
            [[order_id]], {'fields': ['order_line', 'partner_id']})
        
        if not order_data:
            log(f"❌ No se pudo leer la orden")
            return False, log_messages
        
        order_line_ids = order_data[0].get('order_line', [])
        partner_id = order_data[0]['partner_id'][0] if order_data[0].get('partner_id') else None
        
        log(f"📋 Orden tiene {len(order_line_ids)} línea(s)")
        
        # 1. Limpiar invoice_lines en las líneas de orden
        log(f"🧹 Limpiando referencias de facturación en líneas...")
        cleaned_lines = 0
        for line_id in order_line_ids:
            try:
                models.execute_kw(db, uid, password, 'sale.order.line', 'write',
                    [[line_id], {'invoice_lines': [(5, 0, 0)]}])
                cleaned_lines += 1
            except Exception as e:
                log(f"   ⚠️ Error en línea {line_id}: {str(e)[:50]}")
        
        log(f"   ✅ {cleaned_lines}/{len(order_line_ids)} línea(s) limpiadas")
        
        # 2. Limpiar transaction_ids en la orden
        log(f"🧹 Limpiando referencias de pagos en orden...")
        try:
            models.execute_kw(db, uid, password, 'sale.order', 'write',
                [[order_id], {'transaction_ids': [(5, 0, 0)]}])
            log(f"   ✅ Referencias de transacciones limpiadas")
        except Exception as e:
            log(f"   ⚠️ Error limpiando pagos: {str(e)[:50]}")
        
        # 3. Verificar pagos del cliente
        if partner_id:
            log(f"🔍 Verificando pagos del cliente (ID {partner_id})...")
            try:
                partner_payment_ids = models.execute_kw(db, uid, password, 'account.payment', 'search',
                    [[('partner_id', '=', partner_id)]], {'limit': 100})
                
                if partner_payment_ids:
                    log(f"   📋 Encontrados {len(partner_payment_ids)} pago(s) del cliente")
                    corrupted_payments = []
                    for payment_id in partner_payment_ids:
                        try:
                            models.execute_kw(db, uid, password, 'account.payment', 'read',
                                [[payment_id], ['id']])
                        except:
                            corrupted_payments.append(payment_id)
                    
                    if corrupted_payments:
                        log(f"   ⚠️ Pagos corruptos detectados: {corrupted_payments}")
                    else:
                        log(f"   ✅ Todos los pagos del cliente son válidos")
                else:
                    log(f"   ✓ No hay pagos previos del cliente")
            except Exception as e:
                log(f"   ⚠️ Error verificando pagos: {str(e)[:50]}")
        
        log(f"✅ Limpieza completada para orden {order_code}")
        log(f"ℹ️ La orden ahora está lista para ser facturada manualmente desde Odoo")
        
        return True, log_messages
        
    except Exception as e:
        log(f"❌ Error durante limpieza: {str(e)}")
        return False, log_messages

def render_cleanup_page():
    """Renderiza la página de limpieza de órdenes"""
    st.title("🧹 Limpieza de Órdenes")
    st.markdown("""
    Esta herramienta limpia referencias corruptas en órdenes de venta para que puedan ser facturadas manualmente desde Odoo.
    
    **¿Qué hace esta herramienta?**
    - ✅ Limpia referencias de facturas corruptas (`invoice_lines`)
    - ✅ Limpia referencias de pagos corruptos (`transaction_ids`)
    - ✅ Verifica pagos del cliente
    - ✅ **NO crea** facturas ni pagos (solo limpia)
    
    **Después de la limpieza:**
    Podrás crear la factura manualmente desde Odoo sin errores de "Record does not exist".
    """)
    
    # Verificar conexión
    if not st.session_state.get('connection_verified', False):
        st.warning("⚠️ Primero debes conectarte a Odoo usando el menú lateral.")
        return
    
    st.markdown("---")
    
    # Tabs para diferentes modos
    tab1, tab2 = st.tabs(["📝 Orden Individual", "📊 Limpieza Masiva (Excel)"])
    
    with tab1:
        st.subheader("Limpiar una orden específica")
        
        order_code = st.text_input(
            "Código de Orden",
            placeholder="Ej: S38621",
            help="Ingresa el código de la orden de venta (ej: S38621)"
        )
        
        if st.button("🧹 Limpiar Orden", type="primary", disabled=not order_code):
            if order_code:
                # Conectar a Odoo
                models, db, uid, password = connect_to_odoo()
                if not all([models, db, uid, password]):
                    st.error("❌ No se pudo conectar a Odoo")
                    return
                
                # Crear contenedor para logs
                log_container = st.empty()
                
                with st.spinner(f"Limpiando orden {order_code}..."):
                    success, log_messages = cleanup_single_order(models, db, uid, password, order_code)
                
                # Mostrar logs
                with log_container.container():
                    st.text_area("📋 Log de Limpieza", "\n".join(log_messages), height=300)
                
                if success:
                    st.success(f"✅ Orden {order_code} limpiada exitosamente")
                    st.info("💡 Ahora puedes ir a Odoo y crear la factura manualmente sin errores.")
                else:
                    st.error(f"❌ No se pudo limpiar la orden {order_code}")
    
    with tab2:
        st.subheader("Limpieza masiva desde Excel")
        st.markdown("""
        Sube un archivo Excel con una columna **'Reserva'** que contenga los códigos de las órdenes a limpiar.
        """)
        
        # Botón para descargar plantilla
        template_data = pd.DataFrame({
            'Reserva': ['S12345', 'S12346', 'S12347']
        })
        template_output = io.BytesIO()
        template_data.to_excel(template_output, index=False, engine='openpyxl')
        
        st.download_button(
            label="📥 Descargar Plantilla Excel",
            data=template_output.getvalue(),
            file_name="plantilla_limpieza_ordenes.xlsx",
            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
        )
        
        uploaded_file = st.file_uploader("Cargar archivo Excel", type=['xlsx'], key='cleanup_excel')
        
        if uploaded_file is not None:
            try:
                df = pd.read_excel(uploaded_file)
                
                if 'Reserva' not in df.columns:
                    st.error("❌ El archivo debe contener una columna 'Reserva'")
                    return
                
                st.write(f"📋 Vista previa ({len(df)} órdenes):")
                st.dataframe(df.head(10))
                
                if st.button("🧹 Limpiar Todas las Órdenes", type="primary"):
                    # Conectar a Odoo
                    models, db, uid, password = connect_to_odoo()
                    if not all([models, db, uid, password]):
                        st.error("❌ No se pudo conectar a Odoo")
                        return
                    
                    # Procesar cada orden
                    progress_bar = st.progress(0)
                    results = []
                    
                    for idx, row in df.iterrows():
                        order_code = str(row['Reserva']).strip()
                        
                        st.write(f"🔄 Procesando {idx+1}/{len(df)}: {order_code}")
                        
                        success, log_messages = cleanup_single_order(models, db, uid, password, order_code)
                        
                        results.append({
                            'Reserva': order_code,
                            'Estado': '✅ Limpiada' if success else '❌ Error',
                            'Detalles': log_messages[-1] if log_messages else 'Sin detalles'
                        })
                        
                        progress_bar.progress((idx + 1) / len(df))
                    
                    # Mostrar resultados
                    results_df = pd.DataFrame(results)
                    st.subheader("📊 Resultados de Limpieza")
                    st.dataframe(results_df, use_container_width=True)
                    
                    # Estadísticas
                    success_count = len([r for r in results if '✅' in r['Estado']])
                    st.metric("Órdenes Limpiadas", f"{success_count}/{len(df)}")
                    
                    # Descargar resultados
                    output = io.BytesIO()
                    results_df.to_excel(output, index=False, engine='openpyxl')
                    
                    st.download_button(
                        label="📥 Descargar Resultados",
                        data=output.getvalue(),
                        file_name=f"resultados_limpieza_{datetime.now().strftime('%Y%m%d_%H%M%S')}.xlsx",
                        mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
                    )
                    
            except Exception as e:
                st.error(f"❌ Error al procesar el archivo: {str(e)}")

if __name__ == "__main__":
    render_cleanup_page()
