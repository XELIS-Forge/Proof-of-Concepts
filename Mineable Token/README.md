# XELIS Mineable Token - Proof of Concept

A proof-of-concept implementation of a mineable token on the XELIS blockchain using smart contracts. This project demonstrates on-chain Proof-of-Work (PoW) mining with SHA3-256d hashing and dynamic difficulty adjustment.

## 🎯 Overview

This project consists of two main components:

1. **mineable_token_contract.slx** - A XELIS smart contract written in Silex that implements:
   - Launching of a Confidential Token on Xelis-Blockchain
   - On-chain Proof-of-Work verification
   - Bitcoin-inspired difficulty adjustment algorithm
   - Token minting rewards for successful miners
   - SHA3-256d hashing algorithm
   - Event-driven architecture for miner synchronization

2. **Python Miner** - An optimized single-threaded miner that:
   - Mines blocks using SHA3-256d
   - Submits solutions via RPC transactions
   - Listens to contract events via WebSocket
   - Reports real-time hashrate statistics

## 📊 Token Economics

- **Token Name:** Xelis Mineable Token
- **Ticker:** MINETOK
- **Decimals:** 8
- **Max Supply:** 21,000,000 tokens
- **Block Reward:** 50 tokens per block
- **Target Block Time:** 60 seconds
- **Initial Difficulty:** 10,000,000
- **Difficulty Adjustment:** Every 100 blocks

## 🔧 Technical Details

### Smart Contract Architecture

The contract implements a complete mining system on-chain:

```
Block Header = [block_number][miner_address][difficulty][prev_hash][timestamp]
                    (8 bytes)      (34 bytes)    (32 bytes)  (32 bytes)  (8 bytes)

Header Hash = BLAKE3(Block Header)
PoW Hash = SHA3-256(SHA3-256(Header Hash + Nonce))
```

#### Difficulty Adjustment Algorithm

Adjusts every 100 blocks based on actual vs. expected time:
- **< 80% of target:** Increase difficulty by 25%
- **80-90% of target:** Increase difficulty by 10%
- **110-120% of target:** Decrease difficulty by 10%
- **> 120% of target:** Decrease difficulty by 20%

#### Timestamp Validation

The contract enforces strict timestamp rules to prevent manipulation:
- **Future drift:** Maximum 5 seconds ahead of block time
- **Past drift:** Maximum 30 seconds behind block time
- **Monotonic:** Each submission must have a timestamp greater than the previous

### Mining Algorithm

1. Fetch current chain state (block number, difficulty, prev_hash)
2. Generate header hash using BLAKE3
3. Iterate through nonces, computing SHA3-256d(header_hash + nonce)
4. Submit solution when hash meets difficulty target
5. Listen for contract events to start mining next block

## 🚀 Getting Started

### Prerequisites

