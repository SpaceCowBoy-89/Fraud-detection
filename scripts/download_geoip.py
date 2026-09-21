"""
Download GeoIP databases from db-ip.com (free, no registration required).

  City database  : ~40 MB compressed → ~65 MB uncompressed
  ASN  database  : ~10 MB compressed → ~16 MB uncompressed

Saves to data/GeoLite2-City.mmdb and data/GeoLite2-ASN.mmdb so they match
the default paths in config.py.

Usage:
    python3 scripts/download_geoip.py
"""

import os
import sys
import urllib.request
from datetime import datetime

DATA_DIR = os.path.join(os.path.dirname(__file__), "..", "data")

DATABASES = [
    {
        "url": "https://github.com/P3TERX/GeoLite.mmdb/raw/download/GeoLite2-City.mmdb",
        "dest": os.path.join(DATA_DIR, "GeoLite2-City.mmdb"),
        "label": "City (geo mismatch / country / state)",
    },
    {
        "url": "https://github.com/P3TERX/GeoLite.mmdb/raw/download/GeoLite2-ASN.mmdb",
        "dest": os.path.join(DATA_DIR, "GeoLite2-ASN.mmdb"),
        "label": "ASN (datacenter / VPN detection)",
    },
]


def _download(url: str, dest: str, label: str):
    print(f"\nDownloading {label}...")
    print(f"  URL : {url}")
    print(f"  Dest: {dest}")

    def _progress(count, block, total):
        if total > 0:
            pct = min(100, int(count * block * 100 / total))
            print(f"\r  {pct}% ", end="", flush=True)

    try:
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(req) as resp, open(dest, "wb") as f_out:
            total = int(resp.headers.get("Content-Length", 0))
            downloaded = 0
            block = 65536
            while True:
                chunk = resp.read(block)
                if not chunk:
                    break
                f_out.write(chunk)
                downloaded += len(chunk)
                if total > 0:
                    pct = min(100, int(downloaded * 100 / total))
                    print(f"\r  {pct}% ({downloaded // 1_048_576} MB / {total // 1_048_576} MB) ", end="", flush=True)
        print()
        size_mb = os.path.getsize(dest) / 1_048_576
        print(f"  Done ({size_mb:.1f} MB)")
        return True
    except Exception as exc:
        print(f"\n  ERROR downloading: {exc}")
        if os.path.exists(dest):
            os.remove(dest)
        return False


def main():
    os.makedirs(DATA_DIR, exist_ok=True)

    success = 0
    for db in DATABASES:
        if _download(db["url"], db["dest"], db["label"]):
            success += 1

    print(f"\n{'='*50}")
    if success == len(DATABASES):
        print(f"All {success} databases downloaded successfully.")
        print("Restart the dashboard server to activate GeoIP rules.")
    else:
        failed = len(DATABASES) - success
        print(f"{success} succeeded, {failed} failed.")
        print("Check your internet connection and try again.")
        sys.exit(1)


if __name__ == "__main__":
    main()
