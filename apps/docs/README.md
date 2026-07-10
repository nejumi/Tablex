# Tablex documentation site

This app builds the public Tablex documentation site.

English is the canonical source. Japanese, Simplified Chinese, and Korean pages live under `i18n/` and should track the same paths and document ids.

```bash
npm install
npm run check:locales
npm run build
npm run start
```

Local translated previews:

```bash
npm run start:ja
npm run start:zh
npm run start:ko
```

Production URL after GitHub Pages is enabled:

```text
https://nejumi.github.io/Tablex/
```

First-time GitHub setup: open the repository settings and set **Settings → Pages → Build and deployment → Source** to **GitHub Actions**. If the workflow fails at `actions/configure-pages` with `Get Pages site failed`, Pages has not been enabled for this repository yet.
