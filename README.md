# Privacy-Preserving DeFi Experiment Prototype

Academic dissertation prototype for measuring the trade-offs between plaintext Central Limit Order Book (CLOB) matching, Paillier partially homomorphic encryption (PHE), and blockchain-backed auditability.

The repository contains four experiment variants, deterministic synthetic order generation, research-ready CSV outputs, figures, a local Solidity audit contract, and a read-only blockchain explorer.

> This is a research prototype. It does not perform real trading, settlement, custody, live market integration, or production blockchain deployment.

## Implemented experiments

| Variant | Computation | Blockchain audit | Main purpose |
|---|---|---:|---|
| `plaintext` | Price-time-priority CLOB matching | No | Correctness and performance baseline |
| `plaintext_blockchain` | Price-time-priority CLOB matching | Yes | Measure evidence hashing, transaction, confirmation, and gas overhead |
| `paillier_phe` | Paillier-encrypted BUY/SELL quantity aggregation | No | Measure encryption, homomorphic addition, decryption, and ciphertext overhead |
| `paillier_phe_blockchain` | Paillier-encrypted BUY/SELL quantity aggregation | Yes | Combine encrypted aggregation with auditable evidence hashes and batch results |

The Paillier variants implement real encryption and homomorphic addition, but they are **not encrypted CLOB matching**. They aggregate encrypted BUY and SELL quantities, decrypt only the final totals, and calculate:

```text
matched_volume = min(decrypted_buy_volume, decrypted_sell_volume)
```

The plaintext variants instead perform price-aware CLOB matching. Their `matched_volume` is the sum of quantities in executed trades. These two meanings must be kept separate when interpreting the final comparison.

## Experiment flow

```text
Deterministic synthetic orders
            |
            v
    One of four runners
            |
            +--> raw run CSVs
            +--> measured-run summaries
            +--> evidence files
            +--> PNG figures
            |
            +--> final comparison tables and figures

Blockchain variants additionally:

evidence files --> SHA-256 hashes --> BatchAudit contract --> read-only explorer
```

Matching and encrypted aggregation remain off-chain. The local blockchain stores lifecycle state, hashes, aggregate batch values, and transaction metadata rather than complete order books or private keys.

## Prerequisites

The current project has been tested with:

- Python 3.12
- Node.js 20
- npm 10
- Git

The shell commands below assume Linux, WSL, or macOS.

## Installation

Clone the repository and enter it:

```bash
git clone https://github.com/LvLTroubleshooter/phe-thesis-prototype.git
cd phe-thesis-prototype
```

Create and activate a Python virtual environment:

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
```

Install the blockchain and frontend dependencies:

```bash
npm --prefix blockchain ci
npm --prefix frontend ci
```

Run all non-integration checks:

```bash
python scripts/run_automatic_tests.py --all
```

## Quick end-to-end smoke run

This profile uses two small batches and one measured run. It verifies the complete workflow but is not intended to produce dissertation-quality timing statistics.

All commands in this section use the same batch sizes and seed so their input hashes are comparable.

### 1. Run the non-blockchain variants

From the repository root:

```bash
python -m src.experiments.run_plaintext_baseline \
  --batch-sizes 10 25 \
  --warmup-runs 0 \
  --measured-runs 1 \
  --seed 42

python -m src.experiments.run_paillier_phe_experiment \
  --batch-sizes 10 25 \
  --warmup-runs 0 \
  --measured-runs 1 \
  --key-size-bits 2048 \
  --seed 42
```

### 2. Start and deploy the local blockchain

In terminal 1:

```bash
cd blockchain
npm run node
```

Keep terminal 1 running. In terminal 2:

```bash
cd blockchain
npm run deploy:localhost
cd ..
```

The deployment creates:

```text
blockchain/deployments/BatchAudit.localhost.json
frontend/public/deployments/BatchAudit.localhost.json
```

### 3. Run the blockchain variants

Continue in terminal 2 from the repository root:

```bash
python -m src.experiments.run_plaintext_blockchain_experiment \
  --batch-sizes 10 25 \
  --warmup-runs 0 \
  --measured-runs 1 \
  --confirmations 0 \
  --submission-mode sequential \
  --seed 42

python -m src.experiments.run_paillier_phe_blockchain_experiment \
  --batch-sizes 10 25 \
  --warmup-runs 0 \
  --measured-runs 1 \
  --paillier-key-size 2048 \
  --confirmations 0 \
  --submission-mode sequential \
  --seed 42
