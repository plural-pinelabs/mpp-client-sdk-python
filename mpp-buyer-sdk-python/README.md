# plural-mpp-buyer-sdk (Python)

Python port of [`@plural/mpp-buyer-sdk`](../mpp-buyer-sdk). x402 Machine
Payments Protocol client for AI agents.

Automatically intercepts HTTP 402 Payment Required responses, constructs
UPI SBMD credentials, and completes the payment flow — zero manual
payment handling required.

## Installation

```bash
pip install plural-mpp-buyer-sdk
# or from source
cd mpp-buyer-sdk-python
pip install -e .
```

Requires Python ≥ 3.9. Depends on `httpx` and `PyJWT[crypto]`.

## Quick Start

```python
from plural_mpp_buyer import PluralBuyer, PluralBuyerConfig, MppEnvironment

buyer = PluralBuyer.create(PluralBuyerConfig(
    clientId="your-client-id",
    clientSecret="your-client-secret",
    baseUrl=MppEnvironment.SANDBOX,  # or MppEnvironment.PRODUCTION
))

# `buyer.get` / `buyer.post` / `buyer.request` intercept 402s automatically.
response = buyer.get("https://api.example.com/paid-resource")
print(response.json())

buyer.close()
```

`PluralBuyer.create(...)` supports context-manager usage to release the
underlying HTTP client:

```python
with PluralBuyer.create(config) as buyer:
    response = buyer.get(url)
```

## Configuration

```python
from plural_mpp_buyer import (
    PluralBuyer, PluralBuyerConfig, TokenDefaults,
    GrantexConfig, JwksConfig, MppEnvironment,
)

buyer = PluralBuyer.create(PluralBuyerConfig(
    clientId="…", clientSecret="…",

    baseUrl=MppEnvironment.SANDBOX,
    autoHandlePayment=True,

    requestTimeoutMs=30_000,
    maxRetries=3,
    initialRetryDelayMs=500,

    onChallenge=lambda challenge: None,
    onPaymentComplete=lambda receipt: None,

    tokenDefaults=TokenDefaults(maxCharges=10, ttlSeconds=3600),

    grantex=GrantexConfig(
        grantToken="eyJ…",
        jwks=JwksConfig(jwksUrl="https://grantex.dev/.well-known/jwks.json"),
        agentId="my-agent",
        enforceSpendingLimits=True,
    ),
))
```

## How the 402 flow works

1. Your code calls `buyer.get(url)` (or any HTTP method).
2. If the server returns **HTTP 402** with a `WWW-Authenticate: Payment <challenge>` header, the SDK:
   - decodes the challenge,
   - creates a one-time UPI SBMD payment token,
   - builds a credential,
   - retries the request with `Authorization: Payment <credential>`.
3. The server captures the payment and returns **HTTP 200** with a `Payment-Receipt` header.
4. Your code receives the final 200 response transparently.

## API

### `PluralBuyer.create(config)`  /  `PluralBuyer.create_verified(config)`

`create_verified` additionally verifies the Grantex grant token before returning.

### `PluralBuyerInstance`

| Attribute | Description |
|---|---|
| `get`, `post`, `put`, `delete`, `patch`, `request`, `fetch` | HTTP methods with 402 interception |
| `raw_http` | Underlying `httpx.Client` (no interception) |
| `methods.create_mandate(...)` / `.get_mandate(...)` / `.create_token(...)` | Direct MPP API ops |
| `create_credential(challenge)` | Manually build a credential |
| `grant_claims` / `verify_grant()` | Grantex helpers |
| `close()` / context manager | Close the HTTP client |

## Utilities

```python
from plural_mpp_buyer import decode_challenge, decode_receipt, validate_challenge

challenge = decode_challenge(www_authenticate_header)
validate_challenge(challenge)
receipt = decode_receipt(payment_receipt_header)
```

## Error handling

```python
from plural_mpp_buyer import MppError, MppNetworkError, MppChallengeError

try:
    response = buyer.get(url)
except MppChallengeError as err:
    ...
except MppNetworkError as err:
    ...
except MppError as err:
    print(err.code, err.http_status, err.details)
```

## Grantex (AI Agent Authorization)

```python
from plural_mpp_buyer import (
    PluralBuyer, PluralBuyerConfig, GrantexConfig, JwksConfig,
    check_payment_authorization, extract_spending_limit, has_scope, parse_scope,
)

buyer = PluralBuyer.create_verified(PluralBuyerConfig(
    clientId="…", clientSecret="…",
    grantex=GrantexConfig(
        grantToken=grant_token,
        jwks=JwksConfig(jwksUrl="https://grantex.dev/.well-known/jwks.json"),
    ),
))

print(buyer.grant_claims)  # GrantTokenClaims(...)
```

## License

MIT
