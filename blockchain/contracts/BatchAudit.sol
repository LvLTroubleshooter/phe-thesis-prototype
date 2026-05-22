// SPDX-License-Identifier: MIT
pragma solidity ^0.8.28;

/// @title BatchAudit
/// @notice Variant-neutral audit registry for batch-level experiment results.
/// @dev Stores metadata, hashes, and aggregate results only. CLOB matching and
/// full datasets remain off-chain.
contract BatchAudit {
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

    mapping(bytes32 => BatchRecord) private records;
    bytes32[] private recordKeys;

    function getRecordKeyByVariantAndBatchId(
        string calldata variant,
        string calldata batchId
    ) public pure returns (bytes32) {
        return keccak256(abi.encodePacked(variant, ":", batchId));
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
    ) external returns (bytes32 recordKey) {
        require(bytes(variant).length > 0, "variant is required");
        require(bytes(batchId).length > 0, "batchId is required");
        require(batchSize > 0, "batchSize must be positive");
        require(resultRowHash != bytes32(0), "resultRowHash is required");

        recordKey = getRecordKeyByVariantAndBatchId(variant, batchId);
        require(!records[recordKey].exists, "audit record already exists");

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

    function _getBatchAuditByKey(bytes32 recordKey) internal view returns (BatchRecord memory) {
        require(records[recordKey].exists, "audit record not found");
        return records[recordKey];
    }
}
