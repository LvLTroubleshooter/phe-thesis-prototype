// SPDX-License-Identifier: MIT
pragma solidity ^0.8.28;

/// @title BatchAudit
/// @notice Variant-neutral audit registry for batch-level experiment results.
/// @dev Stores metadata, hashes, and aggregate results only. CLOB matching and
/// full datasets remain off-chain.
contract BatchAudit {
    enum BatchStatus {
        None,
        Opened,
        Closed,
        Audited,
        Cancelled
    }

    struct BatchRecord {
        string variant;
        string batchId;
        uint256 batchSize;
        uint256 buyVolume;
        uint256 sellVolume;
        uint256 matchedVolume;
        uint256 executedTradeCount;
        bytes32 ordersFileHash;
        bytes32 tradesFileHash;
        bytes32 unmatchedOrdersFileHash;
        bytes32 resultRowHash;
        address submitter;
        uint256 recordedAt;
        uint256 recordedBlock;
        bool exists;
    }

    struct BatchLifecycle {
        string variant;
        string batchId;
        bytes32 batchCommitment;
        bytes32 resultCommitment;
        bytes32 cancelReasonHash;
        BatchStatus status;
        address openedBy;
        address closedBy;
        address auditedBy;
        address cancelledBy;
        uint256 openedAt;
        uint256 closedAt;
        uint256 auditedAt;
        uint256 cancelledAt;
        bool exists;
    }

    address public owner;
    mapping(address => bool) public operators;
    mapping(address => bool) public auditors;

    event BatchAuditRecorded(
        string variant,
        string batchId,
        uint256 batchSize,
        uint256 matchedVolume,
        uint256 executedTradeCount,
        bytes32 resultRowHash,
        address submitter,
        uint256 recordedAt,
        uint256 recordedBlock
    );

    event OperatorAdded(address indexed operator);
    event OperatorRemoved(address indexed operator);
    event AuditorAdded(address indexed auditor);
    event AuditorRemoved(address indexed auditor);

    event BatchOpened(
        string variant,
        string batchId,
        bytes32 batchCommitment,
        address indexed operator,
        uint256 openedAt,
        uint256 openedBlock
    );

    event BatchClosed(
        string variant,
        string batchId,
        bytes32 resultCommitment,
        address indexed operator,
        uint256 closedAt,
        uint256 closedBlock
    );

    event BatchCancelled(
        string variant,
        string batchId,
        bytes32 reasonHash,
        address indexed operator,
        uint256 cancelledAt,
        uint256 cancelledBlock
    );

    mapping(bytes32 => BatchRecord) private records;
    mapping(bytes32 => BatchLifecycle) private lifecycles;
    bytes32[] private recordKeys;

    modifier onlyOwner() {
        require(msg.sender == owner, "owner only");
        _;
    }

    modifier onlyOperator() {
        require(operators[msg.sender], "operator only");
        _;
    }

    constructor() {
        owner = msg.sender;
        operators[msg.sender] = true;
        auditors[msg.sender] = true;
        emit OperatorAdded(msg.sender);
        emit AuditorAdded(msg.sender);
    }

    function getRecordKeyByVariantAndBatchId(
        string calldata variant,
        string calldata batchId
    ) public pure returns (bytes32) {
        return keccak256(abi.encodePacked(variant, ":", batchId));
    }

    function addOperator(address operator) external onlyOwner {
        require(operator != address(0), "operator is required");
        operators[operator] = true;
        emit OperatorAdded(operator);
    }

    function removeOperator(address operator) external onlyOwner {
        require(operator != owner, "owner operator required");
        operators[operator] = false;
        emit OperatorRemoved(operator);
    }

    function addAuditor(address auditor) external onlyOwner {
        require(auditor != address(0), "auditor is required");
        auditors[auditor] = true;
        emit AuditorAdded(auditor);
    }

    function removeAuditor(address auditor) external onlyOwner {
        auditors[auditor] = false;
        emit AuditorRemoved(auditor);
    }

    function openBatch(
        string calldata variant,
        string calldata batchId,
        bytes32 batchCommitment
    ) external onlyOperator returns (bytes32 recordKey) {
        require(bytes(variant).length > 0, "variant is required");
        require(bytes(batchId).length > 0, "batchId is required");
        require(batchCommitment != bytes32(0), "batchCommitment is required");

        recordKey = getRecordKeyByVariantAndBatchId(variant, batchId);
        require(!lifecycles[recordKey].exists, "batch lifecycle already exists");

        lifecycles[recordKey] = BatchLifecycle({
            variant: variant,
            batchId: batchId,
            batchCommitment: batchCommitment,
            resultCommitment: bytes32(0),
            cancelReasonHash: bytes32(0),
            status: BatchStatus.Opened,
            openedBy: msg.sender,
            closedBy: address(0),
            auditedBy: address(0),
            cancelledBy: address(0),
            openedAt: block.timestamp,
            closedAt: 0,
            auditedAt: 0,
            cancelledAt: 0,
            exists: true
        });

        emit BatchOpened(
            variant,
            batchId,
            batchCommitment,
            msg.sender,
            block.timestamp,
            block.number
        );
    }

    function closeBatch(
        string calldata variant,
        string calldata batchId,
        bytes32 resultCommitment
    ) external onlyOperator {
        require(resultCommitment != bytes32(0), "resultCommitment is required");

        bytes32 recordKey = getRecordKeyByVariantAndBatchId(variant, batchId);
        BatchLifecycle storage lifecycle = lifecycles[recordKey];
        require(lifecycle.exists, "batch lifecycle not found");
        require(lifecycle.status == BatchStatus.Opened, "batch is not open");

        lifecycle.resultCommitment = resultCommitment;
        lifecycle.status = BatchStatus.Closed;
        lifecycle.closedBy = msg.sender;
        lifecycle.closedAt = block.timestamp;

        emit BatchClosed(
            variant,
            batchId,
            resultCommitment,
            msg.sender,
            block.timestamp,
            block.number
        );
    }

    function cancelBatch(
        string calldata variant,
        string calldata batchId,
        bytes32 reasonHash
    ) external onlyOperator {
        require(reasonHash != bytes32(0), "reasonHash is required");

        bytes32 recordKey = getRecordKeyByVariantAndBatchId(variant, batchId);
        BatchLifecycle storage lifecycle = lifecycles[recordKey];
        require(lifecycle.exists, "batch lifecycle not found");
        require(lifecycle.status != BatchStatus.Audited, "audited batch cannot be cancelled");
        require(lifecycle.status != BatchStatus.Cancelled, "batch already cancelled");

        lifecycle.cancelReasonHash = reasonHash;
        lifecycle.status = BatchStatus.Cancelled;
        lifecycle.cancelledBy = msg.sender;
        lifecycle.cancelledAt = block.timestamp;

        emit BatchCancelled(
            variant,
            batchId,
            reasonHash,
            msg.sender,
            block.timestamp,
            block.number
        );
    }

    function recordBatchAudit(
        string calldata variant,
        string calldata batchId,
        uint256 batchSize,
        uint256 buyVolume,
        uint256 sellVolume,
        uint256 matchedVolume,
        uint256 executedTradeCount,
        bytes32 ordersFileHash,
        bytes32 tradesFileHash,
        bytes32 unmatchedOrdersFileHash,
        bytes32 resultRowHash
    ) external onlyOperator returns (bytes32 recordKey) {
        require(bytes(variant).length > 0, "variant is required");
        require(bytes(batchId).length > 0, "batchId is required");
        require(batchSize > 0, "batchSize must be positive");
        require(resultRowHash != bytes32(0), "resultRowHash is required");

        recordKey = getRecordKeyByVariantAndBatchId(variant, batchId);
        require(!records[recordKey].exists, "audit record already exists");
        BatchLifecycle storage lifecycle = lifecycles[recordKey];
        require(lifecycle.exists, "batch lifecycle not found");
        require(lifecycle.status == BatchStatus.Closed, "batch is not closed");
        require(lifecycle.batchCommitment == ordersFileHash, "batch commitment mismatch");
        require(lifecycle.resultCommitment == resultRowHash, "result commitment mismatch");

        records[recordKey] = BatchRecord({
            variant: variant,
            batchId: batchId,
            batchSize: batchSize,
            buyVolume: buyVolume,
            sellVolume: sellVolume,
            matchedVolume: matchedVolume,
            executedTradeCount: executedTradeCount,
            ordersFileHash: ordersFileHash,
            tradesFileHash: tradesFileHash,
            unmatchedOrdersFileHash: unmatchedOrdersFileHash,
            resultRowHash: resultRowHash,
            submitter: msg.sender,
            recordedAt: block.timestamp,
            recordedBlock: block.number,
            exists: true
        });

        recordKeys.push(recordKey);
        lifecycle.status = BatchStatus.Audited;
        lifecycle.auditedBy = msg.sender;
        lifecycle.auditedAt = block.timestamp;

        emit BatchAuditRecorded(
            variant,
            batchId,
            batchSize,
            matchedVolume,
            executedTradeCount,
            resultRowHash,
            msg.sender,
            block.timestamp,
            block.number
        );
    }

    function getBatchAudit(
        string calldata variant,
        string calldata batchId
    ) external view returns (BatchRecord memory) {
        bytes32 recordKey = getRecordKeyByVariantAndBatchId(variant, batchId);
        return _getBatchAuditByKey(recordKey);
    }

    function getBatchAuditByKey(bytes32 recordKey) external view returns (BatchRecord memory) {
        return _getBatchAuditByKey(recordKey);
    }

    function batchExists(
        string calldata variant,
        string calldata batchId
    ) external view returns (bool) {
        bytes32 recordKey = getRecordKeyByVariantAndBatchId(variant, batchId);
        return records[recordKey].exists;
    }

    function getRecordCount() external view returns (uint256) {
        return recordKeys.length;
    }

    function getRecordKey(uint256 index) external view returns (bytes32) {
        require(index < recordKeys.length, "record index out of bounds");
        return recordKeys[index];
    }

    function getBatchLifecycle(
        string calldata variant,
        string calldata batchId
    ) external view returns (BatchLifecycle memory) {
        bytes32 recordKey = getRecordKeyByVariantAndBatchId(variant, batchId);
        return _getBatchLifecycleByKey(recordKey);
    }

    function getBatchLifecycleByKey(bytes32 recordKey) external view returns (BatchLifecycle memory) {
        return _getBatchLifecycleByKey(recordKey);
    }

    function getBatchStatus(
        string calldata variant,
        string calldata batchId
    ) external view returns (BatchStatus) {
        bytes32 recordKey = getRecordKeyByVariantAndBatchId(variant, batchId);
        return lifecycles[recordKey].status;
    }

    function _getBatchAuditByKey(bytes32 recordKey) internal view returns (BatchRecord memory) {
        require(records[recordKey].exists, "audit record not found");
        return records[recordKey];
    }

    function _getBatchLifecycleByKey(bytes32 recordKey) internal view returns (BatchLifecycle memory) {
        require(lifecycles[recordKey].exists, "batch lifecycle not found");
        return lifecycles[recordKey];
    }
}
