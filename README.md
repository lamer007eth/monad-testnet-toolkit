# Monad Testnet Toolkit 🧪⚡️

Python automation toolkit for **Monad testnet** — multi-wallet execution for swaps, liquidity management, and mint operations from a single orchestrator. Built for farming, testing, and on-chain routine automation.

<p align="left">
  <img src="https://img.shields.io/badge/Python-3.10%2B-blue">
  <img src="https://img.shields.io/badge/Network-Monad%20Testnet-purple">
  <img src="https://img.shields.io/badge/Web3-web3.py-blue">
  <img src="https://img.shields.io/badge/Type-Automation%20Toolkit-brightgreen">
  <img src="https://img.shields.io/badge/DEX-V2%20Router-orange">
</p>

---

## ✨ Features

• 🔁 TOKEN ⇄ MON swaps  
• 💧 Add / Remove liquidity  
• 👛 Multi-wallet execution  
• 🧾 Tx hash logging  
• ⚙️ Modular script architecture  
• 🧪 Testnet farming ready  

---

## 📁 Project structure

monad-testnet-toolkit/

├─ main.py  
├─ scripts/  
│  ├─ swap_mon_token.py  
│  ├─ swap_token_mon.py  
│  ├─ add_liq.py  
│  ├─ remove_liq.py  
│  └─ mint.py  
│  
├─ config/  
│  └─ router_abi.json  
│  
├─ data/  
│  ├─ wallets.example.txt  
│  ├─ wallets.txt  
│  └─ txhashes.txt  
│  
├─ logs/  
├─ templates/  
├─ .env.example  
├─ .env  
├─ .gitignore  
└─ requirements.txt  

---

## ✅ Requirements

• Python 3.10+  
• Monad testnet RPC  
• Funded wallets (MON + token balances)  

---

## 🚀 Quick start

Install dependencies:

pip install -r requirements.txt

Create `.env`:

RPC_URL=  
# or  
YOUR_API_KEY=  

V2_ROUTER=0xfb8e1c3b833f9e67a71c859a132cf783b645e436  
WALLETS_FILE=data/wallets.txt  
TX_LOG_FILE=data/txhashes.txt  

Add wallets → data/wallets.txt

0xAddress=private_key  
0xAddress2=private_key2  

Run:

python main.py

---

## 🧠 Notes

• Testnet tooling — use at your own risk  
• Do NOT commit `.env` or `wallets.txt`  
• Pair must exist for swaps / liquidity  
• Ensure wallet balances before execution
