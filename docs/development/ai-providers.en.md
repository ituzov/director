# Adding a model provider

In Director, a provider is a profile: how to build a Pydantic AI model, how to
check a key, how to list models, and how to translate errors into our codes.
It gets the key and the address with every call. It doesn't touch the
database, the call log, or the connection card: the `ai` service handles
those.

The code lives in `api/app/ai/providers/`.

## OpenAI-compatible provider

If the provider accepts `chat/completions` and lists models at `/models`
(Timeweb, OpenRouter, vLLM, and Ollama work this way), subclass
`OpenAICompatible`:

```python
class OpenRouterProvider(OpenAICompatible):
    kind = "openrouter"
    default_url = "https://openrouter.ai/api/v1"
```

`kind` is stored in the database (`ai.connection.provider`), so don't change
it after a release.

If `/models` also returns image, speech, or embedding models, override
`keep(raw)` and keep only the text ones. When the response has no field that
tells them apart, it's better to show an extra model than to hide a needed
one: the owner notices an extra model right away but won't notice a missing
one. See `timeweb.py` for an example.

For a server whose address the owner enters, set `needs_base_url = True` and
leave `default_url` unset.

## Provider with its own format

Subclass `Provider`; `anthropic.py` is an example. What to write:

- `model()` builds a Pydantic AI model on top of the `httpx2` client it's
  given. The SDK runs without its own retries (`max_retries=0`): every request
  has to reach the call log, and whoever calls `ai.run` decides whether to
  retry. `model()` makes no network requests.
- `models()` returns the text models. Make the request with `get_json`, which
  translates errors into our codes.
- `check_key()` lists models by default because that's free. Override it if
  the provider charges for the list or doesn't have one.
- Override `error_code(status)` and `error_from(exc)` if the provider doesn't
  follow the general rule below.

## Error codes

The general rule is in `base.error_code`: 401 and 403 become `key_rejected`,
402 `no_funds`, 404 `model_missing`, 429 `rate_limited`, a timeout `timeout`,
and everything else `server`. `key_rejected` and `no_funds` show up on the
connection card; the rest are one-off failures and leave the card as it is.

Check the rule against the provider's docs and a live request. For example,
with Anthropic a 403 on a model call means the key has no access to that
model, not that the key is bad, which is why it has its own `error_from`.

We don't store or log the body of an error response: providers put parts of
the request there, and the request contains people's messages.

## Registry and tests

Add the provider as one line in `REGISTRY` (`providers/__init__.py`). No
migration is needed, and `GET /ai/providers` lists it on its own. The
`test_providers` test in `tests/ai/test_routes.py` checks the whole list, so
add the new kind there.

Write tests following `tests/ai/test_timeweb.py` and `test_anthropic.py`:

- the model list, using a provider response captured from a live request and
  saved in `tests/ai/data/`;
- translating statuses into our codes;
- a call through `ai.run` with a mocked network (`httpx2.MockTransport`),
  including streaming if the provider's SDK streams.
