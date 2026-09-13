# Third-party notices

Wardline itself is licensed under [Apache-2.0](LICENSE). This file records
attribution for third-party *code* this repository is inspired by or
depends on beyond what's already declared in `pyproject.toml`/`globe/package.json`
(ordinary open-source dependencies, not called out individually here).
Live third-party *data* attribution (required by several sources' terms)
renders in-app instead — see `globe/README.md`'s Attribution section and
`globe/src/hud.js`.

## gods-eye-view (MIT)

`globe/` is an original build (no code copied) inspired by
[bilawalsidhu/gods-eye-view](https://github.com/bilawalsidhu/gods-eye-view),
credited in-app via the Live Globe HUD's attribution line. A full-fidelity
integration — consuming that project's actual code via a maintained fork
rather than reimplementing it — is planned; see
[`docs/LIVE_GLOBE_FULL_INTEGRATION_ROADMAP.md`](docs/LIVE_GLOBE_FULL_INTEGRATION_ROADMAP.md).
The fork itself, once it carries real commits, will retain the upstream
project's own MIT `LICENSE` file in full, per that license's terms:

```
MIT License

Copyright (c) 2026 Bilawal Sidhu

Permission is hereby granted, free of charge, to any person obtaining a copy
of this software and associated documentation files (the "Software"), to
deal in the Software without restriction, including without limitation the
rights to use, copy, modify, merge, publish, distribute, sublicense, and/or
sell copies of the Software, and to permit persons to whom the Software is
furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in
all copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING
FROM, OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER
DEALINGS IN THE SOFTWARE.
```
