import os
import requests
import json
from flask import Flask, request, jsonify
from google.cloud import tasks_v2
from google.protobuf import timestamp_pb2
import datetime
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

app = Flask(__name__)

# -------------------------------------------------------------------
# Session with retry strategy
# -------------------------------------------------------------------

def create_requests_session():
    """
    Crée une session requests avec retry strategy pour gérer les connexions instables.
    """
    session = requests.Session()
    
    retry_strategy = Retry(
        total=3,
        status_forcelist=[429, 500, 502, 503, 504],
        allowed_methods=["POST", "GET"],
        backoff_factor=1
    )
    
    adapter = HTTPAdapter(max_retries=retry_strategy)
    session.mount("http://", adapter)
    session.mount("https://", adapter)
    
    return session

# -------------------------------------------------------------------
# Config Odoo
# -------------------------------------------------------------------

ODOO_DB_URL = os.environ.get("ODOO_DB_URL")  # à définir dans Cloud Run (base URL)
ODOO_SECRET = os.environ.get("ODOO_SECRET")  # à définir dans Cloud Run
ODOO_ENDPOINT = "/json/2/crm.lead/create"
ODOO_FULL_URL = f"{ODOO_DB_URL}{ODOO_ENDPOINT}" if ODOO_DB_URL else None

# -------------------------------------------------------------------
# Config Cloud Tasks
# -------------------------------------------------------------------

GCP_PROJECT_ID = os.environ.get("GCP_PROJECT_ID")  # à définir dans Cloud Run
GCP_REGION = os.environ.get("GCP_REGION", "europe-west1")  # à définir dans Cloud Run
CLOUD_TASKS_QUEUE = os.environ.get("CLOUD_TASKS_QUEUE", "mail-writer-queue")  # à définir dans Cloud Run
MAIL_WRITER_ENDPOINT = os.environ.get("MAIL_WRITER_ENDPOINT")  # à définir dans Cloud Run (ex: https://mail-writer-xxx.a.run.app)


# -------------------------------------------------------------------
# Helpers de mapping Pharow -> Odoo
# -------------------------------------------------------------------

def parse_address(full_address: str):
    """
    Exemple : '89 Rue Nationale 59000 Lille'
    → street = '89 Rue Nationale'
      zip = '59000'
      city = 'Lille'
    """
    if not full_address:
        return "", "", ""

    parts = full_address.split()
    zip_code = ""
    city = ""
    street = full_address

    for i, part in enumerate(parts):
        if len(part) == 5 and part.isdigit():
            zip_code = part
            street = " ".join(parts[:i])
            city = " ".join(parts[i + 1 :]) if i + 1 < len(parts) else ""
            break

    return street, city, zip_code


def build_description(position: dict, person: dict, company: dict) -> str:
    """
    Construit la description Odoo à partir des infos Pharow,
    sans répéter les champs déjà remplis ailleurs.
    """
    lines = []

    activity = company.get("companyActivity") or ""
    if activity:
        # base = 'Développement de logiciels'
        lines.append(activity)

    extra = []

    naf = company.get("companyNafSector")
    if naf:
        extra.append(f"Secteur NAF : {naf}")

    founding_year = company.get("companyFoundingYear")
    if founding_year:
        extra.append(f"Année de création : {founding_year}")

    siren = company.get("companySiren")
    if siren:
        extra.append(f"SIREN : {siren}")

    employees = company.get("companyEmployeeRangeCorrected") or company.get("companyNbEmployees")
    if employees:
        extra.append(f"Taille estimée : {employees}")

    growing = company.get("companyGrowing")
    if growing is True:
        extra.append("Entreprise en croissance : Oui")
    elif growing is False:
        extra.append("Entreprise en croissance : Non")

    generic_email = company.get("companyGenericEmail")
    if generic_email:
        extra.append(f"Email générique : {generic_email}")

    company_linkedin = company.get("companyLinkedinUrl")
    if company_linkedin:
        extra.append(f"LinkedIn entreprise : {company_linkedin}")

    person_linkedin = person.get("personLinkedinUrl")
    if person_linkedin:
        extra.append(f"LinkedIn contact : {person_linkedin}")

    reliability = position.get("positionEmailReliability")
    status = position.get("positionEmailStatus")
    if reliability or status:
        parts = []
        if status:
            parts.append(f"statut e-mail : {status}")
        if reliability:
            parts.append(f"fiabilité e-mail : {reliability}")
        extra.append("Email contact (" + ", ".join(parts) + ")")

    if extra:
        lines.append("")
        lines.append("Infos issues de Pharow :")
        for e in extra:
            lines.append(f"- {e}")

    if not lines:
        return ""

    return "\n".join(lines)


