import streamlit as st
import pandas as pd
import plotly.graph_objects as go
from fpdf import FPDF
import io
from datetime import datetime, timedelta

# --- 1. CONFIGURACIÓN E IDENTIDAD ---
st.set_page_config(page_title="Confidelis - Wealth Management", layout="wide")

st.markdown("""
    <style>
    .main { background-color: #f4f6f9; }
    .stButton>button { background-color: #002147; color: #D4AF37; border-radius: 8px; font-weight: bold; width: 100%;}
    .metric-box { background-color: white; padding: 15px; border-radius: 10px; text-align: center; border-top: 4px solid #002147; box-shadow: 0 2px 5px rgba(0,0,0,0.1);}
    .header-box { background-color: #002147; color: #D4AF37; padding: 15px; border-radius: 10px; margin-bottom: 20px;}
    .resumen-card { background-color: #002147; color: white; padding: 20px; border-radius: 10px; border-left: 8px solid #D4AF37; margin-top: 15px;}
    .progress-text { font-weight: bold; color: #002147; font-size: 1.1em;}
    .ayuda-dinero { font-size: 1.2em; color: #002147; background-color: #e9ecef; padding: 5px 10px; border-radius: 5px; display: inline-block; margin-bottom: 10px;}
    </style>
    """, unsafe_allow_html=True)

# --- 2. VARIABLES DE SESIÓN GLOBALES ---
if 'instrumentos' not in st.session_state: st.session_state.instrumentos = []
if 'monto_base' not in st.session_state: st.session_state.monto_base = 5000000.0
if 'prestamo' not in st.session_state: st.session_state.prestamo = 2000000.0
if 'pago_mensual' not in st.session_state: st.session_state.pago_mensual = 45000.0
if 'tasa_prestamo' not in st.session_state: st.session_state.tasa_prestamo = 12.0
if 'plazo_meses' not in st.session_state: st.session_state.plazo_meses = 60
if 'retiros' not in st.session_state: st.session_state.retiros = []

# --- 3. FUNCIONES DE CÁLCULO BÁSICAS ---
def generar_df_actual(instrumentos, monto_base):
    cols = ['Categoría', 'Instrumento', '% Asignación', 'Monto (MXN)', 'Tasa Anual %', 'Flujo Mensual', 'Flujo Anual', 'Horizonte', 'Liquidez']
    if not instrumentos: return pd.DataFrame(columns=cols)
    df = pd.DataFrame(instrumentos)
    df['% Asignación'] = (df['Monto (MXN)'] / monto_base) * 100 if monto_base > 0 else 0
    df['Flujo Anual'] = df['Monto (MXN)'] * (df['Tasa Anual %'] / 100)
    df['Flujo Mensual'] = df['Flujo Anual'] / 12
    return df[cols]

def generar_df_propuesto(instrumentos, monto_base, total_prestamo):
    cols = ['Categoría', 'Instrumento', 'Monto Anterior', 'Inyección Préstamo', 'Nuevo Saldo', '% Nuevo Portafolio', 'Tasa Anual %', 'Flujo Extra Mensual', 'Nuevo Flujo Mensual', 'Nuevo Flujo Anual']
    if not instrumentos: return pd.DataFrame(columns=cols)
    df = pd.DataFrame(instrumentos)
    monto_total_nuevo = monto_base + total_prestamo
    df['Monto Anterior'] = df['Monto (MXN)']
    df['Inyección Préstamo'] = df.get('Inyección', 0.0)
    df['Nuevo Saldo'] = df['Monto Anterior'] + df['Inyección Préstamo']
    df['% Nuevo Portafolio'] = (df['Nuevo Saldo'] / monto_total_nuevo) * 100 if monto_total_nuevo > 0 else 0
    df['Flujo Extra Mensual'] = (df['Inyección Préstamo'] * (df['Tasa Anual %'] / 100)) / 12
    df['Nuevo Flujo Mensual'] = (df['Nuevo Saldo'] * (df['Tasa Anual %'] / 100)) / 12
    df['Nuevo Flujo Anual'] = df['Nuevo Flujo Mensual'] * 12
    return df[cols]

# === MOTOR CENTRAL DE DATOS GLOBALES ===
df_actual = generar_df_actual(st.session_state.instrumentos, st.session_state.monto_base)
df_prop = generar_df_propuesto(st.session_state.instrumentos, st.session_state.monto_base, st.session_state.prestamo)

capital_inicial = st.session_state.monto_base + sum(inst.get('Inyección', 0.0) for inst in st.session_state.instrumentos)
tasa_ponderada = (df_prop['Nuevo Flujo Anual'].sum() / capital_inicial) if capital_inicial > 0 else 0

