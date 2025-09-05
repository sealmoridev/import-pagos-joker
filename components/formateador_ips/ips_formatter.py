import pandas as pd
import re
from datetime import datetime
from typing import Dict, List, Tuple, Optional
import streamlit as st

class IPSFormatter:
    """
    Formateador de archivos de descuento según especificaciones IPS
    """
    
    def __init__(self):
        self.field_definitions = {
            'DISA-RUTBEN': {'format': 'PIC 9(08)', 'length': 8, 'start': 1, 'end': 8, 'type': 'numeric'},
            'DISA-DVRBEN': {'format': 'PIC X(01)', 'length': 1, 'start': 9, 'end': 9, 'type': 'text'},
            'DISA-CODINSC': {'format': 'PIC 9(02)', 'length': 2, 'start': 10, 'end': 11, 'type': 'numeric'},
            'DISA-TIPREG': {'format': 'PIC 9(01)', 'length': 1, 'start': 12, 'end': 12, 'type': 'numeric'},
            'DISA-ATRIB': {'format': 'PIC 9(01)', 'length': 1, 'start': 13, 'end': 13, 'type': 'numeric'},
            'DISA-CODDES': {'format': 'PIC 9(04)', 'length': 4, 'start': 14, 'end': 17, 'type': 'numeric'},
            'DISA-UMDESC': {'format': 'PIC 9(02)', 'length': 2, 'start': 18, 'end': 19, 'type': 'numeric'},
            'DISA-NUMINS': {'format': 'PIC 9(13)', 'length': 13, 'start': 20, 'end': 32, 'type': 'numeric'},
            'DISA-DVNINS': {'format': 'PIC X(01)', 'length': 1, 'start': 33, 'end': 33, 'type': 'text'},
            'DISA-GRUPA': {'format': 'PIC 9(01)', 'length': 1, 'start': 34, 'end': 34, 'type': 'numeric'},
            'DISA-NUMBE': {'format': 'PIC 9(02)', 'length': 2, 'start': 35, 'end': 36, 'type': 'numeric'},
            'DISA-NUMRET': {'format': 'PIC 9(01)', 'length': 1, 'start': 37, 'end': 37, 'type': 'numeric'},
            'DISA-TIPMOV': {'format': 'PIC 9(01)', 'length': 1, 'start': 38, 'end': 38, 'type': 'numeric'},
            'DISA-NOMBRE': {'format': 'PIC X(40)', 'length': 40, 'start': 39, 'end': 78, 'type': 'text'},
            'DISA-MONDE': {'format': 'PIC 9(10)', 'length': 10, 'start': 79, 'end': 88, 'type': 'numeric'},
            'DISA-FECINI': {'format': 'PIC 9(08)', 'length': 8, 'start': 89, 'end': 96, 'type': 'numeric'},
            'DISA-FECVEN': {'format': 'PIC 9(08)', 'length': 8, 'start': 97, 'end': 104, 'type': 'numeric'},
            'DISA-CANCUO': {'format': 'PIC 9(03)', 'length': 3, 'start': 105, 'end': 107, 'type': 'numeric'},
            'DISA-FECMOV': {'format': 'PIC 9(06)', 'length': 6, 'start': 108, 'end': 113, 'type': 'numeric'},
            'DISA-AGENCIA': {'format': 'PIC 9(03)', 'length': 3, 'start': 114, 'end': 116, 'type': 'numeric'},
        }
        
        self.errors = []
        self.warnings = []
    
    def validate_rut(self, rut: str) -> Tuple[bool, str, str]:
        """Valida RUT chileno y retorna RUT sin DV y DV"""
        try:
            # Limpiar RUT
            rut_clean = re.sub(r'[^0-9kK]', '', str(rut))
            
            if len(rut_clean) < 2:
                return False, "", ""
            
            rut_number = rut_clean[:-1]
            dv = rut_clean[-1].upper()
            
            # Calcular DV
            factor = 2
            sum_val = 0
            
            for digit in reversed(rut_number):
                sum_val += int(digit) * factor
                factor = factor + 1 if factor < 7 else 2
            
            remainder = sum_val % 11
            calculated_dv = 'K' if remainder == 1 else ('0' if remainder == 0 else str(11 - remainder))
            
            is_valid = dv == calculated_dv
            
            return is_valid, rut_number.zfill(8), calculated_dv
            
        except Exception:
            return False, "", ""
    
    def format_field(self, value, field_name: str) -> str:
        """Formatea un campo según las especificaciones"""
        field_def = self.field_definitions[field_name]
        length = field_def['length']
        field_type = field_def['type']
        
        if pd.isna(value) or value == "":
            if field_type == 'numeric':
                return '0' * length
            else:
                return ' ' * length
        
        str_value = str(value).strip()
        
        if field_type == 'numeric':
            # Remover caracteres no numéricos
            numeric_value = re.sub(r'[^0-9]', '', str_value)
            if not numeric_value:
                numeric_value = '0'
            return numeric_value.zfill(length)
        else:
            # Texto - truncar o rellenar con espacios
            return str_value[:length].ljust(length)
    
    def generate_filename(self, coddes: str, mes: int, año: int) -> str:
        """Genera nombre de archivo según formato IPS"""
        codigo_desc_padded = str(coddes).zfill(4)
        mes_año = f"{mes:02d}{año}"
        
        return f"fu{codigo_desc_padded}01{mes_año}.txt"
    
    def validate_record(self, record: Dict, line_number: int) -> List[str]:
        """Valida un registro completo"""
        errors = []
        
        # Validar RUT
        rut_valid, _, _ = self.validate_rut(record.get('DISA-RUTBEN', ''))
        if not rut_valid:
            errors.append(f"Línea {line_number}: RUT inválido")
        
        # Validar longitud total
        formatted_record = self.format_record(record)
        if len(formatted_record) != 116:
            errors.append(f"Línea {line_number}: Registro no tiene 116 caracteres")
        
        # Validar campos obligatorios
        required_fields = ['DISA-RUTBEN', 'DISA-CODDES', 'DISA-MONDE', 'DISA-FECINI']
        for field in required_fields:
            field_value = record.get(field)
            if field_value is None or pd.isna(field_value) or str(field_value).strip() == '':
                errors.append(f"Línea {line_number}: Campo {field} es obligatorio")
        
        return errors
    
    def format_record(self, record: Dict) -> str:
        """Formatea un registro completo a 116 caracteres"""
        formatted = ""
        
        for field_name in self.field_definitions.keys():
            value = record.get(field_name, "")
            formatted += self.format_field(value, field_name)
        
        return formatted
    
    def process_dataframe_complete(self, df: pd.DataFrame, 
                                  fixed_params: Dict) -> Tuple[str, List[str], str]:
        """
        Procesa un DataFrame completo con todos los campos IPS
        Returns: (contenido_archivo, errores, nombre_archivo)
        """
        self.errors = []
        records = []
        
        # Validar columnas requeridas
        required_columns = ['RUT', 'NOMBRE', 'MONTO', 'CODINSC', 'NUMINS', 'DVNINS', 'FECINI', 'CANCUO']
        missing_columns = [col for col in required_columns if col not in df.columns]
        if missing_columns:
            self.errors.append(f"Faltan columnas requeridas: {', '.join(missing_columns)}")
            return "", self.errors, ""
        
        for idx, row in df.iterrows():
            line_number = int(idx) + 1 if isinstance(idx, (int, float)) else 1
            
            # Validar y procesar RUT
            rut_str = str(row['RUT'])
            rut_valid, rut_number, dv = self.validate_rut(rut_str)
            if not rut_valid:
                self.errors.append(f"Línea {line_number}: RUT inválido: {rut_str}")
                continue
            
            # Procesar fecha FECINI
            try:
                fecini_str = str(row['FECINI'])
                if '/' in fecini_str:
                    fecha_parts = fecini_str.split('/')
                    if len(fecha_parts) == 3:
                        fecini = f"{fecha_parts[0].zfill(2)}{fecha_parts[1].zfill(2)}{fecha_parts[2]}"
                    else:
                        raise ValueError("Formato de fecha incorrecto")
                else:
                    fecini = "01012024"  # Valor por defecto
            except:
                self.errors.append(f"Línea {line_number}: Fecha FECINI inválida: {row['FECINI']}")
                continue
            
            # Crear registro completo
            record = {
                'DISA-RUTBEN': rut_number,
                'DISA-DVRBEN': dv,
                'DISA-CODINSC': str(row['CODINSC']).zfill(2),
                'DISA-TIPREG': str(fixed_params['tipreg']),
                'DISA-ATRIB': str(fixed_params['atrib']),
                'DISA-CODDES': str(fixed_params['coddes']).zfill(4),
                'DISA-UMDESC': str(fixed_params['umdesc']).zfill(2),
                'DISA-NUMINS': str(row['NUMINS']).zfill(13),
                'DISA-DVNINS': str(row['DVNINS']),
                'DISA-GRUPA': str(fixed_params['grupa']),
                'DISA-NUMBE': str(fixed_params['numbe']).zfill(2),
                'DISA-NUMRET': str(fixed_params['numret']),
                'DISA-TIPMOV': str(fixed_params['tipmov']),
                'DISA-NOMBRE': str(row['NOMBRE'])[:40],
                'DISA-MONDE': str(row['MONTO']).zfill(10),
                'DISA-FECINI': fecini,
                'DISA-FECVEN': str(fixed_params.get('fecven', '99999999')),
                'DISA-CANCUO': str(row['CANCUO']).zfill(3),
                'DISA-FECMOV': f"{fixed_params['mes']:02d}{fixed_params['año']}",
                'DISA-AGENCIA': str(fixed_params['agencia']).zfill(3)
            }
            
            # Formatear registro
            formatted_record = self.format_record(record)
            records.append(formatted_record)
        
        # Generar contenido y nombre de archivo
        content = '\n'.join(records)
        filename = self.generate_filename(fixed_params['coddes'], fixed_params['mes'], fixed_params['año'])
        
        return content, self.errors, filename
    
    def generate_preview_with_markers(self, df, fixed_params, max_records=3):
        """
        Genera un preview del archivo TXT con marcadores de posición para cada campo
        """
        if df.empty:
            return "No hay datos para mostrar"
        
        preview_lines = []
        
        # Línea de posiciones (1-116) sin "Pos:"
        pos_line = "".join([str(i % 10) for i in range(1, 117)])
        preview_lines.append(pos_line)
        
        # Línea de decenas
        tens_line = "".join([str(i // 10) if i % 10 == 0 and i > 0 else " " for i in range(1, 117)])
        preview_lines.append(tens_line)
        
        preview_lines.append("")  # Línea en blanco
        
        # Procesar algunos registros como ejemplo
        for idx in range(min(max_records, len(df))):
            row = df.iloc[idx]
            
            # Crear registro para formatear
            record = {
                'DISA-RUTBEN': str(row.get('RUT', '')),
                'DISA-NOMBRE': str(row.get('NOMBRE', '')),
                'DISA-MONDE': str(row.get('MONTO', 0)),
                'DISA-CODINSC': str(row.get('CODINSC', '')),
                'DISA-NUMINS': str(row.get('NUMINS', '')),
                'DISA-DVNINS': str(row.get('DVNINS', '')),
                'DISA-FECINI': row.get('FECINI'),
                'DISA-CANCUO': str(row.get('CANCUO', '0')),
                'DISA-TIPREG': str(fixed_params.get('tipreg', 2)),
                'DISA-ATRIB': str(fixed_params.get('atrib', 0)),
                'DISA-CODDES': str(fixed_params.get('coddes', 1005)),
                'DISA-UMDESC': str(fixed_params.get('umdesc', '02')),
                'DISA-GRUPA': str(fixed_params.get('grupa', 1)),
                'DISA-NUMBE': str(fixed_params.get('numbe', '01')),
                'DISA-NUMRET': str(fixed_params.get('numret', 0)),
                'DISA-TIPMOV': str(fixed_params.get('tipmov', 1)),
                'DISA-FECMOV': f"{fixed_params.get('mes', 1):02d}{fixed_params.get('año', 2024)}",
                'DISA-FECVEN': '99999999',
                'DISA-AGENCIA': str(fixed_params.get('agencia', 972))
            }
            
            # Formatear el registro completo
            formatted_record = self.format_record(record)
            preview_lines.append(f"Reg {idx + 1}: {formatted_record}")
            
            # Mostrar desglose de campos con colores/símbolos para identificación
            preview_lines.append("Campos DISA:")
            
            # Formatear campos para mostrar
            rut_formatted = self.format_field(record['DISA-RUTBEN'], 'DISA-RUTBEN')
            nombre_formatted = self.format_field(record['DISA-NOMBRE'], 'DISA-NOMBRE')
            monto_formatted = self.format_field(record['DISA-MONDE'], 'DISA-MONDE')
            codinsc_formatted = self.format_field(record['DISA-CODINSC'], 'DISA-CODINSC')
            numins_formatted = self.format_field(record['DISA-NUMINS'], 'DISA-NUMINS')
            dvnins_formatted = self.format_field(record['DISA-DVNINS'], 'DISA-DVNINS')
            fecini_formatted = self.format_field(record['DISA-FECINI'], 'DISA-FECINI')
            cancuo_formatted = self.format_field(record['DISA-CANCUO'], 'DISA-CANCUO')
            
            # Formatear campos fijos para mostrar
            tipreg_formatted = self.format_field(record['DISA-TIPREG'], 'DISA-TIPREG')
            atrib_formatted = self.format_field(record['DISA-ATRIB'], 'DISA-ATRIB')
            coddes_formatted = self.format_field(record['DISA-CODDES'], 'DISA-CODDES')
            umdesc_formatted = self.format_field(record['DISA-UMDESC'], 'DISA-UMDESC')
            grupa_formatted = self.format_field(record['DISA-GRUPA'], 'DISA-GRUPA')
            numbe_formatted = self.format_field(record['DISA-NUMBE'], 'DISA-NUMBE')
            numret_formatted = self.format_field(record['DISA-NUMRET'], 'DISA-NUMRET')
            tipmov_formatted = self.format_field(record['DISA-TIPMOV'], 'DISA-TIPMOV')
            fecmov_formatted = self.format_field(record['DISA-FECMOV'], 'DISA-FECMOV')
            fecven_formatted = self.format_field(record['DISA-FECVEN'], 'DISA-FECVEN')
            agencia_formatted = self.format_field(record['DISA-AGENCIA'], 'DISA-AGENCIA')
            
            # Mostrar campos con símbolos para diferenciación visual
            preview_lines.append(f"  🔵 RUTBEN(1-8): '{rut_formatted[:8]}' | 🔵 DVRBEN(9-9): '{rut_formatted[8:9]}'")
            preview_lines.append(f"  🟢 CODINSC(10-11): '{codinsc_formatted}' | 🔴 TIPREG(12-12): '{tipreg_formatted}'")
            preview_lines.append(f"  🔴 ATRIB(13-13): '{atrib_formatted}' | 🔴 CODDES(14-17): '{coddes_formatted}'")
            preview_lines.append(f"  🔴 UMDESC(18-19): '{umdesc_formatted}' | 🔴 GRUPA(20-20): '{grupa_formatted}'")
            preview_lines.append(f"  🔴 NUMBE(21-22): '{numbe_formatted}' | 🔴 NUMRET(23-23): '{numret_formatted}'")
            preview_lines.append(f"  🔴 TIPMOV(24-24): '{tipmov_formatted}' | 🔴 FECMOV(25-30): '{fecmov_formatted}'")
            preview_lines.append(f"  🟡 MONDE(31-38): '{monto_formatted}' | 🟢 NUMINS(39-50): '{numins_formatted}'")
            preview_lines.append(f"  🟢 DVNINS(51-51): '{dvnins_formatted}' | 🟢 FECINI(52-59): '{fecini_formatted}'")
            preview_lines.append(f"  🟢 CANCUO(60-61): '{cancuo_formatted}' | 🔴 FECVEN(62-69): '{fecven_formatted}'")
            preview_lines.append(f"  🟡 NOMBRE(70-99): '{nombre_formatted}' | 🔴 AGENCIA(100-102): '{agencia_formatted}'")
            preview_lines.append(f"  ⚪ ESPACIOS(103-116): '{' ' * 14}'")
            preview_lines.append("")  # Línea en blanco entre registros
        
        return "\n".join(preview_lines)

    def process_dataframe(self, df: pd.DataFrame, 
                         column_mapping: Dict[str, str],
                         codigo_descuento: str,
                         agrupacion: str,
                         mes: int,
                         año: int) -> Tuple[str, List[str], str]:
        """
        Procesa un DataFrame completo (método legacy)
        Returns: (contenido_archivo, errores, nombre_archivo)
        """
        self.errors = []
        records = []
        
        # Mapear columnas
        mapped_df = df.rename(columns=column_mapping)
        
        # Agregar campos fijos
        mapped_df['DISA-CODDES'] = codigo_descuento
        mapped_df['DISA-FECMOV'] = f"{mes:02d}{año}"
        
        for idx, row in mapped_df.iterrows():
            # Validar registro
            line_number = int(idx) + 1 if isinstance(idx, (int, float)) else 1
            record_errors = self.validate_record(row.to_dict(), line_number)
            self.errors.extend(record_errors)
            
            # Formatear registro
            formatted_record = self.format_record(row.to_dict())
            records.append(formatted_record)
        
        # Generar contenido y nombre de archivo
        content = '\n'.join(records)
        filename = self.generate_filename(codigo_descuento, mes, año)
        
        return content, self.errors, filename