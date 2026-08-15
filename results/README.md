# Experiment results

This directory contains the committed result snapshot for the four experiment variants. The source repository is [LvLTroubleshooter/phe-thesis-prototype](https://github.com/LvLTroubleshooter/phe-thesis-prototype).

## Folder contents

- `datasets/`: deterministic synthetic order batches and their manifest, including input hashes.
- `plaintext_baseline/`: plaintext CLOB run data, summaries, trade and unmatched-order evidence, and figures.
- `plaintext_blockchain/`: plaintext CLOB results, per-batch evidence, blockchain audit records, and figures.
- `paillier_phe/`: Paillier encrypted-aggregation runs, per-batch input and aggregate evidence, summaries, and figures.
- `paillier_phe_blockchain/`: encrypted-aggregation evidence, its evidence index, blockchain audit records, summaries, and figures.
- `final_comparison/`: combined CSV analyses, thesis-ready tables, and comparison figures for all available variants.

Within an experiment folder, `csv/` contains measurements and summaries, `figures/` contains generated charts, and `batch_evidence/` contains auditable per-batch artifacts where that variant produces them.

## Experiment commands

Run these from the repository root after installing the dependencies. Use the same `--batch-sizes` and `--seed` for comparable runs; see the main README for the full committed-profile arguments.

```bash
python -m src.experiments.run_plaintext_baseline
python -m src.experiments.run_paillier_phe_experiment
python -m src.experiments.run_plaintext_blockchain_experiment
python -m src.experiments.run_paillier_phe_blockchain_experiment
python -m src.experiments.generate_final_comparison
```

The blockchain variants also require a running and freshly deployed local Hardhat chain (`cd blockchain && npm run node`, then `npm run deploy:localhost` in another terminal).

## Unavailable evidence

- The archived results contain the encrypted-evidence index, but the 15 indexed JSONL/JSON files from the Paillier PHE + blockchain variant were not retained. Therefore, their hashes and storage sizes could not be recomputed.
- The plaintext baseline does not produce a separate `batch_evidence/` directory. Its evidence is consolidated in `csv/trades.csv` and `csv/unmatched_orders.csv`, with inputs stored under `datasets/`.
- Paillier private-key material is intentionally not stored; only public-key hashes and the evidence needed to check decrypted aggregate totals are included.
- The historical Hardhat chain state and generated deployment JSON files are not committed because the local chain is ephemeral. Transaction hashes and receipt metrics remain in the blockchain audit CSVs, but the old transactions cannot be queried unless that original node state was preserved separately.
- `paillier_phe_blockchain/csv/blockchain_audit.csv` records a failed `recordBatchAudit` attempt for `batch_0001` (`existing record does not match evidence`); therefore, a successful on-chain audit record for that attempt is unavailable.
