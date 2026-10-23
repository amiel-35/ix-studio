# Searching the web for the brand's visuals

Page search finds articles; it misses images. Use a real **image search** in a browser the session can drive (the
built-in browser, or the user's own browser if they ask for it). Refuse non-essential cookies; if a CAPTCHA or a
sign-in wall appears, stop there and tell the user, never get around it.

## Queries

The brand's name alone, then with: `campagne` / `campaign`, `affiche` / `poster`, `publicité` / `ad`, `logo`,
`nouvelle identité` / `rebrand`, the agency's name when an article gives it, the campaign's name. Look at results
from the brand's domain, its official social accounts, and the trade press.

## Classify every image you open

| Ownership | When |
|---|---|
| `official` | on the brand's domain or an account the brand runs |
| `official_relayed` | on another site (often the trade press), in an article that names the brand **and** the agency or the campaign |
| `probable` | the brand's mark is clearly there and the context fits, but nothing states it |
| `uncertain` | a moodboard, a fan, a reseller, a competitor, a mock-up, an image with no context |

The domain alone does not decide: a real campaign often lives on a press site, and a brand's name on a page does not
make the page the brand's. Only the first three feed the inference; `uncertain` is evidence and nothing more. The
user confirms or corrects every classification at the review, and a correction takes out what rested only on it.

## Old and new, campaign and identity

An identity that changed shows up twice: old logo and new logo, old colours and new. Name each as a **look**
(`old_identity`, `brand`, `campaign`, with a date if you have one), attach each image to its look with the
evidence's `look` field, and never mix them. A campaign has its own look; it is never the master look without the
user's word. It mostly feeds the voice (its headlines, quoted).

## Never keep the file

Record the image address (and the page it was found on), the date, the ownership, a one-line note of what it shows.
To read colours off an image, `python3 "$BK" sample <image address>` downloads it to a temporary folder, measures it
and deletes it. Do not save screenshots of web images in the dossier either.
