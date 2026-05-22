import { useCallback, useEffect, useMemo, useState, type ReactNode } from "react";
import { Contract, JsonRpcProvider, LogDescription, TransactionResponse } from "ethers";

type Deployment = {
  contractName: string;
  address: string;
  deploymentTransactionHash?: string;
  deploymentBlockNumber?: number | null;
  deployer?: string;
  network?: string;
  chainId?: number;
  rpcUrl: string;
  miningMode: string;
  blockCreationTimeSeconds: number;
  blockGasLimit: number;
  initialBaseFeePerGas?: number;
  deployedAt?: string;
  abi: Array<Record<string, unknown>>;
};

type ExplorerTab =
  | "overview"
  | "blocks"
  | "transactions"
  | "contract"
  | "records"
  | "events";

type Detail =
  | { type: "block"; value: BlockRow }
  | { type: "transaction"; value: TransactionRow }
  | { type: "record"; value: AuditRecord }
  | { type: "event"; value: AuditEvent }
  | null;

type BlockRow = {
  number: number;
  hash: string;
  parentHash: string;
  timestamp: number;
  transactionCount: number;
  gasUsed: string;
  gasLimit: string;
  gasPercent: number;
  miner: string;
  status: string;
  raw: unknown;
};

type TransactionRow = {
  hash: string;
  method: string;
  status: string;
  blockNumber: number;
  timestamp: number;
  from: string;
  to: string;
  contractAddress: string;
  gasUsed: string;
  gasLimit: string;
  effectiveGasPrice: string;
  transactionFee: string;
  nonce: number;
  transactionIndex: number;
  logsCount: number;
  relatedBatchId: string;
  inputPreview: string;
  decodedArguments: Array<{ name: string; value: string }>;
  rawTransaction: unknown;
  rawReceipt: unknown;
};

type AuditRecord = {
  key: string;
  variant: string;
  batchId: string;
  batchSize: string;
  buyVolume: string;
  sellVolume: string;
  matchedVolume: string;
  executedTradeCount: string;
  ordersFileHash: string;
  tradesFileHash: string;
  unmatchedOrdersFileHash: string;
  resultRowHash: string;
  submitter: string;
  recordedAt: number;
  recordedBlock: string;
  transactionHash: string;
  blockTimestamp: number;
  verificationStatus: string;
  raw: unknown;
};

type AuditEvent = {
  eventName: string;
  contractAddress: string;
  transactionHash: string;
  blockNumber: number;
  logIndex: number;
  timestamp: number;
  variant: string;
  batchId: string;
  batchSize: string;
  matchedVolume: string;
  executedTradeCount: string;
  resultRowHash: string;
  raw: unknown;
};

type ExplorerState = {
  connected: boolean;
  networkName: string;
  chainId: string;
  currentBlockNumber: number | null;
  latestBlockTimestamp: number | null;
  blocks: BlockRow[];
  transactions: TransactionRow[];
  auditRecords: AuditRecord[];
  auditEvents: AuditEvent[];
  bytecodeDetected: boolean;
  error: string | null;
  lastUpdated: string | null;
};

const fallbackDeploymentInfo: Deployment = {
  contractName: "BatchAudit",
  address: "",
  network: "localhost",
  chainId: 31337,
  rpcUrl: "http://127.0.0.1:8545",
  miningMode: "interval",
  blockCreationTimeSeconds: 12,
  blockGasLimit: 60_000_000,
  initialBaseFeePerGas: 1_000_000_000,
  abi: []
};

let deploymentInfo = fallbackDeploymentInfo;
const BLOCK_SCAN_LIMIT = 80;
const TRANSACTION_ROW_LIMIT = 40;
const DEPLOYMENT_METADATA_URL = "/deployments/BatchAudit.localhost.json";
const ZERO_HASH = "0x0000000000000000000000000000000000000000000000000000000000000000";

const initialState: ExplorerState = {
  connected: false,
  networkName: deploymentInfo.network ?? "localhost",
  chainId: String(deploymentInfo.chainId),
  currentBlockNumber: null,
  latestBlockTimestamp: null,
  blocks: [],
  transactions: [],
  auditRecords: [],
  auditEvents: [],
  bytecodeDetected: false,
  error: null,
  lastUpdated: null
};

const tabs: Array<{ id: ExplorerTab; label: string }> = [
  { id: "overview", label: "Overview" },
  { id: "blocks", label: "Blocks" },
  { id: "transactions", label: "Transactions" },
  { id: "contract", label: "Contract" },
  { id: "records", label: "Batch Records" },
  { id: "events", label: "Events" }
];

function formatNumber(value: bigint | number | string): string {
  const numeric = Number(value);
  if (!Number.isFinite(numeric)) return "n/a";
  return Intl.NumberFormat("en-US").format(numeric);
}

function formatPercent(value: number): string {
  return `${value.toFixed(2)}%`;
}

function formatTimestamp(timestamp: number | null): string {
  if (!timestamp) return "n/a";
  return new Date(timestamp * 1000).toLocaleString();
}

function formatAge(timestamp: number | null): string {
  if (!timestamp) return "n/a";
  const seconds = Math.max(0, Math.floor(Date.now() / 1000 - timestamp));
  if (seconds < 60) return `${seconds}s ago`;
  const minutes = Math.floor(seconds / 60);
  if (minutes < 60) return `${minutes}m ago`;
  return `${Math.floor(minutes / 60)}h ago`;
}

function shortHash(value?: string | null): string {
  if (!value) return "n/a";
  if (value.length <= 18) return value;
  return `${value.slice(0, 10)}...${value.slice(-8)}`;
}

function safeString(value: unknown): string {
  if (value === null || value === undefined) return "";
  if (typeof value === "bigint") return value.toString();
  if (Array.isArray(value)) return value.map(safeString).join(", ");
  if (typeof value === "object") {
    try {
      return JSON.stringify(value, (_, nested) =>
        typeof nested === "bigint" ? nested.toString() : nested
      );
    } catch {
      return String(value);
    }
  }
  return String(value);
}

function toJson(value: unknown): string {
  return JSON.stringify(
    value,
    (_, nested) => (typeof nested === "bigint" ? nested.toString() : nested),
    2
  );
}

function statusForHashes(record: AuditRecord): string {
  const hashes = [
    record.ordersFileHash,
    record.tradesFileHash,
    record.unmatchedOrdersFileHash,
    record.resultRowHash
  ];
  return hashes.every((hash) => hash && hash !== ZERO_HASH)
    ? "Recorded on-chain"
    : "Not available";
}

async function loadDeploymentInfo(): Promise<Deployment> {
  const response = await fetch(`${DEPLOYMENT_METADATA_URL}?t=${Date.now()}`, {
    cache: "no-store"
  });
  if (!response.ok) return deploymentInfo;
  const metadata = (await response.json()) as Deployment;
  deploymentInfo = metadata;
  return metadata;
}