def pharow_item_to_odoo_lead(item: dict) -> dict:
    """
    Convertit un objet 'data[...]' de Pharow en dict lead Odoo.
    """
    position = item.get("position", {}) or {}
    person = item.get("person", {}) or {}
    company = item.get("company", {}) or {}

    brand = company.get("companyBrandName") or company.get("companyName") or ""
    company_name = company.get("companyName") or brand

    # 🔥 Récupération du pharowCompanyId
    external_id = company.get("pharowCompanyId") or ""

    full_address = company.get("companyHqFullAddress", "") or ""
    street, city, zip_code = parse_address(full_address)

    first_name = person.get("personFirstName", "") or ""
    last_name = person.get("personLastName", "") or ""
    contact_name = (first_name + " " + last_name).strip()

    email = (
        position.get("positionEmail")
        or company.get("companyGenericEmail")
        or ""
    )

    job_title = position.get("positionJobTitle") or ""
    description = build_description(position, person, company)

    lead = {
        "name": f"🎥 Idée de vidéo pour {brand}".strip() or company_name,
        "type": "lead",
        "contact_name": contact_name,
        "partner_name": company_name,
        "function": job_title,
        "email_from": email,
        "phone": company.get("companyMainPhone") or "",
        "website": company.get("companyUrl") or "",
        "street": street,
        "street2": "",
        "zip": zip_code,
        "city": city,
        "description": description or "",
        "source_id": 25,

        # ⬇️⬇️ Enregistrement du pharowCompanyId dans ton champ custom Odoo
        "x_external_id": external_id,
    }

    return lead



def pharow_payload_to_odoo_vals_list(payload: dict) -> dict:
    """
    Transforme le payload Pharow complet en JSON prêt pour Odoo :
    {
      "vals_list": [ {...}, {...} ]
    }
    """
    vals_list = []

    for item in payload.get("data", []):
        vals_list.append(pharow_item_to_odoo_lead(item))

    return {"vals_list": vals_list}


def search_existing_lead(external_id: str) -> list:
    """
    Recherche un lead existant dans Odoo par son external_id (pharowCompanyId).
    Retourne la liste des IDs trouvés (généralement 0 ou 1).
    """
    if not ODOO_DB_URL:
        raise RuntimeError("ODOO_DB_URL n'est pas défini dans les variables d'environnement")
    if not ODOO_SECRET:
        raise RuntimeError("ODOO_SECRET n'est pas défini dans les variables d'environnement")

    search_url = f"{ODOO_DB_URL}/json/2/crm.lead/search"
    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {ODOO_SECRET}",
        "Connection": "keep-alive"
    }
    
    payload = {
        "domain": [["x_external_id", "ilike", external_id]]
    }

    print(f"[DEBUG] Recherche lead existant avec external_id: {external_id}")
    print(f"[DEBUG] URL recherche : {search_url}")
    print(f"[DEBUG] Payload recherche : {payload}")

    try:
        session = create_requests_session()
        resp = session.post(search_url, headers=headers, json=payload, timeout=15)
        print(f"[DEBUG] Statut HTTP recherche : {resp.status_code}")
        print(f"[DEBUG] Response recherche : {resp.text}")
        
        resp.raise_for_status()
        result = resp.json()
        print(f"[DEBUG] IDs trouvés : {result}")
        return result if isinstance(result, list) else []
    except requests.exceptions.ConnectionError as e:
        print(f"[ERROR] Connection Error lors de la recherche: {e}")
        raise RuntimeError(f"Impossible de se connecter à Odoo: {str(e)}")
    except requests.exceptions.Timeout as e:
        print(f"[ERROR] Timeout lors de la recherche: {e}")
        raise RuntimeError(f"Timeout de connexion à Odoo (15s dépassé): {str(e)}")
    except Exception as e:
        print(f"[ERROR] Erreur lors de la recherche : {e}")
        raise


