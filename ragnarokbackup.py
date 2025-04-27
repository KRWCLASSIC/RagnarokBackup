from pathlib import Path
import subprocess
import tempfile
import argparse
import tarfile
import filecmp
import shutil
import json
import sys
import os

# ANSI color codes
class Colors:
    HEADER = '\033[95m'
    OKBLUE = '\033[94m'
    OKCYAN = '\033[96m'
    OKGREEN = '\033[92m'
    WARNING = '\033[93m'
    FAIL = '\033[91m'
    ENDC = '\033[0m'
    BOLD = '\033[1m'

def cprint(msg, color):
    print(f"{color}{msg}{Colors.ENDC}")

def check_zstd():
    from shutil import which
    if which("zstd") is None:
        cprint("ERROR: zstd compression selected but 'zstd' is not installed or not in PATH.", Colors.FAIL)
        sys.exit(1)

def get_archive_path(src_path, home):
    src = Path(src_path)
    # Handle /root
    if str(src) == "/root" or str(src).startswith("/root/"):
        rel = src.relative_to("/root")
        return f"home_dirs/root/{rel}", "home_dirs"
    # Handle /home/<username>
    elif str(src).startswith("/home/"):
        parts = src.parts
        if len(parts) >= 3:
            username = parts[2]
            rel = Path(*parts[3:]) if len(parts) > 3 else Path()
            return f"home_dirs/{username}/{rel}".rstrip("/"), "home_dirs"
    # Handle current user's home (for non-root users)
    elif str(src).startswith(str(home)):
        rel = src.relative_to(home)
        username = home.name
        return f"home_dirs/{username}/{rel}", "home_dirs"
    # Everything else
    rel = src.relative_to("/")
    return f"files/{rel}", "files"

def collect_installed_packages(metadata_dir):
    try:
        # Get manually installed packages
        manual = subprocess.check_output(
            "comm -23 <(apt-mark showmanual | sort) <(apt-mark showauto | sort)",
            shell=True, executable="/bin/bash"
        ).decode().splitlines()
        if not manual:
            raise Exception("No manual packages found or not a Debian-based system.")

        # Get versions for those packages
        dpkg_cmd = f"dpkg -l | grep -E '^ii' | grep -Ff <(printf '%s\n' {' '.join(manual)})"
        versions = subprocess.check_output(
            dpkg_cmd,
            shell=True, executable="/bin/bash"
        ).decode()
        (metadata_dir / "installed_packages.txt").write_text(versions)
    except Exception as e:
        (metadata_dir / "installed_packages.txt").write_text(
            f"# Could not collect installed packages: {e}\n"
        )

def collect_apt_repos(metadata_dir):
    try:
        sources = ""
        if Path("/etc/apt/sources.list").exists():
            sources += "### /etc/apt/sources.list\n"
            sources += Path("/etc/apt/sources.list").read_text() + "\n"
        sources += "### /etc/apt/sources.list.d/\n"
        sources_list_d = Path("/etc/apt/sources.list.d")
        if sources_list_d.exists():
            for f in sorted(sources_list_d.glob("*.list")):
                sources += f"## {f}\n"
                sources += f.read_text() + "\n"
        (metadata_dir / "apt_repos.txt").write_text(sources)
    except Exception as e:
        (metadata_dir / "apt_repos.txt").write_text(
            f"# Could not collect apt repositories: {e}\n"
        )

