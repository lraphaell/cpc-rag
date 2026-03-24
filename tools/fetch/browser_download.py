#!/usr/bin/env python3
"""
Browser-automated download for Google Workspace files blocked by org policy.

Uses Selenium + Chrome with the user's existing profile (already logged into Google)
to download files that the Drive API cannot export (403 org policy).

Strategy:
1. Try direct export URL first (fastest)
2. Fall back to UI automation (File menu > Download > Format)

Usage:
    PYTHONPATH=. python tools/fetch/browser_download.py
    PYTHONPATH=. python tools/fetch/browser_download.py --test     # Test with 1 file
    PYTHONPATH=. python tools/fetch/browser_download.py --dry-run  # Show what would be downloaded
"""

import json
import os
import sys
import time
import glob
import shutil
import argparse
from pathlib import Path
from datetime import datetime, timezone

import chromedriver_autoinstaller
from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.common.by import By
from selenium.webdriver.common.keys import Keys
from selenium.webdriver.common.action_chains import ActionChains
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC

# Paths
PROJECT_DIR = Path(__file__).resolve().parent.parent.parent
TMP_DIR = PROJECT_DIR / ".tmp"
DOWNLOADS_DIR = TMP_DIR / "downloads"
BROWSER_DL_DIR = TMP_DIR / "browser_downloads"  # Temp dir for Selenium downloads

# Chrome user profile
CHROME_PROFILE_DIR = Path.home() / "Library" / "Application Support" / "Google" / "Chrome"

# Export URL templates for Google Workspace files
EXPORT_URLS = {
    "google_slides": "https://docs.google.com/presentation/d/{file_id}/export/pptx",
    "google_doc": "https://docs.google.com/document/d/{file_id}/export?format=docx",
    "google_sheet": "https://docs.google.com/spreadsheets/d/{file_id}/export?format=xlsx",
}

# Expected extensions per type
TYPE_EXTENSIONS = {
    "google_slides": ".pptx",
    "google_doc": ".docx",
    "google_sheet": ".xlsx",
}

# File menu xpath (from user) and download menu items
FILE_MENU_XPATH = "/html/body/div[2]/div[5]/div[1]/div[1]/div[1]"


def get_failed_files():
    """Load the list of files that failed API download (403 only, not 404)."""
    results_path = TMP_DIR / "retry_download_results.json"
    manifest_path = TMP_DIR / "manual_download_manifest.json"

    if not results_path.exists() or not manifest_path.exists():
        print("ERROR: Missing retry_download_results.json or manual_download_manifest.json")
        sys.exit(1)

    with open(results_path) as f:
        results = json.load(f)
    with open(manifest_path) as f:
        manifest = json.load(f)

    # Build manifest lookup
    manifest_map = {e["drive_id"]: e for e in manifest["changes"]}

    # Filter: only 403 failures (not 404)
    failed_403 = []
    for entry in results.get("failed", []):
        if "404" in entry.get("error", ""):
            continue  # Skip deleted files

        drive_id = entry["drive_id"]
        manifest_entry = manifest_map.get(drive_id, {})

        failed_403.append({
            "drive_id": drive_id,
            "name": entry.get("name", manifest_entry.get("name", "")),
            "drive_type": manifest_entry.get("drive_type", ""),
            "url": manifest_entry.get("url", ""),
            "expected_ext": manifest_entry.get("expected_ext", ""),
        })

    return failed_403


def setup_chrome_driver():
    """Set up Chrome WebDriver with user's existing profile."""
    chromedriver_autoinstaller.install()

    BROWSER_DL_DIR.mkdir(parents=True, exist_ok=True)

    options = Options()
    # Use existing Chrome profile for Google auth
    options.add_argument(f"--user-data-dir={CHROME_PROFILE_DIR}")
    options.add_argument("--profile-directory=Default")
    # Download settings
    options.add_experimental_option("prefs", {
        "download.default_directory": str(BROWSER_DL_DIR.resolve()),
        "download.prompt_for_download": False,
        "download.directory_upgrade": True,
        "safebrowsing.enabled": True,
    })
    # Suppress automation warnings
    options.add_experimental_option("excludeSwitches", ["enable-automation"])
    options.add_argument("--disable-blink-features=AutomationControlled")
    # Visible mode (needed for Google auth)
    # options.add_argument("--headless")  # DO NOT use headless

    driver = webdriver.Chrome(options=options)
    driver.set_window_size(1200, 800)
    return driver