async function getScannedBlocks(provider: JsonRpcProvider, latest: number): Promise<BlockRow[]> {
  const first = Math.max(0, latest - BLOCK_SCAN_LIMIT + 1);
  const rows: BlockRow[] = [];

  for (let blockNumber = latest; blockNumber >= first; blockNumber -= 1) {
    const block = await provider.getBlock(blockNumber);
    if (!block) continue;
    const gasUsed = Number(block.gasUsed);
    const gasLimit = Number(block.gasLimit);
    rows.push({
      number: block.number,
      hash: block.hash ?? "",
      parentHash: block.parentHash,
      timestamp: block.timestamp,
      transactionCount: block.transactions.length,
      gasUsed: block.gasUsed.toString(),
      gasLimit: block.gasLimit.toString(),
      gasPercent: gasLimit > 0 ? (gasUsed / gasLimit) * 100 : 0,
      miner: "miner" in block ? safeString((block as unknown as { miner?: string }).miner) : "not available",
      status: "canonical",
      raw: block.toJSON()
    });
  }

  return rows;
}

function decodeTransaction(contract: Contract, tx: TransactionResponse) {
  try {
    const decoded = contract.interface.parseTransaction({
      data: tx.data,
      value: tx.value
    });
    if (!decoded) return { method: "transfer", args: [], relatedBatchId: "" };
    return {
      method: decoded.name,
      args: decoded.fragment.inputs.map((input, index) => ({
        name: input.name || `arg${index}`,
        value: safeString(decoded.args[index])
      })),
      relatedBatchId:
        decoded.name === "recordBatchAudit" && decoded.args.length > 1
          ? safeString(decoded.args[1])
          : ""
    };
  } catch {
    return { method: tx.to ? "contract call" : "contract creation", args: [], relatedBatchId: "" };
  }
}

async function getLatestTransactions(
  provider: JsonRpcProvider,
  contract: Contract,
  latestBlockNumber: number,
  auditEvents: AuditEvent[],
  deployment: Deployment
): Promise<TransactionRow[]> {
  const hashes = new Set<string>();
  auditEvents.forEach((event) => hashes.add(event.transactionHash));

  const deploymentTxHash = await getDeploymentTransactionHash(provider, latestBlockNumber, deployment);
  if (deploymentTxHash) hashes.add(deploymentTxHash);

  const rows = await Promise.all(
    Array.from(hashes).map(async (hash) => {
      const tx = await provider.getTransaction(hash);
      if (!tx) return null;
      const receipt = await provider.getTransactionReceipt(hash);
      return transactionToRow(provider, contract, tx, receipt);
    })
  );

  return rows
    .filter((row): row is TransactionRow => row !== null)
    .sort(
      (left, right) =>
        right.blockNumber - left.blockNumber ||
        right.transactionIndex - left.transactionIndex
    )
    .slice(0, TRANSACTION_ROW_LIMIT);
}

async function getDeploymentTransactionHash(
  provider: JsonRpcProvider,
  latestBlockNumber: number,
  deployment: Deployment
): Promise<string | null> {
  if (deployment.deploymentTransactionHash) {
    return deployment.deploymentTransactionHash;
  }

  if (deployment.deploymentBlockNumber !== undefined && deployment.deploymentBlockNumber !== null) {
    const block = await provider.getBlock(deployment.deploymentBlockNumber, true);
    const txs = block?.prefetchedTransactions ?? [];
    for (const tx of txs) {
      const receipt = await provider.getTransactionReceipt(tx.hash);
      if (receipt?.contractAddress?.toLowerCase() === deployment.address.toLowerCase()) {
        return tx.hash;
      }
    }
  }

  const chunkSize = 25;
  for (let chunkStart = latestBlockNumber; chunkStart >= 0; chunkStart -= chunkSize) {
    const chunkEnd = Math.max(0, chunkStart - chunkSize + 1);
    const blocks = await Promise.all(
      Array.from(
        { length: chunkStart - chunkEnd + 1 },
        (_, index) => provider.getBlock(chunkStart - index, true)
      )
    );

    for (const block of blocks) {
      if (!block) continue;
      const txs = block.prefetchedTransactions ?? [];
      for (const tx of txs) {
        const receipt = await provider.getTransactionReceipt(tx.hash);
        if (receipt?.contractAddress?.toLowerCase() === deployment.address.toLowerCase()) {
          return tx.hash;
        }
      }
    }
  }

  return null;
}

async function transactionToRow(
  provider: JsonRpcProvider,
  contract: Contract,
  tx: TransactionResponse,
  receipt: Awaited<ReturnType<JsonRpcProvider["getTransactionReceipt"]>>
): Promise<TransactionRow | null> {
  const blockNumber = receipt?.blockNumber ?? tx.blockNumber;
  if (blockNumber === null) return null;

  const block = await provider.getBlock(blockNumber);
  const decoded = decodeTransaction(contract, tx);
  const receiptGasPrice = receipt as unknown as {
    effectiveGasPrice?: bigint;
    gasPrice?: bigint;
    feePrice?: bigint;
  } | null;
  const effectiveGasPrice =
    receiptGasPrice?.effectiveGasPrice ??
    receiptGasPrice?.gasPrice ??
    receiptGasPrice?.feePrice ??
    tx.gasPrice ??
    0n;
  const gasUsed = receipt?.gasUsed ?? 0n;

  return {
    hash: tx.hash,
    method: decoded.method,
    status: receipt?.status === 1 ? "Success" : receipt?.status === 0 ? "Failed" : "Pending",
    blockNumber,
    timestamp: block?.timestamp ?? 0,
    from: tx.from,
    to: tx.to ?? "contract creation",
    contractAddress: receipt?.contractAddress ?? "",
    gasUsed: gasUsed.toString(),
    gasLimit: tx.gasLimit.toString(),
    effectiveGasPrice: effectiveGasPrice.toString(),
    transactionFee: (gasUsed * effectiveGasPrice).toString(),
    nonce: tx.nonce,
    transactionIndex: receipt?.index ?? tx.index ?? 0,
    logsCount: receipt?.logs.length ?? 0,
    relatedBatchId: decoded.relatedBatchId,
    inputPreview: tx.data && tx.data !== "0x" ? `${tx.data.slice(0, 34)}...` : "0x",
    decodedArguments: decoded.args,
    rawTransaction: tx.toJSON(),
    rawReceipt: receipt?.toJSON() ?? {}
  };
}

