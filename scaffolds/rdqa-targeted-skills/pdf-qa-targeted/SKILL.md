---
name: pdf-qa-targeted
description: "Answer a question about a specific PDF document by reasoning about which page(s) the answer lives on, fetching only those pages, and self-reflecting before returning. Use whenever the agent is asked a fine-grained question about a PDF where the answer is a closed-form value (number, name, date, identifier, short verdict)."
version: 1.0.0
author: Hermes Agent
license: MIT
platforms: [linux, macos, windows]
metadata:
  hermes:
    tags: [pdf, document, qa, cot, self-reflection]
    related_skills: [video-qa-targeted, audio-qa-targeted]
---

# Targeted PDF QA

## Overview

Same pattern as `video-qa-targeted` and `audio-qa-targeted`, but for PDFs.
The agent does NOT extract the whole document and does NOT answer from
search snippets about the URL's filename. Instead it:

1. **Probes** the PDF (page count, first-page preview, table-of-contents).
2. **Reasons** about which page(s) the answer is most likely on.
3. **Fetches only those pages**, not the entire document.
4. **Self-reflects** on whether the extracted text answers the query.
5. **Iterates** with adjacent pages or chapter neighbours if low confidence.
6. **Returns** the answer with a `page_index` citation.

## When to Use

- The user provides a PDF URL or path and asks a fine-grained question
  whose answer is a single short string located in the document.
- The question implies a particular section (e.g. *"in the TOC"*,
  *"on the cover page"*, *"in the appendix"*).

Don't use for:

- Open-ended summarization (use a generic summarization skill).
- Questions answerable from the PDF's filename/title without opening it.

## Dependencies

```bash
# poppler-utils (provides pdfinfo + pdftotext + pdftoppm)
brew install poppler          # macOS
apt install poppler-utils     # Debian/Ubuntu
```

## Workflow

### Step 1 — Probe

```bash
python3 SKILL_DIR/scripts/pdf_skill.py probe <URL_or_path>
# returns: {n_pages, page1_preview (first ~2k chars), runid}
```

The probe also returns a `page1_preview` of ~2k characters from the first
page so the agent can decide whether the document has a visible TOC or
cover-page structure.

### Step 2 — Locate (agent CoT)

```
## Locate
- query intent: <one sentence>
- structural clue from probe: <e.g. has TOC on page 1, 32-page doc>
- predicted page(s): [p1, p2, p3]
- rationale: <why those pages>
```

Heuristics:

| Question pattern | Predicted page(s) |
|---|---|
| *"on the cover page / title page"* | 1 |
| *"in the executive summary / abstract"* | 1–3 |
| *"in the table of contents"* | first 2-3 pages |
| *"in the appendix / glossary"* | last 5-10 pages |
| *"on page N"* | exactly N |
| *"in section X.Y"* | pages around (X * total/total_sections) |
| Specific numeric/financial answer | scan first 6 pages (executive summary), then dense central |
| No clue | sample {1, 25 %, 50 %, 75 %, last} of pages |

### Step 3 — Extract

```bash
python3 SKILL_DIR/scripts/pdf_skill.py extract <URL_or_path> \
    --pages 1,2,3,7  --runid <id>
```

Returns text content per page:

```json
{"runid": "...", "pages": [
  {"page": 1, "text": "..."},
  {"page": 2, "text": "..."}
]}
```

### Step 4 — Self-reflect

```
## Reflect
- best page: <N>
- extracted answer: <value>
- supporting evidence: "<quote from page N>"
- did the page text literally contain the answer? <yes/no>
- residual uncertainty: <low/medium/high>
```

If uncertainty is medium or high, re-extract adjacent pages or
the appendix.

### Step 5 — Return

```json
{
  "answer_value": "Risk Management of Valartis Group",
  "evidence_page_index": 1,
  "evidence_quote": "Page 15 — Risk Management of Valartis Group",
  "confidence": 0.92
}
```

## Iteration Policy

- Iter 1: 3 candidate pages from heuristic.
- Iter 2 (if iter 1 confidence < 0.7): 3 adjacent pages around best lead.
- Iter 3 (last resort): scan {1 .. n_pages} in batches of 5.

Cap: 12 distinct pages extracted per question.

## Common Pitfalls

1. **Extracting the whole PDF.** Long documents (budgets, manuals,
   syllabi) can be hundreds of pages — extract only what the locate
   reasoning predicts.
2. **Answering from the filename.** The PDF URL often contains keywords
   that look like the answer; the answer must be cited with a
   `page_index`.
3. **Skipping the TOC.** For "in section X" or "table of contents"
   questions, the TOC page IS the answer source — extract it explicitly.

## Verification Checklist

- [ ] Probe was called; n_pages cited in Locate.
- [ ] Locate block lists ≥1 candidate page with rationale.
- [ ] Extract returned non-empty text for at least one candidate page.
- [ ] Reflect block confirms confidence ≥ 0.7.
- [ ] Final answer includes `evidence_page_index`.
