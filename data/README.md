# Data layout

| Folder | What goes here | In Git? |
| --- | --- | --- |
| `raw/` | Downloads exactly as received (RBI tables, Earth Engine exports, IMD tracks, EM-DAT) | No, DVC only (`data/raw.dvc`), except EM-DAT and Sen1Floods11 |
| `interim/` | Working files and caches that `make all` rebuilds | No, and not in DVC either |
| `processed/` | The tables every later phase reads; schemas are in `docs/contracts/` | No, DVC only (`data/processed.dvc`) |
| `models/` | Models that passed their gate (`cri.ml.tracking.keep_model`) | No, DVC only (`data/models.dvc`) |
| `events/` | Small hand-built CSVs (candidate event list, confounders) | Yes |

Every file in `raw/` has a data card in `docs/data_cards/` with its source, licence and download date.
A file made by hand (a review sheet, a manual correction) does not belong in `interim/`, which
nothing backs up: put it in `events/` if it is small, or in `raw/` so DVC keeps it.

## DVC: sharing the data between us

The `.dvc` files in Git record which version of each folder goes with the code. The files
themselves live in one Google Drive folder, `cri-dvc-store`, shared between the two of us and
synced to each laptop by Google Drive for desktop. DVC's own Google Drive login is not used:
Google blocks DVC's default app, and a synced folder needs no login at all.

`.dvcignore` keeps two raw sources out of DVC, so they never reach the shared folder:
`raw/emdat/` (EM-DAT's terms forbid passing the export on, so each of us downloads our own)
and `raw/s1_labels/` (Sen1Floods11 has no licence that allows sharing; the pipeline downloads
it with `python -m cri.ingest.sen1floods11`).

### Once per laptop

1. Install Google Drive for desktop and sign in. The owner of `cri-dvc-store` shares it with
   the other person as Editor; the other person adds it to My Drive (in the Drive website:
   right-click the folder, *Organize*, *Add shortcut*, *My Drive*).
2. Point DVC at it. The path contains your Google account, so let the shell find it:

   ```bash
   make dvc-remote URL="$(echo ~/Library/CloudStorage/GoogleDrive-*/My\ Drive/cri-dvc-store)"
   ```

   This writes `.dvc/config.local`, which is not committed (the path is different on each
   laptop). `dvc remote list` should show `storage` with that path.

### Every day

```bash
git pull
dvc pull
```

`dvc pull` brings the data that matches the `.dvc` files you just pulled.

After a change to `raw/`, a rebuild that changes `processed/`, or a new model in `models/`:

```bash
make dvc-track
dvc push
git add data/*.dvc
git commit -m "Update the processed tables after the rebuild"
```

`make dvc-track` runs `dvc add data/raw data/processed data/models`, and `dvc push` copies
the new files to the shared folder. Change the commit message to say what changed.

Push to DVC before you push the commit, so the other person never pulls `.dvc` files whose
data is not in the folder yet.

## Data versions

`configs/project.yaml` holds `data_version` (now `dev`), which every table and run records. At
a gate the version is frozen with a Git tag on the commit whose `.dvc` files point at that
data (`data-v1` at the Phase 1 gate, then `exposure-v1`, `effects-v1` and `stress-v1`), and
`data_version` is set to the same name. `git checkout data-v1 && dvc pull` then brings back
exactly that data.