function getDeploymentBlockNumber(bytecodeDetected: boolean, deploymentTx?: TransactionRow): number | string {
  if (!bytecodeDetected) {
    return "stale metadata";
  }
  if (deploymentInfo.deploymentBlockNumber !== undefined && deploymentInfo.deploymentBlockNumber !== null) {
    return deploymentInfo.deploymentBlockNumber;
  }
  return deploymentTx?.blockNumber ?? "not found";
}

function getDeploymentTimestamp(bytecodeDetected: boolean, deploymentTx?: TransactionRow): string {
  if (!bytecodeDetected) {
    return "stale metadata";
  }
  if (deploymentTx) {
    return formatTimestamp(deploymentTx.timestamp);
  }
  return deploymentInfo.deployedAt ? new Date(deploymentInfo.deployedAt).toLocaleString() : "not found";
}

async function getAuditEvents(contract: Contract, blocks: BlockRow[]): Promise<AuditEvent[]> {
  const timestamps = new Map(blocks.map((block) => [block.number, block.timestamp]));
  const events = await contract.queryFilter(contract.filters.BatchAuditRecorded(), 0, "latest");

  const mapped: Array<AuditEvent | null> = events.map((event) => {
      const fallback = contract.interface.parseLog(event) as LogDescription | null;
      const args = "args" in event && event.args ? event.args : fallback?.args;
      if (!args) return null;
      return {
        eventName: "BatchAuditRecorded",
        contractAddress: event.address,
        transactionHash: event.transactionHash,
        blockNumber: event.blockNumber,
        logIndex: event.index,
        timestamp: timestamps.get(event.blockNumber) ?? 0,
        variant: safeString(args.variant),
        batchId: safeString(args.batchId),
        batchSize: safeString(args.batchSize),
        matchedVolume: safeString(args.matchedVolume),
        executedTradeCount: safeString(args.executedTradeCount),
        resultRowHash: safeString(args.resultRowHash),
        raw: event as unknown
      };
    });

  return mapped.filter((event): event is AuditEvent => event !== null).reverse();
}

async function getAuditRecords(
  contract: Contract,
  events: AuditEvent[],
  blocks: BlockRow[]
): Promise<AuditRecord[]> {
  const count = Number(await contract.getRecordCount());
  const blockTimestamps = new Map(blocks.map((block) => [String(block.number), block.timestamp]));
  const eventByBatch = new Map(events.map((event) => [`${event.variant}:${event.batchId}`, event]));
  const rows: AuditRecord[] = [];

  for (let index = 0; index < count; index += 1) {
    const key = await contract.getRecordKey(index);
    const record = await contract.getBatchAuditByKey(key);
    const event = eventByBatch.get(`${record.variant}:${record.batchId}`);
    const row: AuditRecord = {
      key,
      variant: record.variant,
      batchId: record.batchId,
      batchSize: record.batchSize.toString(),
      buyVolume: record.buyVolume.toString(),
      sellVolume: record.sellVolume.toString(),
      matchedVolume: record.matchedVolume.toString(),
      executedTradeCount: record.executedTradeCount.toString(),
      ordersFileHash: record.ordersFileHash,
      tradesFileHash: record.tradesFileHash,
      unmatchedOrdersFileHash: record.unmatchedOrdersFileHash,
      resultRowHash: record.resultRowHash,
      submitter: record.submitter,
      recordedAt: Number(record.recordedAt),
      recordedBlock: record.recordedBlock.toString(),
      transactionHash: event?.transactionHash ?? "",
      blockTimestamp: blockTimestamps.get(record.recordedBlock.toString()) ?? Number(record.recordedAt),
      verificationStatus: "Not verified locally",
      raw: record
    };
    row.verificationStatus = statusForHashes(row) === "Recorded on-chain" ? "Not verified locally" : "Not available";
    rows.push(row);
  }

  return rows;
}