# --- CÁLCULO EXACTO DEL MES DE LIQUIDACIÓN ---
temp_saldo = st.session_state.prestamo
mes_liquidacion = None
if temp_saldo > 0:
    for m in range(1, 1201):
        int_d = temp_saldo * ((st.session_state.tasa_prestamo/100)/12)
        if st.session_state.pago_mensual <= int_d:
            mes_liquidacion = "Nunca (El pago no cubre los intereses)"
            break
        
        if st.session_state.pago_mensual >= (temp_saldo + int_d):
            mes_liquidacion = m
            break
        else:
            temp_saldo -= (st.session_state.pago_mensual - int_d)

if isinstance(mes_liquidacion, int):
    fecha_fin = (datetime.now() + timedelta(days=mes_liquidacion*30)).strftime("%B %Y")
    mes_txt = f"exactamente en el Mes {mes_liquidacion} ({fecha_fin})"
else:
    mes_txt = f"[{mes_liquidacion}]" if mes_liquidacion else "en un plazo prolongado"

texto_resumen = f"El portafolio total será de ${capital_inicial:,.2f}. Generará flujos mensuales basados en una tasa ponderada de {tasa_ponderada*100:.2f}%. El crédito quedará liquidado {mes_txt}."

# --- SIMULACIÓN DE FLUJOS (AMBOS ESCENARIOS A LA VEZ) ---
datos_simple = []
datos_compuesto = []

saldo_inv_s = capital_inicial
saldo_inv_c = capital_inicial

saldo_deuda_s = st.session_state.prestamo
saldo_deuda_c = st.session_state.prestamo

for m in range(1, st.session_state.plazo_meses + 1):
    if saldo_deuda_s > 0:
        int_d = saldo_deuda_s * ((st.session_state.tasa_prestamo/100)/12)
        if st.session_state.pago_mensual >= (saldo_deuda_s + int_d):
            pago_real = saldo_deuda_s + int_d
            saldo_deuda_s = 0.0
            saldo_deuda_c = 0.0
        else:
            pago_real = st.session_state.pago_mensual
            saldo_deuda_s -= (pago_real - int_d)
            saldo_deuda_c -= (pago_real - int_d)
    else:
        pago_real = 0.0

    retiro_mes = sum(r['Monto'] for r in st.session_state.retiros if r['Mes'] == m)
    
    # ESCENARIO INTERÉS SIMPLE
    rend_s = saldo_inv_s * (tasa_ponderada / 12)
    flujo_neto_s = rend_s - pago_real - retiro_mes
    bolsillo_s = flujo_neto_s if flujo_neto_s > 0 else 0.0
    if flujo_neto_s < 0:
        saldo_inv_s += flujo_neto_s 
        if saldo_inv_s < 0: saldo_inv_s = 0.0
        
    datos_simple.append({
        "Mes": int(m), "Rendimiento Generado": rend_s, "Pago Crédito": pago_real, 
        "Retiro Programado": retiro_mes, "Flujo Libre (Bolsillo)": bolsillo_s, 
        "Saldo Inversión": saldo_inv_s, "Deuda Restante": saldo_deuda_s
    })

    # ESCENARIO INTERÉS COMPUESTO
    rend_c = saldo_inv_c * (tasa_ponderada / 12)
    flujo_neto_c = rend_c - pago_real - retiro_mes
    saldo_inv_c += flujo_neto_c 
    if saldo_inv_c < 0: saldo_inv_c = 0.0
        
    datos_compuesto.append({
        "Mes": int(m), "Rendimiento Generado": rend_c, "Pago Crédito": pago_real, 
        "Retiro Programado": retiro_mes, "Flujo Libre (Bolsillo)": 0.0, 
        "Saldo Inversión": saldo_inv_c, "Deuda Restante": saldo_deuda_c
    })

df_simple = pd.DataFrame(datos_simple)
df_compuesto = pd.DataFrame(datos_compuesto)

# --- FUNCIONES DE PDF Y EXCEL ---
class ConfidelisPDF(FPDF):
    def header(self):
        self.set_fill_color(0, 33, 71)
        self.rect(0, 0, 297, 30, 'F')
        self.set_font('Arial', 'B', 16)
        self.set_text_color(212, 175, 55)
        self.cell(0, 10, 'CONFIDELIS: ESTRATEGIA PATRIMONIAL', 0, 1, 'C')
        self.ln(5)

