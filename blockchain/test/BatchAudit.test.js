const { expect } = require("chai");
const { ethers, network } = require("hardhat");
const { anyValue } = require("@nomicfoundation/hardhat-chai-matchers/withArgs");

function testHash(value) {
  return ethers.keccak256(ethers.toUtf8Bytes(value));
}

function validRecord(overrides = {}) {
  return {
    variant: "plaintext_blockchain",
    batchId: "batch_0001",
    batchSize: 10000,
    buyVolume: 514500,
    sellVolume: 488200,
    matchedVolume: 479100,
    executedTradeCount: 4930,
    ordersFileHash: testHash("orders"),
    tradesFileHash: testHash("trades"),
    unmatchedOrdersFileHash: testHash("unmatched"),
    resultRowHash: testHash("result-row"),
    ...overrides
  };
}

async function recordBatch(batchAudit, record) {
  await (await batchAudit.openBatch(
    record.variant,
    record.batchId,
    record.ordersFileHash
  )).wait();
  await (await batchAudit.closeBatch(
    record.variant,
    record.batchId,
    record.resultRowHash
  )).wait();
  return batchAudit.recordBatchAudit(
    record.variant,
    record.batchId,
    record.batchSize,
    record.buyVolume,
    record.sellVolume,
    record.matchedVolume,
    record.executedTradeCount,
    record.ordersFileHash,
    record.tradesFileHash,
    record.unmatchedOrdersFileHash,
    record.resultRowHash
  );
}

