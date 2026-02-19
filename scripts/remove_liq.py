# -*- coding: utf-8 -*-
"""
Remove liquidity from TOKEN / MON pool on Monad testnet (UniswapV2Router02 style).

Expected project structure:
- .env (repo root)
- data/wallets.txt   (address=private_key per line)
- data/txhashes.txt  (appends tx hashes)
- config/router_abi.json (optional; fallback ABI used if missing)

This script is designed to be launched from main.py (calls run()).
"""

import os
import time
import random
from pathlib import Path

from web3 import Web3
from dotenv import load_dotenv


DEFAULT_V2_ROUTER = "0xfb8e1c3b833f9e67a71c859a132cf783b645e436"

TOKENS = {
    "USDC": "0xf817257fed379853cDe0fa4F97AB987181B1E5Ea",
    "USDT": "0x88b8E2161DEDC77EF4ab7585569D2415a1C1055D",
    "YAKI": "0xfe140e1dCe99Be9F4F15d657CD9b7BF622270C50",
    "CHOG": "0xE0590015A873bF326bd645c3E1266d4db41C4E6B",
    "DAK":  "0x0F0BDEbF0F83cD1EE3974779Bcb7315f9808c714",
}
# (WMON not included — removing from TOKEN/ETH pool)

SLIPPAGE_BPS = 500
DEADLINE_SEC = 300

GAS_LIMIT_APPROVE = 60_000
GAS_LIMIT_REMOVE  = 260_000

BUMP_EVERY_SEC = 15
MAX_BUMPS      = 6
TIP_GWEI_START = 2.0
TIP_GWEI_STEP  = 1.25
FEE_MULT_START = 2.0
FEE_MULT_STEP  = 1.15

RANDOM_DELAY_S = (3, 10)
MAX_UINT256    = (1 << 256) - 1


# ====== ABIs ======
ERC20_ABI = [
    {"name": "decimals", "stateMutability": "view", "type": "function", "inputs": [], "outputs": [{"type": "uint8"}]},
    {"name": "balanceOf", "stateMutability": "view", "type": "function",
     "inputs": [{"name": "owner", "type": "address"}], "outputs": [{"type": "uint256"}]},
    {"name": "allowance", "stateMutability": "view", "type": "function",
     "inputs": [{"name": "owner", "type": "address"}, {"name": "spender", "type": "address"}], "outputs": [{"type": "uint256"}]},
    {"name": "approve", "stateMutability": "nonpayable", "type": "function",
     "inputs": [{"name": "spender", "type": "address"}, {"name": "amount", "type": "uint256"}], "outputs": [{"type": "bool"}]},
]

ROUTER_ABI_MIN = [
    {"name": "WETH", "stateMutability": "view", "type": "function", "inputs": [], "outputs": [{"type": "address"}]},
    {"name": "factory", "stateMutability": "view", "type": "function", "inputs": [], "outputs": [{"type": "address"}]},
    {"name": "removeLiquidityETH", "stateMutability": "nonpayable", "type": "function",
     "inputs": [
         {"name": "token", "type": "address"},
         {"name": "liquidity", "type": "uint256"},
         {"name": "amountTokenMin", "type": "uint256"},
         {"name": "amountETHMin", "type": "uint256"},
         {"name": "to", "type": "address"},
         {"name": "deadline", "type": "uint256"},
     ],
     "outputs": [{"name": "amountToken", "type": "uint256"}, {"name": "amountETH", "type": "uint256"}]},
]

FACTORY_ABI = [
    {"name": "getPair", "stateMutability": "view", "type": "function",
     "inputs": [{"name": "tokenA", "type": "address"}, {"name": "tokenB", "type": "address"}],
     "outputs": [{"name": "pair", "type": "address"}]},
]

PAIR_ABI = [
    {"name": "getReserves", "stateMutability": "view", "type": "function",
     "inputs": [], "outputs": [{"type": "uint112"}, {"type": "uint112"}, {"type": "uint32"}]},
    {"name": "token0", "stateMutability": "view", "type": "function", "inputs": [], "outputs": [{"type": "address"}]},
    {"name": "token1", "stateMutability": "view", "type": "function", "inputs": [], "outputs": [{"type": "address"}]},
    {"name": "totalSupply", "stateMutability": "view", "type": "function", "inputs": [], "outputs": [{"type": "uint256"}]},
]


def _project_root() -> Path:
    return Path(__file__).resolve().parents[1]


def _load_env():
    load_dotenv(_project_root() / ".env")


def _rpc_url() -> str:
    rpc = (os.getenv("RPC_URL") or "").strip()
    if rpc:
        return rpc
    api_key = (os.getenv("YOUR_API_KEY") or "").strip()
    if not api_key:
        raise RuntimeError("Missing RPC_URL or YOUR_API_KEY in .env")
    return f"https://monad-testnet.g.alchemy.com/v2/{api_key}"


