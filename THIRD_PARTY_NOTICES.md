# Third-party notices

Hearthforge depends on the following packages at runtime. Verify licences yourself with `pip-licenses` before each release;
this list was written from package metadata knowledge, not from an automated scan.

| Package | Role | Licence (as generally published) |
|---|---|---|
| FastAPI / Starlette | HTTP server | MIT / BSD-3-Clause |
| Uvicorn | ASGI server | BSD-3-Clause |
| httpx | HTTP client | BSD-3-Clause |
| Pydantic | Validation | MIT |
| psutil | Hardware detection | BSD-3-Clause |
| keyring | OS credential store | MIT |
| pypdf (optional) | PDF text extraction | BSD-3-Clause |

Dev only: pytest, pytest-asyncio, ruff, build, hatchling.
The UI uses no third-party JavaScript, fonts or images.
