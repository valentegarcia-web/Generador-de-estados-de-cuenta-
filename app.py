import streamlit as st
import pdfplumber
import pandas as pd
import io
import re
from copy import copy
from collections import defaultdict
from openpyxl import load_workbook

# ============================================================
# 1. CONFIGURACIÓN Y UTILIDADES BÁSICAS
# ============================================================
st.set_page_config(page_title="Consolidador Financiero Confidelis", layout="wide")

def normalizar(t):
    return str(t).upper().strip() if t else ""

def extraer_numeros(texto):
    return [float(n.replace(",", "")) for n in re.findall(r"[\d,]+\.\d+", texto)]

def extraer_todos_numeros(texto):
    return [float(n.replace(",", "")) for n in re.findall(r"[\d,]+\.?\d*", texto) if n]

def extraer_numero_despues_de(texto, clave):
    idx = texto.find(clave)
    if idx == -1: return 0.0
    sub = texto[idx + len(clave):]
    nums = extraer_numeros(sub)
    return nums[0] if nums else 0.0

def extraer_periodo(texto):
    m = re.search(r"DE\s+([A-Z]+)\s+DE\s+(\d{4})", texto.upper())
    return f"{m.group(1)} {m.group(2)}" if m else "NUEVO"

# ============================================================
# 2. MOTOR DE EXTRACCIÓN FINANCIERA (PDF -> DATOS)
# ============================================================
def procesar_pdf_financiero(f):
    with pdfplumber.open(f) as pdf:
        texto_p1 = pdf.pages[0].extract_text() or ""
        plataforma = "Prestadero" if "PRESTADERO" in texto_p1.upper() else "GBM"
        nombre = "DESCONOCIDO"
        periodo_str = extraer_periodo(texto_p1)
        datos = {}

        if plataforma == "Prestadero":
            for l in texto_p1.split("\n"):
                if "Periodo:" in l and "Estado de Cuenta" not in l:
                    nombre = re.split(r"\s+Periodo:", l)[0].strip().upper()
            datos = {
                "plataforma": "Prestadero",
                "valor_total": extraer_numero_despues_de(texto_p1, "Valor de la Cuenta:"),
                "depositos": extraer_numero_despues_de(texto_p1, "Abonos:"),
                "retiros": extraer_numero_despues_de(texto_p1, "Retiros:"),
                "interes_mes": 0.0
            }
            for l in texto_p1.split("\n"):
                if "Interés Recibido" in l or "Interes Recibido" in l:
                    nums = extraer_numeros(l)
                    if nums: datos["interes_mes"] = nums[0]
        else:
            for l in texto_p1.split("\n"):
                if "Contrato:" in l:
                    nombre = re.split(r"\s+Contrato:", l)[0].replace("PUBLICO EN GENERAL - ", "").strip().upper()
            
            portafolio = []
            movs = {"COMPRAS": defaultdict(float), "VENTAS": defaultdict(float)}
            efectivo_total = 0.0
            en_acciones = en_mov = False
            
            for pag in pdf.pages:
                texto_pag = pag.extract_text() or ""
                if "VALOR TOTAL" in texto_pag.upper() or "EFECTIVO" in texto_pag.upper():
                    nums = extraer_todos_numeros(texto_pag)
                    if len(nums) > 0: efectivo_total = nums[-1]
                
                for ls in texto_pag.split("\n"):
                    lu = ls.strip().upper()
                    if "ACCIONES" in lu: en_acciones = True; continue
                    if en_acciones and (lu.startswith("TOTAL") or "RENDIMIENTO" in lu): en_acciones = False; continue
                    if en_acciones:
                        m = re.match(r"^([A-Z]+(?:\s+\d+)?)\s+", ls.strip())
                        if m:
                            nums = extraer_todos_numeros(ls[m.end():])
                            if len(nums) >= 8:
                                portafolio.append({"emisora": m.group(1).strip(), "valor_mercado": nums[7]})
                    
                    if "DESGLOSE DE MOVIMIENTOS" in lu: en_mov = True; continue
                    if en_mov and "RENDIMIENTO" in lu: en_mov = False; continue
                    if en_mov:
                        if "COMPRA DE ACCIONES" in lu:
                            m = re.search(r"ACCIONES\.\s+([A-Z0-9\s]+?)\s+[\d,]", ls, re.I)
                            nums = extraer_todos_numeros(ls)
                            if m and len(nums) >= 6: movs["COMPRAS"][m.group(1).strip().upper()] += nums[-2]
                        elif "VENTA DE ACCIONES" in lu:
                            m = re.search(r"ACCIONES\.\s+([A-Z0-9\s]+?)\s+[\d,]", ls, re.I)
                            nums = extraer_todos_numeros(ls)
                            if m and len(nums) >= 6: movs["VENTAS"][m.group(1).strip().upper()] += nums[-2]

            datos = {
                "plataforma": "GBM", "periodo": periodo_str,
                "portafolio": portafolio, "movs": movs, "efectivo_total": efectivo_total
            }
        return nombre, datos

