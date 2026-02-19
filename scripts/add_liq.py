# -*- coding: utf-8 -*-
"""
Add liquidity to TOKEN / MON pool on Monad testnet (UniswapV2Router02 style).

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


# ====== DEFAULTS (can be overridden via .env) ======
DEFAULT_V2_ROUTER = "0xfb8e1c3b833f9e67a71c859a132cf783b645e436"  # UniswapV2Router02 on Monad testnet

TOKENS = {
    "USDC": "0xf817257fed379853cDe0fa4F97AB987181B1E5Ea",
    "USDT": "0x88b8E2161DEDC77EF4ab7585569D2415a1C1055D",
    "YAKI": "0xfe140e1dCe99Be9F4F15d657CD9b7BF622270C50",
    "CHOG": "0xE0590015A873bF326bd645c3E1266d4db41C4E6B",
    "DAK":  "0x0F0BDEbF0F83cD1EE3974779Bcb7315f9808c714",
}
# (WMON not included — we add liquidity via addLiquidityETH)


# Slippage / buffers
SLIPPAGE_BPS = 500   # 5%
BUFFER_BPS   = 100   # +1% extra MON, leftover will be refunded
DEADLINE_SEC = 300

# Gas limits
GAS_LIMIT_APPROVE = 60_000
GAS_LIMIT_ADDLIQ  = 260_000

# Auto bump (EIP-1559 replacement txs)
BUMP_EVERY_SEC = 15
MAX_BUMPS      = 6
TIP_GWEI_START = 2.0
TIP_GWEI_STEP  = 1.25
FEE_MULT_START = 2.0
FEE_MULT_STEP  = 1.15

RANDOM_DELAY_S = (3, 10)
MAX_UINT256    = (1 << 256) - 1


# ====== ABIs (minimal fallbacks) ======
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
    {"name": "getAmountsIn", "stateMutability": "view", "type": "function",
     "inputs": [{"name": "amountOut", "type": "uint256"}, {"name": "path", "type": "address[]"}],
     "outputs": [{"name": "", "type": "uint256[]"}]},
    {"name": "addLiquidityETH", "stateMutability": "payable", "type": "function",
     "inputs": [
         {"name": "token", "type": "address"},
         {"name": "amountTokenDesired", "type": "uint256"},
         {"name": "amountTokenMin", "type": "uint256"},
         {"name": "amountETHMin", "type": "uint256"},
         {"name": "to", "type": "address"},
         {"name": "deadline", "type": "uint256"},
     ],
     "outputs": [{"name": "amountToken", "type": "uint256"}, {"name": "amountETH", "type": "uint256"}, {"name": "liquidity", "type": "uint256"}]},
]


# ====== Helpers ======
def _project_root() -> Path:
    return Path(__file__).resolve().parents[1]


def _load_env() -> None:
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
    print("\n🎯 Choose token to ADD liquidity with (TOKEN/MON):")
    for i, k in enumerate(keys, start=1):
        print(f" {i}) {k}")
    idx = int(input("> number: ").strip())
    sym = keys[idx - 1]
    return sym, Web3.to_checksum_address(TOKENS[sym])


def ask_amount_range(sym: str) -> tuple[float, float, int]:
    lo = float(input(f"📉 min amount {sym}: ").strip())
    hi = float(input(f"📈 max amount {sym}: ").strip())
    rounds = int(input("🔁 rounds: ").strip())
    return lo, hi, rounds


def ensure_allowance(w3: Web3, token, owner: str, pk: str, spender: str, need: int, txlog_path: Path):
    allowance = token.functions.allowance(owner, spender).call()
    if allowance >= need:
        return

    base = w3.eth.get_block("pending").get("baseFeePerGas", w3.eth.gas_price)
    tip = w3.to_wei(TIP_GWEI_START, "gwei")
    maxfee = int(base * FEE_MULT_START + tip)

    tx = token.functions.approve(spender, MAX_UINT256).build_transaction({
        "from": owner,
        "nonce": w3.eth.get_transaction_count(owner),
        "gas": GAS_LIMIT_APPROVE,
        "maxFeePerGas": maxfee,
        "maxPriorityFeePerGas": tip,
        "type": 2,
    })
    signed = w3.eth.account.sign_transaction(tx, pk)
    txh = w3.eth.send_raw_transaction(signed.raw_transaction).hex()
    print(f"✅ approve tx: {txh}")

    txlog_path.parent.mkdir(parents=True, exist_ok=True)
    with txlog_path.open("a", encoding="utf-8") as f:
        f.write(txh + "\n")


def build_addliq_tx(
    w3: Web3,
    router,
    WMON: str,
    token_addr: str,
    amount_token_desired: int,
    wallet: str,
    nonce: int,
    fee_mult: float,
    tip_gwei: float,
    deadline: int,
):
    # Estimate needed MON via getAmountsIn(WMON->TOKEN)
    path = [WMON, token_addr]
    need_eth = int(router.functions.getAmountsIn(amount_token_desired, path).call()[0])

    amount_token_min = max(1, amount_token_desired * (10_000 - SLIPPAGE_BPS) // 10_000)
    amount_eth_min   = max(1, need_eth * (10_000 - SLIPPAGE_BPS) // 10_000)
    value_to_send    = int(need_eth * (10_000 + BUFFER_BPS) // 10_000)

    base   = w3.eth.get_block("pending").get("baseFeePerGas", w3.eth.gas_price)
    tip    = w3.to_wei(tip_gwei, "gwei")
    maxfee = int(base * fee_mult + tip)

    tx = router.functions.addLiquidityETH(
        token_addr,
        amount_token_desired,
        amount_token_min,
        amount_eth_min,
        wallet,
        deadline
    ).build_transaction({
        "from": wallet,
        "nonce": nonce,
        "gas": GAS_LIMIT_ADDLIQ,
        "maxFeePerGas": maxfee,
        "maxPriorityFeePerGas": tip,
        "type": 2,
        "value": value_to_send,
    })

    return tx, value_to_send, maxfee, tip, need_eth, amount_token_min, amount_eth_min


def send_with_bump(w3: Web3, make_tx_fn, pk: str) -> str | None:
    """Send a tx and if it stays pending for too long, replace it with higher fees (same nonce)."""
    for bump in range(MAX_BUMPS + 1):
        tx, _, _, _, _, _, _ = make_tx_fn(bump)

        signed = w3.eth.account.sign_transaction(tx, pk)
        txh = w3.eth.send_raw_transaction(signed.raw_transaction).hex()
        print(f"✅ sent tx (bump={bump}): {txh}")

        # wait a bit, check receipt
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

    print("✅ Add Liquidity: Web3 connected")
    print(f"ℹ️ Chain ID: {w3.eth.chain_id}")

    router_abi = _load_router_abi()
    router = w3.eth.contract(address=Web3.to_checksum_address(v2_router), abi=router_abi)

    WMON = router.functions.WETH().call()

    wallets = derive_wallets(w3, wallets_path)
    if not wallets:
        raise RuntimeError("No wallets loaded")

    sym, token_addr = ask_token_choice()
    lo, hi, rounds = ask_amount_range(sym)

    token = w3.eth.contract(address=token_addr, abi=ERC20_ABI)
    dec = token.functions.decimals().call()

    txlog_path.parent.mkdir(parents=True, exist_ok=True)

    for r in range(1, rounds + 1):
        print(f"\n=== ROUND {r}/{rounds} ===")
        items = list(wallets.items())
        random.shuffle(items)

        processed = 0
        for wallet, pk in items:
            try:
                target = round(random.uniform(lo, hi), min(dec, 6))
                amount_token_desired = int(target * (10 ** dec))

                bal = token.functions.balanceOf(wallet).call()
                if bal < amount_token_desired:
                    print(f"⚠️ {short(wallet)} not enough {sym} balance ({bal/(10**dec):.6f} < {target})")
                    continue

                ensure_allowance(w3, token, wallet, pk, Web3.to_checksum_address(v2_router), amount_token_desired, txlog_path)

                def make_tx(bump_i: int):
                    fee_mult = FEE_MULT_START * (FEE_MULT_STEP ** bump_i)
                    tip_gwei = TIP_GWEI_START + TIP_GWEI_STEP * bump_i
                    nonce = w3.eth.get_transaction_count(wallet)
                    deadline = int(time.time()) + DEADLINE_SEC

                    tx, value_needed, max_fee, tip, need_eth, tmin, emin = build_addliq_tx(
                        w3, router, WMON, token_addr, amount_token_desired, wallet,
                        nonce, fee_mult, tip_gwei, deadline
                    )

                    print(
                        f"   → {short(wallet)} add {target:.6f} {sym} + ≈{need_eth/1e18:.6f} MON "
                        f"(mins: {tmin/(10**dec):.6f} {sym}, {emin/1e18:.6f} MON)"
                    )
                    return tx, value_needed, max_fee, tip, need_eth, tmin, emin

                txh = send_with_bump(w3, make_tx, pk)
                if txh:
                    with txlog_path.open("a", encoding="utf-8") as f:
                        f.write(txh + "\n")

            except Exception as e:
                print(f"❌ {short(wallet)}: {e}")
            finally:
                processed += 1
                time.sleep(random.randint(*RANDOM_DELAY_S))

        print(f"✅ Round {r} done: processed wallets = {processed}/{len(wallets)}")

    print("\n🎉 Add Liquidity finished.")


if __name__ == "__main__":
    run()
