# OCR regression crops

Small unmodified pixel crops from the screenshot supplied with the OCR bug
report on 2026-09-25. The full screenshot is not included. Only PNG metadata
was stripped. The green annotation is outside the character crops.

| File | Expected text | Crop (width x height + x + y) |
| --- | --- | --- |
| love.png | 愛 | 29x35+588+662 |
| love-tight.png | 愛 | 27x29+589+664 |
| time.png | 時 | 28x32+477+627 |
| place.png | 場所 | 51x32+527+627 |
| work.png | 作品 | 51x32+490+662 |
| talk.png | 語 | 29x36+639+662 |
| line.png | 時と場所をわきまえず | 255x32+477+627 |
| dark-background.png | 晩 | 51x56+760+111 |
| blank.png | no text | 45x30+320+65 |

These cover small outlined subtitles on a scene, tight selections, kanji
radicals incorrectly split into multiple lines, the existing dark-background
behavior, and bright scenery that must not be mistaken for text. The capture
test substitutes these pixels for grim output and runs real OCR; it does not
simulate a live desktop drag gesture.