# ============================================================
# 3. LÓGICA MAESTRA DE CONSOLIDACIÓN (EXCEL)
# ============================================================
def actualizar_hoja_maestra(ws, info):
    fila_header = 23
    fila_totales = fila_efectivo_gbm = None
    
    for r in range(1, 150):
        val = normalizar(ws.cell(r, 1).value)
        if "INSTRUMENTO" in val: fila_header = r
        if "EFECTIVO GBM" in val: fila_efectivo_gbm = r
        if "TOTALES" in val: 
            fila_totales = r
            break
    
    if not fila_totales: return

    # --------------------------------------------------------
    # CASO A: PRESTADERO
    # --------------------------------------------------------
    if info["plataforma"] == "Prestadero":
        for r in range(fila_header + 1, fila_totales):
            if "PRESTADERO" in normalizar(ws.cell(r, 1).value):
                saldo_ini = ws.cell(r, 2).value or 0.0
                ws.cell(r, 3).value = info["valor_total"]
                ws.cell(r, 5).value = info["valor_total"] - saldo_ini
                ws.cell(r, 7).value = info["interes_mes"]
                ws.cell(r, 9).value = "ESPECULATIVO\nMODERADO" # I: Clasificación
                ws.cell(r, 10).value = info["retiros"]
                ws.cell(r, 11).value = info["depositos"]
                ws.cell(r, 13).value = "BAJA" # M: Liquidez
                ws.cell(r, 14).value = info["valor_total"]

    # --------------------------------------------------------
    # CASO B: GBM (Fibras, Acciones, Efectivo)
    # --------------------------------------------------------
    elif info["plataforma"] == "GBM":
        port_pdf = info["portafolio"]
        movs = info["movs"]
        emisoras_en_pdf = {normalizar(i["emisora"]): i["valor_mercado"] for i in port_pdf}
        instrumentos_vistos = set()
        
        total_compras_mes = sum(movs["COMPRAS"].values())
        total_ventas_mes = sum(movs["VENTAS"].values())

        # 1. Actualizar Fibras Existentes
        for r in range(fila_header + 1, fila_totales):
            nom = normalizar(ws.cell(r, 1).value)
            if not nom or nom == "-" or "EFECTIVO GBM" in nom: continue
            
            instrumentos_vistos.add(nom)
            old_b = ws.cell(r, 2).value or 0.0
            old_c = ws.cell(r, 3).value or 0.0 
            
            compra = movs["COMPRAS"].get(nom, 0.0)
            venta = movs["VENTAS"].get(nom, 0.0)
            nuevo_c = emisoras_en_pdf.get(nom, 0.0)

            if nom not in emisoras_en_pdf and venta == 0 and compra == 0: continue

            nuevo_b = max(0, old_b + compra - venta)
            ws.cell(r, 2).value = nuevo_b
            ws.cell(r, 3).value = nuevo_c
            ws.cell(r, 5).value = nuevo_c - nuevo_b
            ws.cell(r, 7).value = nuevo_c - old_c + venta - compra
            ws.cell(r, 10).value = venta  # J: Retiros (Venta de fibra)
            ws.cell(r, 11).value = compra # K: Depósitos (Compra de fibra)
            ws.cell(r, 14).value = nuevo_c

        # 2. Insertar Fibras Nuevas
        for item in port_pdf:
            emisora_pdf = normalizar(item["emisora"])
            if emisora_pdf not in instrumentos_vistos:
                pos = fila_efectivo_gbm if fila_efectivo_gbm else fila_totales
                ws.insert_rows(pos)
                compra_nueva = movs["COMPRAS"].get(emisora_pdf, item["valor_mercado"])
                
                ws.cell(pos, 1).value = emisora_pdf
                ws.cell(pos, 2).value = compra_nueva
                ws.cell(pos, 3).value = item["valor_mercado"]
                ws.cell(pos, 4).value = info["periodo"]
                ws.cell(pos, 5).value = item["valor_mercado"] - compra_nueva
                ws.cell(pos, 7).value = item["valor_mercado"] - compra_nueva
                ws.cell(pos, 9).value = "ESPECULATIVO\nCONSERVADOR" # I: Clasificación
                ws.cell(pos, 10).value = 0 # J: Retiros
                ws.cell(pos, 11).value = compra_nueva # K: Depósitos
                ws.cell(pos, 13).value = "ALTA" # M: Liquidez
                ws.cell(pos, 14).value = item["valor_mercado"]
                ws.cell(pos, 15).value = "GBM"
                
                if fila_efectivo_gbm: fila_efectivo_gbm += 1
                fila_totales += 1

        # 3. Balancear EFECTIVO GBM (Espejo de transacciones)
        if fila_efectivo_gbm:
            old_efec_b = ws.cell(fila_efectivo_gbm, 2).value or 0.0
            # Si compraste instrumentos (salida de efectivo), baja el saldo inicial.
            ws.cell(fila_efectivo_gbm, 2).value = old_efec_b + total_ventas_mes - total_compras_mes
            ws.cell(fila_efectivo_gbm, 3).value = info["efectivo_total"]
            ws.cell(fila_efectivo_gbm, 5).value = "-"
            ws.cell(fila_efectivo_gbm, 7).value = "-"
            ws.cell(fila_efectivo_gbm, 9).value = "CONSERVADOR\nCONSERVADOR" # I
            ws.cell(fila_efectivo_gbm, 10).value = total_compras_mes # J: Salida de efectivo hacia Fibras
            ws.cell(fila_efectivo_gbm, 11).value = total_ventas_mes  # K: Entrada de efectivo desde Fibras
            ws.cell(fila_efectivo_gbm, 13).value = "ALTA" # M
            ws.cell(fila_efectivo_gbm, 14).value = info["efectivo_total"]

    # --------------------------------------------------------
    # ACTUALIZAR FORMULAS % CARTERA (Para toda la hoja)
    # --------------------------------------------------------
    for r in range(fila_header + 1, fila_totales):
        if ws.cell(r, 1).value and ws.cell(r, 1).value != "-":
            # Inyectar fórmula de Excel real: =C{fila actual}/C{fila totales}
            ws.cell(r, 12).value = f"=C{r}/C{fila_totales}"