```

Even with zero extra confirmations, this smoke run takes time because each audited batch has three lifecycle transactions and the local network mines at 12-second intervals.

### 4. Generate the combined comparison

```bash
python -m src.experiments.generate_final_comparison
```

Each experiment runner already refreshes `results/final_comparison/` after a successful run. Running the command explicitly at the end guarantees that it includes the latest outputs from all available variants.

## Reproduce the committed result profile

The result snapshot currently committed to the repository uses the same five batch sizes, seed, warmup count, and measured-run count across all four variants:

```text
batch sizes   = 100, 500, 1,000, 5,000, 10,000
seed          = 42
warmup runs   = 1 per batch
measured runs = 5 per batch
Paillier key  = 2,048 bits
confirmations = 2 for blockchain variants
```

This is a **long-running profile**. The real 2,048-bit Paillier runs, especially the 5,000- and 10,000-order batches, can take several hours depending on the CPU. Blockchain runs also wait for 12-second blocks and confirmations.

Run the two non-blockchain variants:

```bash
python -m src.experiments.run_plaintext_baseline \
  --batch-sizes 100 500 1000 5000 10000 \
  --warmup-runs 1 \
  --measured-runs 5 \
  --seed 42

python -m src.experiments.run_paillier_phe_experiment \
  --batch-sizes 100 500 1000 5000 10000 \
  --warmup-runs 1 \
  --measured-runs 5 \
  --key-size-bits 2048 \
  --seed 42
```

Start a fresh Hardhat node and deploy `BatchAudit` as described above, then run each blockchain variant once:

```bash
python -m src.experiments.run_plaintext_blockchain_experiment \
  --batch-sizes 100 500 1000 5000 10000 \
  --warmup-runs 1 \
  --measured-runs 5 \
  --confirmations 2 \
  --submission-mode sequential \
  --seed 42

python -m src.experiments.run_paillier_phe_blockchain_experiment \
  --batch-sizes 100 500 1000 5000 10000 \
  --warmup-runs 1 \
  --measured-runs 5 \
  --paillier-key-size 2048 \
  --confirmations 2 \
  --submission-mode sequential \
  --seed 42

python -m src.experiments.generate_final_comparison
```

Do not rely on every runner's no-argument defaults for a cross-variant comparison. The plaintext runners default to batch sizes from 10,000 to 1,000,000 with 5 warmups and 30 measured runs, while the Paillier runners default to 100, 500, and 1,000 with 1 warmup and 5 measured runs. Always pass the same `--batch-sizes` and `--seed` explicitly when comparing variants.

## Useful runner options

Inspect every supported option with `--help`, for example:

```bash
python -m src.experiments.run_plaintext_baseline --help
python -m src.experiments.run_plaintext_blockchain_experiment --help
python -m src.experiments.run_paillier_phe_experiment --help
python -m src.experiments.run_paillier_phe_blockchain_experiment --help
```

Common options include:

| Option | Meaning |
|---|---|
| `--batch-sizes ...` | Generate deterministic batches with the requested sizes |
| `--seed N` | Synthetic-data seed; default is `42` |
| `--warmup-runs N` | Runs excluded from summary statistics |
| `--measured-runs N` | Runs included in summary statistics |
| `--skip-visualizations` | Write data outputs without generating PNG figures |
| `--skip-final-comparison` | Do not refresh the combined comparison after this runner |
| `--skip-cache-cleanup` | Keep generated Python cache directories |
| `--confirmations N` | Extra confirmation depth for blockchain transactions |
| `--submission-mode` | Select either `sequential` or `burst` |
| `--key-size-bits N` | Paillier key size for `paillier_phe` |
| `--paillier-key-size N` | Paillier key size for `paillier_phe_blockchain` |

The CLI runners currently regenerate `data/synthetic_orders.csv` because `--batch-sizes` always has a default. The `--input` option selects the CSV path that is regenerated; it does not disable generation when the CLI is used.

## Expected outputs

Every runner writes a deterministic dataset snapshot and manifest:

```text
data/
└── synthetic_orders.csv

results/datasets/
├── dataset_manifest.csv
└── synthetic_orders/
    └── batch_*.csv
```

`dataset_manifest.csv` records each batch's size, BUY/SELL counts and volumes, seed, file path, creation time, and SHA-256 input hash.

### Plaintext CLOB baseline

```text
results/plaintext_baseline/
├── csv/
│   ├── batch_summary.csv
│   ├── raw_runs.csv
│   ├── trades.csv
│   └── unmatched_orders.csv
└── figures/
    ├── plaintext_baseline_runtime.png
    ├── plaintext_baseline_throughput.png
    └── plaintext_baseline_volumes.png
