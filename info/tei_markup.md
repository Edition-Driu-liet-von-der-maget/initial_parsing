# TEI markup generated from pseudo tags

This document describes how the script
[initial_parsing/pyscripts/table_2_tei.py](../pyscripts/table_2_tei.py)
turns the inline pseudo markup in the CSV into TEI XML.

Pseudo markup has the general form `#x...+`, where `#x` opens a
markup span and `+` closes it. The content between them is attached as
text to the corresponding TEI element.

## Inline pseudo tags → TEI

| Pseudo tag | Meaning (comment in code)              | Primary TEI element created                                  | Notes |
|-----------:|----------------------------------------|--------------------------------------------------------------|-------|
| `#s`       | Superskripte                           | `choice[@type='superscript']` with `abbr/hi[@rend='superscript']/expan` | Abbreviation where the last character is written in superscript. |
| `#a`       | abbreviation                           | `choice[@type='abbreviation']` with `abbr` and `expan`       | Handles many abbreviation patterns; the visible mark is in `abbr`, the reading text in `expan`. |
| `#d`       | gelöscht                               | `del`                                                        | Kept as a plain TEI `<del>` element with its text content. |
| `#z`       | Zusatz                                 | `add`                                                        | Kept as a plain TEI `<add>` element with its text content. |
| `#l`       | de-Ligatur                             | `choice[@type='ligature']` with `orig` and `reg`             | Both `orig` and `reg` currently contain the same text. |
| `#r`       | Rubrizierungen                         | `hi[@rend='rubrication']`                                    | Used for rubricated text. |
| `#f`       | Seitenwechsel                          | `pb`                                                         | Page break marker. |
| `#?`       | unclear                                | `unclear`                                                    | Kept as a plain TEI `<unclear>` element. |
| `#I`       | initial                                | `hi[@rend='initial']`                                        | Marks decorated initials. |
| `#i`       | lombard                                | `hi[@rend='lombard']`                                        | Marks lombard initials. |
| `#^`       | zirkumflex / supplied                  | `zirkumflex`                                                 | Currently stays as a plain TEI `<zirkumflex>` element. |
| `#&`       | et-ligature                            | `choice[@type='et_ligature']` with `orig` and `reg`          | `orig` is `&`, `reg` is `et`. |

Any other pseudo tag is turned into a `<wrong_markup>` TEI element
and a warning is logged.

### Behaviour of `#a` (abbreviations)

For abbreviations, the script always creates

- `choice[@type='abbreviation']`
  - `abbr` – the written abbreviation sign (often base letter plus a combining mark or special glyph)
  - `expan` – the expanded reading

The exact content of `abbr` depends on the abbreviated word (e.g.
`en`, `em`, `men`, `nem`, `per`, `par`, `us`, `az`, etc.) and sometimes
on the witness siglum. In some cases a preceding character is moved
inside the abbreviation and marked as superscript.

## Structural TEI created by the script

In addition to inline markup, the script also creates structural
elements in the TEI document:

- Each verse becomes an `l` element:
  - `l` with `xml:id="v<local_count>"` (if non-empty) and
    `n="v<global_count>"`.
- Each witness gets a container line group:
  - `lg[@type='witness'][@n='<siglum>']` wrapping all verses of that
    witness.
- Sections based on decorated initials are grouped as:
  - `lg[@type='sub_group']` around sequences starting with an `l`
    that contains `hi[@rend='initial' or @rend='lombard']`.
  - `lg[@type='group']` grouping consecutive `lg[@type='sub_group']`
    blocks and the following verses.

The rest of the TEI structure (header, text/body, etc.) is taken from
the template file [initial_parsing/templates/tei_template.xml](../templates/tei_template.xml).