export default function App() {
  const [state, setState] = useState<ExplorerState>(initialState);
  const [activeTab, setActiveTab] = useState<ExplorerTab>("overview");
  const [autoRefresh, setAutoRefresh] = useState(true);
  const [isLoading, setIsLoading] = useState(false);
  const [search, setSearch] = useState("");
  const [searchMessage, setSearchMessage] = useState("");
  const [detail, setDetail] = useState<Detail>(null);
  const [blockLimit, setBlockLimit] = useState(20);
  const [txStatusFilter, setTxStatusFilter] = useState("all");
  const [txMethodFilter, setTxMethodFilter] = useState("all");
  const [recordVariantFilter, setRecordVariantFilter] = useState("all");
  const [recordBatchFilter, setRecordBatchFilter] = useState("");
  const [eventVariantFilter, setEventVariantFilter] = useState("all");
  const [eventSearch, setEventSearch] = useState("");

  const provider = useMemo(() => new JsonRpcProvider(deploymentInfo.rpcUrl), []);

  const refresh = useCallback(async () => {
    setIsLoading(true);
    try {
      const network = await provider.getNetwork();
      const activeDeployment = await loadDeploymentInfo();
      const currentBlockNumber = await provider.getBlockNumber();
      const latestBlock = await provider.getBlock(currentBlockNumber);
      const contract = new Contract(activeDeployment.address, activeDeployment.abi, provider);
      const bytecode = await provider.getCode(activeDeployment.address);
      const blocks = await getScannedBlocks(provider, currentBlockNumber);
      const warnings: string[] = [];
      if (bytecode === "0x") {
        warnings.push(
          "Deployment metadata exists, but no contract code was found at this address. The local chain may have been restarted. Redeploy the contract."
        );
      }

      let auditEvents: AuditEvent[] = [];
      try {
        auditEvents = await getAuditEvents(contract, blocks);
      } catch (error) {
        warnings.push(`Audit events could not be loaded: ${error instanceof Error ? error.message : safeString(error)}`);
      }

      let auditRecords: AuditRecord[] = [];
      try {
        auditRecords = await getAuditRecords(contract, auditEvents, blocks);
      } catch (error) {
        warnings.push(`Audit records could not be loaded: ${error instanceof Error ? error.message : safeString(error)}`);
      }

      let transactions: TransactionRow[] = [];
      try {
        transactions = await getLatestTransactions(provider, contract, currentBlockNumber, auditEvents, activeDeployment);
      } catch (error) {
        warnings.push(`Transactions could not be loaded: ${error instanceof Error ? error.message : safeString(error)}`);
      }

      setState({
        connected: true,
        networkName: "Local Private Network",
        chainId: network.chainId.toString(),
        currentBlockNumber,
        latestBlockTimestamp: latestBlock?.timestamp ?? null,
        blocks,
        transactions,
        auditRecords,
        auditEvents,
        bytecodeDetected: bytecode !== "0x",
        error: warnings.length ? warnings.join(" ") : null,
        lastUpdated: new Date().toLocaleTimeString()
      });
    } catch (error) {
      setState((current) => ({
        ...current,
        connected: false,
        error:
          `Hardhat node is not reachable or BatchAudit is not available. The local chain may have been restarted. Deploy the contract and run the blockchain experiment again to repopulate records. Details: ${error instanceof Error ? error.message : safeString(error)}`,
        lastUpdated: new Date().toLocaleTimeString()
      }));
    } finally {
      setIsLoading(false);
    }
  }, [provider]);

  useEffect(() => {
    void refresh();
  }, [refresh]);

  useEffect(() => {
    if (!autoRefresh) return undefined;
    const interval = window.setInterval(() => void refresh(), 10_000);
    return () => window.clearInterval(interval);
  }, [autoRefresh, refresh]);

  const deploymentTx = useMemo(
    () =>
      state.transactions.find(
        (tx) => tx.contractAddress.toLowerCase() === deploymentInfo.address.toLowerCase()
      ),
    [state.transactions]
  );

  const filteredTransactions = state.transactions.filter(
    (tx) =>
      (txStatusFilter === "all" || tx.status === txStatusFilter) &&
      (txMethodFilter === "all" || tx.method === txMethodFilter)
  );

  const filteredRecords = state.auditRecords
    .filter(
      (record) =>
        (recordVariantFilter === "all" || record.variant === recordVariantFilter) &&
        record.batchId.toLowerCase().includes(recordBatchFilter.toLowerCase())
    )
    .sort((left, right) => Number(right.recordedBlock) - Number(left.recordedBlock));

  const filteredEvents = state.auditEvents.filter(
    (event) =>
      (eventVariantFilter === "all" || event.variant === eventVariantFilter) &&
      `${event.batchId} ${event.transactionHash}`.toLowerCase().includes(eventSearch.toLowerCase())
  );

  function runSearch() {
    const value = search.trim().toLowerCase();
    if (!value) {
      setSearchMessage("Enter a block number, transaction hash, address, batch ID, variant, or hash.");
      return;
    }

    const block = /^\d+$/.test(value)
      ? state.blocks.find((item) => String(item.number) === value)
      : state.blocks.find((item) => item.hash.toLowerCase() === value || item.parentHash.toLowerCase() === value);
    if (block) {
      setActiveTab("blocks");
      setDetail({ type: "block", value: block });
      setSearchMessage(`Found block ${block.number}.`);
      return;
    }

    const tx = state.transactions.find(
      (item) =>
        item.hash.toLowerCase() === value ||
        item.from.toLowerCase() === value ||
        item.to.toLowerCase() === value ||
        item.contractAddress.toLowerCase() === value
    );
    if (tx) {
      setActiveTab("transactions");
      setDetail({ type: "transaction", value: tx });
      setSearchMessage(`Found transaction ${shortHash(tx.hash)}.`);
      return;
    }

    const record = state.auditRecords.find((item) =>
      [
        item.variant,
        item.batchId,
        item.submitter,
        item.ordersFileHash,
        item.tradesFileHash,
        item.unmatchedOrdersFileHash,
        item.resultRowHash
      ]
        .map((itemValue) => itemValue.toLowerCase())
        .includes(value)
    );
    if (record) {
      setActiveTab("records");
      setDetail({ type: "record", value: record });
      setSearchMessage(`Found batch record ${record.batchId}.`);
      return;
    }

    const event = state.auditEvents.find(
      (item) =>
        item.batchId.toLowerCase() === value ||
        item.variant.toLowerCase() === value ||
        item.transactionHash.toLowerCase() === value ||
        item.resultRowHash.toLowerCase() === value
    );
    if (event) {
      setActiveTab("events");
      setDetail({ type: "event", value: event });
      setSearchMessage(`Found event for ${event.batchId}.`);
      return;
    }

    if (deploymentInfo.address.toLowerCase() === value) {
      setActiveTab("contract");
      setSearchMessage("Found BatchAudit contract.");
      return;
    }

    setSearchMessage("No matching record found.");
  }

  return (
    <main className="explorer-shell">
      <header className="explorer-topbar">
        <div className="brand-block">
          <div className="brand-mark">BA</div>
          <div>
            <p className="eyebrow">Local Private Network</p>
            <h1>BatchAudit Explorer</h1>
          </div>
        </div>
        <div className="search-bar">
          <input
            value={search}
            onChange={(event) => setSearch(event.target.value)}
            onKeyDown={(event) => {
              if (event.key === "Enter") runSearch();
            }}
            placeholder="Search block, tx hash, address, batch ID, variant, or hash"
          />
          <button onClick={runSearch}>Search</button>
        </div>
        <div className="topbar-status">
          <StatusBadge value={state.connected ? "Connected" : "Disconnected"} />
          <span>Block {state.currentBlockNumber ?? "n/a"}</span>
          <span>{deploymentInfo.rpcUrl}</span>
        </div>
      </header>

      {searchMessage && <div className="search-message">{searchMessage}</div>}

      <div className="explorer-layout">
        <aside className="sidebar">
          {tabs.map((tab) => (
            <button
              key={tab.id}
              className={activeTab === tab.id ? "active" : ""}
              onClick={() => setActiveTab(tab.id)}
            >
              {tab.label}
            </button>
          ))}
          <div className="sidebar-tools">
            <label className="toggle">
              <input
                type="checkbox"
                checked={autoRefresh}
                onChange={(event) => setAutoRefresh(event.target.checked)}
              />
              Auto refresh
            </label>
            <button onClick={() => void refresh()} disabled={isLoading}>
              Refresh
            </button>
            {isLoading && <span className="refresh-indicator" title="Refreshing" aria-label="Refreshing" />}
            <span>Last refreshed: {state.lastUpdated ?? "n/a"}</span>
          </div>
        </aside>

        <section className="content-area">
          {state.error && <Notice>{state.error}</Notice>}

          {activeTab === "overview" && (
            <Overview
              state={state}
              deploymentTx={deploymentTx}
              onBlock={(block) => setDetail({ type: "block", value: block })}
              onTx={(tx) => setDetail({ type: "transaction", value: tx })}
              onEvent={(event) => setDetail({ type: "event", value: event })}
            />
          )}
          {activeTab === "blocks" && (
            <BlocksPage
              blocks={state.blocks}
              limit={blockLimit}
              setLimit={setBlockLimit}
              onSelect={(block) => setDetail({ type: "block", value: block })}
            />
          )}
          {activeTab === "transactions" && (
            <TransactionsPage
              rows={filteredTransactions}
              allRows={state.transactions}
              statusFilter={txStatusFilter}
              methodFilter={txMethodFilter}
              setStatusFilter={setTxStatusFilter}
              setMethodFilter={setTxMethodFilter}
              onSelect={(tx) => setDetail({ type: "transaction", value: tx })}
            />
          )}
          {activeTab === "contract" && (
            <ContractPage
              state={state}
              deploymentTx={deploymentTx}
              onRecord={(record) => setDetail({ type: "record", value: record })}
            />
          )}
          {activeTab === "records" && (
            <BatchRecordsPage
              rows={filteredRecords}
              allRows={state.auditRecords}
              variantFilter={recordVariantFilter}
              batchFilter={recordBatchFilter}
              setVariantFilter={setRecordVariantFilter}
              setBatchFilter={setRecordBatchFilter}
              onSelect={(record) => setDetail({ type: "record", value: record })}
            />
          )}
          {activeTab === "events" && (
            <EventsPage
              rows={filteredEvents}
              allRows={state.auditEvents}
              variantFilter={eventVariantFilter}
              search={eventSearch}
              setVariantFilter={setEventVariantFilter}
              setSearch={setEventSearch}
              onSelect={(event) => setDetail({ type: "event", value: event })}
            />
          )}
        </section>
      </div>

      {detail && <DetailPanel detail={detail} onClose={() => setDetail(null)} />}
    </main>
  );
}