def backup(args):
    home = Path.home()
    backup_dir = home / "ragnarokbackup"
    backups_dir = backup_dir / "backups"
    list_file = backup_dir / ".ragnarokbackup"
    verbose = args.verbose

    # Zstd check
    if args.compress == "zstd":
        check_zstd()

    # Console info
    if args.dry_run:
        cprint("Running backup in dry-run mode: all files in the archive will be empty.", Colors.OKCYAN)
    else:
        cprint("Running real backup: files will be copied with data.", Colors.OKGREEN)

    cprint("Collecting files and building backup structure...", Colors.OKBLUE)

    # Ensure backup_dir, backups_dir, and .ragnarokbackup exist
    for d in [backup_dir, backups_dir]:
        if not d.exists():
            d.mkdir(parents=True)
            cprint(f"Created directory: {d}", Colors.OKGREEN)
    if not list_file.exists():
        list_file.touch()
        cprint(f"Created file: {list_file}", Colors.OKGREEN)

    # Read list of files/folders to back up
    with open(list_file, "r") as f:
        paths = [line.strip() for line in f if line.strip() and not line.strip().startswith("#")]

    if not paths:
        cprint("No files or folders listed in .ragnarokbackup. Nothing to back up.", Colors.WARNING)
        return

    # Create temp dir for backup structure
    with tempfile.TemporaryDirectory() as tempdir:
        tempdir = Path(tempdir)
        metadata_dir = tempdir / "metadata"
        (metadata_dir).mkdir()
        (tempdir / "home_dirs").mkdir()
        (tempdir / "files").mkdir()
        affiliation = {}

        # --- METADATA COLLECTION ---
        cprint("Collecting system metadata...", Colors.OKBLUE)
        collect_installed_packages(metadata_dir)
        collect_apt_repos(metadata_dir)
        cprint("Created metadata files.", Colors.OKGREEN)

        for path in paths:
            src = Path(path)
            if not src.is_absolute():
                cprint(f"Skipping non-absolute path: {path}", Colors.WARNING)
                continue
            if not src.exists():
                cprint(f"Skipping missing path: {path}", Colors.WARNING)
                continue

            # Determine archive path
            archive_path, top_folder = get_archive_path(src, home)
            dest = tempdir / archive_path

            if src.is_file():
                dest.parent.mkdir(parents=True, exist_ok=True)
                if args.dry_run:
                    dest.touch()
                else:
                    shutil.copy2(src, dest)
                affiliation[str(dest.relative_to(tempdir))] = str(src)
                if verbose:
                    cprint(f"Added file: {src} -> {dest} (empty: {args.dry_run})", Colors.OKCYAN)
            elif src.is_dir():
                for root, dirs, files in os.walk(src):
                    rel_root = Path(root).relative_to(src)
                    for d in dirs:
                        (dest / rel_root / d).mkdir(parents=True, exist_ok=True)
                    for file in files:
                        src_file = Path(root) / file
                        dest_file = dest / rel_root / file
                        dest_file.parent.mkdir(parents=True, exist_ok=True)
                        if args.dry_run:
                            dest_file.touch()
                        else:
                            shutil.copy2(src_file, dest_file)
                        affiliation[str(dest_file.relative_to(tempdir))] = str(src_file)
                        if verbose:
                            cprint(f"Added file: {src_file} -> {dest_file} (empty: {args.dry_run})", Colors.OKCYAN)
            else:
                cprint(f"Skipping unknown path type: {path}", Colors.WARNING)

        # Write affiliation.json
        aff_path = tempdir / "affiliation.json"
        with open(aff_path, "w") as f:
            json.dump(affiliation, f, indent=2)
        cprint(f"Created affiliation.json with {len(affiliation)} entries.", Colors.OKGREEN)

        # Determine output archive path and compression
        from datetime import datetime
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        ext = {
            "none": ".tar",
            "gz": ".tar.gz",
            "zstd": ".tar.zst",
            "zip": ".zip"
        }[args.compress]

        if args.output:
            output_dir = Path(args.output)
            if not output_dir.exists():
                output_dir.mkdir(parents=True)
        else:
            output_dir = backups_dir

        output = output_dir / f"backup_{ts}{ext}"

        cprint(f"Creating archive at: {output}", Colors.HEADER)

        # Compression logic
        if args.compress == "none":
            shutil.make_archive(str(output).replace(".tar", ""), "tar", tempdir)
        elif args.compress == "gz":
            shutil.make_archive(str(output).replace(".tar.gz", ""), "gztar", tempdir)
        elif args.compress == "zip":
            shutil.make_archive(str(output).replace(".zip", ""), "zip", tempdir)
        elif args.compress == "zstd":
            tar_path = str(output).replace(".tar.zst", ".tar")
            shutil.make_archive(tar_path.replace(".tar", ""), "tar", tempdir)
            subprocess.run(["zstd", "-f", tar_path, "-o", str(output)], check=True)
            os.remove(tar_path)
        else:
            cprint(f"Unknown compression: {args.compress}", Colors.FAIL)
            sys.exit(1)

        cprint("Backup complete!", Colors.OKGREEN)

def prompt_overwrite(path):
    while True:
        ans = input(f"File exists: {path}. Overwrite? (y/n): ").strip().lower()
        if ans in ("y", "yes"):
            return True
        elif ans in ("n", "no"):
            return False

