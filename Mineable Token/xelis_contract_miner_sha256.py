import asyncio
import struct
import hashlib
import sys
import time
import json
import requests
import blake3
from requests.auth import HTTPBasicAuth
import websockets
from threading import Thread, Lock, Event
import random
import argparse

# ====================
# CONFIG
# ====================
NODE_RPC_URL = "https://testnet-node.xelis.io/json_rpc"
RPC_URL = "http://127.0.0.1:8081/json_rpc"
RPC_USER = "user"
RPC_PASS = "password"

CONTRACT_HASH = "a5f71cfb9897384da12b69c6abd4a90a3233f6512221028fd60e3e66fb6ae982"
ENTRY_ID_SUBMIT = 5

# Contract event to listen for
CONTRACT_EVENT_ID = 1


def decode_xet_address(address):
    # Bech32 charset
    charset = "qpzry9x8gf2tvdw0s3jn54khce6mua7l"

    # Get the data part after colon
    _, data_part = address.split(':')

    # Decode each character to its 5-bit value
    data_5bit = [charset.index(c) for c in data_part]

    # Convert from 5-bit to 8-bit (without padding at the end)
    acc = 0
    bits = 0
    result = []

    for value in data_5bit:
        acc = (acc << 5) | value
        bits += 5

        while bits >= 8:
            bits -= 8
            result.append((acc >> bits) & 0xFF)

    result = [0] + result[:33]
    return result


MAX_TARGET = (1 << 256) - 1

WS_URL = "ws://127.0.0.1:8080/json_rpc"

# Configurable gas limit
MAX_GAS = 5_000_000

# Hashrate reporting interval (seconds)
HASHRATE_REPORT_INTERVAL = 10

# Timestamp refresh interval (seconds)
TIMESTAMP_REFRESH_INTERVAL = 10

# ====================
# AUTHENTICATED SESSION
# ====================
session = requests.Session()
session.auth = HTTPBasicAuth(RPC_USER, RPC_PASS)
session.headers.update({"Content-Type": "application/json"})


# ====================
# RPC HELPERS
# ====================
def rpc_call(url: str, method: str, params: dict):
    payload = {
        "jsonrpc": "2.0",
        "method": method,
        "id": 1,
        "params": params,
        "broadcast": True
    }
    r = session.post(url, json=payload, timeout=15)
    r.raise_for_status()
    j = r.json()
    if "error" in j:
        raise RuntimeError(j["error"])
    return j["result"]


def get_contract_data(contract_hash: str, key: str):
    return rpc_call(NODE_RPC_URL,
                    "get_contract_data",
                    {
                        "contract": contract_hash,
                        "key": {
                            "type": "primitive",
                            "value": {"type": "string", "value": key}
                        }
                    }
                    )


def submit_solution(nonce: int, ts: int):
    result = rpc_call(RPC_URL,
                      "build_transaction",
                      {
                          "invoke_contract": {
                              "contract": CONTRACT_HASH,
                              "max_gas": MAX_GAS,
                              "entry_id": ENTRY_ID_SUBMIT,
                              "parameters": [
                                  {"type": "primitive", "value": {"type": "u64", "value": str(nonce)}},
                                  {"type": "primitive", "value": {"type": "u64", "value": str(ts)}}
                              ],
                              "permission": "all"
                          },
                          "broadcast": True
                      }
                      )
    return result


def parse_contract_error(result):
    """Parse contract return codes for debugging"""
    error_codes = {
        0: "✅ Success - Block mined!",
        1: "⚠️ Max supply reached - Mining complete",
        2: "❌ Timestamp out of bounds (must be: now-30 <= ts <= now+5)",
        3: "❌ Timestamp is stale (ts <= last_time)",
        4: "❌ PoW verification failed (hash doesn't meet difficulty)"
    }

    try:
        if isinstance(result, dict):
            if "tx" in result and "result" in result["tx"]:
                return_code = result["tx"]["result"]
            elif "result" in result:
                return_code = result["result"]
            elif "return_value" in result:
                return_code = result["return_value"]
            else:
                return None

            if isinstance(return_code, int):
                return error_codes.get(return_code, f"❓ Unknown return code: {return_code}")
    except:
        pass

    return None