def create_mail_writer_task(first_name: str, last_name: str, email: str, website: str, partner_name: str, function: str, description: str, x_external_id: str = "") -> dict:
    """
    Crée une task dans Google Cloud Tasks pour générer un mail de prospection.
    La task appelle le service mail-writer avec les infos du prospect.
    """
    if not GCP_PROJECT_ID:
        raise RuntimeError("GCP_PROJECT_ID n'est pas défini dans les variables d'environnement")
    if not MAIL_WRITER_ENDPOINT:
        raise RuntimeError("MAIL_WRITER_ENDPOINT n'est pas défini dans les variables d'environnement")

    try:
        client = tasks_v2.CloudTasksClient()
        parent = client.queue_path(GCP_PROJECT_ID, GCP_REGION, CLOUD_TASKS_QUEUE)

        # Construire le payload de la task
        task_payload = {
            "first_name": first_name,
            "last_name": last_name,
            "email": email,
            "website": website,
            "partner_name": partner_name,
            "function": function,
            "description": description,
            "x_external_id": x_external_id
        }

        task = {
            "http_request": {
                "http_method": tasks_v2.HttpMethod.POST,
                "url": MAIL_WRITER_ENDPOINT,
                "headers": {"Content-Type": "application/json"},
                "body": json.dumps(task_payload).encode()
            }
        }

        print(f"[DEBUG] Création de task Cloud Tasks")
        print(f"[DEBUG] Queue: {parent}")
        print(f"[DEBUG] Endpoint: {MAIL_WRITER_ENDPOINT}")
        print(f"[DEBUG] Payload: {task_payload}")

        response = client.create_task(request={"parent": parent, "task": task})
        
        print(f"[DEBUG] Task créée avec succès : {response.name}")
        return {
            "status": "task_created",
            "task_name": response.name
        }

    except Exception as e:
        print(f"[ERROR] Erreur lors de la création de la task : {e}")
        raise


def send_to_odoo(vals_list_payload: dict) -> dict:
    """
    Envoie le JSON à Odoo.
    Hypothèse : auth via header Authorization: Bearer <token>.
    Adapte si ton Odoo attend autre chose.
    """
    if not ODOO_DB_URL:
        raise RuntimeError("ODOO_DB_URL n'est pas défini dans les variables d'environnement")
    if not ODOO_SECRET:
        raise RuntimeError("ODOO_SECRET n'est pas défini dans les variables d'environnement")

    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {ODOO_SECRET}",
        "Connection": "keep-alive"
    }

    print(f"[DEBUG] Envoi vers Odoo : {ODOO_FULL_URL}")
    print(f"[DEBUG] Payload Odoo : {vals_list_payload}")
    print(f"[DEBUG] Headers : Content-Type={headers.get('Content-Type')}, Auth={'Bearer ' + '*' * 10 + '...'}")

    try:
        session = create_requests_session()
        resp = session.post(ODOO_FULL_URL, headers=headers, json=vals_list_payload, timeout=15)
        print(f"[DEBUG] Statut HTTP réponse : {resp.status_code}")
        print(f"[DEBUG] Headers réponse : {resp.headers}")
        print(f"[DEBUG] Body réponse (raw) : {resp.text}")
        
        resp.raise_for_status()
        # On suppose que Odoo renvoie du JSON. Si ce n'est pas le cas, adapte ici.
        try:
            return resp.json()
        except ValueError:
            return {"raw_response": resp.text}
    except requests.exceptions.ConnectionError as e:
        print(f"[ERROR] Connection Error : {e}")
        raise RuntimeError(f"Impossible de se connecter à Odoo: {str(e)}")
    except requests.exceptions.Timeout as e:
        print(f"[ERROR] Timeout : {e}")
        raise RuntimeError(f"Timeout de connexion à Odoo (15s dépassé): {str(e)}")
    except requests.exceptions.HTTPError as e:
        print(f"[ERROR] HTTP Error : {e}")
        print(f"[ERROR] Status code : {e.response.status_code}")
        print(f"[ERROR] Response body : {e.response.text}")
        print(f"[ERROR] Response headers : {e.response.headers}")
        raise
    except requests.exceptions.RequestException as e:
        print(f"[ERROR] Request Exception : {e}")
        raise


# -------------------------------------------------------------------
# Webhook Flask (Cloud Run)
# -------------------------------------------------------------------

