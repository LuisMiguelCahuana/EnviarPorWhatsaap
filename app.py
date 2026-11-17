import io
import re
import time
import zipfile
from datetime import datetime
from pathlib import PurePosixPath

import pandas as pd
import requests
import streamlit as st

st.set_page_config(page_title="Envío de documentos de vacaciones", page_icon="📄", layout="wide")

DEFAULT_MESSAGE = """El área de RR. HH. de Global Micha les comparte los documentos de vacaciones para realizar la gestión de su pago.

Deberán imprimirlos, firmarlos y colocar su huella en ambos documentos. En el documento que dice MEMO DE CONTROLADORES, escribir a mano “RECIBÍ CONFORME”.
Luego, enviarlos escaneados en 1 solo archivo PDF.

Importante: No se aceptarán firmas digitales."""

st.title("📄 Envío de documentos de vacaciones")
st.caption("Carga el Excel y un ZIP con los PDF. La aplicación cruza los archivos por DNI y envía cada documento al WhatsApp correspondiente.")

with st.sidebar:
    st.header("Conexión WhatsApp")
    st.info("Configura los secretos de Meta en Streamlit Cloud antes de habilitar los envíos reales.")
    dry_run = st.toggle("Modo de prueba (no envía)", value=True)
    st.caption("Mantén activado el modo de prueba para validar la relación DNI–PDF antes del primer envío.")

def get_secret(name, default=""):
    try:
        return str(st.secrets.get(name, default))
    except Exception:
        return default

def clean_dni(value):
    if pd.isna(value):
        return ""
    s = str(value).strip()
    if re.fullmatch(r"\d+\.0", s):
        s = s[:-2]
    digits = re.sub(r"\D", "", s)
    return digits if len(digits) == 8 else ""

def clean_phone(value):
    if pd.isna(value):
        return ""
    s = str(value).strip()
    if re.fullmatch(r"\d+\.0", s):
        s = s[:-2]
    digits = re.sub(r"\D", "", s)
    if digits.startswith("00"):
        digits = digits[2:]
    # Números peruanos: 9 dígitos locales o 51 + 9 dígitos.
    if len(digits) == 9:
        return "51" + digits
    if len(digits) == 11 and digits.startswith("51"):
        return digits
    return ""

def extract_dni(filename):
    # El DNI debe ser el primer bloque de 8 dígitos del nombre del PDF.
    name = PurePosixPath(filename).name
    match = re.match(r"^\s*(\d{8})(?:\s|_|-)", name)
    return match.group(1) if match else ""

def classify_pdf(filename):
    upper = PurePosixPath(filename).stem.upper()
    if re.search(r"\bMEMO\b", upper):
        return "MEMO"
    if re.search(r"\bSOLI\b", upper):
        return "SOLI"
    return ""

def read_zip(uploaded_zip):
    files = {}
    errors = []
    try:
        with zipfile.ZipFile(uploaded_zip) as zf:
            for info in zf.infolist():
                if info.is_dir():
                    continue
                name = PurePosixPath(info.filename).name
                if not name.lower().endswith(".pdf"):
                    continue
                dni = extract_dni(name)
                kind = classify_pdf(name)
                if not dni:
                    errors.append(f"{name}: no comienza con un DNI de 8 dígitos.")
                    continue
                if not kind:
                    errors.append(f"{name}: no se identifica como MEMO o SOLI.")
                    continue
                key = (dni, kind)
                if key in files:
                    errors.append(f"DNI {dni}: hay más de un archivo {kind} ({files[key][0]} y {name}).")
                    files.pop(key, None)
                    files[("DUPLICADO", f"{dni}_{kind}")] = (name, None)
                    continue
                if ("DUPLICADO", f"{dni}_{kind}") in files:
                    continue
                files[key] = (name, zf.read(info.filename))
    except zipfile.BadZipFile:
        raise ValueError("El archivo cargado no es un ZIP válido.")
    return files, errors