describe("BatchAudit", function () {
  beforeEach(async function () {
    await network.provider.send("evm_setAutomine", [true]);
  });

  async function deployBatchAudit() {
    const [owner, operator, auditor, otherSubmitter] = await ethers.getSigners();
    const batchAudit = await ethers.deployContract("BatchAudit");
    await batchAudit.waitForDeployment();
    return { batchAudit, owner, operator, auditor, otherSubmitter };
  }

  it("deploys", async function () {
    const { batchAudit, owner } = await deployBatchAudit();
    expect(await batchAudit.getAddress()).to.match(/^0x[a-fA-F0-9]{40}$/);
    expect(await batchAudit.owner()).to.equal(owner.address);
    expect(await batchAudit.operators(owner.address)).to.equal(true);
    expect(await batchAudit.auditors(owner.address)).to.equal(true);
  });

  it("owner can add and remove operators and auditors", async function () {
    const { batchAudit, operator, auditor } = await deployBatchAudit();

    await expect(batchAudit.addOperator(operator.address))
      .to.emit(batchAudit, "OperatorAdded")
      .withArgs(operator.address);
    await expect(batchAudit.addAuditor(auditor.address))
      .to.emit(batchAudit, "AuditorAdded")
      .withArgs(auditor.address);

    expect(await batchAudit.operators(operator.address)).to.equal(true);
    expect(await batchAudit.auditors(auditor.address)).to.equal(true);

    await expect(batchAudit.removeOperator(operator.address))
      .to.emit(batchAudit, "OperatorRemoved")
      .withArgs(operator.address);
    await expect(batchAudit.removeAuditor(auditor.address))
      .to.emit(batchAudit, "AuditorRemoved")
      .withArgs(auditor.address);

    expect(await batchAudit.operators(operator.address)).to.equal(false);
    expect(await batchAudit.auditors(auditor.address)).to.equal(false);
  });

  it("rejects role changes from non-owner accounts", async function () {
    const { batchAudit, operator, otherSubmitter } = await deployBatchAudit();

    await expect(
      batchAudit.connect(otherSubmitter).addOperator(operator.address)
    ).to.be.revertedWith("owner only");
  });

  it("records the opened and closed batch lifecycle", async function () {
    const { batchAudit, owner } = await deployBatchAudit();
    const input = validRecord();

    await expect(batchAudit.openBatch(input.variant, input.batchId, input.ordersFileHash))
      .to.emit(batchAudit, "BatchOpened")
      .withArgs(input.variant, input.batchId, input.ordersFileHash, owner.address, anyValue, anyValue);
    expect(await batchAudit.getBatchStatus(input.variant, input.batchId)).to.equal(1n);

    await expect(batchAudit.closeBatch(input.variant, input.batchId, input.resultRowHash))
      .to.emit(batchAudit, "BatchClosed")
      .withArgs(input.variant, input.batchId, input.resultRowHash, owner.address, anyValue, anyValue);
    expect(await batchAudit.getBatchStatus(input.variant, input.batchId)).to.equal(2n);
  });

  it("rejects audit writes from unauthorized accounts", async function () {
    const { batchAudit, otherSubmitter } = await deployBatchAudit();
    const input = validRecord();

    await (await batchAudit.openBatch(input.variant, input.batchId, input.ordersFileHash)).wait();
    await (await batchAudit.closeBatch(input.variant, input.batchId, input.resultRowHash)).wait();

    await expect(batchAudit.connect(otherSubmitter).recordBatchAudit(
      input.variant,
      input.batchId,
      input.batchSize,
      input.buyVolume,
      input.sellVolume,
      input.matchedVolume,
      input.executedTradeCount,
      input.ordersFileHash,
      input.tradesFileHash,
      input.unmatchedOrdersFileHash,
      input.resultRowHash
    )).to.be.revertedWith("operator only");
  });

  it("rejects opening a batch with an empty commitment", async function () {
    const { batchAudit } = await deployBatchAudit();
    const input = validRecord();

    await expect(batchAudit.openBatch(
      input.variant,
      input.batchId,
      ethers.ZeroHash
    )).to.be.revertedWith("batchCommitment is required");
  });

  it("rejects auditing a closed batch twice", async function () {
    const { batchAudit } = await deployBatchAudit();
    const input = validRecord();

    await (await recordBatch(batchAudit, input)).wait();

    await expect(batchAudit.recordBatchAudit(
      input.variant,
      input.batchId,
      input.batchSize,
      input.buyVolume,
      input.sellVolume,
      input.matchedVolume,
      input.executedTradeCount,
      input.ordersFileHash,
      input.tradesFileHash,
      input.unmatchedOrdersFileHash,
      input.resultRowHash
    )).to.be.revertedWith("audit record already exists");
  });

  it("rejects auditing before a batch is closed", async function () {
    const { batchAudit } = await deployBatchAudit();
    const input = validRecord();

    await (await batchAudit.openBatch(input.variant, input.batchId, input.ordersFileHash)).wait();

    await expect(batchAudit.recordBatchAudit(
      input.variant,
      input.batchId,
      input.batchSize,
      input.buyVolume,
      input.sellVolume,
      input.matchedVolume,
      input.executedTradeCount,
      input.ordersFileHash,
      input.tradesFileHash,
      input.unmatchedOrdersFileHash,
      input.resultRowHash
    )).to.be.revertedWith("batch is not closed");
  });

  it("recordBatchAudit stores a valid audit record", async function () {
    const { batchAudit, owner } = await deployBatchAudit();
    const input = validRecord();

    const tx = await recordBatch(batchAudit, input);
    const receipt = await tx.wait();

    const record = await batchAudit.getBatchAudit(input.variant, input.batchId);

    expect(record.variant).to.equal(input.variant);
    expect(record.batchId).to.equal(input.batchId);
    expect(record.batchSize).to.equal(BigInt(input.batchSize));
    expect(record.buyVolume).to.equal(BigInt(input.buyVolume));
    expect(record.sellVolume).to.equal(BigInt(input.sellVolume));
    expect(record.matchedVolume).to.equal(BigInt(input.matchedVolume));
    expect(record.executedTradeCount).to.equal(BigInt(input.executedTradeCount));
    expect(record.ordersFileHash).to.equal(input.ordersFileHash);
    expect(record.tradesFileHash).to.equal(input.tradesFileHash);
    expect(record.unmatchedOrdersFileHash).to.equal(input.unmatchedOrdersFileHash);
    expect(record.resultRowHash).to.equal(input.resultRowHash);
    expect(record.submitter).to.equal(owner.address);
    expect(record.recordedBlock).to.equal(BigInt(receipt.blockNumber));
    expect(record.exists).to.equal(true);
    expect(await batchAudit.getBatchStatus(input.variant, input.batchId)).to.equal(3n);
  });

  it("getBatchAudit returns correct values", async function () {
    const { batchAudit } = await deployBatchAudit();
    const input = validRecord({ batchId: "batch_0002", matchedVolume: 1200 });

    await (await recordBatch(batchAudit, input)).wait();

    const record = await batchAudit.getBatchAudit(input.variant, input.batchId);
    expect(record.batchId).to.equal("batch_0002");
    expect(record.matchedVolume).to.equal(1200n);
  });

  it("batchExists returns true after storing", async function () {
    const { batchAudit } = await deployBatchAudit();
    const input = validRecord();

    expect(await batchAudit.batchExists(input.variant, input.batchId)).to.equal(false);
    await (await recordBatch(batchAudit, input)).wait();
    expect(await batchAudit.batchExists(input.variant, input.batchId)).to.equal(true);
  });

  it("getRecordCount increases after storing", async function () {
    const { batchAudit } = await deployBatchAudit();

    expect(await batchAudit.getRecordCount()).to.equal(0n);
    await (await recordBatch(batchAudit, validRecord())).wait();
    expect(await batchAudit.getRecordCount()).to.equal(1n);
  });

  it("getRecordKey returns a valid indexed key", async function () {
    const { batchAudit } = await deployBatchAudit();
    const input = validRecord();

    await (await recordBatch(batchAudit, input)).wait();

    const expectedKey = await batchAudit.getRecordKeyByVariantAndBatchId(
      input.variant,
      input.batchId
    );
    expect(await batchAudit.getRecordKey(0)).to.equal(expectedKey);
  });

  it("getBatchAuditByKey returns a record directly by key", async function () {
    const { batchAudit } = await deployBatchAudit();
    const input = validRecord();

    await (await recordBatch(batchAudit, input)).wait();

    const recordKey = await batchAudit.getRecordKeyByVariantAndBatchId(
      input.variant,
      input.batchId
    );
    const record = await batchAudit.getBatchAuditByKey(recordKey);

    expect(record.variant).to.equal(input.variant);
    expect(record.batchId).to.equal(input.batchId);
  });

  it("emits BatchAuditRecorded with expected values", async function () {
    const { batchAudit, owner } = await deployBatchAudit();
    const input = validRecord();

    await expect(recordBatch(batchAudit, input))
      .to.emit(batchAudit, "BatchAuditRecorded")
      .withArgs(
        input.variant,
        input.batchId,
        input.batchSize,
        input.matchedVolume,
        input.executedTradeCount,
        input.resultRowHash,
        owner.address,
        anyValue,
        anyValue
      );
  });

  it("rejects duplicate records for the same variant and batchId", async function () {
    const { batchAudit } = await deployBatchAudit();
    const input = validRecord();

    await (await recordBatch(batchAudit, input)).wait();

    await expect(recordBatch(batchAudit, input)).to.be.revertedWith(
      "batch lifecycle already exists"
    );
  });

  it("allows the same batchId for different variants", async function () {
    const { batchAudit } = await deployBatchAudit();

    await (await recordBatch(batchAudit, validRecord({
      variant: "plaintext_blockchain",
      batchId: "batch_0001"
    }))).wait();
    await (await recordBatch(batchAudit, validRecord({
      variant: "basic_encryption_blockchain",
      batchId: "batch_0001"
    }))).wait();
    await (await recordBatch(batchAudit, validRecord({
      variant: "paillier_phe_blockchain",
      batchId: "batch_0001"
    }))).wait();

    expect(await batchAudit.getRecordCount()).to.equal(3n);
    expect(await batchAudit.batchExists("plaintext_blockchain", "batch_0001")).to.equal(true);
    expect(await batchAudit.batchExists("basic_encryption_blockchain", "batch_0001")).to.equal(true);
    expect(await batchAudit.batchExists("paillier_phe_blockchain", "batch_0001")).to.equal(true);
  });

  it("rejects empty variant", async function () {
    const { batchAudit } = await deployBatchAudit();
    await expect(recordBatch(batchAudit, validRecord({ variant: "" }))).to.be.revertedWith(
      "variant is required"
    );
  });

  it("rejects empty batchId", async function () {
    const { batchAudit } = await deployBatchAudit();
    await expect(recordBatch(batchAudit, validRecord({ batchId: "" }))).to.be.revertedWith(
      "batchId is required"
    );
  });

  it("rejects zero batchSize", async function () {
    const { batchAudit } = await deployBatchAudit();
    await expect(recordBatch(batchAudit, validRecord({ batchSize: 0 }))).to.be.revertedWith(
      "batchSize must be positive"
    );
  });

  it("rejects zero resultRowHash", async function () {
    const { batchAudit } = await deployBatchAudit();
    const input = validRecord({
      resultRowHash: ethers.ZeroHash
    });
    await (await batchAudit.openBatch(input.variant, input.batchId, input.ordersFileHash)).wait();
    await expect(batchAudit.closeBatch(
      input.variant,
      input.batchId,
      input.resultRowHash
    )).to.be.revertedWith("resultCommitment is required");
  });
});
