import json
import os
import re
import tempfile
from flask import Flask, request, jsonify, send_from_directory

app = Flask(__name__, static_folder="static")

PORT = int(os.environ.get("PORT", 5001))


# PEM helpers
def fix_pem(raw: str) -> str:
    fixed = raw.replace("\\n", "\n")
    fixed = re.sub(r"\n{3,}", "\n\n", fixed)
    return fixed.strip() + "\n"


def extract_fields(data: dict) -> dict:
    cert_raw = data.get("certificate", "")
    key_raw  = data.get("key", "")
    auth_ep  = data.get("authorization_endpoint", "")

    token_url = re.sub(r"/oauth2/authorize$", "/oauth2/token", auth_ep)
    if not token_url.endswith("/oauth2/token"):
        from urllib.parse import urlparse, urlunparse
        p = urlparse(auth_ep)
        token_url = urlunparse(p._replace(path="/oauth2/token", query="", fragment=""))

    return {
        "clientid":               data.get("clientid", ""),
        "token_url":              token_url,
        "authorization_endpoint": auth_ep,
        "service_url":            data.get("url", ""),
        "cert_pem":               fix_pem(cert_raw),
        "key_pem":                fix_pem(key_raw),
        "cert_expires":           data.get("certificate_expires_at", ""),
        "credential_type":        data.get("credential-type", ""),
        "app_tid":                data.get("app_tid", ""),
    }


def do_mtls_request(method: str, url: str, cert_pem: str, key_pem: str,
                    headers: dict = None, data=None, json_body=None):
    """mTLS-Request; Zertifikate landen nur kurzlebig in Temp-Dateien."""
    import requests as req

    cert_path = key_path = None
    try:
        with tempfile.NamedTemporaryFile(mode="w", suffix=".crt", delete=False) as f:
            f.write(cert_pem)
            cert_path = f.name
        with tempfile.NamedTemporaryFile(mode="w", suffix=".key", delete=False) as f:
            f.write(key_pem)
            key_path = f.name

        h = {"Accept": "application/json"}
        if headers:
            h.update(headers)

        resp = req.request(
            method, url,
            cert=(cert_path, key_path),
            headers=h,
            data=data,
            json=json_body,
            timeout=30,
            verify=True,
        )
        return resp.status_code, resp.text, None

    except Exception as e:
        return None, None, str(e)

    finally:
        for path in [cert_path, key_path]:
            if path:
                try:
                    os.unlink(path)
                except OSError:
                    pass


# Routes
@app.route("/")
def index():
    return send_from_directory("static", "index.html")


@app.route("/parse", methods=["POST"])
def parse_json():
    try:
        data = request.get_json(force=True)
        if not data:
            return jsonify({"error": "Kein JSON erhalten"}), 400
        fields = extract_fields(data)
        return jsonify({"ok": True, "fields": fields})
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/parse-grounding", methods=["POST"])
def parse_grounding():
    try:
        data = request.get_json(force=True)
        if not data:
            return jsonify({"error": "Kein JSON erhalten"}), 400

        url         = data.get("url", "")
        rag_info    = data.get("endpoints", {}).get("retrieval-augmented-generation", {})
        rag_uri     = rag_info.get("uri", "")
        base_url    = rag_uri or url
        swagger     = data.get("swagger", {})

        return jsonify({
            "ok": True,
            "grounding": {
                "base_url":      base_url,
                "url":           url,
                "rag_uri":       rag_uri,
                "requires_mtls": rag_info.get("requires-mtls", False),
                "swagger":       swagger,
            }
        })
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/get-token", methods=["POST"])
def get_token():
    try:
        payload   = request.get_json(force=True)
        fields    = payload.get("fields", {})
        clientid  = fields.get("clientid", "").strip()
        token_url = fields.get("token_url", "").strip()
        cert_pem  = fields.get("cert_pem", "")
        key_pem   = fields.get("key_pem", "")

        if not all([clientid, token_url, cert_pem, key_pem]):
            return jsonify({"error": "Fehlende Felder: clientid, token_url, cert oder key"}), 400

        status, body, err = do_mtls_request(
            "POST", token_url,
            cert_pem, key_pem,
            headers={"Content-Type": "application/x-www-form-urlencoded"},
            data=f"client_id={clientid}&grant_type=client_credentials",
        )

        if err:
            return jsonify({"error": f"Request fehlgeschlagen: {err}\n\nVerwende URL: {token_url}"}), 500
        if status >= 400:
            return jsonify({"error": f"HTTP {status} bei URL: {token_url}\n\nAntwort: {body}"}), 500

        try:
            token_data = json.loads(body)
        except json.JSONDecodeError:
            return jsonify({"error": f"Ungültige Antwort:\n{body}"}), 500

        if "access_token" not in token_data:
            return jsonify({"error": f"Kein access_token in Antwort: {body}"}), 500

        return jsonify({"ok": True, "token": token_data})

    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/api-call", methods=["POST"])
def api_call():
    try:
        payload      = request.get_json(force=True)
        method       = payload.get("method", "GET").upper()
        url          = payload.get("url", "").strip()
        token        = payload.get("token", "").strip()
        body         = payload.get("body", None)
        extra_headers = payload.get("headers", {})

        cert_pem = payload.get("cert_pem", "")
        key_pem  = payload.get("key_pem", "")

        if not cert_pem or not key_pem:
            return jsonify({"error": "Zertifikate fehlen – bitte zuerst Service Key hochladen."}), 400

        headers = {"Authorization": f"Bearer {token}"}
        headers.update(extra_headers)

        json_body = body if method in ("POST", "PUT", "PATCH") else None

        status, raw, err = do_mtls_request(
            method, url, cert_pem, key_pem,
            headers=headers,
            json_body=json_body,
        )

        if err:
            return jsonify({"ok": False, "status": None, "raw": err, "parsed": None,
                            "debug": {"url": url, "method": method}})

        try:
            parsed = json.loads(raw)
        except Exception:
            parsed = None

        return jsonify({
            "ok":     status < 400,
            "status": status,
            "raw":    raw,
            "parsed": parsed,
            "debug":  {"url": url, "method": method},
        })

    except Exception as e:
        return jsonify({"error": str(e)}), 500


if __name__ == "__main__":
    print(f"\nDocument Grounding Setup Manager running on http://localhost:{PORT}\n")
    app.run(port=PORT, debug=False)