@app.route("/", methods=["POST"])
def webhook():
    payload = request.get_json(force=True)

    print("──── Webhook Pharow reçu ────")
    print(payload)
    print("─────────────────────────────")

    vals_payload = pharow_payload_to_odoo_vals_list(payload)

    print("──── Payload Odoo généré ────")
    print(vals_payload)
    print("─────────────────────────────")

    odoo_status = "ok"
    odoo_response = None

    try:
        # Vérifier si les leads existent déjà avant de les créer
        checked_vals = []
        lead_items = []  # Pour stocker les items originaux avec checked_vals
        
        for item in payload.get("data", []):
            val = pharow_item_to_odoo_lead(item)
            external_id = val.get("x_external_id")
            if external_id:
                existing_leads = search_existing_lead(external_id)
                if existing_leads and len(existing_leads) > 0:
                    print(f"[INFO] Lead avec external_id '{external_id}' existe déjà (IDs: {existing_leads})")
                    odoo_response = {
                        "status": "skipped",
                        "reason": f"Lead with external_id '{external_id}' already exists",
                        "existing_ids": existing_leads
                    }
                    odoo_status = "skipped"
                else:
                    print(f"[INFO] Lead avec external_id '{external_id}' n'existe pas, création...")
                    checked_vals.append(val)
                    lead_items.append(item)
            else:
                checked_vals.append(val)
                lead_items.append(item)
        
        # Créer seulement les leads qui n'existent pas
        if checked_vals:
            filtered_payload = {"vals_list": checked_vals}
            odoo_response = send_to_odoo(filtered_payload)
            print("──── Réponse Odoo ──────────")
            print(odoo_response)
            print("─────────────────────────────")
            
            # Créer une task Cloud Tasks pour chaque lead créé
            tasks_created = []
            for item in lead_items:
                try:
                    person = item.get("person", {}) or {}
                    company = item.get("company", {}) or {}
                    position = item.get("position", {}) or {}
                    
                    first_name = person.get("personFirstName", "") or ""
                    last_name = person.get("personLastName", "") or ""
                    email = position.get("positionEmail") or company.get("companyGenericEmail") or ""
                    website = company.get("companyUrl", "") or ""
                    partner_name = company.get("companyName", "") or ""
                    function = position.get("positionJobTitle", "") or ""
                    description = company.get("companyActivity", "") or ""
                    x_external_id = company.get("pharowCompanyId", "") or ""
                    
                    task_result = create_mail_writer_task(
                        first_name,
                        last_name,
                        email,
                        website,
                        partner_name,
                        function,
                        description,
                        x_external_id
                    )
                    tasks_created.append(task_result)
                    
                except Exception as task_error:
                    print(f"[WARNING] Erreur lors de la création de la task mail-writer : {task_error}")
                    tasks_created.append({"status": "error", "error": str(task_error)})
            
            # Ajouter les tasks créées à la réponse
            if "tasks_created" not in odoo_response:
                odoo_response["tasks_created"] = tasks_created
                
        elif not odoo_response:
            odoo_response = {"status": "skipped", "reason": "All leads already exist"}
            odoo_status = "skipped"
    except Exception as e:
        # On log l'erreur, mais on renvoie quand même 200 à Pharow
        # pour éviter qu'il considère ça comme un échec de webhook.
        odoo_status = "error"
        odoo_response = {"error": str(e)}
        print("[ERROR] Erreur lors de l'appel Odoo :")
        print(f"[ERROR] Type: {type(e).__name__}")
        print(f"[ERROR] Message: {str(e)}")
        import traceback
        print(f"[ERROR] Traceback:\n{traceback.format_exc()}")
        
        # Si c'est une erreur de connexion, on peut essayer un retry une fois
        if isinstance(e, (requests.exceptions.ConnectionError, requests.exceptions.Timeout)):
            print("[INFO] Tentative de retry après erreur de connexion...")
            try:
                # Réessayer une seule fois après un court délai
                import time
                time.sleep(2)
                
                checked_vals = []
                for item in payload.get("data", []):
                    val = pharow_item_to_odoo_lead(item)
                    checked_vals.append(val)
                
                if checked_vals:
                    filtered_payload = {"vals_list": checked_vals}
                    odoo_response = send_to_odoo(filtered_payload)
                    odoo_status = "ok"
                    print("[INFO] Retry successful après reconnexion")
                    
            except Exception as retry_error:
                print(f"[ERROR] Retry échoué : {retry_error}")
                odoo_response = {"error": f"Erreur après retry: {str(retry_error)}"}
                odoo_status = "error"

    return jsonify({
        "status": "ok",               # pour Pharow
        "odoo_status": odoo_status,   # pour toi
        "odoo_response": odoo_response
    }), 200


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=8080)