def is_same_file(src, dst, verbose=False):
    """Return True if files exist and are byte-for-byte identical."""
    try:
        src_path = Path(src)
        dst_path = Path(dst)
        
        # Check existence first
        if not dst_path.exists() or not dst_path.is_file():
            if verbose:
                cprint(f"Comparison: {dst} does not exist or is not a file", Colors.WARNING)
            return False
        if not src_path.exists() or not src_path.is_file():
            if verbose:
                cprint(f"Comparison: {src} does not exist or is not a file", Colors.WARNING)
            return False
        
        # Check sizes first (quick comparison)
        src_size = src_path.stat().st_size
        dst_size = dst_path.stat().st_size
        if src_size != dst_size:
            if verbose:
                cprint(f"Comparison: File sizes differ - {src}: {src_size} bytes, {dst}: {dst_size} bytes", Colors.WARNING)
            return False
        
        # Do full comparison if sizes match
        is_identical = filecmp.cmp(src, dst, shallow=False)
        if verbose:
            if is_identical:
                cprint(f"Comparison: Files are identical - {src} and {dst}", Colors.OKGREEN)
            else:
                cprint(f"Comparison: Files have different content - {src} and {dst}", Colors.WARNING)
        return is_identical
    except Exception as e:
        cprint(f"Error comparing files: {e}", Colors.WARNING)
        return False

def handle_conflict(src, dst, dry_run, conflict, what="file", verbose=False):
    # First check - dst might not exist yet
    dst_path = Path(dst)
    if not dst_path.exists():
        if dry_run or verbose:
            msg = f"Would restore: {dst}" if dry_run else f"Restored: {dst}"
            cprint(f"[DRY-RUN] {msg}" if dry_run else msg, Colors.OKGREEN)
        return "restore"

    # Now check if identical
    identical = is_same_file(src, dst, verbose)
    if identical:
        # Always show skipping identical messages
        msg = f"Skipping identical {what}: {dst}"
        cprint(f"[DRY-RUN] {msg}" if dry_run else msg, Colors.OKCYAN)
        return "skip"

    # Different file exists - handle conflict
    if conflict == "overwrite":
        if dry_run or verbose:
            msg = f"Would overwrite: {dst}" if dry_run else f"Overwritten: {dst}"
            cprint(f"[DRY-RUN] {msg}" if dry_run else msg, Colors.OKGREEN)
        return "overwrite"
    elif conflict == "skip":
        if dry_run or verbose:
            msg = f"Would skip: {dst}" if dry_run else f"Skipped: {dst}"
            cprint(f"[DRY-RUN] {msg}" if dry_run else msg, Colors.WARNING)
        return "skip"
    else:
        if dry_run:
            cprint(f"[DRY-RUN] Would ask: Overwrite existing {what} {dst}? (y/n)", Colors.OKCYAN)
            return "ask"
        else:
            # Always show prompts
            if prompt_overwrite(dst):
                if verbose:
                    cprint(f"Overwritten: {dst}", Colors.OKGREEN)
                return "overwrite"
            else:
                if verbose:
                    cprint(f"Skipped: {dst}", Colors.WARNING)
                return "skip"

def compare_apt_repos(backup_apt_repos_file, verbose=False):
    """Compare backed up apt repos with current system repos."""
    try:
        # Generate current apt repos content using the same method as backup
        current_sources = ""
        if Path("/etc/apt/sources.list").exists():
            current_sources += "### /etc/apt/sources.list\n"
            current_sources += Path("/etc/apt/sources.list").read_text() + "\n"
        current_sources += "### /etc/apt/sources.list.d/\n"
        sources_list_d = Path("/etc/apt/sources.list.d")
        if sources_list_d.exists():
            for f in sorted(sources_list_d.glob("*.list")):
                current_sources += f"## {f}\n"
                current_sources += f.read_text() + "\n"
        
        # Read backed up sources
        backup_sources = Path(backup_apt_repos_file).read_text()
        
        # Compare
        if current_sources == backup_sources:
            if verbose:
                cprint(f"APT repos are identical to current system", Colors.OKGREEN)
            return True
        else:
            if verbose:
                cprint(f"APT repos differ from current system", Colors.WARNING)
            return False
    except Exception as e:
        cprint(f"Error comparing apt repos: {e}", Colors.WARNING)
        return False

def parse_dpkg_list(dpkg_text):
    """Parse dpkg -l output into a dict of {package: version}."""
    packages = {}
    for line in dpkg_text.splitlines():
        if line.startswith("ii"):
            parts = line.split()
            if len(parts) >= 3:
                pkg, ver = parts[1], parts[2]
                packages[pkg] = ver
    return packages

def get_current_packages():
    """Get currently installed packages and versions as a dict."""
    try:
        output = subprocess.check_output(
            ["dpkg", "-l"], universal_newlines=True
        )
        return parse_dpkg_list(output)
    except Exception as e:
        cprint(f"Error getting current packages: {e}", Colors.WARNING)
        return {}

