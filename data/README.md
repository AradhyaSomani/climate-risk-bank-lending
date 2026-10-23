# Data layout

| Folder | What goes here | In Git? |
| --- | --- | --- |
| `raw/` | Downloads exactly as received (RBI tables, Earth Engine exports, IMD tracks, EM-DAT) | No, DVC only |
| `interim/` | Working files, manual review sheets (for example `crosswalk_review.csv`) | No, DVC only |
| `processed/` | The tables every later phase reads; schemas are in `docs/contracts/` | No, DVC only |
| `events/` | Small hand-built CSVs (candidate event list, confounders) | Yes |

Every file in `raw/` has a data card in `docs/data_cards/` with its source, licence and download date.
