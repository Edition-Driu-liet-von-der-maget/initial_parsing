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
| `#s`       | Superskripte                           | `choice` with `abbr/hi[@rend='superscript']` + `expan`     | No custom `@type`; superscript form lives inside `abbr`. |
| `#a`       | abbreviation                           | `choice` with `abbr` and `expan`                             | No custom `@type`. Visible mark in `abbr` (Unicode where known), reading in `expan`. |
| `#d`       | gelöscht                               | `del`                                                        | Kept as a plain TEI `<del>` element with its text content. |
| `#z`       | Zusatz                                 | `add`                                                        | Kept as a plain TEI `<add>` element with its text content. |
| `#l`       | de-Ligatur                             | `choice[@type='ligature']` with `orig` and `reg`             | Ligature glyph in `orig` when known; plain sequence in `reg`. |
| `#r`       | Rubrizierungen                         | `hi[@rend='rubric']`                                         | Rubricated text. |
| `#f`       | Seitenwechsel                          | `pb`                                                         | Page break marker. |
| `#?`       | unclear                                | `unclear`                                                    | Kept as a plain TEI `<unclear>` element. |
| `#I`       | initial                                | `c[@type='initial']`                                         | Decorated initial letter. |
| `#i`       | lombard                                | `c[@type='lombard']`                                         | Lombard initial. |
| `#^`       | Zirkumflex                             | `hi[@rend='circumflex']`                                     | Markup records circumflex; display text gets combining U+0302 except on â ê î ô û (e.g. `#^æ+`, `#^w+`, `#^v+`, `#^m+`). |
| `#&`       | et-ligature                            | `choice[@type='et_ligature']` with `orig` and `reg`          | `orig` is `&`, `reg` is `et`. |

Any other pseudo tag is turned into a `<wrong_markup>` TEI element
and a warning is logged.

### Behaviour of `#a` (abbreviations)

For abbreviations, the script always creates a plain TEI

- `choice`
  - `abbr` – the written abbreviation sign (base letter plus combining mark or special Unicode glyph when known)
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
    that contains `c[@type='initial' or @type='lombard']`.
  - `lg[@type='group']` grouping consecutive `lg[@type='sub_group']`
    blocks and the following verses.

The rest of the TEI structure (header, text/body, etc.) is taken from
the template file [initial_parsing/templates/tei_template.xml](../templates/tei_template.xml).
