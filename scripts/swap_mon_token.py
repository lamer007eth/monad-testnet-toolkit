# -*- coding: utf-8 -*-
import os, time, random
from pathlib import Path
from web3 import Web3
from dotenv import load_dotenv


def _project_root() -> Path:
    return Path(__file__).resolve().parents[1]


def _load_env():
    load_dotenv(_project_root() / ".env")


def _paths():
    root = _project_root()
    wallets = Path(os.getenv("WALLETS_FILE", root / "data" / "wallets.txt"))
    txlog = Path(os.getenv("TX_LOG_FILE", root / "data" / "txhashes.txt"))
    return wallets, txlog


def _rpc_url() -> str:
    rpc = (os.getenv("RPC_URL") or "").strip()
    if rpc:
        return rpc
    api_key = (os.getenv("YOUR_API_KEY") or "").strip()
    if not api_key:
        raise RuntimeError("Нет RPC_URL и нет YOUR_API_KEY в .env")
    return f"https://monad-testnet.g.alchemy.com/v2/{api_key}"


# ====== КОНСТАНТЫ СЕТИ / КОНТРАКТОВ ======
V2_ROUTER = os.getenv("V2_ROUTER", "0xfb8e1c3b833f9e67a71c859a132cf783b645e436")

TOKENS = {
    "USDC": "0xf817257fed379853cDe0fa4F97AB987181B1E5Ea",
    "USDT": "0x88b8E2161DEDC77EF4ab7585569D2415a1C1055D",
    "WMON": "0x760AfE86e5de5fa0Ee542fc7B7B713e1c5425701",
    "YAKI": "0xfe140e1dCe99Be9F4F15d657CD9b7BF622270C50",
    "CHOG": "0xE0590015A873bF326bd645c3E1266d4db41C4E6B",
    "DAK":  "0x0F0BDEbF0F83cD1EE3974779Bcb7315f9808c714",
}

# ====== ПАРАМЕТРЫ СВАПА ======
SLIPPAGE_BPS   = 500
DEADLINE_SEC   = 300
GAS_LIMIT_SWAP = 180_000
GAS_LIMIT_WRAP = 80_000
RANDOM_DELAY_S = (3, 10)


ERC20_ABI = [{"name":"decimals","stateMutability":"view","type":"function","inputs":[],"outputs":[{"type":"uint8"}]}]
ROUTER_ABI = [
    {"name":"WETH","stateMutability":"view","type":"function","inputs":[],"outputs":[{"type":"address"}]},
    {"name":"getAmountsIn","stateMutability":"view","type":"function",
     "inputs":[{"name":"amountOut","type":"uint256"},{"name":"path","type":"address[]"}],
     "outputs":[{"name":"","type":"uint256[]"}]},
    {"name":"swapETHForExactTokens","stateMutability":"payable","type":"function",
     "inputs":[
        {"name":"amountOut","type":"uint256"},
        {"name":"path","type":"address[]"},
        {"name":"to","type":"address"},
        {"name":"deadline","type":"uint256"}
     ],
     "outputs":[{"name":"","type":"uint256[]"}]},
]
WMON_ABI = [{"name":"deposit","stateMutability":"payable","type":"function","inputs":[],"outputs":[]}]


def _derive_wallets(w3: Web3, path: Path) -> dict[str, str]:
    if not path.exists():
        raise RuntimeError(f"wallets not found: {path}")
    raw = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        a, p = line.split("=", 1)
        raw[a.strip()] = p.strip()

    ok = {}
    for shown, pk in raw.items():
        try:
            real = w3.eth.account.from_key(pk).address
        except Exception:
            print(f"⚠️ skip bad key: {shown[:8]}…")
            continue
        shown = Web3.to_checksum_address(shown)
        real = Web3.to_checksum_address(real)
        if shown != real:
            print(f"⚠️ mismatch: file {shown} != pk {real}. Using {real}.")
        ok[real] = pk
    return ok


def _short(addr: str) -> str:
    a = Web3.to_checksum_address(addr)
    return f"{a[:8]}…{a[-4:]}"


