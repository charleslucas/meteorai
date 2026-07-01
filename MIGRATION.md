# MeteorAI â€” Moving to a New Windows Machine

This project is best installed **natively** on the new machine (not in Docker).
The tools are a quick `pip install`; the real work is moving the PostgreSQL
database, ~7 GB of media, and the machine-local config â€” and Docker doesn't
make any of that easier (and complicates GPU use for training/SAM on Windows).

The [migrate_data.ps1](scripts/migrate_data.ps1) script automates the data move. This
file is the end-to-end checklist around it.

---

## What lives where

| Thing | Covered by `export_backup.py` (the zip)? | How it moves |
|---|---|---|
| PostgreSQL DB (`meteorite_images`) | âœ… | backup zip â†’ `import_backup.py` |
| `meteorite_scraper/images` | âœ… | backup zip |
| Label Studio annotations | âœ… | backup zip â†’ re-imported via API |
| `unsorted_media`, `sorted_*`, `import` | âŒ | `migrate_data.ps1` (robocopy) |
| `meteorite_scraper/videos`, `metadata` | âŒ | `migrate_data.ps1` |
| `classifier_training_data`, `training` | âŒ | `migrate_data.ps1` (regenerable) |
| `label_studio/sam_weights`, `model_dir` | âŒ | `migrate_data.ps1` (regenerable) |
| Root `yolo*.pt` weights | âŒ | `migrate_data.ps1` (regenerable) |
| `.env`, `db_config.py` (secrets) | âŒ | `migrate_data.ps1` (`secrets/`) |
| Code | tracked in git | `git clone` |

"Regenerable" = can be rebuilt or re-downloaded on the new machine. Use
`-SkipRegenerable` on both export and import for a lean ~5 GB transfer; otherwise
the full bundle is ~7 GB.

---

## OLD machine

> **Services must be RUNNING for the export**, not stopped: the export reads the
> live PostgreSQL DB (pg_dump + a query) and pulls annotations from the Label
> Studio API. Run `.\start_services.ps1` first if they aren't up. (Use
> `--skip-label-studio`-equivalent only if you don't need annotations.)

```powershell
# Preview first: lists every item + sizes + grand total, copies nothing.
.\scripts\migrate_data.ps1 -Mode Export -Dest E:\meteorai_migration -DryRun

# Produce the migration bundle on an external drive / network share.
.\scripts\migrate_data.ps1 -Mode Export -Dest E:\meteorai_migration
```

> Tip: `-DryRun` works on both `-Mode Export` and `-Mode Import`. Add
> `-SkipRegenerable` to see/produce the lean (~3.9 GB) bundle instead of the
> full (~6.7 GB) one.

This writes to `E:\meteorai_migration`:
- `meteorai_backup.zip` â€” DB + images + annotations
- `data\â€¦` â€” the large media/data dirs
- `secrets\â€¦` â€” `.env` and `db_config.py`

Copy that whole folder to the new machine.

> âš ï¸ `secrets\` contains your DB password and Label Studio API key in cleartext.
> Transfer it over a trusted medium, and see "Security" below.

---

## NEW machine â€” prerequisites (one-time)

1. **Python 3.11+** (same minor version as the old machine if possible).
2. **PostgreSQL 18** â€” install the Windows service. The launch scripts expect
   the service name `postgresql-x64-18`. During install, create (or note) a
   superuser password.
3. **Git**, then clone the repo to your chosen location, e.g.:
   ```powershell
   git clone <your-repo-url> C:\meteorai
   cd C:\meteorai
   ```
4. **Python dependencies:**
   ```powershell
   pip install -r meteorite_scraper\requirements.txt
   # Optional, only if you use the SAM annotation backend:
   pip install -r label_studio\requirements_sam.txt
   # GPU PyTorch (recommended for training/SAM).
   # First check your CUDA version: nvidia-smi | findstr "CUDA Version"
   # Then install the matching wheel (cu128 works for CUDA 12.8â€“13.x):
   pip install torch torchvision --index-url https://download.pytorch.org/whl/cu128 --force-reinstall --no-deps
   # --force-reinstall is required if pip already installed the CPU build of torch
   # (pip won't upgrade +cpu â†’ +cu128 without it). Verify with:
   # python -c "import torch; print(torch.cuda.is_available())"
   ```

---

## NEW machine â€” restore

```powershell
# Run from inside the cloned repo. -ProjectDir defaults to the repo root.
.\scripts\migrate_data.ps1 -Mode Import -Source E:\meteorai_migration

# If your PostgreSQL password differs from the one in db_config.py:
.\scripts\migrate_data.ps1 -Mode Import -Source E:\meteorai_migration -DbPassword <pwd>
```

The import step:
1. Restores `secrets\` so `import_backup.py` can authenticate.
2. Robocopies the media/data dirs into the repo.
3. **Rewrites the hardcoded `C:\cygwin64\home\charl\meteorai` path** in
   `start_services.ps1`, `start_label_studio.bat`, and `stop_services.ps1` to
   the new project location.
4. Runs `import_backup.py` to load the DB, images, and annotations.

---

## Verify

```powershell
.\start_services.ps1
```

Then check:
- **Streamlit** â†’ http://localhost:8501 (data shows up)
- **Label Studio** â†’ http://localhost:8081 (projects + annotations present,
  images render â€” confirms the local-files path rewrite worked)
- **PostgreSQL** â†’ `python meteorite_scraper\test_connection.py`

If Label Studio images 404, confirm `LABEL_STUDIO_LOCAL_FILES_DOCUMENT_ROOT`
in `start_label_studio.bat` points at `<project>\meteorite_scraper`.

---

## Security (do this during the move)

- `db_config.py` has the DB password as a hardcoded fallback
  (`meteorite_scraper/db_config.py`). A move is a good time to **rotate the
  PostgreSQL password** and keep it only in `.env`.
- Rotate the **Label Studio API key** in `.env` after the move.
- Delete the `secrets\` folder from the transfer drive once the new machine is
  verified working.
