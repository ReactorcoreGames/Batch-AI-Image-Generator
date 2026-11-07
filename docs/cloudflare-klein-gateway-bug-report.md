## What is the name of the model you're running?

`@cf/black-forest-labs/flux-2-klein-4b` (the same applies to `@cf/black-forest-labs/flux-2-klein-9b` — both FLUX.2 klein models take multipart/form-data)

## What is the error number?

`7000` (HTTP 500) on the multipart request.

Also relevant, as the other half of the contradiction: `5006` (HTTP 400).

## What is the error message?

With a `multipart/form-data` body:

```json
{"errors":[{"message":"Invalid request body","code":7000}],"success":false,"result":{},"messages":[]}
```

With a JSON body (same endpoint, same header):

```json
{"errors":[{"message":"AiError: Bad input: Error: required properties at '/' are 'multipart' (39d38831-08d1-4438-975b-1d845b4ce934)","code":5006}],"success":false,"result":{},"messages":[]}
```

## What is the issue or error you're encountering

**The FLUX.2 klein models cannot be routed through AI Gateway, because the two encoding requirements contradict each other.**

`@cf/black-forest-labs/flux-2-klein-4b` requires a `multipart/form-data` body — that is the model's documented schema, and a JSON body is rejected with `5006 "required properties at '/' are 'multipart'"`.

But when the `cf-aig-gateway-id` header is added, a `multipart/form-data` body is rejected with `7000 "Invalid request body"`. The gateway path appears to accept JSON only.

So:

- multipart **without** the gateway header → works (billed to the daily neuron allowance)
- multipart **with** the gateway header → `7000 Invalid request body`
- JSON **with** the gateway header → `5006 ... are 'multipart'`

There is no body encoding that both the model and the gateway will accept, so these models cannot be used with Unified Billing at all.

This is specific to the multipart models. **JSON-bodied Workers AI models route through the gateway correctly** — I verified `@cf/bytedance/stable-diffusion-xl-lightning` returns HTTP 200 and a valid image through the same header, on the same account and token, and correctly billed to prepaid credit. So the gateway, the credentials, the token permissions and the `unified` billing mode are all confirmed working. It is only the multipart request encoding that fails.

The practical impact is that `flux-2-klein-4b` is the most cost-effective image model in the Workers AI catalogue, and it is the one model that cannot be reached once the daily free neuron allocation is used up, despite having prepaid credit available specifically to cover that case.

The docs at developers.cloudflare.com/ai-gateway/usage/rest-api/ state "Workers AI requests always require this header", with no exception noted for multipart models, so I believe this is a gap rather than intended behaviour.

## What steps have you taken to resolve the issue?

- Confirmed the gateway exists and is correctly configured: `GET /accounts/{account_id}/ai-gateway/gateways/default` returns `"workers_ai_billing_mode": "unified"` and `"is_default": true`.
- Confirmed prepaid credit is loaded and that unified billing works in general — the same header on `@cf/bytedance/stable-diffusion-xl-lightning` (a JSON-bodied model) returns HTTP 200 with a valid 1024x576 image, after that same model had been returning `4006` neuron-exhaustion errors immediately beforehand. This isolates the failure to the multipart encoding rather than to the account, token or gateway.
- Tried both ways of sending multipart from an HTTP client: an implicitly-encoded form body, and an explicitly-bounded `multipart/form-data` body. Both return `7000`.
- Tried the bare `/ai/run` endpoint with the model id in the request body (`{"model": ..., "input": {...}}`) instead of the URL path. With JSON this returns the same `5006 ... are 'multipart'`; with a multipart body it returns `6003 "Request body is not valid json"`.
- Confirmed the model itself is healthy — the identical multipart body succeeds on the same URL when the `cf-aig-gateway-id` header is simply removed (billing to neurons rather than credit).

## What are the steps to reproduce the issue?

Account has prepaid AI Gateway credit and the `default` gateway set to `workers_ai_billing_mode: unified`.

**1. Multipart + gateway header → `7000` (the bug):**

```bash
curl -X POST \
  "https://api.cloudflare.com/client/v4/accounts/$ACCOUNT_ID/ai/run/@cf/black-forest-labs/flux-2-klein-4b" \
  -H "Authorization: Bearer $API_TOKEN" \
  -H "cf-aig-gateway-id: default" \
  -F "prompt=a red cube on a white table" \
  -F "width=1536" -F "height=864" -F "seed=4242"
```

Returns HTTP 500, `{"code":7000,"message":"Invalid request body"}`.

**2. JSON + gateway header → `5006` (shows multipart is mandatory):**

```bash
curl -X POST \
  "https://api.cloudflare.com/client/v4/accounts/$ACCOUNT_ID/ai/run/@cf/black-forest-labs/flux-2-klein-4b" \
  -H "Authorization: Bearer $API_TOKEN" \
  -H "cf-aig-gateway-id: default" \
  -H "Content-Type: application/json" \
  -d '{"prompt":"a red cube on a white table","width":1536,"height":864,"seed":4242}'
```

Returns HTTP 400, `{"code":5006,"message":"... required properties at '/' are 'multipart'"}`.

**3. Control — remove the header and the same multipart body works:**

```bash
curl -X POST \
  "https://api.cloudflare.com/client/v4/accounts/$ACCOUNT_ID/ai/run/@cf/black-forest-labs/flux-2-klein-4b" \
  -H "Authorization: Bearer $API_TOKEN" \
  -F "prompt=a red cube on a white table" \
  -F "width=1536" -F "height=864" -F "seed=4242"
```

Returns HTTP 200 and an image (or `4006` if the daily neuron allowance is exhausted — which is the situation that makes this a problem).

**4. Control — a JSON model routes through the gateway fine:**

```bash
curl -X POST \
  "https://api.cloudflare.com/client/v4/accounts/$ACCOUNT_ID/ai/run/@cf/bytedance/stable-diffusion-xl-lightning" \
  -H "Authorization: Bearer $API_TOKEN" \
  -H "cf-aig-gateway-id: default" \
  -H "Content-Type: application/json" \
  -d '{"prompt":"a red cube on a white table","width":1024,"height":576,"num_steps":8,"seed":4242}'
```

Returns HTTP 200 and a valid image, billed to prepaid credit.

### Request identifiers

| Case | cf-ray | requestId |
|---|---|---|
| multipart (implicit) + header → 7000 | `a384c8650aaf266f-HEL` | — |
| multipart (explicit boundary) + header → 7000 | `a384c8686f7ba1a0-HEL` | — |
| JSON `{model,input}` + header → 5006 | — | `39d38831-08d1-4438-975b-1d845b4ce934` |
| JSON on model path + header → 5006 | — | `1a0241e6-eb89-4c2a-9884-d1a84e82e21a` |

The `7000` responses carry no `requestId` in the body, which is itself a small papercut for reporting — only the `cf-ray` is available. All of the above were captured within the last hour (2026-09-09, UTC+3).