def _paths() -> tuple[Path, Path]:
    root = _project_root()
    wallets = Path(os.getenv("WALLETS_FILE", root / "data" / "wallets.txt"))
    txlog = Path(os.getenv("TX_LOG_FILE", root / "data" / "txhashes.txt"))
    return wallets, txlog


def _load_router_abi() -> list:
    cfg = _project_root() / "config" / "router_abi.json"
    if cfg.exists():
        try:
            import json
            return json.loads(cfg.read_text(encoding="utf-8"))
        except Exception:
            pass
    return ROUTER_ABI_MIN


def short(addr: str) -> str:
    a = Web3.to_checksum_address(addr)
    return f"{a[:8]}…{a[-4:]}"


def derive_wallets(w3: Web3, path: Path) -> dict[str, str]:
    if not path.exists():
        raise RuntimeError(f"wallets file not found: {path}")

    raw: dict[str, str] = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        a, p = line.split("=", 1)
        raw[a.strip()] = p.strip()

    ok: dict[str, str] = {}
    for shown, pk in raw.items():
        try:
            real = w3.eth.account.from_key(pk).address
        except Exception:
            print(f"⚠️ bad key: {shown[:8]}…")
            continue
        ok[Web3.to_checksum_address(real)] = pk
    return ok


def ask_token_choice() -> tuple[str, str]:
    keys = list(TOKENS.keys())
    print("\n🎯 Choose token to REMOVE liquidity from (TOKEN/MON):")
    for i, k in enumerate(keys, start=1):
        print(f" {i}) {k}")
    idx = int(input("> number: ").strip())
    sym = keys[idx - 1]
    return sym, Web3.to_checksum_address(TOKENS[sym])


def ask_percent_range() -> tuple[float, float, int]:
    raw = input("📊 Percent range to remove (min max), Enter=100 100: ").strip()
    if raw:
        a, b = raw.replace(",", " ").split()
        pmin, pmax = float(a), float(b)
    else:
        pmin, pmax = 100.0, 100.0
    rounds = int(input("🔁 rounds: ").strip())
    return pmin, pmax, rounds


def ensure_allowance_lp(w3: Web3, lp_token, owner: str, pk: str, spender: str, need: int, txlog_path: Path):
    allowance = lp_token.functions.allowance(owner, spender).call()
    if allowance >= need:
        return

    base = w3.eth.get_block("pending").get("baseFeePerGas", w3.eth.gas_price)
    tip = w3.to_wei(TIP_GWEI_START, "gwei")
    maxfee = int(base * FEE_MULT_START + tip)

    tx = lp_token.functions.approve(spender, MAX_UINT256).build_transaction({
        "from": owner,
        "nonce": w3.eth.get_transaction_count(owner),
        "gas": GAS_LIMIT_APPROVE,
        "maxFeePerGas": maxfee,
        "maxPriorityFeePerGas": tip,
        "type": 2,
    })
    signed = w3.eth.account.sign_transaction(tx, pk)
    txh = w3.eth.send_raw_transaction(signed.raw_transaction).hex()
    print(f"✅ approve LP tx: {txh}")

    txlog_path.parent.mkdir(parents=True, exist_ok=True)
    with txlog_path.open("a", encoding="utf-8") as f:
        f.write(txh + "\n")


