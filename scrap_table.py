import json
import os
import uuid
import urllib.request
from datetime import datetime, timezone

import boto3

# La pagina https://ultimosismo.igp.gob.pe/productos/reportes-sismicos es una app
# Nuxt (JavaScript): el HTML que llega no trae la tabla, se llena desde esta API.
API_URL = "https://ultimosismo.igp.gob.pe/api/ultimo-sismo/ajaxb/{anio}"
TABLE_NAME = os.environ.get("TABLE_NAME", "TablaSismosIGP")
N_SISMOS = 10


def obtener_sismos(anio):
    req = urllib.request.Request(
        API_URL.format(anio=anio),
        headers={"User-Agent": "Mozilla/5.0", "Accept": "application/json"},
    )
    with urllib.request.urlopen(req, timeout=20) as resp:
        return json.loads(resp.read().decode("utf-8"))


def lambda_handler(event, context):
    anio = datetime.now(timezone.utc).year
    try:
        sismos = obtener_sismos(anio)
        if len(sismos) < N_SISMOS:  # inicio de anio: completar con el anio anterior
            sismos = obtener_sismos(anio - 1) + sismos
    except Exception as e:
        return {"statusCode": 502, "body": f"Error al acceder al IGP: {e}"}

    # La API devuelve del mas antiguo al mas reciente -> tomar los 10 ultimos
    ultimos = sorted(sismos, key=lambda s: (s["fecha_utc"][:10], s["hora_utc"][11:19]), reverse=True)[:N_SISMOS]

    rows = []
    for i, s in enumerate(ultimos, start=1):
        rows.append({
            "id": str(uuid.uuid4()),
            "#": i,
            "codigo_reporte": f"IGP/CENSIS/RS {s['codigo']}",
            "referencia": s["referencia"],
            "magnitud": str(s["magnitud"]),
            "profundidad_km": str(s["profundidad"]),
            "latitud": str(s["latitud"]),
            "longitud": str(s["longitud"]),
            "intensidad": s.get("intensidad") or "",
            "fecha_hora_local": f"{s['fecha_local'][:10]} {s['hora_local'][11:19]}",
            "reporte_pdf": s.get("reporte_acelerometrico_pdf") or "",
        })

    table = boto3.resource("dynamodb").Table(TABLE_NAME)

    # Borrar lo anterior (con paginacion) e insertar los 10 nuevos
    scan_kwargs = {"ProjectionExpression": "id"}
    with table.batch_writer() as batch:
        while True:
            scan = table.scan(**scan_kwargs)
            for item in scan["Items"]:
                batch.delete_item(Key={"id": item["id"]})
            if "LastEvaluatedKey" not in scan:
                break
            scan_kwargs["ExclusiveStartKey"] = scan["LastEvaluatedKey"]

    with table.batch_writer() as batch:
        for row in rows:
            batch.put_item(Item=row)

    return {"statusCode": 200, "body": rows}
