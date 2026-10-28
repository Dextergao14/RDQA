# RDQA project homepage

A responsive, English academic project page for GitHub Pages. The site is plain HTML, CSS, JavaScript, and JSON; it needs no package installation or build step. Everything needed to publish lives under `docs/`.

## Publish after merging

1. Merge the homepage pull request into `main`.
2. Open [Settings → Pages](https://github.com/Dextergao14/RDQA/settings/pages).
3. Under **Build and deployment**, choose **Source: Deploy from a branch**.
4. Select **Branch: main** and **Folder: /docs**, then click **Save**.
5. Wait for GitHub's Pages deployment to complete. The expected URL is [https://dextergao14.github.io/RDQA/](https://dextergao14.github.io/RDQA/).

The supplied `.nojekyll` serves these static files directly. No custom domain or additional Actions workflow is required. The repository's original code, data, evaluation scripts, and README are not replaced by this page.

## Preview locally

Run this from the repository root, then visit `http://localhost:8000/`:

```sh
python3 -m http.server 8000 --directory docs
```

Use a local HTTP server: opening `index.html` as a `file://` URL can prevent the browser from loading the results JSON. Check desktop and mobile widths, the search and scaffold filters, both result tabs, sorting, empty results, and the citation copy/download actions.

## Files and maintenance

- `index.html`: page content, social metadata, scholarly metadata, and structured data.
- `assets/styles.css` and `assets/site.js`: responsive presentation and browser interactions.
- `data/leaderboard.json`: `schemaVersion`, `verifiedOn`, `sourceCommit`, `metrics`, and separate `sets.paper.rows` / `sets.artifacts.rows`. Every row carries `raw`, `plr`, `adjusted`, `sampleNote`, and `source`; paper rows also include `familyScores`. Unavailable values are `null`.
- `data/provenance.json`: `commit`, `audited_at`, `counts`, `rawParts`, `skips`, `fieldQuality`, `schema`, `discrepancies`, and source URLs. This records the pinned dataset audit, including raw/evaluable counts and missing metadata.
- `assets/examples.js`: three real, sourced annotations used by the interactive task examples. Keep them synchronized with the pinned dataset audit and retain their item/source references.
- `citation.bib`: citation fields verified against the [ACL Anthology record](https://aclanthology.org/2026.emnlp-main.1855/). Keep the displayed BibTeX in `index.html` synchronized.
- `assets/social-card.png`, `assets/favicon.svg`, and `sitemap.xml`: sharing, identity, and discovery assets. If the hosting URL changes, update canonical, Open Graph, Twitter, structured data, and sitemap URLs together.

Keep each numeric result paired with its original source and the exact metric. Preserve `null` for unavailable values; a missing value is not zero. Do not calculate an asserted overall raw accuracy from the paper's rounded adjusted accuracy and PLR. Retain artifact filenames and pinned commit references when updating source data, and update the audit date and explanatory text in `index.html` at the same time. Recheck external paper and dataset links before publishing changes.

These audits are checked-in snapshots, not live API feeds. To refresh, inspect the new source revision, re-count the raw data parts using the filtering rules in `eval/convert_dataset.py`, re-check the original result artifacts or paper tables, and update both JSON files and their explanatory copy together. There is no automatic refresh command.

## Scope and interpretation

The paper describes a 1,350-question benchmark. The pinned repository release has different raw and converted counts, documented on the page and in `data/provenance.json`; these are not interchangeable sample sizes. The paper does not report per-system scored N and excludes inaccessible sources. It reports one run per configuration, without variance estimates.

Published Table 3 results are transcribed from the paper, not independently reproduced. Repository artifacts cover partial, differing item sets and must remain separate. Do not rank paper scores against artifact scores or interpret small differences as statistically significant.

The paper's L1 video family is **VTE** in Tables 2–3 and **VTR** in Figure 3 and the repository README. The page discloses this notation difference. The paper's retrieval criterion (source URL or SHA-256 match plus parsing) and the released trace judge's textual/source-host heuristics are also distinct. Trace labels are outputs of the released implementation, not proof of evidence-grounded reasoning.

Source media remains with the original providers. The homepage distributes links and benchmark metadata, not copies of the underlying documents, video, or audio.
