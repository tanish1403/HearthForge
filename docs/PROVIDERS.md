# Providers

All providers are configured in **Models and privacy**. Locality is derived from the URL.

| Provider | Kind | Base URL | Notes |
|---|---|---|---|
| Ollama | `ollama` | `http://127.0.0.1:11434` | Native API: model discovery, capability reporting via `/api/show`, token counts |
| llama.cpp server | `openai_compat` | `http://127.0.0.1:8080/v1` | Start `llama-server -m model.gguf`; one model per server |
| LM Studio | `openai_compat` | `http://127.0.0.1:1234/v1` | Enable the local server in LM Studio |
| OmniRoute (gateway) | `openai_compat` | `http://localhost:20128/v1` (default per its docs) or your hosted `https://<domain>/v1` | Use an endpoint API key from its dashboard; models are whatever it lists (e.g. `auto`, `provider/model`). Local copies count as local; hosted copies are remote |
| OpenRouter / Groq / Gemini (OpenAI-compat) / Hugging Face router | `openai_compat` | presets in the UI | **Presets only.** Confirm endpoint paths, model ids and free-tier terms in each provider's current documentation. They were not contacted during development |
| Custom | `openai_compat` | your URL | Any server implementing `/models` and streaming `/chat/completions` |

See [GUIDE.md](GUIDE.md) for click-by-click recipes. Other aggregator or "free LLM API" sites are *not* presets: verify the exact service and its API contract first,
then add it as a Custom provider. Unknown services start as cost class `unknown` and are blocked in free/budget modes until you classify them.

## Keys
Saved to the OS keychain (Windows Credential Manager, macOS Keychain, Secret Service/KWallet). Or set `HEARTHFORGE_KEY_<ID>`.

## Capabilities detection
Ollama reports capabilities (`vision`, `tools`…). For other servers you can declare `vision_models` / `tool_models` on the provider; declared
capabilities are labelled *(declared)* in the UI. Images are only sent to models known or declared to support vision.

## Errors
Normalised kinds: `auth`, `rate_limit` (retried up to 2×, honouring Retry-After capped at 10 s), `timeout`, `unreachable`, `not_found`,
`bad_request`, `server`, `policy` (blocked locally, never sent).