def wait_for_download(timeout=60):
    """Wait for a new file to appear in BROWSER_DL_DIR (not .crdownload)."""
    start = time.time()
    initial_files = set(BROWSER_DL_DIR.glob("*"))

    while time.time() - start < timeout:
        current_files = set(BROWSER_DL_DIR.glob("*"))
        new_files = current_files - initial_files
        # Filter out partial downloads
        completed = [f for f in new_files if not f.name.endswith(".crdownload")]
        if completed:
            return completed[0]
        time.sleep(1)

    return None


def download_via_export_url(driver, file_entry):
    """Try downloading via direct export URL."""
    drive_type = file_entry["drive_type"]
    drive_id = file_entry["drive_id"]

    url_template = EXPORT_URLS.get(drive_type)
    if not url_template:
        return None

    export_url = url_template.format(file_id=drive_id)

    # Clear temp download dir
    for f in BROWSER_DL_DIR.glob("*"):
        f.unlink()

    driver.get(export_url)
    downloaded = wait_for_download(timeout=60)

    if downloaded:
        return downloaded

    # Check if we got an error page instead of download
    try:
        page_text = driver.find_element(By.TAG_NAME, "body").text.lower()
        if "denied" in page_text or "error" in page_text or "unable" in page_text:
            return None
    except Exception:
        pass

    return None


def download_via_ui_click(driver, file_entry):
    """Fall back to UI automation: File > Download > Format."""
    url = file_entry["url"]
    drive_type = file_entry["drive_type"]

    if not url:
        return None

    # Clear temp download dir
    for f in BROWSER_DL_DIR.glob("*"):
        f.unlink()

    # Navigate to the editor
    driver.get(url)
    time.sleep(5)  # Wait for page to fully load

    try:
        # Click File menu
        try:
            file_menu = WebDriverWait(driver, 10).until(
                EC.element_to_be_clickable((By.XPATH, FILE_MENU_XPATH))
            )
            file_menu.click()
        except Exception:
            # Fallback: try aria-label based selector
            try:
                file_menu = driver.find_element(By.CSS_SELECTOR, '[aria-label="File"]')
                file_menu.click()
            except Exception:
                try:
                    file_menu = driver.find_element(By.CSS_SELECTOR, '[aria-label="Archivo"]')
                    file_menu.click()
                except Exception:
                    return None

        time.sleep(1)

        # Click "Download" submenu
        download_items = driver.find_elements(By.XPATH,
            "//*[contains(text(), 'Download') or contains(text(), 'Descargar') or contains(text(), 'Baixar')]"
        )
        for item in download_items:
            try:
                if item.is_displayed():
                    item.click()
                    break
            except Exception:
                continue
        else:
            return None

        time.sleep(1)

        # Click the format option
        format_labels = {
            "google_slides": ["PowerPoint", ".pptx", "Microsoft PowerPoint"],
            "google_doc": ["Word", ".docx", "Microsoft Word"],
            "google_sheet": ["Excel", ".xlsx", "Microsoft Excel"],
        }

        labels = format_labels.get(drive_type, [])
        for label in labels:
            try:
                format_items = driver.find_elements(By.XPATH,
                    f"//*[contains(text(), '{label}')]"
                )
                for fi in format_items:
                    if fi.is_displayed():
                        fi.click()
                        break
                break
            except Exception:
                continue

        # Wait for download
        downloaded = wait_for_download(timeout=90)
        return downloaded

    except Exception as e:
        print(f"    UI click failed: {e}")
        return None