```

- `raw_runs.csv` contains one row per warmup and measured run.
- `batch_summary.csv` contains measured-run statistics for runtime and throughput, result counts, hashes, and correctness.
- `trades.csv` and `unmatched_orders.csv` contain the evidence from the first measured run of each batch.

### Plaintext CLOB with blockchain audit

```text
results/plaintext_blockchain/
├── csv/
│   ├── batch_summary.csv
│   ├── raw_runs.csv
│   ├── blockchain_audit.csv
│   ├── trades.csv
│   └── unmatched_orders.csv
├── batch_evidence/
│   ├── batch_*_orders.csv
│   ├── batch_*_trades.csv
│   └── batch_*_unmatched_orders.csv
└── figures/
    ├── plaintext_blockchain_blocks.png
    ├── plaintext_blockchain_gas_used.png
    └── plaintext_blockchain_transaction_time.png
```

`blockchain_audit.csv` records evidence and result hashes, contract and transaction identifiers, block numbers and timestamps, gas and fee fields, nonce, receipt status, submission/mining/confirmation timings, confirmation depth, and failure information.

### Paillier/PHE aggregation

```text
results/paillier_phe/
├── csv/
│   ├── batch_summary.csv
│   └── raw_runs.csv
├── batch_evidence/
│   ├── batch_*_orders.csv
│   └── batch_*_paillier_aggregate.csv
└── figures/
    ├── paillier_phe_runtime.png
    ├── paillier_phe_throughput.png
    ├── paillier_phe_components.png
    └── paillier_phe_ciphertext_size.png
```

The summary separates encryption, encrypted-computation, and final-decryption timings. Evidence records the source batch and the decrypted aggregate result used for independent correctness checking. Individual order quantities are not decrypted during aggregation.

### Paillier/PHE aggregation with blockchain audit

```text
results/paillier_phe_blockchain/
├── csv/
│   ├── batch_summary.csv
│   ├── raw_runs.csv
│   ├── blockchain_audit.csv
│   └── encrypted_evidence_index.csv
├── batch_evidence/
│   ├── encrypted_orders_batch_*.jsonl
│   ├── phe_result_batch_*.json
│   └── phe_metadata_batch_*.json
└── figures/
    ├── runtime.png
    ├── throughput.png
    ├── encryption_time.png
    ├── encrypted_computation_time.png
    ├── decryption_time.png
    ├── ciphertext_size.png
    ├── blockchain_time.png
    └── gas_used.png
```

- `encrypted_orders_batch_*.jsonl` contains encrypted BUY and SELL quantity columns plus hashed order identifiers.
- `phe_result_batch_*.json` contains encrypted aggregate ciphertexts, decrypted final totals, the reference totals, and correctness status.
- `phe_metadata_batch_*.json` describes the key size and evidence format without storing private key material.
- `encrypted_evidence_index.csv` links each evidence file to its SHA-256 hash, size, batch, and public-key hash.
- `blockchain_audit.csv` contains one row per requested lifecycle stage with transaction, gas, receipt, confirmation, and error fields.

### Final comparison

```text
results/final_comparison/
├── csv/
│   ├── all_raw_runs.csv
│   ├── comparison_summary.csv
│   ├── correctness_comparison.csv
│   ├── experiment_manifest.csv
│   ├── overhead_breakdown.csv
│   ├── blockchain_overhead.csv
│   └── run_time_by_experiment_run.csv
├── tables/
│   ├── thesis_table_experiment_config.csv
│   ├── thesis_table_runtime_summary.csv
│   ├── thesis_table_run_time_by_run.csv
│   ├── thesis_table_correctness_summary.csv
│   └── thesis_table_blockchain_overhead.csv
└── figures/
    ├── 01_total_runtime_comparison.png
    ├── 02_throughput_comparison.png
    ├── 03_runtime_component_breakdown.png
    ├── 04_relative_slowdown_vs_baseline.png
    ├── 05_audit_overhead_percentage.png
    ├── 06_correctness_matched_volume.png
    ├── 07_blockchain_gas_used.png
    ├── 08_blockchain_transaction_time.png
    └── 09_scalability_loglog_runtime.png
```

The generator includes any experiment folder containing `csv/batch_summary.csv`. It prints warnings when variants use different batch sizes, lack a plaintext baseline, or have different input hashes.

## Interpreting the results

- `raw_runs.csv` includes warmups and measured runs. Filter `is_warmup == False` for reported timing observations.
- Component timing statistics in `batch_summary.csv` are calculated from measured runs only. The human-facing `total_runtime_s_*` and summary throughput fields use the full wall-clock time for each batch; inspect `raw_runs.csv` for per-run totals and throughput.
- Runtime columns ending in `_s` are seconds. Audit columns ending in `_ms` are milliseconds.
- Throughput is reported as orders per second.
- Input and evidence hashes are SHA-256 digests used to check that compared runs used the intended data and that blockchain records match local evidence.
- `correctness_pass` is variant-specific. For plaintext it checks CLOB/trade consistency; for Paillier it checks decrypted aggregate totals against an independent plaintext aggregation; blockchain variants additionally verify the stored audit record. It does not mean that Paillier aggregation is algorithmically equivalent to price-aware CLOB matching.
- Timings depend on the CPU, operating system, Python/Node versions, and other machine load. Exact runtime values are not expected to be identical across machines.

## Local blockchain profile

| Setting | Value |
|---|---|
| Network | Local Hardhat Ethereum-compatible chain |
| RPC URL | `http://127.0.0.1:8545` |
| Chain ID | `31337` |
| Mining | Fixed 12-second interval |
| Block gas limit | `60,000,000` gas |
| Initial base fee | `1,000,000,000` wei |
| Default experiment confirmations | `2` |

