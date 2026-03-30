import streamlit as st
import pdfplumber
import pandas as pd
import io
import re
from copy import copy
from collections import defaultdict
from openpyxl import load_workbook

# ============================================================
# 1. CONFIGURACIÓN DE PÁGINA Y UTILIDADES
# ============================================================
st.set_page_config(page_title="Consolidador Confidelis PRO", layout="wide")

def normalizar(t):
    return str(t).upper().strip() if t else ""

def extraer_numeros(texto):
    return [float(n.replace(",", "")) for n in re.findall(r"[\d,]+\.\d+", texto)]

def extraer_todos_numeros(texto):
    return [float(n.replace(",", "")) for n in re.findall(r"[\d,]+\.?\d*", texto) if n]

# ============================================================
# 2. MOTOR DE EXTRACCIÓN (PDF -> Datos)
# ============================================================
def detectar_plataforma(texto):
    return "Prestadero" if "PRESTADERO" in texto.upper() else "GBM"

def extraer_nombre_cliente(pdf, plataforma):
    texto = pdf.pages[0].extract_text() or ""
    lineas = texto.split("\n")
    if plataforma == "Prestadero":
        for l in lineas:
            if "Periodo:" in l and "Estado de Cuenta" not in l:
                return re.split(r"\s+Periodo:", l)[0].strip().upper()
    else:
        for l in lineas:
            if "Contrato:" in l:
                p = re.split(r"\s+Contrato:", l)[0].strip()
                return p.replace("PUBLICO EN GENERAL - ", "").upper()
    return "DESCONOCIDO"

def extraer_portafolio_gbm(pdf):
    portafolio = []
    en_acciones = False
    for pag in pdf.pages:
        texto = pag.extract_text() or ""
        for l in texto.split("\n"):
            lu = l.upper()
            if "ACCIONES" in lu: en_acciones = True; continue
            if en_acciones and (lu.startswith("TOTAL") or "RENDIMIENTO" in lu): 
                en_acciones = False; continue
            if not en_acciones: continue
            
            m = re.match(r"^([A-Z]+(?:\s+\d+)?)\s+", l.strip())
            if m:
                nums = extraer_todos_numeros(l[m.end():])
                if len(nums) >= 8:
                    portafolio.append({"emisora": m.group(1).strip(), "valor": nums[7]})
    return portafolio

# ============================================================
# 3. LÓGICA DE CONSOLIDACIÓN (Actualización de Celdas)
# ============================================================
def actualizar_hoja_maestra(ws, datos_pdf):
    fila_header = 23
    fila_totales = None
    # Buscar dinámicamente la fila de Totales
    for r in range(1, 150):
        val = str(ws.cell(r, 1).value).upper()
        if "INSTRUMENTO" in val: fila_header = r
        if "TOTALES" in val: 
            fila_totales = r
            break
    
    if not fila_totales: return

    # Mapear instrumentos existentes en el Excel
    existentes = {}
    for r in range(fila_header + 1, fila_totales):
        nom = normalizar(ws.cell(r, 1).value)
        if nom and nom != "-": existentes[nom] = r

    # Actualizar saldos o insertar nuevos
    port_pdf = {normalizar(i["emisora"]): i["valor"] for i in datos_pdf.get("portafolio", [])}
    
    for emisora, valor_nuevo in port_pdf.items():
        if emisora in existentes:
            row = existentes[emisora]
            old_b = ws.cell(row, 2).value or 0
            ws.cell(row, 3).value = valor_nuevo
            ws.cell(row, 5).value = valor_nuevo - old_b
            ws.cell(row, 14).value = valor_nuevo
        else:
            # Insertar nueva fila antes de Totales
            ws.insert_rows(fila_totales)
            ws.cell(fila_totales, 1).value = emisora
            ws.cell(fila_totales, 2).value = valor_nuevo
            ws.cell(fila_totales, 3).value = valor_nuevo
            ws.cell(fila_totales, 14).value = valor_nuevo
            ws.cell(fila_totales, 15).value = "GBM"
            fila_totales += 1

# ============================================================
# 4. APLICACIÓN STREAMLIT
# ============================================================
def main():
    st.title("💰 Consolidador Confidelis - Versión Cloud")
    st.info("Sube el archivo maestro y los PDFs para consolidar la información.")

    # Selectores de Archivos
    maestro_file = st.file_uploader("1. Sube el Maestro (.xlsx)", type="xlsx")
    pdf_files = st.file_uploader("2. Sube los PDFs", type="pdf", accept_multiple_files=True)

    if st.button("🚀 Iniciar Consolidación"):
        if maestro_file and pdf_files:
            try:
                # Cargar Maestro en memoria
                wb = load_workbook(maestro_file)
                
                # Procesar PDFs
                clientes_dict = defaultdict(lambda: {"portafolio": []})
                for f in pdf_files:
                    with pdfplumber.open(f) as pdf:
                        plat = detectar_plataforma(pdf.pages[0].extract_text() or "")
                        nombre = extraer_nombre_cliente(pdf, plat)
                        if plat == "GBM":
                            clientes_dict[nombre]["portafolio"].extend(extraer_portafolio_gbm(pdf))

                # Actualizar hojas del Excel
                for nombre, data in clientes_dict.items():
                    sheet_name = next((s for s in wb.sheetnames if nombre in s.upper() or s.upper() in nombre), None)
                    if sheet_name:
                        actualizar_hoja_maestra(wb[sheet_name], data)
                        st.success(f"Hoja '{sheet_name}' actualizada correctamente.")
                    else:
                        st.warning(f"No se encontró hoja para: {nombre}")

                # --- MANEJO SEGURO DEL BUFFER DE DESCARGA ---
                buffer = io.BytesIO()
                wb.save(buffer)
                buffer.seek(0) # Mover puntero al inicio del archivo
                
                st.download_button(
                    label="📥 Descargar Excel Consolidado",
                    data=buffer,
                    file_name="Consolidado_Final.xlsx",
                    mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
                )
                
            except Exception as e:
                st.error(f"Error durante el procesamiento: {e}")
        else:
            st.warning("Asegúrate de cargar todos los archivos necesarios.")

if __name__ == "__main__":
    main()
