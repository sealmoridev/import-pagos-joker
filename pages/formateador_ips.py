"""
Página del Formateador IPS
Convierte archivos Excel a formato IPS para sistemas de descuentos
"""

import streamlit as st
import sys
import os

# Agregar el directorio raíz al path para importar componentes
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from components.formateador_ips import render_ips_formatter

def main():
    """Página principal del formateador IPS"""
    
    # Configuración de la página
    st.set_page_config(
        page_title="Formateador IPS",
        page_icon="📄",
        layout="wide",
        initial_sidebar_state="expanded"
    )
    
    # Título principal
    st.title("📄 Formateador de Archivos IPS")
    st.markdown("---")
    
    # Información en sidebar
    with st.sidebar:
        st.markdown("### ℹ️ Información")
        st.info("""
        **Formateador IPS** convierte archivos Excel a formato de texto 
        compatible con sistemas de descuentos IPS.
        
        **Características:**
        - Validación de RUT chileno
        - Mapeo flexible de columnas
        - Generación automática de nombres de archivo
        - Validación de campos obligatorios
        - Preview del archivo generado
        """)
        
        st.markdown("### 📋 Formato de Archivo")
        st.info("""
        **Archivo de salida:**
        - Formato: Texto plano (.txt)
        - Longitud: 116 caracteres por línea
        - Codificación: ASCII
        - Nombre: fuDDDDGGMMAAAA.txt
        
        Donde:
        - DDDD: Código descuento (4 dígitos)
        - GG: Agrupación (2 dígitos)  
        - MM: Mes (2 dígitos)
        - AAAA: Año (4 dígitos)
        """)
    
    # Renderizar el componente principal
    render_ips_formatter()
    
    # Footer
    st.markdown("---")
    st.markdown(
        "<div style='text-align: center; color: #666;'>"
        "Formateador IPS v1.0 | Desarrollado para sistemas de descuentos"
        "</div>", 
        unsafe_allow_html=True
    )

if __name__ == "__main__":
    main()