def meta_request(method, url, token, **kwargs):
    headers = kwargs.pop("headers", {})
    headers["Authorization"] = f"Bearer {token}"
    response = requests.request(method, url, headers=headers, timeout=90, **kwargs)
    try:
        data = response.json()
    except Exception:
        data = {"raw": response.text}
    if not response.ok:
        msg = data.get("error", {}).get("message", str(data))
        raise RuntimeError(f"Meta API ({response.status_code}): {msg}")
    return data

def upload_pdf_to_meta(pdf_bytes, filename, phone_id, token, version):
    url = f"https://graph.facebook.com/{version}/{phone_id}/media"
    files = {"file": (filename, pdf_bytes, "application/pdf")}
    data = {"messaging_product": "whatsapp", "type": "application/pdf"}
    result = meta_request("POST", url, token, files=files, data=data)
    return result["id"]

def send_text_template(to, template_name, language, phone_id, token, version):
    url = f"https://graph.facebook.com/{version}/{phone_id}/messages"
    payload = {
        "messaging_product": "whatsapp",
        "to": to,
        "type": "template",
        "template": {"name": template_name, "language": {"code": language}}
    }
    return meta_request("POST", url, token, json=payload)

def send_document_template(to, template_name, language, media_id, phone_id, token, version):
    url = f"https://graph.facebook.com/{version}/{phone_id}/messages"
    payload = {
        "messaging_product": "whatsapp",
        "to": to,
        "type": "template",
        "template": {
            "name": template_name,
            "language": {"code": language},
            "components": [{
                "type": "header",
                "parameters": [{
                    "type": "document",
                    "document": {"id": media_id}
                }]
            }]
        }
    }
    return meta_request("POST", url, token, json=payload)

def get_column_options(df):
    cols = list(df.columns)
    dni_guess = next((c for c in cols if "DNI" in str(c).upper()), cols[0])
    name_guess = next((c for c in cols if "APELLIDOS" in str(c).upper() or "NOMBRE" in str(c).upper()), cols[0])
    phone_guess = None
    # Prefer columns whose heading mentions phone/WhatsApp; otherwise inspect numeric values.
    phone_guess = next((c for c in cols if any(x in str(c).upper() for x in ["WHATSAPP", "CELULAR", "TELEFONO", "TELÉFONO", "MOVIL", "MÓVIL"])), None)
    if phone_guess is None:
        scores = {}
        for c in cols:
            vals = df[c].dropna().head(30).tolist()
            score = sum(1 for v in vals if len(re.sub(r"\D", "", str(v).replace(".0", ""))) in (9, 11))
            scores[c] = score
        candidates = sorted(scores, key=scores.get, reverse=True)
        phone_guess = candidates[0] if candidates and scores[candidates[0]] > 0 else cols[-1]
    return dni_guess, name_guess, phone_guess

st.subheader("1. Cargar archivos")
c1, c2 = st.columns(2)
with c1:
    excel_file = st.file_uploader("Archivo Excel de trabajadores (.xlsx)", type=["xlsx"])
with c2:
    zip_file = st.file_uploader("ZIP con los PDF individuales", type=["zip"])