- XELIS Wallet (CLI) [XELIS WALLET](https://github.com/xelis-project/xelis-blockchain/releases/)
- Python 3.8+
- Required Python packages: `blake3`, `websockets`, `requests`

### Step 1: Deploy the Smart Contract

#### 1.1 Compile the Contract

1. Go to [XELIS Playground](https://playground.xelis.io)
2. Copy and paste the contents of `mineable_token_contract.slx`
3. Click **"Compile"** button
4. Verify compilation succeeds with no errors
5. Click **"Export Hex"** to download the compiled contract bytecode

#### 1.2 Deploy to Chain

1. Start your XELIS CLI wallet:
   ```bash
   xelis_wallet
   ```

2. Open or create your wallet

3. Deploy the contract:
   ```
   deploy_contract
   ```

4. When prompted:
   - **Paste the hex code** (from step 1.1)
   - **Min Gas:** `1000000000` (1 XEL/XET)
   - **Deposit:** `1000000000` (1 XEL/XET) with default asset
   
   This deposit covers the constructor execution which initializes the token.

5. Note the **contract hash** from the deployment transaction - you'll need this for mining!

### Step 2: Start the Wallet RPC Server

The miner submits solutions as transactions, so you need to enable the RPC server:

```
start_rpc_server 0.0.0.0:8081 user password
```

**Important:** 
- `0.0.0.0:8081` - The address and port (can be changed)
- `user` - RPC username (must match miner config)
- `password` - RPC password (must match miner config)

### Step 3: Configure and Run the Miner

#### 3.1 Install Python Dependencies

```bash
pip install blake3 websockets requests
```

#### 3.2 Update Miner Configuration

Edit `xelis_contract_sha256_miner.py` and update:

```python
RPC_USER = "user"        # Match your RPC username
RPC_PASS = "password"    # Match your RPC password
CONTRACT_HASH = "YOUR_CONTRACT_HASH_HERE"  # From deployment
```

#### 3.3 Run the Miner

```bash
python xelis_contract_sha256_miner.py --address xet:YOUR_WALLET_ADDRESS
```

**Required Arguments:**
- `--address` or `-a`: Your XELIS wallet address (xet:...)

**Optional Arguments:**
- `--rpc-url`: Wallet RPC URL (default: `http://127.0.0.1:8081/json_rpc`)
- `--ws-url`: WebSocket URL (default: `ws://127.0.0.1:8080/json_rpc`)
- `--contract`: Contract hash (default: set in code)
- `--max-gas`: Maximum gas per transaction (default: `5000000`)

**Example:**
```bash
python xelis_contract_sha256_miner.py \
  --address xet:4cka26kpvq6nj93lguycywn8flccvrf537dzqa0x0jyhawddepfsqtka05w \
  --contract a5f71cfb9897384da12b69c6abd4a90a3233f6512221028fd60e3e66fb6ae982
```

## 📈 Miner Output

The miner will display:
- Initialization information (address, contract, RPC URLs)
- Real-time hashrate (KH/s and MH/s)
- Solution notifications with compact output
- Contract event notifications (new blocks)

Example output:
```
Starting mining on block 42, difficulty 15000000
Hashrate: 125.43 KH/s (0.1254 MH/s) | Nonce: 5,234,891
🎉 SOLUTION! nonce=5234891 hash=00000a4f3c2d1e9b... ✅ Submitted
🔔 Contract event received - restarting mining
```

## 🔍 How It Works

### Mining Process

1. **Sync Chain State**: Fetch current block number, difficulty, and previous hash from contract
2. **Generate Header**: Create block header with miner address and timestamp
3. **Compute Header Hash**: BLAKE3 hash of the header (done once per mining session)
4. **Mining Loop**: 
   - Iterate nonces starting from random value
   - Compute SHA3-256d(header_hash + nonce)
   - Check if result meets difficulty target
5. **Submit Solution**: Send transaction invoking `submit_solution(nonce, timestamp)`
6. **Wait for Event**: Listen for contract event indicating new block
7. **Repeat**: Go back to step 1

### Contract Validation

When a solution is submitted, the contract:

1. Validates timestamp is within acceptable bounds
2. Reconstructs the header hash
3. Verifies the PoW hash meets difficulty
4. Mints reward tokens
5. Transfers tokens to miner
6. Updates chain state (prev_hash, block number, timestamp)
7. Adjusts difficulty if needed (every 100 blocks)
8. Fires event to notify miners

### Error Codes

The contract returns the following codes:
- **0**: ✅ Success - Block mined!
- **1**: ⚠️ Max supply reached - Mining complete
- **2**: ❌ Timestamp out of bounds
- **3**: ❌ Timestamp is stale (not greater than last)
- **4**: ❌ PoW verification failed

## ⚡ Performance Optimization

The Python miner is optimized for single-threaded performance:

- **No GIL overhead**: Python's GIL makes multi-threading slower for CPU-bound tasks
- **Minimal locking**: Mining loop runs lock-free
- **Batch operations**: Hashrate reporting uses modulo checks to reduce overhead
- **Random nonce start**: Reduces collision probability in distributed setups

Typical hashrates on modern hardware:
- Intel i7-12700K: ~150-200 KH/s per core
- AMD Ryzen 9 5900X: ~180-220 KH/s per core
- Apple M1/M2: ~100-150 KH/s per core

## 🛠️ Troubleshooting

### Common Issues

**"401 Unauthorized" errors:**
- Verify RPC server is running in wallet
- Check RPC username/password match in miner config
- Ensure wallet is unlocked

**"Timestamp out of bounds" errors:**
- System clock may be out of sync
- Use NTP to synchronize system time
- Check if timestamp refresh logic is working

**"PoW verification failed" errors:**
- Usually indicates someone else mined the block first
- Miner will automatically restart on next block
- This is normal in competitive mining

**Low hashrate:**
- Python is not optimal for high-performance mining
- Consider implementing in Rust/C++ for production use
- This implementation is a proof-of-concept

### Debug Mode

For verbose output, modify the miner to uncomment debug statements:
```python
print(f"Transaction Result: {json.dumps(res, indent=2)}")
```

## 📝 Contract Functions

### Constructor
```
hook constructor() -> u64
```
Initializes the token and mining system. Called once during deployment.

### Submit Solution
```
entry submit_solution(nonce: u64, ts: u64)
```
Main mining entry point. Validates and processes PoW submissions.

**Parameters:**
- `nonce`: The nonce that produces a valid hash
- `ts`: Timestamp in milliseconds since Unix epoch

**Returns:**
- `0` on success
- Error code on failure

### Events

**MiningSubmission (Event ID: 1)**
```
struct MiningSubmission {
    miner_address: Address,
    nonce: u64,
    pow_hash: Hash,
    block_number: u64,
    new_diff: u256
}
```

Fired after successful block mining. Miners listen to this event to know when to start mining the next block.

## 🔐 Security Considerations

1. **Timestamp manipulation**: The contract enforces strict timestamp bounds to prevent gaming
2. **Difficulty targeting**: Prevents miners from submitting stale/future blocks
3. **Supply cap**: Hard limit at 21M tokens, enforced on-chain
4. **Monotonic time**: Each block must have timestamp > previous block

## 📄 License

This is a proof-of-concept demonstration. Use at your own risk.

## 🤝 Contributing

This is a proof-of-concept project. Feel free to fork and improve:
- Implement new contracts with unique tokenomics
- Implement merge mining
- Implement new mining/hashing algos
- Add mining pool support
- Add monitoring/statistics
- Improve error handling

## 🙏 Acknowledgments

Built on the XELIS blockchain platform using the Silex smart contract language.

## 📚 Additional Resources

- [XELIS Github](https://github.com/xelis-project)
- [XELIS Documentation](https://docs.xelis.io)
- [XELIS Playground](https://playground.xelis.io)
- [Silex Language Reference](https://docs.xelis.io/developers/smart-contracts/silex)

---

**⚠️ Disclaimer**: This is a proof-of-concept implementation intended for educational and testing purposes. It has not been audited for production use. Always test thoroughly on testnet before deploying to mainnet.