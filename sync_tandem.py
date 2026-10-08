import os
import requests
import urllib3

# Disabilita gli avvisi di sicurezza relativi al certificato SSL di AirCare
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

# Recupero delle credenziali coperte da segreto nei Secrets di GitHub
AIRCARE_LOGIN_URL = os.environ.get("AIRCARE_LOGIN_URL")
AIRCARE_LASTDATA_URL = os.environ.get("AIRCARE_LASTDATA_URL")
AIRCARE_USERNAME = os.environ.get("AIRCARE_USERNAME")  # La tua email di AirCare
AIRCARE_PASSWORD = os.environ.get("AIRCARE_PASSWORD")

APS_CLIENT_ID = os.environ.get("APS_CLIENT_ID")
APS_CLIENT_SECRET = os.environ.get("APS_CLIENT_SECRET")
TANDEM_STREAM_URL = os.environ.get("TANDEM_STREAM_URL")

TARGET_DEVICE = "Digitalis_086_IAQ"

def run_sync():
    headers_browser = {
        "Content-Type": "application/json",
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
    }

    # 1. Login ad AirCare (inviamo sia 'email' che 'username' per compatibilità)
    print("1/4 Autenticazione su AirCare...")
    login_resp = requests.post(
        AIRCARE_LOGIN_URL,
        json={
            "email": AIRCARE_USERNAME,
            "username": AIRCARE_USERNAME,
            "password": AIRCARE_PASSWORD
        },
        headers=headers_browser,
        verify=False,
        timeout=15
    )
    login_resp.raise_for_status()
    login_data = login_resp.json()
    aircare_token = login_data.get("token") or login_data.get("access_token")

    # 2. Recupero dati da AirCare
    print("2/4 Estrazione telemetria da AirCare...")
    headers_aircare = {
        "Authorization": f"Bearer {aircare_token}",
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"
    }
    data_resp = requests.get(
        AIRCARE_LASTDATA_URL,
        headers=headers_aircare,
        verify=False,
        timeout=15
    )
    data_resp.raise_for_status()
    raw_data = data_resp.json().get("data", [])

    # 3. Filtraggio e normalizzazione del sensore Digitalis_086_IAQ
    payload = {"timestamp": 0}
    for item in raw_data:
        if item.get("device") == TARGET_DEVICE:
            resource = item.get("resource")
            val = item.get("value")
            checktime = item.get("checktime", 0)

            key = "CO2" if resource == "Co2" else resource
            payload[key] = val

            if checktime > payload["timestamp"]:
                payload["timestamp"] = checktime

    if len(payload) <= 1:
        raise Exception(f"Nessun dato trovato per il dispositivo {TARGET_DEVICE}")

    print(f"Payload preparato per {TARGET_DEVICE}:", payload)

    # 4. Richiesta Token ad Autodesk Platform Services (APS)
    print("3/4 Richiesta Token OAuth ad Autodesk Platform Services...")
    aps_resp = requests.post(
        "https://developer.api.autodesk.com/authentication/v2/token",
        auth=(APS_CLIENT_ID, APS_CLIENT_SECRET),
        data={"grant_type": "client_credentials", "scope": "data:write"},
        timeout=15
    )
    aps_resp.raise_for_status()
    aps_token = aps_resp.json()["access_token"]

    # 5. Invio dati allo Stream di Autodesk Tandem
    print("4/4 Invio payload ad Autodesk Tandem...")
    tandem_headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {aps_token}"
    }
    tandem_resp = requests.post(
        TANDEM_STREAM_URL,
        json=payload,
        headers=tandem_headers,
        timeout=15
    )
    tandem_resp.raise_for_status()

    print("Sincronizzazione completata con successo!")

if __name__ == "__main__":
    run_sync()
