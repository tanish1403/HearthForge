"use strict";
// Single source of truth for the in-app Guide AND docs/GUIDE.md (scripts/build_guide_md.mjs).
// Text uses `code` and **bold** only. Provider facts were checked against public docs when written;
// model names, prices and free tiers change, so always confirm with the provider.
const GUIDE = [
  { id: "start", title: "Start here (3 minutes)", steps: [
    "**Connect a model**: click *Connect a model* (top bar or Home). Paste the service URL and key, press *Connect and find models*, pick a model. Hearthforge sends a test message so you know it works.",
    "**Open a folder** (optional for chat, needed for the agent): click *Open a folder*, browse to your project, press *Select this folder*.",
    "**Use it**: *Chat* for questions, *Agent* to let it read, edit and test your project with your approval.",
    "Nothing leaves your machine unless you connect a remote service or turn on Internet. The top bar always shows the current privacy state.",
  ] },
  { id: "models", title: "Connect a model", intro: "Open **Connect a model**, choose a preset (it fills the URL for you), add a key if the service needs one, then *Connect and find models*. If the model list is empty you can type the model name yourself.", subs: [
    { title: "Ollama (local, free, private)", steps: [
      "Install Ollama from ollama.com and start it. Download a model in a terminal, e.g. `ollama pull qwen2.5-coder:7b` (check the Ollama library for current names and sizes).",
      "Connect a model → preset **Ollama** → URL `http://127.0.0.1:11434`. No key needed.",
      "Pick a model that fits your RAM/VRAM: see *Hardware fit*.",
    ] },
    { title: "llama.cpp server (local)", steps: [
      "Start it: `llama-server -m path/to/model.gguf --port 8080`.",
      "Preset **llama.cpp** → URL `http://127.0.0.1:8080/v1`. The server hosts one model; choose whatever name it lists.",
    ] },
    { title: "LM Studio (local)", steps: [
      "In LM Studio load a model and start the *Local Server*.",
      "Preset **LM Studio** → URL `http://127.0.0.1:1234/v1`.",
    ] },
    { title: "OmniRoute (gateway)", steps: [
      "OmniRoute is a gateway with one OpenAI-compatible endpoint in front of many providers. Its default local address is `http://localhost:20128/v1`; a hosted copy looks like `https://your-domain/v1`.",
      "In the OmniRoute dashboard create an **API key / endpoint key** for the gateway and copy it.",
      "Connect a model → preset **OmniRoute** → paste the URL and the key. If you paste the root URL without `/v1`, Hearthforge tries `/v1` for you.",
      "Model names are what the gateway lists, e.g. `auto` or `provider/model`. If the list is empty, type the name from your dashboard.",
      "A local OmniRoute counts as local (loopback). A hosted one is remote, so you'll be asked to confirm and tell Hearthforge whether it is free or paid.",
    ] },
    { title: "OpenRouter", steps: [
      "Create a key at openrouter.ai (Keys). Preset **OpenRouter** → URL `https://openrouter.ai/api/v1`.",
      "Model ids look like `vendor/model`. Some have free variants; check their site for current free models and limits.",
    ] },
    { title: "Groq", steps: [
      "Create a key in the Groq console. Preset **Groq** → URL `https://api.groq.com/openai/v1`. Choose a model from the list (names and free limits change; check Groq's docs).",
    ] },
    { title: "Google Gemini (OpenAI-compatible)", steps: [
      "Create a key in Google AI Studio. Preset **Gemini** → URL `https://generativelanguage.googleapis.com/v1beta/openai/`.",
    ] },
    { title: "Hugging Face router", steps: [
      "Create a token in your Hugging Face settings. Preset **Hugging Face** → URL `https://router.huggingface.co/v1`.",
    ] },
    { title: "Any other OpenAI-compatible service", steps: [
      "Use preset **Custom**. You need the **base URL** (usually ends in `/v1`), an **API key** if required and a **model name**. Test with `curl BASEURL/models -H \"Authorization: Bearer KEY\"` if unsure.",
    ] },
    { title: "If connecting fails", steps: [
      "**\"Nothing is listening\"**: the service isn't running or the port is wrong.",
      "**\"rejected the key\"**: re-copy the key without spaces, or create a new one.",
      "**\"doesn't look OpenAI-compatible\"**: the base URL usually must end in `/v1`.",
      "**Blocked by privacy mode**: remote services need your confirmation in the wizard; it then switches the privacy mode for you and says so.",
      "**Key can't be saved**: if the OS keychain is unavailable the key is kept only until you quit. For permanent use set the environment variable shown in the wizard.",
    ] },
  ] },
  { id: "privacy", title: "Privacy modes", steps: [
    "**Local only** (default): only models on this computer. Remote services are blocked.",
    "**Free tier only**: remote services you marked *free* are allowed. You declare free status; Hearthforge can't verify it.",
    "**Budgeted cloud**: any connected remote service. Set monthly/task budgets in *Models*; costs are shown only where you entered a price.",
    "The wizard raises the mode only as far as needed and tells you. You can change it any time in *Models*.",
  ] },
  { id: "folders", title: "Open a project folder", steps: [
    "Click **Open a folder** (Home, Agent or Folders). Use the shortcuts (Home, Desktop…) or the path box, then click folders to go inside.",
    "Folders with a Git/package marker show a *project* badge. **New folder** creates one.",
    "Press **Select this folder**. You can't pick your whole home folder or a drive root: pick the project itself.",
    "You can paste a path with quotes (`\"C:\\Projects\\app\"`), `~` or `%USERPROFILE%`; they are cleaned up.",
    "Each folder has its own permissions under **Folders** (Careful, Balanced, Hands-off presets).",
  ] },
  { id: "chat", title: "Chat", steps: [
    "Type a question and press **Enter** (Shift+Enter for a new line). Replies stream in and code blocks have a Copy button.",
    "Toggle **Web** to search the internet first and answer with numbered sources (needs Internet on).",
    "Toggle **Project** to include matching excerpts from your indexed project (index it under *Knowledge*).",
    "Press **Stop** to cancel. **Clear** starts over. Chat history is kept in this browser only.",
  ] },
  { id: "agent", title: "Agent: let it work on your project", steps: [
    "Choose the folder, write the goal, pick **Plan** (read-only investigation) or **Build** (edits and tests), press *Start*.",
    "The **rail** shows each step. An amber **gate** means the agent is waiting for you: review the diff or command, then *Approve* or *Reject* (your feedback goes to the agent).",
    "Open the **Changes** tab to read every diff and **Undo** any change. **Checks** lists the tests/lints it ran.",
    "The final badge is computed from evidence: **Verified** (tests passed after the last edit), **Not verified** (changes but no passing check), **Failed**.",
    "Cancel any time. A stopped or interrupted task can be **Resumed**.",
    "Small local models may fail to follow the strict JSON format; use a larger or coder-tuned model if the task says so.",
  ] },
  { id: "internet", title: "Internet (search and web pages)", steps: [
    "Open **Internet**. Choose **Off** (default), **Ask each time** (the agent asks before every search/fetch) or **On**.",
    "Pick a search engine: DuckDuckGo (no key; unofficial page parsing so it can break or rate-limit), Wikipedia (reliable, encyclopedic) or your own SearXNG (best; enable its JSON format).",
    "Press **Test search** to verify the connection from your machine.",
    "The agent can then use `web_search` and `web_fetch`; chat uses the **Web** toggle.",
    "Safety: pages are plain text only, size-limited, and addresses on your own network or computer (localhost, 192.168.x.x, cloud metadata) are always refused. Page text is untrusted data and cannot give the agent orders.",
    "Privacy: your search words go to the search engine. Keep Internet off for sensitive work.",
  ] },
  { id: "knowledge", title: "Knowledge and memory", steps: [
    "**Knowledge → Index this workspace** builds a local keyword index (PDF, DOCX, XLSX, PPTX, CSV, code, text). Re-index after big changes. Secrets files are never indexed.",
    "Search shows excerpts with file and line/page. **Exclude** removes a document; **Delete index** removes everything.",
    "**Memory** holds short notes the agent can recall later (credentials are refused). Edit, forget or export them.",
    "Vector search and OCR are not implemented yet.",
  ] },
  { id: "caps", title: "Capabilities and plugins", steps: [
    "**Capabilities** turns features on or off. A disabled one disappears from the agent. *Planned* items are not built yet and can't be enabled.",
    "A **plugin** is a JSON file that maps a tool name to a fixed command (no shell). Paste it under *Capabilities → Add plugin*; remove it with the Remove button.",
  ] },
  { id: "perms", title: "Permissions", steps: [
    "Per folder, each level is **allow**, **ask** or **deny**: read, write, exec (run commands), network, install, destructive.",
    "Presets: **Careful** asks before edits and commands; **Balanced** asks before edits but auto-runs recognised test/lint commands; **Hands-off** applies edits and runs commands automatically (changes are still snapshotted and undoable).",
    "Commands run with your user rights. Keep *Careful* for code you don't trust.",
  ] },
  { id: "hardware", title: "Hardware and local models", steps: [
    "**Hardware fit** estimates which model sizes fit your RAM and GPU (±40%). Nothing is downloaded automatically.",
    "As a guide, 4 GB of GPU memory suits ~3B models; 7B runs with CPU help. More memory allows larger models.",
  ] },
  { id: "keys", title: "Shortcuts and FAQ", steps: [
    "**Ctrl/Cmd + K** opens the command palette: switch model, open a folder, new chat, go anywhere.",
    "**Why does it say \"blocked\"?** The privacy mode forbids that action; the message says which setting to change.",
    "**Where is my data?** Settings, indexes, snapshots and the audit log live in your app-data folder (`%APPDATA%\\hearthforge` on Windows). Delete it to reset everything.",
    "**Usage and audit** shows token counts (reported vs estimated) and a log of approvals and policy changes.",
  ] },
];