# ============================================================
# 4. APLICACIÓN WEB STREAMLIT
# ============================================================
def main():
    st.title("🏦 Motor de Consolidación Financiera")
    st.markdown("Automatización de saldos, reclasificación y partida doble.")
    
    col1, col2 = st.columns(2)
    with col1: maestro_file = st.file_uploader("1. Excel Maestro (Mes Anterior)", type="xlsx")
    with col2: pdf_files = st.file_uploader("2. PDFs (Mes Actual)", type="pdf", accept_multiple_files=True)

    if st.button("🚀 Iniciar Consolidación", use_container_width=True):
        if maestro_file and pdf_files:
            try:
                wb = load_workbook(maestro_file)
                with st.spinner("Sincronizando movimientos y balanceando carteras..."):
                    for f in pdf_files:
                        nombre, datos = procesar_pdf_financiero(f)
                        sheet_name = next((s for s in wb.sheetnames if all(p in s.upper() for p in nombre.split()[:2])), None)
                        if sheet_name:
                            actualizar_hoja_maestra(wb[sheet_name], datos)
                            st.success(f"✅ Hoja consolidada: {sheet_name}")
                        else:
                            st.warning(f"⚠️ Cliente no encontrado en el Maestro: {nombre}")

                buf = io.BytesIO()
                wb.save(buf)
                buf.seek(0)
                st.download_button(
                    label="📥 Descargar Estado de Cuenta Consolidado",
                    data=buf,
                    file_name="Estado_Cuenta_Actualizado.xlsx",
                    mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                    use_container_width=True
                )
            except Exception as e:
                st.error(f"❌ Error crítico: {e}")
        else:
            st.error("Por favor, sube el Excel y al menos un PDF.")

if __name__ == "__main__":
    main()
