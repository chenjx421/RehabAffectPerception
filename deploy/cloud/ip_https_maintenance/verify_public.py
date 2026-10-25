"""Direct public-IP checks; never bypass TLS verification or use proxy env."""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import http.client
import json
import ssl
import sys

IP = "YOUR_SERVER_IP"
BLOCKED_PATHS = (
    "/app", "/api/", "/login", "/.env", "/.git/config",
    "/__maintenance.html", "/video_tasks/", "/student_documents/",
    "/etc/passwd", "/.well-known/acme-challenge/not-a-real-token",
)


def request(secure: bool, path: str, method: str = "GET") -> dict:
    if secure:
        connection = http.client.HTTPSConnection(
            IP, 443, timeout=10, context=ssl.create_default_context()
        )
    else:
        connection = http.client.HTTPConnection(IP, 80, timeout=10)
    try:
        connection.connect()
        certificate = connection.sock.getpeercert() if secure else None
        fingerprint = (
            hashlib.sha256(connection.sock.getpeercert(binary_form=True)).hexdigest()
            if secure else None
        )
        connection.request(method, path, headers={"Connection": "close"})
        response = connection.getresponse()
        body = response.read(65537)
        if len(body) > 65536:
            raise AssertionError("Unexpectedly large public response")
        return {
            "status": response.status,
            "headers": {key.lower(): value for key, value in response.getheaders()},
            "body": body,
            "certificate": certificate,
            "sha256": fingerprint,
        }
    finally:
        connection.close()


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", required=True)
    args = parser.parse_args()
    result = {
        "checked_at_utc": datetime.now(timezone.utc).isoformat(),
        "target": IP,
        "direct_connection": True,
        "tls_verification_bypassed": False,
        "checks": [],
    }
    try:
        for path in ("/", *BLOCKED_PATHS):
            response = request(False, path)
            if response["status"] != 404:
                raise AssertionError("Non-challenge HTTP path is not 404")
            result["checks"].append({"scheme": "http", "path": path, "status": 404})
        response = request(True, "/")
        if response["status"] != 503 or b"<h1>Maintenance</h1>" not in response["body"]:
            raise AssertionError("HTTPS maintenance response did not match")
        if response["headers"].get("retry-after") != "300":
            raise AssertionError("Missing maintenance Retry-After header")
        if response["headers"].get("cache-control") != "no-store":
            raise AssertionError("Missing no-store header")
        if "set-cookie" in response["headers"]:
            raise AssertionError("Maintenance must not set application cookies")
        certificate = response["certificate"]
        if ("IP Address", IP) not in certificate.get("subjectAltName", ()):
            raise AssertionError("Missing exact IP subject alternative name")
        result["certificate"] = {
            "issuer": certificate.get("issuer"),
            "subject_alt_name": certificate.get("subjectAltName"),
            "not_before": certificate.get("notBefore"),
            "not_after": certificate.get("notAfter"),
            "sha256": response["sha256"],
            "validated_against_default_trust_store": True,
        }
        result["checks"].append({"scheme": "https", "path": "/", "status": 503})
        for path in BLOCKED_PATHS:
            response = request(True, path)
            if response["status"] != 404:
                raise AssertionError("Non-maintenance HTTPS path is not 404")
            result["checks"].append({"scheme": "https", "path": path, "status": 404})
        response = request(True, "/", method="HEAD")
        if response["status"] != 503 or response["body"]:
            raise AssertionError("Unexpected HTTPS HEAD result")
        result["checks"].append({"scheme": "https", "method": "HEAD", "path": "/", "status": 503})
        result["public_verified"] = True
        result["result"] = "PASS"
    except Exception as error:
        result["public_verified"] = False
        result["result"] = "FAIL"
        result["failure_type"] = type(error).__name__
        result["failure_summary"] = str(error)
    # The report contains only synthetic routes, public TLS metadata and statuses.
    with open(args.output, "w", encoding="utf-8") as stream:
        json.dump(result, stream, indent=2, ensure_ascii=True)
        stream.write("\n")
    print(json.dumps(result, ensure_ascii=True))
    return 0 if result["result"] == "PASS" else 1


if __name__ == "__main__":
    sys.exit(main())
