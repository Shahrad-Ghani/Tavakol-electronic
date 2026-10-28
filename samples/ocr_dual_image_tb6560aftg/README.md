# TB6560AFTG OCR regression sample

This sample documents the failure that motivated Integrated V2.0.

- `original_IMG_8021.JPG`: original phone photo.
- `regenerated_old_6560AFTG.webp`: old generated result from the previous pipeline.

Observed issue:
- Original marking supports a `TB` prefix.
- The old regenerated image can visually distort that prefix toward `T8`.
- The old one-image OCR selected only `6560AFTG`.

V2.0 uses both images in one OCR request, gives original character authority, explicitly
checks `B` vs `8`, and allows a Part Number to be assembled from supported adjacent marking
segments such as `TB` + `6560AFTG`.

This folder is documentation/regression evidence only. The pipeline does not scan `samples/`.