def download_file(driver, file_entry):
    """Download a single file using export URL first, then UI fallback."""
    name = file_entry["name"]
    drive_id = file_entry["drive_id"]
    drive_type = file_entry["drive_type"]
    ext = TYPE_EXTENSIONS.get(drive_type, file_entry.get("expected_ext", ""))

    print(f"\n  Downloading: {name[:60]}...")

    # Strategy 1: Export URL
    print(f"    Trying export URL...", end=" ")
    downloaded = download_via_export_url(driver, file_entry)

    if downloaded:
        print(f"OK ({downloaded.stat().st_size:,} bytes)")
    else:
        print("FAILED")
        # Strategy 2: UI click
        print(f"    Trying UI automation...", end=" ")
        downloaded = download_via_ui_click(driver, file_entry)

        if downloaded:
            print(f"OK ({downloaded.stat().st_size:,} bytes)")
        else:
            print("FAILED")
            return {"drive_id": drive_id, "name": name, "status": "failed"}

    # Move and rename to final location
    DOWNLOADS_DIR.mkdir(parents=True, exist_ok=True)
    final_name = f"{drive_id}{ext}" if ext else downloaded.name
    final_path = DOWNLOADS_DIR / final_name
    shutil.move(str(downloaded), str(final_path))

    return {
        "drive_id": drive_id,
        "name": name,
        "status": "downloaded",
        "path": str(final_path),
        "size": final_path.stat().st_size,
    }


def main():
    parser = argparse.ArgumentParser(description="Browser-automated download for blocked files")
    parser.add_argument("--test", action="store_true", help="Test with just 1 file")
    parser.add_argument("--dry-run", action="store_true", help="Show what would be downloaded")
    args = parser.parse_args()

    files = get_failed_files()

    # Filter out already downloaded/cleaned
    cleaned_ids = set()
    if (TMP_DIR / "cleaned").exists():
        cleaned_ids = {f.stem for f in (TMP_DIR / "cleaned").glob("*.json")}

    # Also check retry results for already downloaded
    downloaded_ids = set()
    retry_path = TMP_DIR / "retry_download_results.json"
    if retry_path.exists():
        with open(retry_path) as f:
            retry = json.load(f)
        downloaded_ids = {e["drive_id"] for e in retry.get("success", [])}

    to_download = [f for f in files if f["drive_id"] not in cleaned_ids and f["drive_id"] not in downloaded_ids]

    print(f"Files to download: {len(to_download)} (of {len(files)} failed)")
    print(f"Already cleaned: {len([f for f in files if f['drive_id'] in cleaned_ids])}")
    print(f"Already downloaded: {len([f for f in files if f['drive_id'] in downloaded_ids])}")

    if args.test:
        to_download = to_download[:1]
        print(f"TEST MODE: downloading only 1 file")

    if args.dry_run:
        for f in to_download:
            print(f"  [{f['drive_type']}] {f['name'][:60]}")
        return

    if not to_download:
        print("Nothing to download!")
        return

    # Set up Chrome
    print("\nStarting Chrome with your profile...")
    print("NOTE: Please close any existing Chrome windows first!")
    print("(Selenium needs exclusive access to the Chrome profile)")
    input("Press Enter when ready...")

    driver = setup_chrome_driver()

    results = {"success": [], "failed": []}

    try:
        for i, entry in enumerate(to_download, 1):
            print(f"\n[{i}/{len(to_download)}]", end="")
            result = download_file(driver, entry)

            if result["status"] == "downloaded":
                results["success"].append(result)
            else:
                results["failed"].append(result)

            # Brief pause between downloads
            time.sleep(2)

    finally:
        driver.quit()

    # Summary
    print(f"\n{'='*60}")
    print(f"Downloaded: {len(results['success'])}")
    print(f"Failed:     {len(results['failed'])}")

    if results["failed"]:
        print("\nFailed files (need manual download):")
        for f in results["failed"]:
            print(f"  - {f['name']}")

    # Save results
    log_path = TMP_DIR / "browser_download_results.json"
    with open(log_path, "w") as f:
        json.dump({
            "downloaded_at": datetime.now(timezone.utc).isoformat(),
            **results,
        }, f, indent=2, ensure_ascii=False)
    print(f"\nResults saved to: {log_path}")

    # Update retry_download_results.json with new successes
    if results["success"] and retry_path.exists():
        with open(retry_path) as f:
            retry = json.load(f)
        retry["success"].extend(results["success"])
        with open(retry_path, "w") as f:
            json.dump(retry, f, indent=2, ensure_ascii=False)
        print(f"Updated retry_download_results.json with {len(results['success'])} new downloads")


if __name__ == "__main__":
    main()
