"""Unauthenticated gateway acceptance, without secrets, cookies or TLS bypass."""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import http.client
import json
import ssl

IP = "YOUR_SERVER_IP"


def request(path: str, secure: bool = True) -> dict:
    connection = (
        http.client.HTTPSConnection(IP, 443, timeout=15, context=ssl.create_default_context())
        if secure else http.client.HTTPConnection(IP, 80, timeout=15)
    )
    try:
        connection.connect()
        certificate = connection.sock.getpeercert() if secure else None
        fingerprint = (
            hashlib.sha256(connection.sock.getpeercert(binary_form=True)).hexdigest()
            if secure else None
        )
        connection.request("GET", path, headers={"Connection": "close"})
        response = connection.getresponse()
        body = response.read(65537)
        if len(body) > 65536:
            raise AssertionError("Unexpectedly large unauthenticated response")
        error_code = None
        if response.status == 401:
            value = json.loads(body)
            error_code = value.get("error", {}).get("code")
        return {
            "status": response.status,
            "error_code": error_code,
            "content_type": response.getheader("Content-Type"),
            "sets_cookie": response.getheader("Set-Cookie") is not None,
            "certificate": certificate,
            "sha256": fingerprint,
        }
    finally:
        connection.close()


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", required=True)
    args = parser.parse_args()
    report = {
        "checked_at_utc": datetime.now(timezone.utc).isoformat(),
        "target": IP,
        "direct_connection": True,
        "credentials_or_cookies_used": False,
        "tls_verification_bypassed": False,
        "checks": [],
    }
    try:
        invite = request("/invite")
        if invite["status"] != 200 or "text/html" not in (invite["content_type"] or ""):
            raise AssertionError("Expected public invite HTML with status 200")
        if invite["sets_cookie"]:
            raise AssertionError("Invite GET must not issue an authorization cookie")
        certificate = invite["certificate"]
        if ("IP Address", IP) not in certificate.get("subjectAltName", ()):
            raise AssertionError("Certificate does not contain the exact IP SAN")
        report["certificate"] = {
            "issuer": certificate.get("issuer"),
            "subject_alt_name": certificate.get("subjectAltName"),
            "not_after": certificate.get("notAfter"),
            "sha256": invite["sha256"],
            "validated_against_default_trust_store": True,
        }
        report["checks"].append({"scheme": "https", "path": "/invite", "status": 200})
        # Three denials stay below the gateway's ten-failure rate limit.
        for path in ("/demo2/login", "/api/v1/demo2/auth/me", "/api/v1/demo2/upload/workspace"):
            response = request(path)
            if response["status"] != 401 or response["error_code"] != "invitation_required":
                raise AssertionError("Expected invitation_required without an invitation")
            if response["sets_cookie"]:
                raise AssertionError("Unauthorized request must not grant a cookie")
            report["checks"].append({
                "scheme": "https", "path": path, "status": 401,
                "error_code": response["error_code"],
            })
        for path in ("/", "/invite", "/.well-known/acme-challenge/not-a-real-token"):
            response = request(path, secure=False)
            if response["status"] != 404:
                raise AssertionError("Port 80 must remain ACME-only")
            report["checks"].append({"scheme": "http", "path": path, "status": 404})
        report.update(result="PASS", public_verified=True)
    except Exception as error:
        report.update(
            result="FAIL", public_verified=False,
            failure_type=type(error).__name__, failure_summary=str(error),
        )
    # Response bodies and cookie values are deliberately excluded from evidence.
    with open(args.output, "w", encoding="utf-8") as stream:
        json.dump(report, stream, indent=2, ensure_ascii=True)
        stream.write("\n")
    print(json.dumps(report, ensure_ascii=True))
    return 0 if report["result"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
