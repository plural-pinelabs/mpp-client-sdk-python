"""Run a local merchant website for manually exercising the Wallet flow.

The browser only talks to this local server. Client credentials stay in the
server process and both SDKs are imported directly from their source trees.
"""

from __future__ import annotations

import json
import os
import sys
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlparse

BUYER_ROOT = Path(__file__).resolve().parents[1]
SELLER_ROOT = Path("/Users/namanpandey/Documents/GitHub/mpp-seller-sdk-python")
sys.path.insert(0, str(BUYER_ROOT / "src"))
sys.path.insert(0, str(SELLER_ROOT / "src"))

from pinelabs_p3p_client import (  # noqa: E402
    Amount as BuyerAmount,
    CreateTokenOptions,
    PineLabsOnlineClient,
    PineLabsOnlineClientConfig,
    PaymentMethod as BuyerPaymentMethod,
)
from pinelabs_p3p_server import (  # noqa: E402
    Amount as SellerAmount,
    CaptureOptions,
    CreatePreAuthorizationOptions,
    PaymentGateway,
    PaymentMethod as SellerPaymentMethod,
    PineLabsOnlineP3P,
    PineLabsOnlineServerConfig,
)

BASE_URL = os.getenv("MPP_BASE_URL", "https://nxt-mpp-service-dev.v2.pinepg.in")
CLIENT_ID = os.getenv("MPP_CLIENT_ID", "")
CLIENT_SECRET = os.getenv("MPP_CLIENT_SECRET", "")
MERCHANT_ID = os.getenv("MPP_MERCHANT_ID", "")
STATE: dict[str, str] = {}


def seller():
    return PineLabsOnlineP3P.create(PineLabsOnlineServerConfig(
        env=BASE_URL,
        clientId=CLIENT_ID,
        clientSecret=CLIENT_SECRET,
        merchantId=MERCHANT_ID,
        paymentGateway=PaymentGateway.PineLabsOnline,
        availablePaymentMethods=[SellerPaymentMethod.CARD, SellerPaymentMethod.WALLET],
        maxRetries=0,
    ))


class Handler(BaseHTTPRequestHandler):
    def do_GET(self):  # noqa: N802
        if urlparse(self.path).path in ("/", "/index.html"):
            self._send(200, (Path(__file__).with_name("google_wallet_demo.html")).read_bytes(), "text/html")
        else:
            self._send(404, b"Not found", "text/plain")

    def do_POST(self):  # noqa: N802
        try:
            body = self._body()
            path = urlparse(self.path).path
            if path == "/api/preauthorize":
                result = self._preauthorize(body)
            elif path == "/api/token":
                result = self._token(body)
            elif path == "/api/debit":
                result = self._debit(body)
            else:
                self._send_json(404, {"error": "Not found"})
                return
            self._send_json(200, result)
        except Exception as exc:  # demo server: surface SDK/backend errors in the UI
            self._send_json(500, {"error": str(exc), "type": type(exc).__name__})

    def _preauthorize(self, body):
        mobile = body["mobile_number"]
        amount = int(body["amount_paise"])
        method = SellerPaymentMethod(body.get("payment_method", "WALLET"))
        options = {"wallet_code": "GOOGLE_PAY"} if method == SellerPaymentMethod.WALLET else None
        result = seller().create_pre_authorization(CreatePreAuthorizationOptions(
            paymentMethod=method,
            paymentMethodOptions=options,
            mobileNumber=mobile,
            amount=SellerAmount(value=amount, currency="INR"),
            validityInDays=int(body.get("validity_days", 4)),
            idempotencyKey=body.get("idempotency_key") or "local-google-wallet-preauth",
        ))
        STATE.update({"mobile": mobile, "amount": str(amount), "reference_id": result.payment_method_reference_id, "payment_method": method.value})
        return {
            "status": result.status,
            "payment_method_reference_id": result.payment_method_reference_id,
            "challenge_url": result.challenge_url or result.redirect_url,
            "raw": result.raw,
        }

    def _token(self, body):
        mobile = body.get("mobile_number") or STATE["mobile"]
        amount = int(body.get("amount_paise") or STATE["amount"])
        client = PineLabsOnlineClient.create(PineLabsOnlineClientConfig(
            env=BASE_URL, clientId=CLIENT_ID, clientSecret=CLIENT_SECRET, merchantId=MERCHANT_ID, maxRetries=0,
        ))
        try:
            result = client.methods.create_token(CreateTokenOptions(
                mobileNumber=mobile,
                challengeId=body["challenge_id"],
                paymentAmount=BuyerAmount(value=amount, currency="INR"),
                paymentMethod=BuyerPaymentMethod(STATE["payment_method"]),
                paymentMethodReferenceId=STATE["reference_id"],
            ))
        finally:
            client.close()
        STATE["token"] = result.token
        return {"token": result.token, "mandate_id": result.mandate_id, "payment_method": str(result.payment_method)}

    def _debit(self, body):
        amount = int(body.get("amount_paise") or STATE["amount"])
        result = seller().capture(CaptureOptions(
            token=STATE["token"],
            amount=SellerAmount(value=amount, currency="INR"),
            paymentMethod=SellerPaymentMethod(STATE["payment_method"]),
            paymentMethodReferenceId=STATE["reference_id"],
            mobileNumber=body.get("mobile_number") or STATE["mobile"],
            challengeId=body["challenge_id"],
            idempotencyKey=body.get("idempotency_key") or "local-google-wallet-debit",
        ))
        return dict(result)

    def _body(self):
        length = int(self.headers.get("Content-Length", "0"))
        return json.loads(self.rfile.read(length) or b"{}")

    def _send_json(self, code, value):
        self._send(code, json.dumps(value, default=str).encode(), "application/json")

    def _send(self, code, data, content_type):
        self.send_response(code)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def log_message(self, format, *args):
        return


if __name__ == "__main__":
    missing = [name for name, value in (("MPP_CLIENT_ID", CLIENT_ID), ("MPP_CLIENT_SECRET", CLIENT_SECRET), ("MPP_MERCHANT_ID", MERCHANT_ID)) if not value]
    if missing:
        raise SystemExit("Set these environment variables first: " + ", ".join(missing))
    port = int(os.getenv("MPP_DEMO_PORT", "8765"))
    print(f"Open http://127.0.0.1:{port}  (MPP: {BASE_URL})")
    ThreadingHTTPServer(("127.0.0.1", port), Handler).serve_forever()