def handle_package_restore(backup_pkg_file, dry_run=False, verbose=False):
    if not backup_pkg_file.exists():
        cprint("No installed_packages.txt found in backup.", Colors.WARNING)
        return

    # Parse backup packages
    backup_pkgs = parse_dpkg_list(backup_pkg_file.read_text())
    current_pkgs = get_current_packages()

    for pkg, backup_ver in backup_pkgs.items():
        current_ver = current_pkgs.get(pkg)
        if current_ver == backup_ver:
            if verbose:
                cprint(f"Package {pkg} already installed at version {backup_ver}.", Colors.OKCYAN)
            continue
        elif current_ver is None:
            cprint(f"Package {pkg} not installed. Will install version {backup_ver}.", Colors.OKGREEN)
            if not dry_run:
                subprocess.run(["sudo", "apt-get", "install", f"{pkg}={backup_ver}"], check=False)
        else:
            # Compare versions
            from packaging import version
            if version.parse(current_ver) < version.parse(backup_ver):
                # Ask to update
                ans = "y"
                if not dry_run:
                    ans = input(f"Package {pkg} is installed at {current_ver}, backup has newer {backup_ver}. Update? (y/n): ").strip().lower()
                if ans in ("y", "yes"):
                    cprint(f"Updating {pkg} to {backup_ver}.", Colors.OKGREEN)
                    if not dry_run:
                        subprocess.run(["sudo", "apt-get", "install", f"{pkg}={backup_ver}"], check=False)
                else:
                    cprint(f"Skipped updating {pkg}.", Colors.WARNING)
            elif version.parse(current_ver) > version.parse(backup_ver):
                cprint(f"Package {pkg} is installed at newer version {current_ver} than backup {backup_ver}. Skipping downgrade.", Colors.WARNING)
            else:
                # Should not reach here, but just in case
                cprint(f"Package {pkg} version mismatch: current {current_ver}, backup {backup_ver}.", Colors.WARNING)

