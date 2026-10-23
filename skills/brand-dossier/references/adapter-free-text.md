# Adapter: free text

The user's own words, from a short interview or a pasted text. Everything here is `typed`, confirmed.

## Only what is missing

Run it last. `python3 "$BK" missing brand` lists the questions whose answer is still missing after the skill and the
inference, grouped in batches (the two batches of brand-intake, plus a third for the promise, the address and the
motion). A field that is inferred and waits for confirmation is not asked here: it goes to the review.

Ask one batch, wait, then the next. If an answer is blank, ask once more, then move on: the field stays ASK.

## Recording

Write one typed source per interview or pasted text:

```json
{"adapter": "typed", "origin": "interview with <who> (2026-10-23)",
 "values": [{"path": "promise.tagline", "value": "the exact words"},
            {"path": "colours", "item": {"hex": "#0B3D2E", "role": "text"}}]}
```

or one answer at a time: `python3 "$BK" answer brand <path> "<value>"`.

- Quote the promise, the tagline, the key messages and samples **word for word**. Do not tidy them.
- A pasted document (a positioning note, a brand book in text) is typed too, with the document as `origin`; take
  only what it states, not what you would conclude from it.
- A colour "like our site" is not an answer: it sends you back to the inference.