# ====================
# HASHING
# ====================
def sha3_256d(data: bytes) -> bytes:
    """Double SHA3-256 hash"""
    return hashlib.sha3_256(hashlib.sha3_256(data).digest()).digest()


def generate_header_hash(
        block_number: int,
        miner: bytes,
        difficulty: int,
        prev_hash: bytes,
        ts: int
) -> bytes:
    header = b""
    header += struct.pack("<Q", block_number)
    header += miner
    header += difficulty.to_bytes(32, "little")
    header += prev_hash
    header += struct.pack("<Q", ts)
    return blake3.blake3(header).digest()


def meets_difficulty(final_hash: bytes, difficulty: int) -> bool:
    hv = int.from_bytes(final_hash)
    target = MAX_TARGET // difficulty
    return hv <= target


# ====================
# MINING STATE (Minimal locking)
# ====================
class MiningState:
    def __init__(self):
        self.lock = Lock()
        self.restart_event = Event()
        self.restart_event.set()  # Start with restart needed

        self.awaiting_confirmation = False

        self.block_number = 0
        self.difficulty = 1
        self.prev_hash = bytes(32)
        self.ts = int(time.time() * 1000)


state = MiningState()


# ====================
# CHAIN SYNC
# ====================
def sync_chain_state(contract: str):
    try:
        block = int(get_contract_data(contract, "block")["data"]["value"]["value"])
        difficulty = int(get_contract_data(contract, "diff")["data"]["value"]["value"])
        prev_hash_hex = get_contract_data(contract, "prev_hash")["data"]["value"]["value"]["value"]
        prev_hash = bytes.fromhex(prev_hash_hex)
        return block, difficulty, prev_hash
    except Exception as e:
        print(f"Error syncing chain state: {e}")
        raise


# ====================
# SINGLE-THREADED MINER (Optimized)
# ====================
def mine_loop(address_bytes: bytes):
    """Optimized single-threaded mining loop with minimal overhead"""

    last_report = time.time()
    local_hashes = 0

    while True:
        # Wait for restart signal
        state.restart_event.wait()

        try:
            # Sync chain state
            with state.lock:
                if state.awaiting_confirmation:
                    continue
                time.sleep(0.1)
                state.block_number, state.difficulty, state.prev_hash = sync_chain_state(CONTRACT_HASH)

                state.ts = int(time.time() * 1000)
                state.restart_event.clear()

                block_number = state.block_number
                difficulty = state.difficulty
                prev_hash = state.prev_hash
                current_ts = state.ts

            print(f"Starting mining on block {block_number}, difficulty {difficulty}")

            # Generate header hash (once per template)
            header_hash = generate_header_hash(
                block_number,
                address_bytes,
                difficulty,
                prev_hash,
                current_ts
            )

            # Start with random nonce
            nonce = random.randint(0, 2 ** 32)
            start_time = time.time()
            last_report = start_time
            local_hashes = 0

        except Exception as e:
            print(f"Error initializing mining: {e}")
            time.sleep(5)
            continue

        # Hot mining loop - no locks, no checks, pure speed
        while not state.restart_event.is_set():
            # Hash attempt (this is the hottest path - keep it minimal)
            data = header_hash + struct.pack("<Q", nonce)
            final_hash = sha3_256d(data)
            local_hashes += 1

            # Check difficulty
            if meets_difficulty(final_hash, difficulty):
                print(f"\n🎉 SOLUTION FOUND! nonce={nonce} hash={final_hash.hex()}")

                try:
                    res = submit_solution(nonce, current_ts)

                    error_msg = parse_contract_error(res)
                    if error_msg:
                        # print(f"Contract Response: {error_msg}")
                        pass

                    # print(f"Transaction Result: {json.dumps(res, indent=2)}")

                    if error_msg and "Max supply reached" in error_msg:
                        print("\n🏁 Maximum supply reached! Mining complete.")
                        sys.exit(0)

                except Exception as e:
                    print(f"❌ Submission failed: {e}")
                    print("Continuing to mine...")

                # Trigger restart
                with state.lock:
                    state.awaiting_confirmation = True

                # stop mining until event or reconnect
                state.restart_event.clear()
                state.restart_event.wait()
                break

            nonce += 1

            # Hashrate reporting (minimal overhead check)
            if local_hashes % 100000 == 0:
                current_time = time.time()
                if current_time - last_report > HASHRATE_REPORT_INTERVAL:
                    elapsed = current_time - start_time
                    hashrate = local_hashes / elapsed
                    print(f"Hashrate: {hashrate / 1000:.2f} KH/s ({hashrate / 1e6:.4f} MH/s) | Nonce: {nonce:,}")
                    last_report = current_time
                    state.restart_event.set()