def quote_remove_amounts(w3: Web3, pair_addr: str, token_addr: str, liq_amount: int):
    pair = w3.eth.contract(address=pair_addr, abi=PAIR_ABI)
    r0, r1, _ = pair.functions.getReserves().call()
    t0 = pair.functions.token0().call()
    t1 = pair.functions.token1().call()
    total = pair.functions.totalSupply().call()
    if total == 0:
        return 0, 0, 0, 0

    frac = liq_amount / total

    if t0.lower() == token_addr.lower():
        token_res, eth_res = int(r0), int(r1)
    else:
        token_res, eth_res = int(r1), int(r0)

    token_out = int(token_res * frac)
    eth_out   = int(eth_res * frac)

    token_min = max(1, token_out * (10_000 - SLIPPAGE_BPS) // 10_000)
    eth_min   = max(1, eth_out   * (10_000 - SLIPPAGE_BPS) // 10_000)
    return token_min, eth_min, token_out, eth_out


def build_remove_tx(
    w3: Web3,
    router,
    token_addr: str,
    liq_amount: int,
    token_min: int,
    eth_min: int,
    wallet: str,
    nonce: int,
    fee_mult: float,
    tip_gwei: float,
    deadline: int,
):
    base   = w3.eth.get_block("pending").get("baseFeePerGas", w3.eth.gas_price)
    tip    = w3.to_wei(tip_gwei, "gwei")
    maxfee = int(base * fee_mult + tip)

    tx = router.functions.removeLiquidityETH(
        token_addr,
        liq_amount,
        token_min,
        eth_min,
        wallet,
        deadline
    ).build_transaction({
        "from": wallet,
        "nonce": nonce,
        "gas": GAS_LIMIT_REMOVE,
        "maxFeePerGas": maxfee,
        "maxPriorityFeePerGas": tip,
        "type": 2,
    })

    return tx, maxfee, tip


def send_with_bump_signed(w3: Web3, make_tx_fn, pk: str) -> str | None:
    for bump in range(MAX_BUMPS + 1):
        tx, _, _ = make_tx_fn(bump)
        signed = w3.eth.account.sign_transaction(tx, pk)
        txh = w3.eth.send_raw_transaction(signed.raw_transaction).hex()
        print(f"✅ sent tx (bump={bump}): {txh}")

        start = time.time()
        while time.time() - start < BUMP_EVERY_SEC:
            try:
                rcpt = w3.eth.get_transaction_receipt(txh)
                if rcpt and rcpt.get("status") in (0, 1):
                    return txh
            except Exception:
                pass
            time.sleep(2)

        if bump < MAX_BUMPS:
            print("⏳ still pending → bumping fees...")
            continue

    print("⚠️ gave up bumping (still pending)")
    return None


def run():
    _load_env()
    wallets_path, txlog_path = _paths()

    v2_router = os.getenv("V2_ROUTER", DEFAULT_V2_ROUTER)
    w3 = Web3(Web3.HTTPProvider(_rpc_url()))
    if not w3.is_connected():
        raise RuntimeError("❌ Web3 not connected")

    print("✅ Remove Liquidity: Web3 connected")
    print(f"ℹ️ Chain ID: {w3.eth.chain_id}")

    router_abi = _load_router_abi()
    router = w3.eth.contract(address=Web3.to_checksum_address(v2_router), abi=router_abi)
    WMON = router.functions.WETH().call()

    factory_addr = router.functions.factory().call()
    factory = w3.eth.contract(address=factory_addr, abi=FACTORY_ABI)

    sym, token_addr = ask_token_choice()
    pmin, pmax, rounds = ask_percent_range()

    pair_addr = factory.functions.getPair(token_addr, WMON).call()
    if int(pair_addr, 16) == 0:
        raise RuntimeError("Pair not found for TOKEN/WMON")

    lp = w3.eth.contract(address=pair_addr, abi=ERC20_ABI)

    wallets = derive_wallets(w3, wallets_path)
    if not wallets:
        raise RuntimeError("No wallets loaded")

    txlog_path.parent.mkdir(parents=True, exist_ok=True)

    for r in range(1, rounds + 1):
        print(f"\n=== ROUND {r}/{rounds} ===")
        items = list(wallets.items())
        random.shuffle(items)

        processed = 0
        for wallet, pk in items:
            try:
                bal_lp = lp.functions.balanceOf(wallet).call()
                if bal_lp <= 0:
                    print(f"⚠️ {short(wallet)} no LP balance")
                    continue

                p = random.uniform(pmin, pmax) / 100.0
                liq_amount = int(bal_lp * p)
                if liq_amount <= 0:
                    continue

                ensure_allowance_lp(w3, lp, wallet, pk, Web3.to_checksum_address(v2_router), liq_amount, txlog_path)

                token_min, eth_min, token_out, eth_out = quote_remove_amounts(w3, pair_addr, token_addr, liq_amount)
                print(
                    f"   → {short(wallet)} remove ~{p*100:.1f}% LP | "
                    f"expected: {token_out} token units, {eth_out/1e18:.6f} MON | "
                    f"mins: {token_min} token units, {eth_min/1e18:.6f} MON"
                )

                def make_tx(bump_i: int):
                    fee_mult = FEE_MULT_START * (FEE_MULT_STEP ** bump_i)
                    tip_gwei = TIP_GWEI_START + TIP_GWEI_STEP * bump_i
                    nonce = w3.eth.get_transaction_count(wallet)
                    deadline = int(time.time()) + DEADLINE_SEC
                    return build_remove_tx(
                        w3, router, token_addr, liq_amount, token_min, eth_min,
                        wallet, nonce, fee_mult, tip_gwei, deadline
                    )

                txh = send_with_bump_signed(w3, make_tx, pk)
                if txh:
                    with txlog_path.open("a", encoding="utf-8") as f:
                        f.write(txh + "\n")

            except Exception as e:
                print(f"❌ {short(wallet)}: {e}")
            finally:
                processed += 1
                time.sleep(random.randint(*RANDOM_DELAY_S))

        print(f"✅ Round {r} done: processed wallets = {processed}/{len(wallets)}")

    print("\n🎉 Remove Liquidity finished.")


if __name__ == "__main__":
    run()
