# Envío de documentos de vacaciones por WhatsApp

Aplicación Streamlit que cruza un Excel de trabajadores con un ZIP de PDF por DNI y envía:
1. Una plantilla de texto con el mensaje de RR. HH.
2. El PDF MEMO correspondiente.
3. El PDF SOLI correspondiente.

## Formato de archivos

El ZIP debe tener nombres que comiencen con el DNI de 8 dígitos y contengan MEMO o SOLI:

- `98989898 VICENTE BERROSPI CARLOS MEMO.pdf`
- `98989898 VICENTE BERROSPI CARLOS SOLI.pdf`

Se aceptan carpetas internas dentro del ZIP. La aplicación usa el nombre base de cada PDF.

## Excel

Debe incluir columnas para DNI, nombres y número de WhatsApp. En la aplicación puedes seleccionar manualmente las tres columnas. Para Perú se aceptan números de 9 dígitos (se agrega 51) o 51 + 9 dígitos.

## Configuración Meta

Configura una cuenta de WhatsApp Business Cloud API y crea/obtén tres plantillas aprobadas:
- `TEXT_TEMPLATE_NAME`: plantilla de texto con el mensaje completo.
- `MEMO_TEMPLATE_NAME`: plantilla con encabezado de tipo Documento.
- `SOLI_TEMPLATE_NAME`: plantilla con encabezado de tipo Documento.

La plantilla de texto debe contener el mensaje que se muestra en la aplicación. Las plantillas MEMO y SOLI deben estar aprobadas y tener encabezado Documento. Si los destinatarios no han abierto una ventana de atención, WhatsApp exige plantillas aprobadas para iniciar la conversación.

En Streamlit Cloud → App → Settings → Secrets agrega:

```toml
WHATSAPP_TOKEN = "TOKEN_PERMANENTE_O_DE_LARGA_DURACION"
PHONE_NUMBER_ID = "ID_DEL_NUMERO_DE_WHATSAPP"
GRAPH_API_VERSION = "VERSIÓN_GRAPH_VIGENTE"
TEMPLATE_LANGUAGE = "es"
TEXT_TEMPLATE_NAME = "nombre_plantilla_texto"
MEMO_TEMPLATE_NAME = "nombre_plantilla_memo"
SOLI_TEMPLATE_NAME = "nombre_plantilla_soli"
```

Usa la versión Graph API vigente para tu aplicación de Meta. No subas secretos al repositorio GitHub.

## Despliegue

1. Crea un repositorio GitHub y sube `app.py`, `requirements.txt`, `README.md` y `.gitignore`.
2. En Streamlit Community Cloud crea una app desde ese repositorio y selecciona `app.py`.
3. Configura los Secrets indicados arriba.
4. Abre la aplicación y deja activado **Modo de prueba**.
5. Carga Excel y ZIP, revisa los cruces y descarga la validación.
6. Solo después de verificar todo, desactiva el modo de prueba y habilita el envío real.

## Consideraciones

- El modo de prueba está activado por defecto.
- La aplicación valida DNI, teléfono y existencia de un MEMO y una SOLI por trabajador.
- Si hay duplicados de un tipo de documento para el mismo DNI, ese trabajador queda fuera de la lista de envío.
- Meta puede aceptar la solicitud sin que eso signifique que el destinatario ya recibió/leyó el mensaje. Para confirmar entrega/lectura se requiere configurar un webhook de estados.
- El reporte CSV descargable es importante para conservar el historial. La sesión y el almacenamiento local de Streamlit Cloud no deben considerarse una base de datos permanente.
- Los documentos contienen información personal: limita el acceso a la app, no compartas los ZIP públicamente y elimina las cargas cuando termines.
- Verifica que todos los trabajadores hayan dado su consentimiento para recibir comunicaciones por WhatsApp.