function Overview({
  state,
  deploymentTx,
  onBlock,
  onTx,
  onEvent
}: {
  state: ExplorerState;
  deploymentTx?: TransactionRow;
  onBlock: (block: BlockRow) => void;
  onTx: (tx: TransactionRow) => void;
  onEvent: (event: AuditEvent) => void;
}) {
  const latestBlock = state.blocks[0];
  const averageBlockTime =
    state.blocks.length > 1
      ? (state.blocks[0].timestamp - state.blocks[state.blocks.length - 1].timestamp) /
        (state.blocks.length - 1)
      : deploymentInfo.blockCreationTimeSeconds;

  return (
    <>
      <section className="metric-grid">
        <Metric label="Network" value={state.networkName} />
        <Metric label="Connection" value={state.connected ? "Connected" : "Disconnected"} status={state.connected ? "success" : "failed"} />
        <Metric label="Chain ID" value={state.chainId} />
        <Metric label="RPC URL" value={deploymentInfo.rpcUrl} mono />
        <Metric label="Latest block" value={state.currentBlockNumber ?? "n/a"} />
        <Metric label="Latest timestamp" value={formatTimestamp(state.latestBlockTimestamp)} />
        <Metric label="Average block time" value={`${averageBlockTime.toFixed(1)}s`} />
        <Metric label="Block gas limit" value={formatNumber(deploymentInfo.blockGasLimit)} />
        <Metric label="Latest gas used" value={latestBlock ? formatNumber(latestBlock.gasUsed) : "n/a"} />
        <Metric label="Scanned blocks" value={state.blocks.length} />
        <Metric label="Transactions found" value={state.transactions.length} />
        <Metric label="Audit records" value={state.auditRecords.length} />
        <Metric label="Audit events" value={state.auditEvents.length} />
        <Metric label="Contract address" value={shortHash(deploymentInfo.address)} mono copyValue={deploymentInfo.address} />
        <Metric label="Deployment block" value={getDeploymentBlockNumber(state.bytecodeDetected, deploymentTx)} />
      </section>

      <section className="activity-grid">
        <ExplorerTable title="Latest Blocks">
          <thead>
            <tr>
              <th>Block</th>
              <th>Age</th>
              <th>Txs</th>
              <th>Gas used</th>
              <th>Hash</th>
            </tr>
          </thead>
          <tbody>
            {state.blocks.slice(0, 6).map((block) => (
              <tr key={block.number} onClick={() => onBlock(block)}>
                <td className="linklike">{block.number}</td>
                <td>{formatAge(block.timestamp)}</td>
                <td>{block.transactionCount}</td>
                <td>{formatNumber(block.gasUsed)}</td>
                <td><Hash value={block.hash} /></td>
              </tr>
            ))}
            {!state.blocks.length && <EmptyRow columns={5} label="Scanning latest blocks..." />}
          </tbody>
        </ExplorerTable>

        <ExplorerTable title="Latest Transactions">
          <thead>
            <tr>
              <th>Txn hash</th>
              <th>Method</th>
              <th>Block</th>
              <th>Gas used</th>
              <th>Status</th>
            </tr>
          </thead>
          <tbody>
            {state.transactions.slice(0, 6).map((tx) => (
              <tr key={tx.hash} onClick={() => onTx(tx)}>
                <td><Hash value={tx.hash} /></td>
                <td><MethodBadge value={tx.method} /></td>
                <td>{tx.blockNumber}</td>
                <td>{formatNumber(tx.gasUsed)}</td>
                <td><StatusBadge value={tx.status} /></td>
              </tr>
            ))}
            {!state.transactions.length && <EmptyRow columns={5} label="No transactions found in the scanned block range." />}
          </tbody>
        </ExplorerTable>
      </section>

      <ExplorerTable title="Latest Audit Events">
        <thead>
          <tr>
            <th>Event</th>
            <th>Variant</th>
            <th>Batch ID</th>
            <th>Block</th>
            <th>Transaction</th>
            <th>Result hash</th>
          </tr>
        </thead>
        <tbody>
          {state.auditEvents.slice(0, 8).map((event) => (
            <tr key={`${event.transactionHash}-${event.logIndex}`} onClick={() => onEvent(event)}>
              <td>{event.eventName}</td>
              <td>{event.variant}</td>
              <td>{event.batchId}</td>
              <td>{event.blockNumber}</td>
              <td><Hash value={event.transactionHash} /></td>
              <td><Hash value={event.resultRowHash} /></td>
            </tr>
          ))}
          {!state.auditEvents.length && <EmptyRow columns={6} label="No BatchAuditRecorded events found." />}
        </tbody>
      </ExplorerTable>
    </>
  );
}

function BlocksPage({
  blocks,
  limit,
  setLimit,
  onSelect
}: {
  blocks: BlockRow[];
  limit: number;
  setLimit: (value: number) => void;
  onSelect: (block: BlockRow) => void;
}) {
  return (
    <Panel title="Blocks">
      <ExplorerTable title={`Scanned Blocks (${blocks.length})`}>
        <thead>
          <tr>
            <th>Block</th>
            <th>Hash</th>
            <th>Timestamp</th>
            <th>Age</th>
            <th>Txs</th>
            <th>Gas used</th>
            <th>Gas limit</th>
            <th>Gas %</th>
            <th>Parent hash</th>
            <th>Miner / validator</th>
            <th>Status</th>
          </tr>
        </thead>
        <tbody>
          {blocks.slice(0, limit).map((block) => (
            <tr key={block.number} onClick={() => onSelect(block)}>
              <td className="linklike">{block.number}</td>
              <td><Hash value={block.hash} /></td>
              <td>{formatTimestamp(block.timestamp)}</td>
              <td>{formatAge(block.timestamp)}</td>
              <td>{block.transactionCount}</td>
              <td>{formatNumber(block.gasUsed)}</td>
              <td>{formatNumber(block.gasLimit)}</td>
              <td>{formatPercent(block.gasPercent)}</td>
              <td><Hash value={block.parentHash} /></td>
              <td><Hash value={block.miner} /></td>
              <td><StatusBadge value={block.status} /></td>
            </tr>
          ))}
          {!blocks.length && <EmptyRow columns={11} label="No blocks available. Connect to the local private network." />}
        </tbody>
      </ExplorerTable>
      {limit < blocks.length && (
        <button className="secondary-action" onClick={() => setLimit(limit + 20)}>
          Load more blocks
        </button>
      )}
    </Panel>
  );
}