def generar_pdf_custom(cliente, modulos, df_act, df_prop, df_simp, df_comp, resumen_txt):
    pdf = ConfidelisPDF(orientation='L')
    if "Resumen Ejecutivo" in modulos:
        pdf.add_page()
        pdf.set_font("Arial", 'B', 14)
        pdf.set_text_color(0, 33, 71)
        pdf.cell(0, 10, f"Resumen Ejecutivo para: {cliente}", ln=True)
        pdf.set_font("Arial", size=11)
        pdf.multi_cell(0, 8, resumen_txt)
    
    def imprimir_tabla(pdf_obj, titulo, df):
        if df.empty: return
        pdf_obj.add_page()
        pdf_obj.set_font("Arial", 'B', 14)
        pdf_obj.set_text_color(0, 33, 71)
        pdf_obj.cell(0, 10, titulo, ln=True)
        pdf_obj.ln(3)
        pdf_obj.set_fill_color(212, 175, 55)
        pdf_obj.set_text_color(255, 255, 255)
        pdf_obj.set_font("Arial", 'B', 7)
        cols = df.columns.tolist()
        ancho_col = 277 / len(cols)
        for col in cols: pdf_obj.cell(ancho_col, 8, str(col)[:15], 1, 0, 'C', True)
        pdf_obj.ln()
        pdf_obj.set_text_color(0, 0, 0)
        pdf_obj.set_font("Arial", size=7)
        for idx, row in df.iterrows():
            es_tot = (idx == 'TOTAL')
            if es_tot:
                pdf_obj.set_font("Arial", 'B', 7)
                pdf_obj.set_fill_color(230, 230, 230)
            for i, val in enumerate(row):
                texto = f"${val:,.0f}" if isinstance(val, (int, float)) and val > 100 else str(val)
                if isinstance(val, float) and val <= 100 and '%' in cols[i]: texto = f"{val:.2f}%"
                if pd.isna(val) or val == "": texto = "-"
                pdf_obj.cell(ancho_col, 8, texto[:20], 1, 0, 'C', fill=es_tot)
            pdf_obj.ln()

    def imprimir_flujos(pdf_obj, titulo, df_f):
        if df_f.empty: return
        pdf_obj.add_page()
        pdf_obj.set_font("Arial", 'B', 14)
        pdf_obj.set_text_color(0, 33, 71)
        pdf_obj.cell(0, 10, titulo, ln=True)
        pdf_obj.set_font("Arial", size=8)
        pdf_obj.set_fill_color(0, 33, 71)
        pdf_obj.set_text_color(255, 255, 255)
        
        cols = df_f.columns.tolist()
        ancho_col = 277 / len(cols)
        for col in cols: pdf_obj.cell(ancho_col, 8, col, 1, 0, 'C', True)
        pdf_obj.ln()
        
        pdf_obj.set_text_color(0, 0, 0)
        for i, r in df_f.iterrows():
            if i % 12 == 0 or i == len(df_f)-1:
                for idx_col, val in enumerate(r):
                    txt = str(val) if idx_col == 0 else (f"${val:,.0f}" if isinstance(val, float) else str(val))
                    pdf_obj.cell(ancho_col, 8, txt, 1, 0, 'C')
                pdf_obj.ln()

    def add_totals(df):
        df_c = df.copy()
        if not df_c.empty:
            t = pd.Series(index=df_c.columns, dtype=object)
            t['Categoría'] = 'TOTAL'; t['Instrumento'] = '-'
            for col in df_c.columns:
                if any(x in col for x in ['Monto', 'Flujo', 'Saldo', 'Inyección']): t[col] = df_c[col].sum()
                elif '%' in col: t[col] = df_c[col].sum() if 'Nuevo Portafolio' in col or 'Asignación' in col else ""
            df_c.loc['TOTAL'] = t
        return df_c

    if "Portafolio Actual" in modulos: imprimir_tabla(pdf, "Portafolio Actual", add_totals(df_act))
    if "Portafolio Propuesto" in modulos: imprimir_tabla(pdf, "Portafolio Propuesto (Apalancado)", add_totals(df_prop))
    if "Flujos (Interés Simple)" in modulos: imprimir_flujos(pdf, "Proyección: Interés Simple", df_simp)
    if "Flujos (Interés Compuesto)" in modulos: imprimir_flujos(pdf, "Proyección: Interés Compuesto", df_comp)

    return pdf.output(dest='S').encode('latin-1')

