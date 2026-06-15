# MeteorAI — Moving to a New Windows Machine

This project is best installed **natively** on the new machine (not in Docker).
The tools are a quick `pip install`; the real work is moving the PostgreSQL
database, ~7 GB of media, and the machine-local config — and Docker doesn't
make any of that easier (and complicates GPU use for training/SAM on Windows).

The [migrate_data.ps1](migrate_data.ps1) script automates the data move. This
file is the end-to-end checklist around it.

---

## What lives where

| Thing | Covered by `export_backup.py` (the zip)? | How it moves |
|---|---|---|
| PostgreSQL DB (`meteorite_images`) | ✅ | backup zip → `import_backup.py` |
| `meteorite_scraper/images` | ✅ | backup zip |
| Label Studio annotations | ✅ | backup zip → re-imported via API |
| `unsorted_media`, `sorted_*`, `import` | ❌ | `migrate_data.ps1` (robocopy) |
| `meteorite_scraper/videos`, `metadata` | ❌ | `migrate_data.ps1` |
| `classifier_training_data`, `training` | ❌ | `migrate_data.ps1` (regenerable) |
| `label_studio/sam_weights`, `model_dir` | ❌ | `migrate_data.ps1` (regenerable) |
| Root `yolo*.pt` weights | ❌ | `migrate_data.ps1` (regenerable) |
| `.env`, `db_config.py` (secrets) | ❌ | `migrate_data.ps1` (`secrets/`) |
| Code | tracked in git | `git clone` |

"Regenerable" = can be rebuilt or re-downloaded on the new machine. Use
`-SkipRegenerable` on both export and import for a lean ~5 GB transfer; otherwise
the full bundle is ~7 GB.

---

## OLD machine

```powershell
# Stop running services so the DB dump is consistent.
.\stop_services.ps1

# Preview first: lists every item + sizes + grand total, copies nothing.
.\migrate_data.ps1 -Mode Export -Dest E:\meteorai_migration -DryRun

# Produce the migration bundle on an external drive / network share.
.\migrate_data.ps1 -Mode Export -Dest E:\meteorai_migration
```

> Tip: `-DryRun` works on both `-Mode Export` and `-Mode Import`. Add
> `-SkipRegenerable` to see/produce the lean (~3.9 GB) bundle instead of the
> full (~6.7 GB) one.

This writes to `E:\meteorai_migration`:
- `meteorai_backup.zip` — DB + images + annotations
- `data\…` — the large media/data dirs
- `secrets\…` — `.env` and `db_config.py`

Copy that whole folder to the new machine.

> ⚠️ `secrets\` contains your DB password and Label Studio API key in cleartext.
> Transfer it over a trusted medium, and see "Security" below.

---

## NEW machine — prerequisites (one-time)

1. **Python 3.11+** (same minor version as the old machine if possible).
2. **PostgreSQL 18** — install the Windows service. The launch scripts expect
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
   # GPU PyTorch (recommended for training/SAM) — pick your CUDA version:
   # pip install torch torchvision --index-url https://download.pytorch.org/whl/cu121
   ```

---

## NEW machine — restore

```powershell
# Run from inside the cloned repo. -ProjectDir defaults to the repo root.
.\migrate_data.ps1 -Mode Import -Source E:\meteorai_migration

# If your PostgreSQL password differs from the one in db_config.py:
.\migrate_data.ps1 -Mode Import -Source E:\meteorai_migration -DbPassword <pwd>
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
- **Streamlit** → http://localhost:8501 (data shows up)
- **Label Studio** → http://localhost:8081 (projects + annotations present,
  images render — confirms the local-files path rewrite worked)
- **PostgreSQL** → `python meteorite_scraper\test_connection.py`

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
