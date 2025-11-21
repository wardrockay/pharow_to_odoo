import os
import requests
from flask import Flask, request, jsonify

app = Flask(__name__)

# -------------------------------------------------------------------
# Config Odoo
# -------------------------------------------------------------------

ODOO_DB_URL = os.environ.get("ODOO_DB_URL")  # à définir dans Cloud Run (base URL)
ODOO_SECRET = os.environ.get("ODOO_SECRET")  # à définir dans Cloud Run
ODOO_ENDPOINT = "/json/2/crm.lead/create"
ODOO_FULL_URL = f"{ODOO_DB_URL}{ODOO_ENDPOINT}" if ODOO_DB_URL else None


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
    }
    
    payload = {
        "domain": [["x_external_id", "ilike", external_id]]
    }

    print(f"[DEBUG] Recherche lead existant avec external_id: {external_id}")
    print(f"[DEBUG] URL recherche : {search_url}")
    print(f"[DEBUG] Payload recherche : {payload}")

    try:
        resp = requests.post(search_url, headers=headers, json=payload, timeout=10)
        print(f"[DEBUG] Statut HTTP recherche : {resp.status_code}")
        print(f"[DEBUG] Response recherche : {resp.text}")
        
        resp.raise_for_status()
        result = resp.json()
        print(f"[DEBUG] IDs trouvés : {result}")
        return result if isinstance(result, list) else []
    except Exception as e:
        print(f"[ERROR] Erreur lors de la recherche : {e}")
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
    }

    print(f"[DEBUG] Envoi vers Odoo : {ODOO_FULL_URL}")
    print(f"[DEBUG] Payload Odoo : {vals_list_payload}")
    print(f"[DEBUG] Headers : Content-Type={headers.get('Content-Type')}, Auth={'Bearer ' + '*' * 10 + '...'}")

    try:
        resp = requests.post(ODOO_FULL_URL, headers=headers, json=vals_list_payload, timeout=10)
        print(f"[DEBUG] Statut HTTP réponse : {resp.status_code}")
        print(f"[DEBUG] Headers réponse : {resp.headers}")
        print(f"[DEBUG] Body réponse (raw) : {resp.text}")
        
        resp.raise_for_status()
        # On suppose que Odoo renvoie du JSON. Si ce n'est pas le cas, adapte ici.
        try:
            return resp.json()
        except ValueError:
            return {"raw_response": resp.text}
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
        for val in vals_payload.get("vals_list", []):
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
            else:
                checked_vals.append(val)
        
        # Créer seulement les leads qui n'existent pas
        if checked_vals:
            filtered_payload = {"vals_list": checked_vals}
            odoo_response = send_to_odoo(filtered_payload)
            print("──── Réponse Odoo ──────────")
            print(odoo_response)
            print("─────────────────────────────")
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

    return jsonify({
        "status": "ok",               # pour Pharow
        "odoo_status": odoo_status,   # pour toi
        "odoo_response": odoo_response
    }), 200


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=8080)
