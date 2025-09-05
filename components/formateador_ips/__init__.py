"""
Componente Formateador IPS
Convierte archivos Excel a formato IPS para sistemas de descuentos
"""

from .ips_formatter import IPSFormatter
from .streamlit_component import render_ips_formatter, ips_formatter_page

__all__ = ['IPSFormatter', 'render_ips_formatter', 'ips_formatter_page']