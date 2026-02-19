# -*- coding: utf-8 -*-
import os
import time
import random
from pathlib import Path

from web3 import Web3
from eth_abi import encode
from dotenv import load_dotenv


def _project_root() -> Path:
    return Path(__file__).resolve().parents[1]


def _load_env() -> None:
    load_dotenv(_project_root() / ".env")


def _get_paths() -> tuple[Path, Path]:
    root = _project_root()
    wallets = Path(os.getenv("WALLETS_FILE", root / "data" / "wallets.txt"))
    txlog = Path(os.getenv("TX_LOG_FILE", root / "data" / "txhashes.txt"))
    return wallets, txlog


def _rpc_url() -> str:
    # поддержка: RPC_URL или YOUR_API_KEY
    rpc = (os.getenv("RPC_URL") or "").strip()
    if rpc:
        return rpc

    api_key = (os.getenv("YOUR_API_KEY") or "").strip()
    if not api_key:
        raise RuntimeError("Нет RPC_URL и нет YOUR_API_KEY в .env")
    return f"https://monad-testnet.g.alchemy.com/v2/{api_key}"


def _read_wallets(path: Path) -> list[tuple[str, str]]:
    if not path.exists():
        raise RuntimeError(f"wallets not found: {path}")
    out = []
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        addr, pk = line.split("=", 1)
        out.append((Web3.to_checksum_address(addr.strip()), pk.strip()))
    if not out:
        raise RuntimeError("wallets.txt пуст или неверный формат (address=private_key)")
    return out


def run():
    _load_env()
    wallets_path, txlog_path = _get_paths()

    w3 = Web3(Web3.HTTPProvider(_rpc_url()))
    if not w3.is_connected():
        raise RuntimeError("Web3 не подключён (RPC)")
    chain_id = w3.eth.chain_id

    print("✅ Mint: Web3 connected")
    print(f"ℹ️ Chain ID: {chain_id}")
    print(f"📁 wallets: {wallets_path}")

    contract_address = Web3.to_checksum_address(
        os.getenv("MINT_CONTRACT", "0x913bf9751fe18762b0fd6771edd512c7137e42bb")
    )

    wallets = _read_wallets(wallets_path)

    # сколько раз минтить с каждого
    try:
        rounds = int(input("🔢 Сколько минтов сделать с каждого кошелька? ").strip())
        if rounds <= 0:
            raise ValueError
    except ValueError:
        print("❌ Введите положительное целое число.")
        return

    METHOD_SELECTOR = os.getenv("METHOD_SELECTOR", "0x9b4f3af5")  # mint(address,uint256,uint256,bytes)
    MINT_ID = int(os.getenv("MINT_ID", "0"))
    QUANTITY = int(os.getenv("QUANTITY", "1"))
    EXTRA_DATA = b""

    delay_min = int(os.getenv("DELAY_MIN", "1"))
    delay_max = int(os.getenv("DELAY_MAX", "10"))
    gas_limit = int(os.getenv("GAS_LIMIT", "70000"))

    for round_num in range(1, rounds + 1):
        print(f"\n=== MINT ROUND {round_num}/{rounds} ===")
        order = wallets[:]
        random.shuffle(order)

        for addr, priv in order:
            try:
                encoded_args = encode(
                    ["address", "uint256", "uint256", "bytes"],
                    [addr, MINT_ID, QUANTITY, EXTRA_DATA]
                ).hex()
                input_data = METHOD_SELECTOR + encoded_args

                nonce = w3.eth.get_transaction_count(addr)
                gas_price = w3.eth.gas_price

                tx = {
                    "chainId": chain_id,
                    "nonce": nonce,
                    "to": contract_address,
                    "value": 0,
                    "gas": gas_limit,
                    "gasPrice": gas_price,
                    "data": input_data,
                }

                signed = w3.eth.account.sign_transaction(tx, priv)
                tx_hash = w3.eth.send_raw_transaction(signed.raw_transaction).hex()

                print(f"✅ {addr[:8]}… mint tx: {tx_hash}")
                txlog_path.parent.mkdir(parents=True, exist_ok=True)
                with txlog_path.open("a", encoding="utf-8") as f:
                    f.write(tx_hash + "\n")

            except Exception as e:
                print(f"❌ {addr[:8]}… mint error: {e}")

            time.sleep(random.randint(delay_min, delay_max))

    print("\n🎉 Mint done.")


if __name__ == "__main__":
    run()