def generar_excel_custom(modulos, df_act, df_prop, df_simp, df_comp):
    output = io.BytesIO()
    with pd.ExcelWriter(output, engine='xlsxwriter') as writer:
        if "Portafolio Actual" in modulos and not df_act.empty: df_act.to_excel(writer, index=False, sheet_name='Actual')
        if "Portafolio Propuesto" in modulos and not df_prop.empty: df_prop.to_excel(writer, index=False, sheet_name='Propuesto')
        if "Flujos (Interés Simple)" in modulos and not df_simp.empty: df_simp.to_excel(writer, index=False, sheet_name='Simple')
        if "Flujos (Interés Compuesto)" in modulos and not df_comp.empty: df_comp.to_excel(writer, index=False, sheet_name='Compuesto')
    return output.getvalue()

# --- 4. INTERFAZ GRÁFICA ---
st.markdown("<div class='header-box'><h2 style='margin:0;'>🏛️ Estructuración Patrimonial Confidelis</h2></div>", unsafe_allow_html=True)

t1, t2, t3, t4, t5 = st.tabs(["1️⃣ Portafolio Base", "2️⃣ Apalancamiento", "3️⃣ Flujos y Retiros", "4️⃣ Resumen General", "📥 Exportar"])

# ----------------- PESTAÑA 1: PORTAFOLIO BASE -----------------
with t1:
    c1, c2 = st.columns([2, 1])
    cliente = c1.text_input("👤 Cliente:", value="Familia Demo")
    
    st.session_state.monto_base = c2.number_input("💰 Escribe Monto Base sin comas:", min_value=0.0, step=50000.0, format="%.2f", key="mb_input")
    c2.markdown(f"<div class='ayuda-dinero'>Monto Formateado: <b>${st.session_state.monto_base:,.2f}</b></div>", unsafe_allow_html=True)
    
    st.divider()
    
    st.subheader("📊 Perfil de Riesgo Objetivo (%)")
    rp1, rp2, rp3 = st.columns(3)
    p_c = rp1.number_input("Conservador (C)", 0, 100, 40)
    p_m = rp2.number_input("Moderado (M)", 0, 100, 40)
    p_e = rp3.number_input("Especulativo (E)", 0, 100, 20)
    
    sum_c = sum((i['Monto (MXN)'] / st.session_state.monto_base * 100) for i in st.session_state.instrumentos if i['Categoría'] == 'C') if st.session_state.monto_base > 0 else 0
    sum_m = sum((i['Monto (MXN)'] / st.session_state.monto_base * 100) for i in st.session_state.instrumentos if i['Categoría'] == 'M') if st.session_state.monto_base > 0 else 0
    sum_e = sum((i['Monto (MXN)'] / st.session_state.monto_base * 100) for i in st.session_state.instrumentos if i['Categoría'] == 'E') if st.session_state.monto_base > 0 else 0

    col_prog1, col_prog2, col_prog3 = st.columns(3)
    col_prog1.progress(min(sum_c / p_c if p_c > 0 else 0, 1.0)); col_prog1.caption(f"Conservador: {sum_c:.1f}% / {p_c}%")
    col_prog2.progress(min(sum_m / p_m if p_m > 0 else 0, 1.0)); col_prog2.caption(f"Moderado: {sum_m:.1f}% / {p_m}%")
    col_prog3.progress(min(sum_e / p_e if p_e > 0 else 0, 1.0)); col_prog3.caption(f"Especulativo: {sum_e:.1f}% / {p_e}%")

    if sum_c > p_c or sum_m > p_m or sum_e > p_e: st.error("🛑 **Alerta:** Asignación mayor a la del perfil.")
    elif (sum_c + sum_m + sum_e) < 100 and len(st.session_state.instrumentos) > 0: st.warning(f"💡 Faltan asignar fondos para el 100%.")

    st.divider()
    
    total_asignado = sum(i['Monto (MXN)'] for i in st.session_state.instrumentos)
    falta_asignar = st.session_state.monto_base - total_asignado
    pct_asignado = min(total_asignado / st.session_state.monto_base, 1.0) if st.session_state.monto_base > 0 else 0
    
    st.markdown(f"<div class='progress-text'>Dinero Asignado: ${total_asignado:,.2f} | Restante para asignar: ${falta_asignar:,.2f}</div>", unsafe_allow_html=True)
    st.progress(pct_asignado)
    
    st.subheader("➕ Agregar Instrumento")
    f1, f2, f3 = st.columns([1, 2, 2])
    cat = f1.selectbox("Categoría", ["Conservador", "Moderado", "Especulativo"])
    nombre = f2.text_input("Nombre (Ej. CETES)")
    tasa = f3.number_input("Rendimiento Anual %", min_value=0.0, step=0.5, format="%.2f")
    
    modo_captura = st.radio("Asignar capital por:", ["Monto ($)", "Porcentaje (%)"], horizontal=True)
    m_col1, m_col2, m_col3 = st.columns(3)
    if modo_captura == "Monto ($)":
        monto_final = m_col1.number_input("Monto a Invertir sin comas ($)", min_value=0.0, max_value=float(falta_asignar) if falta_asignar > 0 else 0.0, value=0.0, step=10000.0)
        pct_calculado = (monto_final / st.session_state.monto_base) * 100 if st.session_state.monto_base > 0 else 0
        m_col2.markdown(f"<div class='ayuda-dinero'>Equivale al <b>{pct_calculado:.2f}%</b></div>", unsafe_allow_html=True)
    else:
        pct_restante = (falta_asignar / st.session_state.monto_base) * 100 if st.session_state.monto_base > 0 else 0
        valor_capturado = m_col1.number_input("Porcentaje a Invertir (%)", min_value=0.0, max_value=float(pct_restante) if pct_restante > 0 else 0.0, value=0.0, step=1.0)
        monto_final = (valor_capturado / 100) * st.session_state.monto_base
        m_col2.markdown(f"<div class='ayuda-dinero'>Equivale a <b>${monto_final:,.2f}</b></div>", unsafe_allow_html=True)
        
    horizonte = m_col3.selectbox("Horizonte", ["1 Año", "3 Años", "5 Años", "10 Años"])
    liquidez = st.selectbox("Liquidez", ["Diaria", "Mensual", "Anual", "Al Vencimiento"])

    if st.button("💾 Guardar Instrumento"):
        if monto_final > 0:
            st.session_state.instrumentos.append({"Categoría": cat[0], "Instrumento": nombre, "Monto (MXN)": monto_final, "Tasa Anual %": tasa, "Horizonte": horizonte, "Liquidez": liquidez, "Inyección": 0.0})
            st.rerun()

    if st.session_state.instrumentos:
        for i, inst in enumerate(st.session_state.instrumentos):
            c_inf, c_btn = st.columns([6, 1])
            c_inf.markdown(f"**{inst['Categoría']}** | {inst['Instrumento']} | Monto: **${inst['Monto (MXN)']:,.2f}** | Rendimiento: **{inst['Tasa Anual %']}%**")
            if c_btn.button("❌ Borrar", key=f"del_inst_{i}"):
                st.session_state.instrumentos.pop(i)
                st.rerun()

    if not df_actual.empty:
        st.dataframe(df_actual.style.format({'% Asignación': '{:.2f}%', 'Monto (MXN)': '${:,.2f}', 'Flujo Mensual': '${:,.2f}', 'Flujo Anual': '${:,.2f}', 'Tasa Anual %': '{:.2f}%'}), use_container_width=True)