def run():
    _load_env()
    wallets_path, txlog_path = _paths()

    w3 = Web3(Web3.HTTPProvider(_rpc_url()))
    if not w3.is_connected():
        raise RuntimeError("Web3 not connected (RPC)")
    print("✅ Swap MON→Token: Web3 connected")
    print(f"ℹ️ Chain ID: {w3.eth.chain_id}")

    router = w3.eth.contract(address=Web3.to_checksum_address(V2_ROUTER), abi=ROUTER_ABI)
    WMON_from_router = router.functions.WETH().call()
    wmon_contract = w3.eth.contract(address=WMON_from_router, abi=WMON_ABI)

    wallets = _derive_wallets(w3, wallets_path)
    if not wallets:
        raise RuntimeError("No wallets loaded")

    print("\n🎯 Что покупаем за MON?")
    keys = list(TOKENS.keys())
    for i, k in enumerate(keys, start=1):
        print(f" {i}) {k}")
    idx = int(input("> номер: ").strip())
    sym = keys[idx - 1]
    token_addr = Web3.to_checksum_address(TOKENS[sym])

    token_dec = 18
    if sym.upper() != "WMON":
        token_dec = w3.eth.contract(address=token_addr, abi=ERC20_ABI).functions.decimals().call()

    lo_amt = float(input("📉 min amountOut: ").strip())
    hi_amt = float(input("📈 max amountOut: ").strip())

    rounds = int(input("🔁 rounds: ").strip())

    def build_wrap_tx(amount_out_wei: int, to_addr: str, nonce: int):
        tx = wmon_contract.functions.deposit().build_transaction({
            "from": to_addr,
            "nonce": nonce,
            "value": amount_out_wei,
            "gas": GAS_LIMIT_WRAP,
            "gasPrice": w3.eth.gas_price,
        })
        return tx

    def build_swap_tx(amount_out: int, to_addr: str, nonce: int, deadline: int):
        path = [WMON_from_router, token_addr]
        quote_in = router.functions.getAmountsIn(amount_out, path).call()[0]
        amount_in_max = int(quote_in * (1 + SLIPPAGE_BPS / 10_000))

        tx = router.functions.swapETHForExactTokens(
            amount_out, path, to_addr, deadline
        ).build_transaction({
            "from": to_addr,
            "nonce": nonce,
            "value": amount_in_max,
            "gas": GAS_LIMIT_SWAP,
            "gasPrice": w3.eth.gas_price,
        })
        return tx

    txlog_path.parent.mkdir(parents=True, exist_ok=True)

    for r in range(1, rounds + 1):
        print(f"\n=== ROUND {r}/{rounds} ===")
        items = list(wallets.items())
        random.shuffle(items)

        for addr, pk in items:
            try:
                wallet = Web3.to_checksum_address(addr)
                target = round(random.uniform(lo_amt, hi_amt), min(token_dec, 6))
                amount_out = int(target * (10 ** token_dec))
                deadline = int(time.time()) + DEADLINE_SEC

                nonce = w3.eth.get_transaction_count(wallet)

                if sym.upper() == "WMON":
                    print(f"   → {_short(wallet)} wrap ≈ {target} WMON")
                    tx = build_wrap_tx(amount_out, wallet, nonce)
                else:
                    print(f"   → {_short(wallet)} buy ≈ {target} {sym}")
                    tx = build_swap_tx(amount_out, wallet, nonce, deadline)

                signed = w3.eth.account.sign_transaction(tx, pk)
                tx_hash = w3.eth.send_raw_transaction(signed.raw_transaction).hex()
                print(f"✅ tx: {tx_hash}")

                with txlog_path.open("a", encoding="utf-8") as f:
                    f.write(tx_hash + "\n")

            except Exception as e:
                print(f"❌ {_short(addr)} swap error: {e}")

            time.sleep(random.randint(*RANDOM_DELAY_S))

    print("\n🎉 Swap MON→Token done.")


if __name__ == "__main__":
    run()
