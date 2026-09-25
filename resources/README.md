# JLPT kanji level estimates

`jlpt-levels.json` maps a kanji character to its estimated modern JLPT level, using integers 1 through 5 for N1 through N5. A missing character has no level in this dataset. The modern JLPT does not publish an official kanji-by-level list, so treat these as community estimates, not official classifications.

## Source and provenance

This is a reduced mapping extracted from [`kanji.json`](https://github.com/davidluzgouveia/kanji-data/blob/00fd7079c3890f430759536f91aa5e854ec0ca4f/kanji.json) in David Gouveia's [`kanji-data`](https://github.com/davidluzgouveia/kanji-data) repository at commit `00fd7079c3890f430759536f91aa5e854ec0ca4f` (2026-02-27). It contains only kanji keys with an integer `jlpt_new` value from 1 through 5; other fields and entries without such a value are omitted. The pinned source has 13,108 records; this mapping has 2,211 entries: N1 1,232, N2 367, N3 367, N4 166, and N5 79. Upstream documents its JLPT source as [Jonathan Waller's JLPT Resources](https://www.tanos.co.uk/jlpt/).

Pinned source SHA-256 (`kanji.json`): `561b72ea9df703c58fae0c68585812e172aaa7611d2fcee6719d55fd2dfd4fa4`.

Mapping SHA-256 (`jlpt-levels.json`): `4f0de03e7624ac6e133e4a7a8be7939f13d6ade7f096ca59a8c20a00545f97f7`.

Jonathan Waller's [sharing terms](https://www.tanos.co.uk/jlpt/sharing/) place the site's content that he is not selling under Creative Commons “BY”, permit commercial and non-commercial reuse, and ask users to credit the site. The page does not specify a license version. Attribution: “JLPT level estimates from Jonathan Waller's JLPT Resources, as compiled in David Gouveia's kanji-data.”

The upstream repository provides an [MIT license](https://github.com/davidluzgouveia/kanji-data/blob/00fd7079c3890f430759536f91aa5e854ec0ca4f/LICENSE); its copyright and permission notice are included in [LICENSE-MIT](LICENSE-MIT). Jonathan Waller's attribution terms are included in [LICENSE-CC-BY](LICENSE-CC-BY).