The chain is ephemeral. Restarting `npm run node` removes its contracts and audit records. Redeploy `BatchAudit` after every restart.

Audit records are keyed by variant and batch ID. If you change a batch or generate new Paillier evidence and then rerun the same variant/batch ID against an existing chain, the existing record may not match. Start a fresh Hardhat node and redeploy before a clean experimental run.

## Blockchain explorer

After the node is running and the contract is deployed, start the frontend in another terminal:

```bash
cd frontend
npm run dev
```

Open <http://127.0.0.1:5173>.

The React/Vite explorer reads the live Hardhat RPC and deployment JSON. It displays network status, blocks, transactions, receipts, decoded methods and events, contract roles, batch lifecycle state, audit records, hashes, and gas usage.

The explorer is read-only. It does not run experiments, execute shell commands, display experiment CSVs/PNGs, or write contract records. Deployment alone produces an empty audit contract; run a blockchain experiment to populate it.

Build the frontend for production:

```bash
npm --prefix frontend run build
```

The build is written to `frontend/dist/`.

## Tests

Run the Python unit tests:

```bash
python -m pytest
```

Run the Solidity contract tests:

```bash
npm --prefix blockchain test
```

Run the frontend TypeScript/Vite build check:

```bash
npm --prefix frontend run build
```

Run all three layers:

```bash
python scripts/run_automatic_tests.py --all
```

The optional integration smoke test requires a running Hardhat node and a current deployment:

```bash
PHE_RUN_BLOCKCHAIN_INTEGRATION=1 \
  python -m pytest tests/test_blockchain_integration_smoke.py -m integration
```

## Troubleshooting

### `Could not connect to local blockchain RPC`

Start the node and keep it running:

```bash
cd blockchain
npm run node
```

### `Deployment file not found`

Deploy the contract from a second terminal:

```bash
cd blockchain
npm run deploy:localhost
```

### Deployment metadata exists but no contract code is found

The Hardhat node was probably restarted. Its state is ephemeral, so redeploy the contract before running another blockchain experiment.

### An existing audit record does not match

The same variant and batch ID was already recorded with different evidence. Stop the node, start a fresh node, redeploy, and run each blockchain variant once.

### Blockchain experiments appear slow

This is expected with 12-second interval mining, three lifecycle transactions per audited batch, and the default confirmation depth of two. Use a small batch profile and `--confirmations 0` only for workflow smoke testing.

### Paillier experiments appear slow

Real 2,048-bit Paillier encryption is CPU-intensive and scales with both the number of orders and repetitions. Use small batches for development; keep 2,048-bit keys and sufficient measured runs for reported research results.

## Repository structure

```text
src/common/                 Data validation, generation, hashing, metrics, and timing
src/variants/plaintext/     Price-time-priority CLOB implementation
src/variants/paillier_phe/  Paillier encryption and homomorphic aggregation
src/variants/blockchain/    Web3 connection, audit submission, and transaction metrics
src/experiments/            Runnable experiment and comparison entry points
src/visualization/          CSV-to-PNG visualization modules
blockchain/                 Hardhat config, BatchAudit contract, deployment, and tests
frontend/                   React/Vite read-only blockchain explorer
scripts/                    Grouped test runner
tests/                      Python unit and optional integration tests
data/                       Generated combined synthetic-order CSV
results/                    Datasets, experiment evidence, summaries, tables, and figures
```

## Reproducibility notes and limitations

- Synthetic orders are deterministic for the same generator settings and seed.
- Paillier key generation and encryption use cryptographic randomness, so ciphertexts, public-key hashes, and encrypted-evidence hashes differ between runs even when decrypted totals agree.
- Experiment runners overwrite their standard output files. Preserve any result snapshot you need before starting a new profile.
- Use identical batch sizes, seeds, and dataset hashes for meaningful comparisons.
- The local Hardhat chain is an experiment instrument, not a production blockchain or a benchmark of a public network.
- The prototype evaluates encrypted volume aggregation, not fully encrypted order matching, price discovery, settlement, or custody.
