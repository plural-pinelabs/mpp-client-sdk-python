# Pine Labs Online P3P Client SDK (Python)

Python SDK for Pine Labs Online P3P client integrations. It mirrors
`p3p-client-sdk`, intercepts HTTP 402 Payment Required
responses, creates customer-scoped P3P payment credentials, and retries paid
requests.

## Installation

```bash
pip install pinelabs-online-p3p-client-sdk
```

Import module: `pinelabs_p3p_client`. Requires Python 3.9 or newer.

## Quick Start

```python
from pinelabs_p3p_client import (
    ClientRuntimeContext,
    P3PEnvironment,
    PaymentMethod,
    PineLabsOnlineClient,
    PineLabsOnlineClientConfig,
)

client = PineLabsOnlineClient.create(PineLabsOnlineClientConfig(
    env=P3PEnvironment.SANDBOX,
    clientId="client-client-id",
    clientSecret="client-client-secret",
    merchantId="merchant-id",
))

response = client.get(
    "https://server.example.com/api/premium",
    context=ClientRuntimeContext(
        customerReference="9876543210",
        mobileNumber="9876543210",
        paymentMethod=PaymentMethod.RESERVE_PAY,
    ),
)
print(response.json())
client.close()
```

Customer identity and payment method are runtime context, not static SDK config.
This lets one client instance safely serve many customers and payment choices.
`paymentMethod` is required for automatic 402 handling.

By default, the SDK uses client-credentials customer auth: it exchanges
`clientId` and `clientSecret` through `POST /api/auth/v1/token`, then calls
`POST /mpp/v1/token`. `merchantId` is mandatory and is sent as `Merchant-ID`
for token creation across `RESERVE_PAY`, `OTM`, `CARD`, and `CREDIT_EMI`.
The SDK rejects missing MID during construction, before any network call.

For customer API-token flows, explicitly set
`customerAuthMode=P3PCustomerAuthMode.CustomerKey` and pass `customerKey` plus
`mobileNumber` in `ClientRuntimeContext`.

Keep the client SDK instance long-lived in production. Auth tokens are cached
per SDK instance.

## 402 Flow

1. Your code calls `client.get(url, context=...)`.
2. The server returns `HTTP 402` with `WWW-Authenticate: Payment <challenge>`.
3. The SDK decodes the challenge and validates amount, expiry, and accepted payment methods.
4. The SDK creates a token:
   - default mode: `POST /mpp/v1/token` with `Authorization: Bearer <token>`
   - customer-key mode: `POST /api/v1/customer/mpp/token` with `Authorization: Bearer <token>` and `X-Customer-Key`
   - `customer.merchant_customer_reference` and/or `customer.mobile_number`
   - `challenge_id`
   - `payment_amount.value` in minor units
5. The SDK retries the server with `P3P-Credential: Payment <credential>`.
6. The server captures the payment and may return `Payment-Receipt`.

## Direct Token API

```python
from pinelabs_p3p_client import Amount, CreateTokenOptions, PaymentMethod

token = client.methods.create_token(CreateTokenOptions(
    customerReference="9876543210",
    mobileNumber="9876543210",
    challengeId="ch_...",
    paymentAmount=Amount(value=50000, currency="INR"),
    paymentMethod=PaymentMethod.RESERVE_PAY,
))
```

The client SDK no longer creates mandates. Mandate/pre-authorization creation
is handled by the server SDK.

Customer-key mode remains available:

```python
from pinelabs_p3p_client import P3PCustomerAuthMode

customer_key_client = PineLabsOnlineClient.create(PineLabsOnlineClientConfig(
    env=P3PEnvironment.SANDBOX,
    customerAuthMode=P3PCustomerAuthMode.CustomerKey,
    clientId="client-client-id",
    clientSecret="client-client-secret",
    merchantId="merchant-id",
))
```

Timeout and retry settings (`requestTimeoutMs`, `maxRetries`,
`initialRetryDelayMs`) apply to internal P3P calls only. The protected
resource request itself uses the integrator's own HTTP timeout policy.

Environment defaults:

| Env | URL | Timeout | Retries | Initial retry delay |
|---|---|---:|---:|---:|
| `P3PEnvironment.SANDBOX` | `https://pluraluat.v2.pinepg.in` | 60000 ms | 3 | 500 ms |
| `P3PEnvironment.PRODUCTION` | `https://api.pluralpay.in` | 45000 ms | 3 | 500 ms |

## Supported Methods

- `PaymentMethod.RESERVE_PAY` -> `"RESERVE_PAY"` / UPI ReservePay
- `PaymentMethod.OTM` -> `"OTM"`
- `PaymentMethod.CARD` -> `"CARD"`
- `PaymentMethod.Crypto` -> `"CRYPTO"` *(currently rejected by token creation)*

### CARD

Card payments require an active card pre-authorization on the **server** side
(see the Server SDK's `create_pre_authorization`). The Client SDK creates the
token bound to that pre-auth; the Server SDK's debit call then sends
`payment_method_reference_id` = the pre-auth reference id.

```python
response = client.get(
    "https://server.example.com/api/premium",
    context=ClientRuntimeContext(
        customerReference="9876543210",
        mobileNumber="9876543210",
        paymentMethod=PaymentMethod.CARD,
    ),
)
```

## Error Handling

```python
from pinelabs_p3p_client import P3PChallengeError, P3PError, P3PNetworkError

try:
    response = client.get(url, context=runtime_context)
except P3PChallengeError as err:
    ...
except P3PNetworkError as err:
    ...
except P3PError as err:
    print(err.code, err.http_status, err.details)
```

## Grantex (Delegated Agent Authorization)

Set `grantex` in config to attach and optionally verify a Grantex grant token
on every payment request.

```python
from pinelabs_p3p_client import (
    P3PEnvironment,
    PineLabsOnlineClient,
    PineLabsOnlineClientConfig,
)
from pinelabs_p3p_client.types.config import ClientGrantexConfig

client = PineLabsOnlineClient.create(PineLabsOnlineClientConfig(
    env=P3PEnvironment.SANDBOX,
    clientId="...",
    clientSecret="...",
    merchantId="...",
    grantex=ClientGrantexConfig(
        enforceGrant=True,                            # raise before payment if no grant token
        agentId=os.environ.get("GRANTEX_AGENT_ID"),  # optional: assert grant is for this agent
        requiredScopes=["mpp:payment:initiate"],       # optional: assert grant has these scopes
        # baseUrl defaults to https://api.grantex.dev
        # Set only for self-hosted Grantex:
        # baseUrl="https://my-grantex.company.com",
    ),
))
```

The JWKS URI is always `<baseUrl>/.well-known/jwks.json`. The path is constant;
only the base URL changes for self-hosted deployments.

| Setting | JWKS endpoint |
|---------|---------------|
| `baseUrl` not set | `https://api.grantex.dev/.well-known/jwks.json` |
| `baseUrl="https://my-grantex.co"` | `https://my-grantex.co/.well-known/jwks.json` |
| `jwksUri="https://..."` | That exact URL (takes precedence over `baseUrl`) |

Pass the grant token per request:

```python
response = client.get(
    url,
    context=ClientRuntimeContext(
        mobileNumber="9876543210",
        paymentMethod=PaymentMethod.RESERVE_PAY,
        grantexToken=user_grant_token,   # per-request grant token
    ),
)
```

## License

MIT
