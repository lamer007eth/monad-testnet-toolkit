import os
import sys
import subprocess
from pathlib import Path
from datetime import datetime

# =========================================
# Project paths
# =========================================
BASE_DIR = Path(__file__).resolve().parent
SCRIPTS_DIR = BASE_DIR / "scripts"
DATA_DIR = BASE_DIR / "data"
LOGS_DIR = BASE_DIR / "logs"

WALLETS_FILE = DATA_DIR / "wallets.txt"
TXHASHES_FILE = DATA_DIR / "txhashes.txt"

# Make sure folders exist (Git doesn't store empty folders)
DATA_DIR.mkdir(exist_ok=True)
LOGS_DIR.mkdir(exist_ok=True)

# =========================================
# Script registry
# (Rename files in scripts/ accordingly)
# =========================================
SCRIPTS = {
    "1": ("SWAP MON → TOKEN", SCRIPTS_DIR / "swap_mon_token.py"),
    "2": ("SWAP TOKEN → MON", SCRIPTS_DIR / "swap_token_mon.py"),
    "3": ("ADD LIQUIDITY",    SCRIPTS_DIR / "add_liq.py"),
    "4": ("REMOVE LIQUIDITY", SCRIPTS_DIR / "remove_liq.py"),
    "6": ("MINT",             SCRIPTS_DIR / "mint.py"),
}

# Optional extra tools
TOOLS = {
    "7": ("OPEN TXHASHES LOG", TXHASHES_FILE),
    "8": ("OPEN WALLETS FILE", WALLETS_FILE),
}

# =========================================
# Helpers
# =========================================
def clear():
    os.system("cls" if os.name == "nt" else "clear")


def banner():
    print("=" * 64)
    print("🧪 MONAD TESTNET AUTOMATION SUITE")
    print(f"📁 Base: {BASE_DIR}")
    print(f"🐍 Python: {sys.executable}")
    print("=" * 64)


def ensure_exists(path: Path, kind: str = "file"):
    if kind == "file" and not path.exists():
        print(f"⚠️ Not found: {path}")
        if path == WALLETS_FILE:
            print("➡️ Create it at: data/wallets.txt")
            print("   Format: address=private_key  (one per line)")
        return False
    if kind == "dir" and not path.exists():
        path.mkdir(parents=True, exist_ok=True)
    return True


def run_script(script_path: Path):
    if not ensure_exists(script_path, "file"):
        print("❌ Script missing. Fix file name/location in scripts/ folder.")
        input("\nPress Enter...")
        return

    # Pass useful env vars to child scripts (optional)
    env = os.environ.copy()
    env["WALLETS_FILE"] = str(WALLETS_FILE)
    env["TX_LOG_FILE"] = str(TXHASHES_FILE)

    print("\n" + "-" * 64)
    print(f"🚀 Running: {script_path.name}")
    print("-" * 64)

    # Run with same python interpreter
    try:
        subprocess.run([sys.executable, str(script_path)], env=env, check=False)
    except KeyboardInterrupt:
        print("\n🛑 Interrupted by user.")
    except Exception as e:
        print(f"\n❌ Failed to run script: {e}")

    input("\nPress Enter to return to menu...")


def open_file(path: Path):
    if not ensure_exists(path, "file"):
        input("\nPress Enter...")
        return

    # Windows: start, macOS: open, Linux: xdg-open
    try:
        if os.name == "nt":
            os.startfile(path)  # type: ignore[attr-defined]
        elif sys.platform == "darwin":
            subprocess.run(["open", str(path)], check=False)
        else:
            subprocess.run(["xdg-open", str(path)], check=False)
    except Exception as e:
        print(f"❌ Could not open file: {e}")
        input("\nPress Enter...")


def status_block():
    print("\n📌 Status")
    print(f"  wallets:  {WALLETS_FILE} {'✅' if WALLETS_FILE.exists() else '❌'}")
    print(f"  tx log:   {TXHASHES_FILE} {'✅' if TXHASHES_FILE.exists() else '⚪️'}")
    print(f"  scripts:  {SCRIPTS_DIR} {'✅' if SCRIPTS_DIR.exists() else '❌'}")

    if WALLETS_FILE.exists():
        try:
            lines = [l.strip() for l in WALLETS_FILE.read_text(encoding="utf-8").splitlines() if l.strip() and not l.strip().startswith("#")]
            print(f"  wallets loaded: {len(lines)}")
        except Exception:
            pass


def menu():
    clear()
    banner()
    status_block()

    print("\n🧩 Actions")
    for k, (title, path) in SCRIPTS.items():
        exists = "✅" if Path(path).exists() else "❌"
        print(f"  [{k}] {title:<18} {exists}  ({Path(path).name})")

    print("\n🧰 Tools")
    for k, (title, path) in TOOLS.items():
        print(f"  [{k}] {title}")

    print("\n  [0] Exit")
    print("-" * 64)


def main():
    # sanity folders
    ensure_exists(SCRIPTS_DIR, "dir")
    ensure_exists(DATA_DIR, "dir")
    ensure_exists(LOGS_DIR, "dir")

    # Create empty tx log if missing (optional)
    if not TXHASHES_FILE.exists():
        try:
            TXHASHES_FILE.write_text("", encoding="utf-8")
        except Exception:
            pass

    while True:
        menu()
        choice = input("Select: ").strip()

        if choice == "0":
            print("\n👋 Bye")
            break

        if choice in SCRIPTS:
            _, script_path = SCRIPTS[choice]
            run_script(Path(script_path))
            continue

        if choice in TOOLS:
            _, path = TOOLS[choice]
            open_file(Path(path))
            continue

        print("❌ Unknown option")
        input("Press Enter...")


if __name__ == "__main__":
    main()