if excel_file and zip_file:
    try:
        df_raw = pd.read_excel(excel_file, dtype=object)
        if df_raw.empty:
            st.error("El Excel no contiene filas.")
            st.stop()
        dni0, name0, phone0 = get_column_options(df_raw)
        st.subheader("2. Confirmar columnas del Excel")
        a, b, c = st.columns(3)
        with a:
            dni_col = st.selectbox("Columna DNI", df_raw.columns, index=list(df_raw.columns).index(dni0))
        with b:
            name_col = st.selectbox("Columna nombres", df_raw.columns, index=list(df_raw.columns).index(name0))
        with c:
            phone_col = st.selectbox("Columna WhatsApp", df_raw.columns, index=list(df_raw.columns).index(phone0))
        data = pd.DataFrame({
            "DNI": df_raw[dni_col].apply(clean_dni),
            "TRABAJADOR": df_raw[name_col].fillna("").astype(str).str.strip(),
            "WHATSAPP": df_raw[phone_col].apply(clean_phone)
        })
        data = data[(data["DNI"] != "") | (data["TRABAJADOR"] != "")]
        data = data.drop_duplicates(subset=["DNI"], keep="first")
        pdfs, zip_errors = read_zip(zip_file)
        rows = []
        for _, row in data.iterrows():
            dni = row["DNI"]
            memo = pdfs.get((dni, "MEMO"))
            soli = pdfs.get((dni, "SOLI"))
            duplicate = ("DUPLICADO", f"{dni}_MEMO") in pdfs or ("DUPLICADO", f"{dni}_SOLI") in pdfs
            status = "LISTO" if dni and row["WHATSAPP"] and memo and soli and not duplicate else "REVISAR"
            reason = []
            if not dni: reason.append("DNI inválido")
            if not row["WHATSAPP"]: reason.append("WhatsApp inválido")
            if not memo: reason.append("Falta MEMO")
            if not soli: reason.append("Falta SOLI")
            if duplicate: reason.append("PDF duplicado para el DNI")
            rows.append({
                "DNI": dni, "TRABAJADOR": row["TRABAJADOR"], "WHATSAPP": row["WHATSAPP"],
                "MEMO": memo[0] if memo else "", "SOLI": soli[0] if soli else "",
                "VALIDACION": status, "OBSERVACION": ", ".join(reason)
            })
        preview = pd.DataFrame(rows)
        st.subheader("3. Resultado de validación")
        x1, x2, x3 = st.columns(3)
        x1.metric("Trabajadores", len(preview))
        x2.metric("Listos para enviar", int((preview["VALIDACION"] == "LISTO").sum()))
        x3.metric("Por revisar", int((preview["VALIDACION"] != "LISTO").sum()))
        st.dataframe(preview, use_container_width=True, hide_index=True)
        if zip_errors:
            with st.expander(f"Advertencias del ZIP ({len(zip_errors)})"):
                for e in zip_errors:
                    st.warning(e)

        st.subheader("4. Mensaje para todos")
        message = st.text_area("Texto del mensaje", value=DEFAULT_MESSAGE, height=190)
        st.caption("El texto se enviará mediante una plantilla de WhatsApp aprobada por Meta. El contenido de la plantilla debe coincidir con el texto configurado aquí.")

        ready = preview[preview["VALIDACION"] == "LISTO"].copy()
        st.subheader("5. Envío")
        if dry_run:
            st.warning("Modo de prueba activo: no se enviará ningún mensaje.")
        else:
            st.error("Modo real activo. Se enviarán mensajes a todos los trabajadores validados. Verifica primero la vista previa y la configuración de Meta.")

        confirm = st.checkbox("Confirmo que los DNI, teléfonos y dos PDF de cada trabajador fueron revisados.")
        if st.button("🚀 Iniciar proceso", type="primary", disabled=(len(ready) == 0 or not confirm), use_container_width=True):
            if dry_run:
                st.success(f"Prueba completada: {len(ready)} trabajadores tienen dos PDF y número válido. No se envió nada.")
                st.download_button("Descargar validación CSV", preview.to_csv(index=False).encode("utf-8-sig"), "validacion_trabajadores.csv", "text/csv")
            else:
                token = get_secret("WHATSAPP_TOKEN")
                phone_id = get_secret("PHONE_NUMBER_ID")
                version = get_secret("GRAPH_API_VERSION")
                language = get_secret("TEMPLATE_LANGUAGE", "es")
                text_template = get_secret("TEXT_TEMPLATE_NAME")
                memo_template = get_secret("MEMO_TEMPLATE_NAME")
                soli_template = get_secret("SOLI_TEMPLATE_NAME")
                missing = [k for k,v in {
                    "WHATSAPP_TOKEN":token, "PHONE_NUMBER_ID":phone_id, "GRAPH_API_VERSION":version,
                    "TEXT_TEMPLATE_NAME":text_template, "MEMO_TEMPLATE_NAME":memo_template,
                    "SOLI_TEMPLATE_NAME":soli_template
                }.items() if not v]
                if missing:
                    st.error("Faltan secretos de Streamlit: " + ", ".join(missing))
                else:
                    log = []
                    progress = st.progress(0)
                    status_box = st.empty()
                    for i, (_, person) in enumerate(ready.iterrows(), start=1):
                        dni, name, to = person["DNI"], person["TRABAJADOR"], person["WHATSAPP"]
                        status_box.info(f"Procesando {i}/{len(ready)}: {name} ({dni})")
                        item = {"FECHA": datetime.now().strftime("%Y-%m-%d %H:%M:%S"), "DNI":dni, "TRABAJADOR":name, "WHATSAPP":to, "ESTADO":"ERROR", "DETALLE":""}
                        try:
                            # Primero se carga cada PDF a Meta y luego se envían como plantillas con encabezado PDF.
                            memo_id = upload_pdf_to_meta(pdfs[(dni,"MEMO")][1], pdfs[(dni,"MEMO")][0], phone_id, token, version)
                            soli_id = upload_pdf_to_meta(pdfs[(dni,"SOLI")][1], pdfs[(dni,"SOLI")][0], phone_id, token, version)
                            send_text_template(to, text_template, language, phone_id, token, version)
                            time.sleep(1.0)
                            send_document_template(to, memo_template, language, memo_id, phone_id, token, version)
                            time.sleep(1.0)
                            send_document_template(to, soli_template, language, soli_id, phone_id, token, version)
                            item["ESTADO"] = "ACEPTADO_POR_META"
                            item["DETALLE"] = "Meta aceptó las 3 solicitudes de envío; la entrega final debe verificarse con los estados de webhook."
                        except Exception as exc:
                            item["DETALLE"] = str(exc)
                        log.append(item)
                        progress.progress(i / len(ready))
                        time.sleep(1.0)
                    log_df = pd.DataFrame(log)
                    st.session_state["last_log"] = log_df
                    accepted = int((log_df["ESTADO"] == "ACEPTADO_POR_META").sum())
                    st.success(f"Proceso terminado. Meta aceptó las solicitudes de {accepted} de {len(log_df)} trabajadores.")
                    st.dataframe(log_df, use_container_width=True, hide_index=True)
                    st.download_button("⬇️ Descargar reporte de envíos CSV", log_df.to_csv(index=False).encode("utf-8-sig"), "reporte_envios_whatsapp.csv", "text/csv")
    except Exception as e:
        st.error(f"No se pudo procesar los archivos: {e}")
else:
    st.info("Carga el Excel y el ZIP para comenzar. El ZIP debe contener dos archivos PDF por trabajador: uno con MEMO y otro con SOLI en el nombre.")

with st.expander("Configuración necesaria de WhatsApp Business Cloud API"):
    st.markdown("""
    Para enviar fuera de la ventana de atención de 24 horas, Meta exige plantillas aprobadas. Esta aplicación utiliza **tres plantillas aprobadas**:
    1. Una plantilla de texto con el mensaje completo de RR. HH.
    2. Una plantilla con encabezado de documento PDF para el MEMO.
    3. Una plantilla con encabezado de documento PDF para la SOLI.

    Las dos plantillas de documento deben tener encabezado de tipo **Documento**. En Meta, configura sus cuerpos con una descripción breve, por ejemplo: “Adjuntamos tu MEMO de vacaciones” y “Adjuntamos tu SOLI de vacaciones”. La plantilla de texto debe contener el mensaje aprobado que aparece en esta aplicación.

    No pegues el token en el código. Guárdalo en **Streamlit Cloud → App → Settings → Secrets**.
    """)