function TransactionsPage({
  rows,
  allRows,
  statusFilter,
  methodFilter,
  setStatusFilter,
  setMethodFilter,
  onSelect
}: {
  rows: TransactionRow[];
  allRows: TransactionRow[];
  statusFilter: string;
  methodFilter: string;
  setStatusFilter: (value: string) => void;
  setMethodFilter: (value: string) => void;
  onSelect: (tx: TransactionRow) => void;
}) {
  const methods = Array.from(new Set(allRows.map((tx) => tx.method)));
  const statuses = Array.from(new Set(allRows.map((tx) => tx.status)));
  return (
    <Panel title="Transactions">
      <div className="filters">
        <Select label="Method" value={methodFilter} options={["all", ...methods]} onChange={setMethodFilter} />
        <Select label="Status" value={statusFilter} options={["all", ...statuses]} onChange={setStatusFilter} />
        <button className="secondary-action" onClick={() => exportCsv("transactions.csv", rows)}>
          Export transactions CSV
        </button>
      </div>
      <ExplorerTable title={`Transactions (${rows.length})`}>
        <thead>
          <tr>
            <th>Transaction hash</th>
            <th>Method</th>
            <th>Status</th>
            <th>Block</th>
            <th>Age</th>
            <th>From</th>
            <th>To</th>
            <th>Gas used</th>
            <th>Effective gas price</th>
            <th>Fee</th>
            <th>Nonce</th>
            <th>Index</th>
            <th>Logs</th>
          </tr>
        </thead>
        <tbody>
          {rows.map((tx) => (
            <tr key={tx.hash} onClick={() => onSelect(tx)}>
              <td><Hash value={tx.hash} /></td>
              <td><MethodBadge value={tx.method} /></td>
              <td><StatusBadge value={tx.status} /></td>
              <td>{tx.blockNumber}</td>
              <td>{formatAge(tx.timestamp)}</td>
              <td><Hash value={tx.from} /></td>
              <td><Hash value={tx.to} /></td>
              <td>{formatNumber(tx.gasUsed)}</td>
              <td>{formatNumber(tx.effectiveGasPrice)}</td>
              <td>{formatNumber(tx.transactionFee)}</td>
              <td>{tx.nonce}</td>
              <td>{tx.transactionIndex}</td>
              <td>{tx.logsCount}</td>
            </tr>
          ))}
          {!rows.length && <EmptyRow columns={13} label="No transactions found in the scanned block range." />}
        </tbody>
      </ExplorerTable>
    </Panel>
  );
}

function ContractPage({
  state,
  deploymentTx,
  onRecord
}: {
  state: ExplorerState;
  deploymentTx?: TransactionRow;
  onRecord: (record: AuditRecord) => void;
}) {
  const [readVariant, setReadVariant] = useState("plaintext_blockchain");
  const [readBatchId, setReadBatchId] = useState("batch_0001");
  const selected = state.auditRecords.find(
    (record) => record.variant === readVariant && record.batchId === readBatchId
  );

  return (
    <Panel title="Contract">
      <section className="contract-summary">
        <div>
          <p className="eyebrow">BatchAudit Contract</p>
          <h2>{deploymentInfo.contractName}</h2>
          <p>
            Stores variant-neutral batch audit records, file hashes, result hashes, and
            final batch-level values for the local private audit chain.
          </p>
        </div>
        <div className="metric-grid compact">
          <Metric label="Contract address" value={shortHash(deploymentInfo.address)} copyValue={deploymentInfo.address} mono />
          <Metric label="Deployer" value={shortHash(deploymentInfo.deployer)} copyValue={deploymentInfo.deployer} mono />
          <Metric
            label="Deployment transaction"
            value={deploymentInfo.deploymentTransactionHash ? shortHash(deploymentInfo.deploymentTransactionHash) : deploymentTx ? shortHash(deploymentTx.hash) : "not found"}
            copyValue={deploymentInfo.deploymentTransactionHash || deploymentTx?.hash}
            mono
          />
          <Metric label="Deployed block" value={getDeploymentBlockNumber(state.bytecodeDetected, deploymentTx)} />
          <Metric label="Deployment timestamp" value={getDeploymentTimestamp(state.bytecodeDetected, deploymentTx)} />
          <Metric label="Chain ID" value={state.chainId} />
          <Metric label="ABI status" value="ABI loaded" status="success" />
          <Metric label="Bytecode" value={state.bytecodeDetected ? "Bytecode found" : "Not detected"} status={state.bytecodeDetected ? "success" : "failed"} />
          <Metric label="Audit records" value={state.auditRecords.length} />
          <Metric label="Emitted events" value={state.auditEvents.length} />
        </div>
      </section>

      <section className="subtabs">
        <div>
          <h2>Read Contract</h2>
          <p className="muted">Read-only access to indexed audit records already stored by BatchAudit.</p>
        </div>
        <div className="filters">
          <label className="field">
            <span>Variant</span>
            <input value={readVariant} onChange={(event) => setReadVariant(event.target.value)} />
          </label>
          <label className="field">
            <span>Batch ID</span>
            <input value={readBatchId} onChange={(event) => setReadBatchId(event.target.value)} />
          </label>
        </div>
        {selected ? (
          <button className="secondary-action" onClick={() => onRecord(selected)}>
            Open matching audit record
          </button>
        ) : (
          <p className="empty-inline">No record found for that variant and batch ID.</p>
        )}
      </section>

      <ExplorerTable title="Contract Transactions">
        <thead>
          <tr>
            <th>Transaction</th>
            <th>Method</th>
            <th>Block</th>
            <th>Status</th>
            <th>Gas used</th>
          </tr>
        </thead>
        <tbody>
          {state.transactions
            .filter((tx) => tx.to.toLowerCase() === deploymentInfo.address.toLowerCase() || tx.contractAddress.toLowerCase() === deploymentInfo.address.toLowerCase())
            .map((tx) => (
              <tr key={`${tx.hash}-contract`}>
                <td><Hash value={tx.hash} /></td>
                <td><MethodBadge value={tx.method} /></td>
                <td>{tx.blockNumber}</td>
                <td><StatusBadge value={tx.status} /></td>
                <td>{formatNumber(tx.gasUsed)}</td>
              </tr>
            ))}
        </tbody>
      </ExplorerTable>
    </Panel>
  );
}