# ====================
# CONTRACT EVENT LISTENER
# ====================
async def listen_contract_events():
    while True:
        try:
            async with websockets.connect(WS_URL, ping_interval=20, ping_timeout=60) as ws:
                subscribe_msg = {
                    "id": 1,
                    "jsonrpc": "2.0",
                    "method": "subscribe",
                    "params": {
                        "notify": {
                            "contract_event": {
                                "contract": CONTRACT_HASH,
                                "id": CONTRACT_EVENT_ID
                            }
                        }
                    }
                }
                await ws.send(json.dumps(subscribe_msg))
                print(f"✅ Subscribed to contract events (contract: {CONTRACT_HASH}, event_id: {CONTRACT_EVENT_ID})")

                while True:
                    msg = await ws.recv()
                    data = json.loads(msg)

                    # Skip subscription confirmation
                    if "result" in data and isinstance(data["result"], bool):
                        continue

                    # Check for contract event
                    if "result" in data and isinstance(data["result"], dict):
                        result = data["result"]

                        if "event" in result and isinstance(result["event"], dict):
                            if "contract_event" in result["event"]:
                                event_info = result["event"]["contract_event"]

                                if event_info.get("contract") == CONTRACT_HASH and event_info.get(
                                        "id") == CONTRACT_EVENT_ID:
                                    print("\n🔔 Contract event received - restarting mining")
                                    with state.lock:
                                        state.awaiting_confirmation = False
                                    state.restart_event.set()

        except Exception as e:
            print(f"❌ WebSocket error: {e}")
            print("Reconnecting in 5 seconds...")
            await asyncio.sleep(5)


# ====================
# MAIN
# ====================
if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description='XELIS Smart Contract Miner (Optimized Single Thread)',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Note: Python's GIL makes multi-threading slower for CPU-bound tasks like mining.
This single-threaded version is optimized for maximum hashrate.

Example:
  %(prog)s --address xet:4cka26kpvq6nj93lguycywn8flccvrf537dzqa0x0jyhawddepfsqtka05w
        """
    )

    parser.add_argument(
        '-a', '--address',
        required=True,
        help='XELIS wallet address (xet:...)'
    )

    parser.add_argument(
        '--rpc-url',
        default=RPC_URL,
        help=f'Wallet RPC URL (default: {RPC_URL})'
    )

    parser.add_argument(
        '--ws-url',
        default=WS_URL,
        help=f'WebSocket URL (default: {WS_URL})'
    )

    parser.add_argument(
        '--contract',
        default=CONTRACT_HASH,
        help=f'Contract hash (default: {CONTRACT_HASH})'
    )

    parser.add_argument(
        '--max-gas',
        type=int,
        default=MAX_GAS,
        help=f'Maximum gas per transaction (default: {MAX_GAS:,})'
    )

    args = parser.parse_args()

    # Update globals
    RPC_URL = args.rpc_url
    WS_URL = args.ws_url
    CONTRACT_HASH = args.contract
    MAX_GAS = args.max_gas

    print("=" * 60)
    print("XELIS Smart Contract Miner (Optimized)")
    print("=" * 60)
    print(f"Address: {args.address}")
    print(f"Contract: {CONTRACT_HASH}")
    print(f"Contract Event ID: {CONTRACT_EVENT_ID}")
    print(f"Max Gas: {MAX_GAS:,}")
    print(f"RPC URL: {RPC_URL}")
    print(f"WebSocket URL: {WS_URL}")
    print("=" * 60)

    try:
        address_bytes = bytes(decode_xet_address(args.address))
    except Exception as e:
        print(f"Error decoding address: {e}")
        sys.exit(1)

    # Start mining in separate thread
    miner_thread = Thread(target=mine_loop, args=(address_bytes,), daemon=True)
    miner_thread.start()

    # Run WebSocket listener
    try:
        asyncio.run(listen_contract_events())
    except KeyboardInterrupt:
        print("\n\nShutting down miner...")
        print("Goodbye! 👋")