# ----------------- PESTAÑA 2: APALANCAMIENTO -----------------
with t2:
    st.subheader("Estrategia de Crédito e Inyección")
    col1, col2, col3 = st.columns(3)
    st.session_state.prestamo = col1.number_input("Monto del Préstamo sin comas ($)", min_value=0.0, step=50000.0, value=st.session_state.prestamo)
    col1.markdown(f"<div class='ayuda-dinero'>Crédito: <b>${st.session_state.prestamo:,.2f}</b></div>", unsafe_allow_html=True)
    
    st.session_state.pago_mensual = col2.number_input("Pago Mensual sin comas ($)", min_value=0.0, step=1000.0, value=st.session_state.pago_mensual)
    col2.markdown(f"<div class='ayuda-dinero'>Pago: <b>${st.session_state.pago_mensual:,.2f}</b></div>", unsafe_allow_html=True)
    
    st.session_state.tasa_prestamo = col3.number_input("Tasa Préstamo (% Anual)", min_value=0.0, step=0.5, format="%.2f", value=st.session_state.tasa_prestamo)

    if not st.session_state.instrumentos:
        st.warning("Agrega instrumentos en la pestaña 1 primero.")
    else:
        st.divider()
        st.write("### 💸 Distribuir el Préstamo en los Instrumentos")
        total_inyeccion = sum(inst.get('Inyección', 0.0) for inst in st.session_state.instrumentos)
        falta_prestamo = st.session_state.prestamo - total_inyeccion
        pct_prestamo = min(total_inyeccion / st.session_state.prestamo, 1.0) if st.session_state.prestamo > 0 else 0
        pct_falta = (falta_prestamo / st.session_state.prestamo) * 100 if st.session_state.prestamo > 0 else 0
        
        modo_iny
