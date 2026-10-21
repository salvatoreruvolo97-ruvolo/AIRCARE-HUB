import os
import requests
import urllib3

# Disabilita gli avvisi di sicurezza relativi al certificato SSL di AirCare
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

AIRCARE_LOGIN_URL = os.environ.get("AIRCARE_LOGIN_URL")
AIRCARE_LASTDATA_URL = os.environ.get("AIRCARE_LASTDATA_URL")
AIRCARE_USERNAME = os.environ.get("AIRCARE_USERNAME")
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

    # 1. Login ad AirCare
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

    # Estrazione del token specifico da 'auth' -> 'token'
    aircare_token = None
    if isinstance(login_data, dict):
        auth_obj = login_data.get("auth")
        if isinstance(auth_obj, dict):
            aircare_token = auth_obj.get("token")
        if not aircare_token:
            aircare_token = login_data.get("token") or login_data.get("access_token")

    if not aircare_token:
        raise Exception(f"Token non trovato nella risposta di login: {login_data}")

    print("Token AirCare estratto con successo!")

    # 2. Recupero dati da AirCare
    print("2/4 Estrazione telemetria da AirCare...")
    auth_header_val = aircare_token if aircare_token.startswith("Bearer ") else f"Bearer {aircare_token}"
    
    headers_aircare = {
        "Authorization": auth_header_val,
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

   # 3. Filtraggio e normalizzazione per ENTRAMBI i sensori
    payload_086 = {"timestamp": 0}
    payload_095 = {"timestamp": 0}

    print("Lista dispositivi visti da AirCare in questo momento:")
    for item in raw_data:
        device_name = item.get("device")
        if device_name:
            # Stampa il nome esatto del dispositivo per scovare eventuali errori
            print(f" -> Trovato in API: '{device_name}'") 
        
        # Se i dati sono del sensore 086
        if device_name == "Digitalis_086_IAQ":
            resource = item.get("resource")
            val = item.get("value")
            checktime = item.get("checktime", 0)
            key = "CO2" if resource == "Co2" else resource
            payload_086[key] = val
            if checktime > payload_086["timestamp"]:
                payload_086["timestamp"] = checktime

        # Se i dati sono del sensore 095
        elif device_name == "Digitalis_095_IAQ":
            resource = item.get("resource")
            val = item.get("value")
            checktime = item.get("checktime", 0)
            key = "CO2" if resource == "Co2" else resource
            payload_095[key] = val
            if checktime > payload_095["timestamp"]:
                payload_095["timestamp"] = checktime

    # Se ENTRAMBI i sensori sono vuoti, usciamo in modo pulito (nessun errore rosso su GitHub)
    if len(payload_086) <= 1 and len(payload_095) <= 1:
        print("ATTENZIONE: Nessun dato trovato per 086 e 095. Forse sono spenti o offline.")
        return

    print(f"Payload preparato 086: {payload_086}")
    print(f"Payload preparato 095: {payload_095}")

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

    # 5. Invio dati agli Stream di Autodesk Tandem
    print("4/4 Invio payload ad Autodesk Tandem...")
    tandem_headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {aps_token}"
    }

    # Invio per il sensore 086 (se ci sono dati)
    if len(payload_086) > 1:
        tandem_resp_086 = requests.post(
            TANDEM_STREAM_URL,
            json=payload_086,
            headers=tandem_headers,
            timeout=15
        )
        tandem_resp_086.raise_for_status()
        print("Sincronizzazione 086 completata con successo!")

    # Invio per il sensore 095 (se ci sono dati)
    TANDEM_STREAM_URL_095 = os.environ.get("TANDEM_STREAM_URL_095")
    if len(payload_095) > 1 and TANDEM_STREAM_URL_095:
        tandem_resp_095 = requests.post(
            TANDEM_STREAM_URL_095,
            json=payload_095,
            headers=tandem_headers,
            timeout=15
        )
        tandem_resp_095.raise_for_status()
        print("Sincronizzazione 095 completata con successo!")
        # === NUOVA SEZIONE: INVIO DATI A GRAFANA CLOUD ===
    GRAFANA_URL = os.environ.get("GRAFANA_URL")
    GRAFANA_USER = os.environ.get("GRAFANA_USER")
    GRAFANA_TOKEN = os.environ.get("GRAFANA_TOKEN")

    if GRAFANA_URL and GRAFANA_USER and GRAFANA_TOKEN:
        print("5/5 Invio metriche a Grafana Cloud...")
        
        # Adattiamo l'URL per permettere l'invio in formato testo (Influx Line Protocol)
        grafana_write_url = GRAFANA_URL.replace('/api/prom/push', '/api/v1/push/influx/write')
        
        line_protocol_data = []
        
        # Formattazione dati per il sensore 086
        if len(payload_086) > 1:
            fields = [f"{k}={v}" for k, v in payload_086.items() if k != "timestamp"]
            ts_ns = payload_086["timestamp"] * 1000000000 # Il database richiede il tempo in nanosecondi
            line_protocol_data.append(f"aircare,device=Digitalis_086_IAQ {','.join(fields)} {ts_ns}")
            
        # Formattazione dati per il sensore 095
        if len(payload_095) > 1:
            fields = [f"{k}={v}" for k, v in payload_095.items() if k != "timestamp"]
            ts_ns = payload_095["timestamp"] * 1000000000 # Il database richiede il tempo in nanosecondi
            line_protocol_data.append(f"aircare,device=Digitalis_095_IAQ {','.join(fields)} {ts_ns}")
            
        # Spedizione del pacchetto a Grafana
        if line_protocol_data:
            grafana_payload = "\n".join(line_protocol_data)
            try:
                grafana_resp = requests.post(
                    grafana_write_url,
                    auth=(GRAFANA_USER, GRAFANA_TOKEN),
                    data=grafana_payload,
                    headers={'Content-Type': 'text/plain'},
                    timeout=15
                )
                grafana_resp.raise_for_status()
                print("Sincronizzazione Grafana completata con successo!")
            except Exception as e:
                print(f"Errore durante l'invio a Grafana: {e}")

if __name__ == "__main__":
    run_sync()