function BatchRecordsPage({
  rows,
  allRows,
  variantFilter,
  batchFilter,
  setVariantFilter,
  setBatchFilter,
  onSelect
}: {
  rows: AuditRecord[];
  allRows: AuditRecord[];
  variantFilter: string;
  batchFilter: string;
  setVariantFilter: (value: string) => void;
  setBatchFilter: (value: string) => void;
  onSelect: (record: AuditRecord) => void;
}) {
  const variants = Array.from(new Set(allRows.map((record) => record.variant)));
  return (
    <Panel title="Batch Records">
      <div className="filters">
        <Select label="Variant" value={variantFilter} options={["all", ...variants]} onChange={setVariantFilter} />
        <label className="field">
          <span>Batch ID</span>
          <input value={batchFilter} onChange={(event) => setBatchFilter(event.target.value)} />
        </label>
        <button className="secondary-action" onClick={() => exportCsv("batch-records.csv", rows)}>
          Export records CSV
        </button>
      </div>
      <ExplorerTable title={`Audit Records (${rows.length})`}>
        <thead>
          <tr>
            <th>Variant</th>
            <th>Batch ID</th>
            <th>Batch size</th>
            <th>Buy volume</th>
            <th>Sell volume</th>
            <th>Matched volume</th>
            <th>Trades</th>
            <th>Recorded block</th>
            <th>Transaction hash</th>
            <th>Submitter</th>
            <th>Status</th>
            <th>Result row hash</th>
          </tr>
        </thead>
        <tbody>
          {rows.map((record) => (
            <tr key={record.key} onClick={() => onSelect(record)}>
              <td>{record.variant}</td>
              <td>{record.batchId}</td>
              <td>{formatNumber(record.batchSize)}</td>
              <td>{formatNumber(record.buyVolume)}</td>
              <td>{formatNumber(record.sellVolume)}</td>
              <td>{formatNumber(record.matchedVolume)}</td>
              <td>{formatNumber(record.executedTradeCount)}</td>
              <td>{record.recordedBlock}</td>
              <td><Hash value={record.transactionHash} /></td>
              <td><Hash value={record.submitter} /></td>
              <td><StatusBadge value="Recorded" /></td>
              <td><Hash value={record.resultRowHash} /></td>
            </tr>
          ))}
          {!rows.length && <EmptyRow columns={12} label="No audit records match the current filters." />}
        </tbody>
      </ExplorerTable>
    </Panel>
  );
}

function EventsPage({
  rows,
  allRows,
  variantFilter,
  search,
  setVariantFilter,
  setSearch,
  onSelect
}: {
  rows: AuditEvent[];
  allRows: AuditEvent[];
  variantFilter: string;
  search: string;
  setVariantFilter: (value: string) => void;
  setSearch: (value: string) => void;
  onSelect: (event: AuditEvent) => void;
}) {
  const variants = Array.from(new Set(allRows.map((event) => event.variant)));
  return (
    <Panel title="Events">
      <div className="filters">
        <Select label="Variant" value={variantFilter} options={["all", ...variants]} onChange={setVariantFilter} />
        <label className="field">
          <span>Search batch or transaction</span>
          <input value={search} onChange={(event) => setSearch(event.target.value)} />
        </label>
        <button className="secondary-action" onClick={() => exportCsv("audit-events.csv", rows)}>
          Export events CSV
        </button>
      </div>
      <ExplorerTable title={`Decoded Events (${rows.length})`}>
        <thead>
          <tr>
            <th>Event name</th>
            <th>Variant</th>
            <th>Batch ID</th>
            <th>Block</th>
            <th>Transaction hash</th>
            <th>Log index</th>
            <th>Timestamp</th>
            <th>Batch size</th>
            <th>Matched volume</th>
            <th>Trades</th>
            <th>Result hash</th>
          </tr>
        </thead>
        <tbody>
          {rows.map((event) => (
            <tr key={`${event.transactionHash}-${event.logIndex}`} onClick={() => onSelect(event)}>
              <td>{event.eventName}</td>
              <td>{event.variant}</td>
              <td>{event.batchId}</td>
              <td>{event.blockNumber}</td>
              <td><Hash value={event.transactionHash} /></td>
              <td>{event.logIndex}</td>
              <td>{formatTimestamp(event.timestamp)}</td>
              <td>{formatNumber(event.batchSize)}</td>
              <td>{formatNumber(event.matchedVolume)}</td>
              <td>{formatNumber(event.executedTradeCount)}</td>
              <td><Hash value={event.resultRowHash} /></td>
            </tr>
          ))}
          {!rows.length && <EmptyRow columns={11} label="No decoded events match the current filters." />}
        </tbody>
      </ExplorerTable>
    </Panel>
  );
}

