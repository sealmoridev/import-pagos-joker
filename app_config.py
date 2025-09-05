"""
Configuración de la aplicación multi-página
"""

import streamlit as st
from typing import Dict, Callable
import os
from dotenv import load_dotenv
import xmlrpc.client

class AppConfig:
    """Configuración centralizada de la aplicación"""
    
    PAGES = {
        "🏠 Importar Pagos": {
            "icon": "🏠",
            "description": "Proceso principal de importación de pagos a Odoo",
            "module": "main",
            "critical": True
        },
        "📄 Formateador IPS": {
            "icon": "📄", 
            "description": "Convertir archivos Excel a formato IPS",
            "module": "pages.formateador_ips",
            "critical": False
        }
    }
    
    @staticmethod
    def get_page_config(page_name: str) -> Dict:
        """Obtiene configuración de una página específica"""
        return AppConfig.PAGES.get(page_name, {})
    
    @staticmethod
    def is_critical_page(page_name: str) -> bool:
        """Verifica si una página es crítica"""
        return AppConfig.get_page_config(page_name).get("critical", False)
    
    @staticmethod
    def get_navigation_menu() -> Dict[str, str]:
        """Genera menú de navegación"""
        return {name: config["description"] for name, config in AppConfig.PAGES.items()}

def setup_page_navigation():
    """Configura la navegación entre páginas"""
    
    # Inicializar página actual en session_state
    if 'current_page' not in st.session_state:
        st.session_state.current_page = "🏠 Importar Pagos"
    
    # Sidebar para navegación
    with st.sidebar:
        st.markdown("## 🧭 Navegación")
        
        # Mostrar páginas disponibles
        for page_name, config in AppConfig.PAGES.items():
            is_current = st.session_state.current_page == page_name
            
            # Estilo diferente para página crítica
            if config.get("critical", False):
                button_type = "primary" if is_current else "secondary"
                help_text = "Proceso crítico de pagos"
            else:
                button_type = "secondary"
                help_text = config["description"]
            
            if st.button(
                f"{config['icon']} {page_name.split(' ', 1)[1]}", 
                key=f"nav_{page_name}",
                help=help_text,
                type=button_type if is_current else "secondary",
                use_container_width=True
            ):
                st.session_state.current_page = page_name
                st.rerun()
        
        # Separador
        st.markdown("---")
        
        # Solo mostrar configuración de Odoo si NO estamos en la página del formateador
        current_page = st.session_state.get('current_page', '🏠 Importar Pagos')
        if current_page != "📄 Formateador IPS":
            # Configuración de Conexión a Odoo
            st.markdown("### 🔐 Configuración de Conexión")
            
            # Obtener URL desde variables de entorno
            url = os.getenv('ODOO_URL', '')
            if url:
                st.info(f"**Servidor:** {url}")
            else:
                st.error("⚠️ ODOO_URL no configurada en .env")
            
            # Campos de credenciales
            username = st.text_input("Usuario", 
                                    value=st.session_state.get('odoo_username', ''),
                                    key="sidebar_username")
            password = st.text_input("Contraseña", 
                                    value=st.session_state.get('odoo_password', ''),
                                    type="password",
                                    key="sidebar_password")
            
            # Guardar credenciales en session_state
            if username:
                st.session_state['odoo_username'] = username
            if password:
                st.session_state['odoo_password'] = password
            
            # Botón de Probar Conexión
            if st.button("🔌 Probar Conexión a Odoo", use_container_width=True):
                if username and password:
                    load_dotenv()
                    url = os.getenv('ODOO_URL', '')
                    db = os.getenv('ODOO_DB', '')
                    
                    try:
                        with st.spinner("Probando conexión..."):
                            # Guardar credenciales para connect_to_odoo
                            st.session_state['odoo_url'] = url
                            st.session_state['odoo_db'] = db
                            
                            # Probar conexión
                            common = xmlrpc.client.ServerProxy(f'{url}/xmlrpc/2/common')
                            uid = common.authenticate(db, username, password, {})
                            
                            if uid:
                                st.success("✅ Conexión exitosa a Odoo")
                                st.session_state['connection_verified'] = True
                            else:
                                st.error("❌ Error de autenticación")
                                st.session_state['connection_verified'] = False
                    except Exception as e:
                        st.error(f"❌ Error de conexión: {str(e)}")
                        st.session_state['connection_verified'] = False
                else:
                    st.warning("⚠️ Ingrese usuario y contraseña")
            
            # Mostrar estado de conexión
            if st.session_state.get('connection_verified', False):
                st.success(f"✅ Conectado como: {username}")
            
            st.markdown("---")
        
        # Información de la página actual
        current_config = AppConfig.get_page_config(st.session_state.current_page)
        if current_config:
            st.markdown("### 📍 Página Actual")
            st.info(f"**{st.session_state.current_page}**\n\n{current_config['description']}")
            
            if current_config.get("critical", False):
                st.warning("⚠️ **Proceso Crítico**\nEsta página maneja operaciones importantes del negocio.")

def get_current_page() -> str:
    """Obtiene la página actual"""
    return st.session_state.get('current_page', "🏠 Importar Pagos")
