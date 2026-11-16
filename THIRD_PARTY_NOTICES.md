# Third-Party Notices

OpenTalos is distributed under the Apache License 2.0. Release bundles also
contain the following third-party software and assets. The bundled license
files and the upstream projects remain the authoritative license texts.

## Desktop and Backend

| Component | License | Project |
| --- | --- | --- |
| Python | PSF License 2.0 | https://www.python.org/ |
| PyInstaller | GPL-2.0-or-later with a special exception for distributing bundled applications | https://pyinstaller.org/ |
| pywebview | BSD-3-Clause | https://pywebview.flowrl.com/ |
| pystray | LGPL-3.0 | https://github.com/moses-palmer/pystray |
| Pillow | HPND | https://python-pillow.org/ |
| cryptography | Apache-2.0 OR BSD-3-Clause | https://cryptography.io/ |
| FastAPI | MIT | https://fastapi.tiangolo.com/ |
| Uvicorn | BSD-3-Clause | https://www.uvicorn.org/ |
| Pydantic | MIT | https://docs.pydantic.dev/ |
| OpenAI Python SDK | Apache-2.0 | https://github.com/openai/openai-python |
| Anthropic Python SDK | MIT | https://github.com/anthropics/anthropic-sdk-python |
| HTTPX | BSD-3-Clause | https://www.python-httpx.org/ |
| tiktoken | MIT | https://github.com/openai/tiktoken |
| PyYAML | MIT | https://pyyaml.org/ |

## Web Runtime

| Component | License | Project |
| --- | --- | --- |
| Node.js | MIT and bundled third-party licenses | https://nodejs.org/ |
| Next.js | MIT | https://nextjs.org/ |
| React and React DOM | MIT | https://react.dev/ |
| TanStack React Virtual | MIT | https://tanstack.com/virtual |
| react-markdown | MIT | https://github.com/remarkjs/react-markdown |
| remark-gfm | MIT | https://github.com/remarkjs/remark-gfm |
| rehype-highlight | MIT | https://github.com/rehypejs/rehype-highlight |
| Lucide | ISC | https://lucide.dev/ |

The JavaScript dependency licenses shipped by pnpm are retained in the
standalone Next.js output under its `node_modules` directories.

## Reference Project

OpenTalos's Magpie parity work references `yetone/magpie`, distributed under
the MIT License:

https://github.com/yetone/magpie

Copyright (c) Yetone and Magpie contributors.

## Full License Texts

The release bundle includes OpenTalos's `LICENSE`, the Python runtime license
at `runtime/python/LICENSE`, and the Node.js license at
`runtime/node/LICENSE` when those upstream files are available in the build
environment. Third-party package license files are included in their
corresponding package directories.
