"""
Utilidades de autenticación para páginas internas
"""

import streamlit as st
import os
from dotenv import load_dotenv

# Cargar variables de entorno
load_dotenv()

def check_internal_auth():
    """
    Verifica si el usuario está autenticado para páginas internas.
    Retorna True si está autenticado, False en caso contrario.
    """
    return st.session_state.get('internal_pages_auth', False)

def show_auth_form():
    """
    Muestra el formulario de autenticación para páginas internas.
    Retorna True si la autenticación es exitosa.
    """
    st.title("🔐 Acceso Restringido")
    st.markdown("---")
    
    st.info("Esta página requiere autenticación. Por favor ingrese la contraseña.")
    
    # Formulario de contraseña
    with st.form("auth_form"):
        password = st.text_input(
            "Contraseña",
            type="password",
            help="Ingrese la contraseña para acceder a las páginas internas"
        )
        submit = st.form_submit_button("🔓 Acceder", use_container_width=True, type="primary")
        
        if submit:
            # Obtener contraseña desde .env
            correct_password = os.getenv('INTERNAL_PAGES_PASSWORD', '')
            
            if not correct_password:
                st.error("⚠️ Error de configuración: INTERNAL_PAGES_PASSWORD no está definida en .env")
                return False
            
            if password == correct_password:
                st.session_state['internal_pages_auth'] = True
                st.success("✅ Autenticación exitosa. Redirigiendo...")
                st.rerun()
                return True
            else:
                st.error("❌ Contraseña incorrecta. Intente nuevamente.")
                return False
    
    return False

def logout_internal():
    """
    Cierra la sesión de páginas internas.
    """
    if 'internal_pages_auth' in st.session_state:
        del st.session_state['internal_pages_auth']
    st.rerun()

def require_auth(page_function):
    """
    Decorador para requerir autenticación en una página.
    
    Uso:
    @require_auth
    def my_page():
        st.write("Contenido protegido")
    """
    def wrapper():
        if check_internal_auth():
            page_function()
        else:
            show_auth_form()
    return wrapper
