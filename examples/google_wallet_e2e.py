"""Exercise the local Buyer and Seller SDK sources against MPP.

This script does not import an installed wheel. It loads both SDK source trees
directly, so the Wallet changes can be tested before publishing packages.

Required environment variables for the deployed service:
    MPP_BASE_URL              default: https://nxt-mpp-service-dev.v2.pinepg.in
    MPP_CLIENT_ID
    MPP_CLIENT_SECRET
    MPP_MERCHANT_ID
    MPP_MOBILE_NUMBER         default: 10-digit test customer number

The script creates a Wallet pre-authorization and prints the hosted Google Pay
URL. Complete that authorization in the browser, then press Enter to mint a
Buyer token and debit it through the Seller SDK.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path


BUYER_ROOT = Path(__file__).resolve().parents[1]
SELLER_ROOT = Path("/Users/namanpandey/Documents/GitHub/mpp-seller-sdk-python")
sys.path.insert(0, str(BUYER_ROOT / "src"))
sys.path.insert(0, str(SELLER_ROOT / "src"))

from pinelabs_p3p_client import (  # noqa: E402
    Amount as BuyerAmount,
    CreateTokenOptions,
    P3PEnvironment,
    PaymentMethod as BuyerPaymentMethod,
    PineLabsOnlineClient,
    PineLabsOnlineClientConfig,
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


def main() -> None:
    base_url = os.getenv("MPP_BASE_URL", "https://nxt-mpp-service-dev.v2.pinepg.in")
    client_id = _required_env("MPP_CLIENT_ID")
    client_secret = _required_env("MPP_CLIENT_SECRET")
    merchant_id = _required_env("MPP_MERCHANT_ID")
    mobile_number = os.getenv("MPP_MOBILE_NUMBER", "9876543210")
    amount_value = int(os.getenv("MPP_AMOUNT_PAISE", "10000"))
    preauth_key = os.getenv("MPP_PREAUTH_IDEMPOTENCY_KEY", "local-google-wallet-preauth-001")
    debit_key = os.getenv("MPP_DEBIT_IDEMPOTENCY_KEY", "local-google-wallet-debit-001")
    challenge_id = os.getenv("MPP_CHALLENGE_ID", "local-google-wallet-challenge-001")

    seller = PineLabsOnlineP3P.create(PineLabsOnlineServerConfig(
        env=base_url,
        clientId=client_id,
        clientSecret=client_secret,
        merchantId=merchant_id,
        paymentGateway=PaymentGateway.PineLabsOnline,
        availablePaymentMethods=[SellerPaymentMethod.WALLET],
        maxRetries=0,
    ))

    print("Creating WALLET / GOOGLE_PAY pre-authorization...")
    preauth = seller.create_pre_authorization(CreatePreAuthorizationOptions(
        paymentMethod=SellerPaymentMethod.WALLET,
        paymentMethodOptions={"wallet_code": "GOOGLE_PAY"},
        mobileNumber=mobile_number,
        amount=SellerAmount(value=amount_value, currency="INR"),
        validityInDays=int(os.getenv("MPP_VALIDITY_DAYS", "4")),
        idempotencyKey=preauth_key,
    ))
    print(f"authorization_id={preauth.payment_method_reference_id}")
    print(f"status={preauth.status}")
    print(f"challenge_url={preauth.challenge_url or preauth.redirect_url}")

    input("Complete Google Pay authorization, then press Enter to continue...")

    buyer = PineLabsOnlineClient.create(PineLabsOnlineClientConfig(
        env=base_url,
        clientId=client_id,
        clientSecret=client_secret,
        merchantId=merchant_id,
        maxRetries=0,
    ))
    try:
        token = buyer.methods.create_token(CreateTokenOptions(
            mobileNumber=mobile_number,
            challengeId=challenge_id,
            paymentAmount=BuyerAmount(value=amount_value, currency="INR"),
            paymentMethod=BuyerPaymentMethod.WALLET,
            paymentMethodReferenceId=preauth.payment_method_reference_id,
        ))
    finally:
        buyer.close()

    print(f"payment_token={token.token}")
    print(f"token_payment_method={token.payment_method}")
    print(f"token_authorization_id={token.mandate_id}")

    result = seller.capture(CaptureOptions(
        token=token.token,
        amount=SellerAmount(value=amount_value, currency="INR"),
        paymentMethod=SellerPaymentMethod.WALLET,
        paymentMethodReferenceId=preauth.payment_method_reference_id,
        mobileNumber=mobile_number,
        challengeId=challenge_id,
        idempotencyKey=debit_key,
    ))
    print(f"debit_status={result.get('status')}")
    print(f"debit_reference={result.get('merchant_payment_debit_reference')}")


def _required_env(name: str) -> str:
    value = os.getenv(name, "").strip()
    if not value:
        raise SystemExit(f"Set {name} before running this integration test")
    return value


if __name__ == "__main__":
    main()
