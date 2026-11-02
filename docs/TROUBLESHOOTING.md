# Troubleshooting

| Symptom | Fix |
|---|---|
| "Not authorised" in the browser | Use the full URL printed by `hearthforge serve` (token changes each launch) |
| Ollama "Cannot connect" | Start Ollama; confirm `http://127.0.0.1:11434` in the provider card |
| "Blocked: cloud mode is Local only" | Intended. Change mode in Models and privacy, and classify the provider |
| "no price is configured" | Budget mode needs a price per model for metered providers (or mark the provider free-tier) |
| "model repeatedly failed to produce a valid JSON action" | Use a larger / coder-tuned model |
| "Command not allowed" | Not on the allowlist; add the executable under Workspace → Extra allowed (shells never allowed) |
| API key won't save | No OS keychain: set `HEARTHFORGE_KEY_<ID>` env var |
| PDF shows "scanned" | The PDF has no text layer. OCR isn't bundled |
| Task stuck "interrupted" | The server restarted; press **Resume** |
| Port in use | `hearthforge serve --port 8800` |
| Model list is empty after connecting | Type the model name yourself in the wizard (gateways often accept `auto` or names not returned by `/models`) |
| "rejected the key" in the wizard | Re-copy the key with no spaces; create a new endpoint key in the service dashboard |
| "doesn't look OpenAI-compatible" | Use the base URL ending in `/v1` |
| Web search: "no parsable results" | DuckDuckGo may be rate-limiting or changed its page; switch engine to Wikipedia or your own SearXNG in Internet |
| "not on the public internet" | By design: the fetch tool refuses localhost/LAN addresses |
| "Pick a project folder inside your home folder" | Choose the project itself, not your whole home folder or a drive root |