def restore(args):
    import tempfile
    import zipfile

    backup_file = Path(args.restore)
    dry_run = args.dry_run
    conflict = args.conflict
    verbose = args.verbose

    # 1. Detect archive type and extract
    suffix = "".join(backup_file.suffixes)
    cprint(f"Detected archive type: {suffix}", Colors.OKBLUE)
    tempdir = tempfile.TemporaryDirectory()
    temp_path = Path(tempdir.name)

    # Extraction
    if suffix == ".zip":
        with zipfile.ZipFile(backup_file, "r") as zf:
            zf.extractall(temp_path)
    elif suffix == ".tar":
        with tarfile.open(backup_file, "r") as tf:
            tf.extractall(temp_path)
    elif suffix == ".tar.gz":
        with tarfile.open(backup_file, "r:gz") as tf:
            tf.extractall(temp_path)
    elif suffix == ".tar.zst":
        check_zstd()
        import subprocess
        tmp_tar = temp_path / "archive.tar"
        subprocess.run(["zstd", "-d", "-c", str(backup_file)], stdout=open(tmp_tar, "wb"), check=True)
        with tarfile.open(tmp_tar, "r") as tf:
            tf.extractall(temp_path)
        tmp_tar.unlink()
    else:
        cprint(f"Unknown archive type: {suffix}", Colors.FAIL)
        tempdir.cleanup()
        sys.exit(1)

    cprint(f"Archive extracted to temp dir: {temp_path}", Colors.OKBLUE)

    # 2. Read affiliation.json
    affil_path = temp_path / "affiliation.json"
    if not affil_path.exists():
        cprint("affiliation.json not found in backup!", Colors.FAIL)
        tempdir.cleanup()
        sys.exit(1)
    with open(affil_path, "r") as f:
        affiliation = json.load(f)

    # 3. Handle metadata
    meta_dir = temp_path / "metadata"
    if meta_dir.exists():
        # Make sure metadata dir exists locally before handling files
        local_meta_dir = Path.home() / "ragnarokbackup" / "metadata"
        if not local_meta_dir.exists():
            local_meta_dir.mkdir(parents=True, exist_ok=True)
        
        # Special handling for installed_packages.txt - always skip
        meta_path = meta_dir / "installed_packages.txt"
        if meta_path.exists():
            dst_path = local_meta_dir / "installed_packages.txt"
            # Only show message in dry run or verbose mode
            if dry_run or verbose:
                cprint(f"[DRY-RUN] Ignoring installed packages file: {dst_path}" if dry_run 
                       else f"Ignoring installed packages file: {dst_path}", Colors.OKCYAN)
        
        # Normal handling for apt_repos.txt
        meta_path = meta_dir / "apt_repos.txt"
        if meta_path.exists():
            dst_path = local_meta_dir / "apt_repos.txt"
            
            # Compare with current system rather than destination file
            identical = compare_apt_repos(meta_path, verbose)
            
            if identical:
                # Always show identical messages
                msg = f"Skipping identical APT repositories"
                cprint(f"[DRY-RUN] {msg}" if dry_run else msg, Colors.OKCYAN)
            else:
                if conflict == "overwrite":
                    if dry_run or verbose:
                        msg = f"Would restore APT repositories: {dst_path}" if dry_run else f"Restored APT repositories: {dst_path}"
                        cprint(f"[DRY-RUN] {msg}" if dry_run else msg, Colors.OKGREEN)
                    if not dry_run:
                        dst_path.parent.mkdir(parents=True, exist_ok=True)
                        shutil.copy2(meta_path, dst_path)
                elif conflict == "skip":
                    if dry_run or verbose:
                        msg = f"Would skip APT repositories: {dst_path}" if dry_run else f"Skipped APT repositories: {dst_path}"
                        cprint(f"[DRY-RUN] {msg}" if dry_run else msg, Colors.WARNING)
                else:
                    if dry_run:
                        cprint(f"[DRY-RUN] Would ask: Restore APT repositories to {dst_path}? (y/n)", Colors.OKCYAN)
                    else:
                        # Always show prompts
                        if prompt_overwrite(dst_path):
                            if verbose:
                                cprint(f"Restored APT repositories: {dst_path}", Colors.OKGREEN)
                            dst_path.parent.mkdir(parents=True, exist_ok=True)
                            shutil.copy2(meta_path, dst_path)
                        else:
                            if verbose:
                                cprint(f"Skipped APT repositories: {dst_path}", Colors.WARNING)

        # --- Handle installed packages ---
        meta_path = meta_dir / "installed_packages.txt"
        if meta_path.exists():
            handle_package_restore(meta_path, dry_run=dry_run, verbose=verbose)

    # 4. Restore files
    cprint("Restoring files...", Colors.HEADER)
    for archive_rel, orig_path in affiliation.items():
        src = temp_path / archive_rel
        dst = Path(orig_path)
        if not src.exists():
            cprint(f"Warning: Archive file missing: {archive_rel}", Colors.WARNING)
            continue

        if src.is_file():
            result = handle_conflict(src, dst, dry_run, conflict, what="file", verbose=verbose)
            if result == "restore" and not dry_run:
                dst.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(src, dst)
            elif result == "overwrite" and not dry_run:
                shutil.copy2(src, dst)
        else:
            continue

    cprint("Restore complete!" if not dry_run else "[DRY-RUN] Restore simulation complete!", Colors.OKBLUE)
    tempdir.cleanup()

def main():
    parser = argparse.ArgumentParser(
        description="RagnarokBackup - Simple, powerful backup tool for Linux servers."
    )

    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Simulate backup by creating empty files with correct structure."
    )
    parser.add_argument(
        "--compress",
        choices=["none", "gz", "zstd", "zip"],
        default="none",
        help="Choose compression method."
    )
    parser.add_argument(
        "--output",
        type=str,
        help="Set output path manually."
    )
    parser.add_argument(
        "--verbose",
        action="store_true",
        help="Enable detailed output."
    )
    parser.add_argument(
        "--prebak",
        type=str,
        help="Script to run before backup (local path or URL)."
    )
    parser.add_argument(
        "--postbak",
        type=str,
        help="Script to run after backup (local path or URL)."
    )
    parser.add_argument(
        "--prerest",
        type=str,
        help="Script to run before restore (local path or URL)."
    )
    parser.add_argument(
        "--postrest",
        type=str,
        help="Script to run after restore (local path or URL)."
    )

    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument(
        "--backup",
        action="store_true",
        help="Create a backup."
    )
    group.add_argument(
        "--restore",
        type=str,
        metavar="BACKUP_FILE",
        help="Restore backup from a specified archive."
    )
    parser.add_argument(
        "--conflict",
        choices=["overwrite", "skip"],
        help="On restore, choose whether to overwrite or skip existing files. If not set, will prompt for each conflict."
    )

    args = parser.parse_args()

    if args.backup:
        backup(args)
    elif args.restore:
        restore(args)

if __name__ == "__main__":
    main()