function DetailPanel({ detail, onClose }: { detail: Detail; onClose: () => void }) {
  const [showRaw, setShowRaw] = useState(false);
  if (!detail) return null;

  let title = "";
  let rows: Array<[string, ReactNode]> = [];
  let raw: unknown = {};

  if (detail.type === "block") {
    const block = detail.value;
    title = `Block ${block.number}`;
    raw = block.raw;
    rows = [
      ["Block number", block.number],
      ["Block hash", <Hash value={block.hash} />],
      ["Parent hash", <Hash value={block.parentHash} />],
      ["Timestamp", formatTimestamp(block.timestamp)],
      ["Transaction count", block.transactionCount],
      ["Gas used", formatNumber(block.gasUsed)],
      ["Gas limit", formatNumber(block.gasLimit)],
      ["Gas usage", formatPercent(block.gasPercent)],
      ["Miner / validator", <Hash value={block.miner} />],
      ["Status", <StatusBadge value={block.status} />]
    ];
  } else if (detail.type === "transaction") {
    const tx = detail.value;
    title = `Transaction ${shortHash(tx.hash)}`;
    raw = { transaction: tx.rawTransaction, receipt: tx.rawReceipt };
    rows = [
      ["Transaction hash", <Hash value={tx.hash} />],
      ["Status", <StatusBadge value={tx.status} />],
      ["Method", <MethodBadge value={tx.method} />],
      ["Related batch ID", tx.relatedBatchId || "not applicable"],
      ["Block number", tx.blockNumber],
      ["Timestamp", formatTimestamp(tx.timestamp)],
      ["From", <Hash value={tx.from} />],
      ["To", <Hash value={tx.to} />],
      ["Nonce", tx.nonce],
      ["Gas used", formatNumber(tx.gasUsed)],
      ["Gas limit", formatNumber(tx.gasLimit)],
      ["Effective gas price", formatNumber(tx.effectiveGasPrice)],
      ["Transaction fee", formatNumber(tx.transactionFee)],
      ["Logs / events", tx.logsCount],
      ["Input preview", <span className="mono">{tx.inputPreview}</span>],
      [
        "Decoded arguments",
        tx.decodedArguments.length
          ? tx.decodedArguments.map((arg) => (
              <div key={arg.name} className="decoded-arg">
                <strong>{arg.name}</strong>
                <span>{arg.value}</span>
              </div>
            ))
          : "not available"
      ]
    ];
  } else if (detail.type === "record") {
    const record = detail.value;
    title = `${record.variant} / ${record.batchId}`;
    raw = record.raw;
    rows = [
      ["Variant", record.variant],
      ["Batch ID", record.batchId],
      ["Batch size", formatNumber(record.batchSize)],
      ["Buy volume", formatNumber(record.buyVolume)],
      ["Sell volume", formatNumber(record.sellVolume)],
      ["Matched volume", formatNumber(record.matchedVolume)],
      ["Executed trades", formatNumber(record.executedTradeCount)],
      ["Submitter", <Hash value={record.submitter} />],
      ["Recorded block", record.recordedBlock],
      ["Transaction hash", <Hash value={record.transactionHash} />],
      ["Block timestamp", formatTimestamp(record.blockTimestamp)],
      ["Contract address", <Hash value={deploymentInfo.address} />],
      ["Orders file hash", <Hash value={record.ordersFileHash} />],
      ["Trades file hash", <Hash value={record.tradesFileHash} />],
      ["Unmatched orders hash", <Hash value={record.unmatchedOrdersFileHash} />],
      ["Result row hash", <Hash value={record.resultRowHash} />]
    ];
  } else {
    const event = detail.value;
    title = `${event.eventName} / ${event.batchId}`;
    raw = event.raw;
    rows = [
      ["Event name", event.eventName],
      ["Contract address", <Hash value={event.contractAddress} />],
      ["Block number", event.blockNumber],
      ["Transaction hash", <Hash value={event.transactionHash} />],
      ["Log index", event.logIndex],
      ["Timestamp", formatTimestamp(event.timestamp)],
      ["Variant", event.variant],
      ["Batch ID", event.batchId],
      ["Batch size", formatNumber(event.batchSize)],
      ["Matched volume", formatNumber(event.matchedVolume)],
      ["Executed trades", formatNumber(event.executedTradeCount)],
      ["Result hash", <Hash value={event.resultRowHash} />]
    ];
  }

  return (
    <aside className="detail-panel">
      <div className="detail-header">
        <div>
          <p className="eyebrow">Details</p>
          <h2>{title}</h2>
        </div>
        <button onClick={onClose}>Close</button>
      </div>
      <dl className="detail-list">
        {rows.map(([label, value]) => (
          <div key={label}>
            <dt>{label}</dt>
            <dd>{value}</dd>
          </div>
        ))}
      </dl>
      <button className="secondary-action" onClick={() => setShowRaw(!showRaw)}>
        {showRaw ? "Hide raw JSON" : "Show raw JSON"}
      </button>
      {showRaw && <pre className="raw-json">{toJson(raw)}</pre>}
    </aside>
  );
}

function Metric({
  label,
  value,
  mono,
  copyValue,
  status
}: {
  label: string;
  value: ReactNode;
  mono?: boolean;
  copyValue?: string;
  status?: string;
}) {
  return (
    <div className="metric">
      <span>{label}</span>
      <strong className={mono ? "mono" : undefined}>{value}</strong>
      {copyValue && <CopyButton value={copyValue} />}
      {status && <StatusBadge value={status} />}
    </div>
  );
}

function Panel({ title, children }: { title: string; children: ReactNode }) {
  return (
    <section className="panel">
      <div className="panel-heading">
        <h2>{title}</h2>
      </div>
      {children}
    </section>
  );
}

function ExplorerTable({ title, children }: { title: string; children: ReactNode }) {
  return (
    <section className="table-section">
      <div className="table-heading">
        <h2>{title}</h2>
      </div>
      <div className="table-wrap">
        <table>{children}</table>
      </div>
    </section>
  );
}

function EmptyRow({ columns, label }: { columns: number; label: string }) {
  return (
    <tr>
      <td className="empty" colSpan={columns}>{label}</td>
    </tr>
  );
}

function Hash({ value }: { value: string }) {
  return (
    <span className="hash-cell" title={value || "not available"}>
      <span className="mono">{shortHash(value)}</span>
      {value && value !== "not available" && <CopyButton value={value} />}
    </span>
  );
}

function CopyButton({ value }: { value: string }) {
  return (
    <button
      className="copy-button"
      onClick={(event) => {
        event.stopPropagation();
        void navigator.clipboard?.writeText(value);
      }}
      title="Copy full value"
    >
      Copy
    </button>
  );
}

function StatusBadge({ value }: { value: string }) {
  const normalized = value.toLowerCase();
  const className =
    normalized.includes("success") || normalized.includes("connected") || normalized.includes("recorded") || normalized.includes("found")
      ? "success"
      : normalized.includes("failed") || normalized.includes("mismatch") || normalized.includes("disconnected")
        ? "failed"
        : normalized.includes("not verified") || normalized.includes("pending")
          ? "warning"
          : "neutral";
  return <span className={`status-badge ${className}`}>{value}</span>;
}

function MethodBadge({ value }: { value: string }) {
  return <span className="method-badge">{value}</span>;
}

function Notice({ children }: { children: ReactNode }) {
  return <div className="notice">{children}</div>;
}

function Select({
  label,
  value,
  options,
  onChange
}: {
  label: string;
  value: string;
  options: string[];
  onChange: (value: string) => void;
}) {
  return (
    <label className="field">
      <span>{label}</span>
      <select value={value} onChange={(event) => onChange(event.target.value)}>
        {options.map((option) => (
          <option key={option} value={option}>{option}</option>
        ))}
      </select>
    </label>
  );
}

function exportCsv(filename: string, rows: Array<Record<string, unknown>>) {
  if (!rows.length) return;
  const columns = Object.keys(rows[0]);
  const csv = [
    columns.join(","),
    ...rows.map((row) => columns.map((column) => JSON.stringify(row[column] ?? "")).join(","))
  ].join("\n");
  const blob = new Blob([csv], { type: "text/csv;charset=utf-8" });
  const url = URL.createObjectURL(blob);
  const link = document.createElement("a");
  link.href = url;
  link.download = filename;
  link.click();
  URL.revokeObjectURL(url);
}
