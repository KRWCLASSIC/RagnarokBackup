# Ragnarok Backup `0.2`

**Ragnarok Backup** is a simple, powerful, and scriptable backup tool for Linux servers. It uses a `.gitignore`-like file to specify exactly what to back up, making it easy to create reproducible, auditable, and minimal backups. Designed for sysadmins and power users, it focuses on reliability, transparency, and automation.

> For now, its only supports apt! other package managers will be added in the future.

<strong>Warning:</strong> Currently, this script does not support linked files. Please address this limitation before proceeding.

## What is Ragnarok Backup?

- **File-based, declarative backups:** You control what gets backed up by editing a plain text file (`~/.ragnarokbackup`), similar to how `.gitignore` works for git. (Doesn't support throwing good ol' /path/* because why tf would you backup all files instead of entire folder, bruh.)
- **Structured archives:** Backups are organized into clear folders (`home_dirs/`, `files/`, `metadata/`) with a mapping file (`affiliation.json`) for easy restoration.
- **Metadata aware:** Captures system package lists and APT repositories for full system reproducibility.
- **Scriptable hooks:** (Planned) Run scripts before/after backup or restore, locally or from URLs.

## Features

- **Selective backup:** Only what you list is included.
- **Supports files and directories:** (No wildcards/partial dirs; must specify full paths.)
- **Compression options:** `none`, `gz`, `zstd`, `zip`.
- **Dry-run mode:** Simulate backups (creates empty files, checks structure).
- **Verbose output:** See every file processed.
- **Metadata capture:** Saves installed packages and APT sources.
- **Conflict handling:** On restore, choose to overwrite, skip, or prompt for each file.
- **Colorful, clear CLI output.**
- **Cross-user support:** Handles `/root`, multiple home directories, and system files.

## Current Status

**Implemented:**

- Core backup/restore logic
- File/directory mapping and structure
- Metadata collection
- Dry-run and verbose modes
- Compression options
- Conflict handling on restore
- User feedback with colored output

**Not yet implemented:**

- Pre/post backup and restore hooks (`--prebak`, `--postbak`, `--prerest`, `--postrest`)
- Error handling for partial directory references (e.g., `/etc/somefolder/*`)
- Advanced logging (log rotation, verbosity levels)
- Automated tests
- Full documentation and usage examples

## Planned Features

- **Hook execution:** Run scripts before/after backup/restore (with security checks, local or remote).
- **Better error handling:** Especially for partial directory references.
- **Improved logging:** More control and log rotation.
- **Automated tests:** Unit and integration tests.
- **Expanded documentation:** More examples and troubleshooting.

## Quick Start

1. **Install dependencies:**  
   - Python 3.6+
   - (Optional) `zstd` for zstd compression

2. **Create your backup list:**

   ```bash
   mkdir -p ~/ragnarokbackup
   nano ~/ragnarokbackup/.ragnarokbackup
   ```

   > Or force its auto-creation with `python3 ragnarokbackup.py --backup`, will add better way later.

3. **Run a backup:**  

   ```bash
   python3 ragnarokbackup.py --backup --compress gz
   ```

4. **Restore:**

   ```bash
   python3 ragnarokbackup.py --restore <backup_file>
   ```

   > Make sure backup file is in the same directory as `ragnarokbackup.py` otherwise you will need to specify paths :(
