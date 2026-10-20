# Local website prototype (not deployed)

A one-page prototype of the future workshop site. It exists so the whole
experience — lesson outline, notebook launch, scoreboard — can be clicked
through locally before anyone decides about hosting.

## Run it locally

From the repo root:

```bash
python -m http.server 8000
```

Then open:

- http://localhost:8000/site/ — this page
- http://localhost:8000/dashboard/?view=score — the projector dashboard
  (live / scoreboard / leaderboard views over `dashboard/data.js`)
- http://localhost:8000/notebooks/workshop-preview.html — the executed,
  read-only preview of the hands-on notebook

The hands-on notebook itself is `../notebooks/workshop.ipynb` — run it with
Jupyter locally today, or in Google Colab later.

## Why the Colab button doesn't embed

Colab sends `X-Frame-Options: DENY`, so a live Colab notebook cannot be
framed inside another site (Google's feature request for it,
googlecolab/colabtools#1225, is open since 2020). The honest pattern is:
our page holds the lesson + a static preview, and the launch button opens
each participant's own notebook copy in Colab via the official deep link:

```text
https://colab.research.google.com/github/<org>/<repo>/blob/<tag>/notebooks/workshop.ipynb
```

That needs a **public** repo or workshop mirror (this repo is currently
private) pinned to a fixed tag — a pending decision, which is why the button
is marked pending. Everything else on the page already works locally.

## Later (only when deployment is requested)

Host `site/` + `dashboard/` + the notebook preview as static files at
`/workshops/break-your-agents-memory`, replace the slide-placeholder cards
with the real deck, and point the Colab button at the public mirror tag.
A true embedded runtime would require self-hosted JupyterHub — out of
scope unless explicitly requested.
