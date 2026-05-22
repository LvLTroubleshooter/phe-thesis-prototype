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
    const [owner, otherSubmitter] = await ethers.getSigners();
    const batchAudit = await ethers.deployContract("BatchAudit");
    await batchAudit.waitForDeployment();
    return { batchAudit, owner, otherSubmitter };
  }

  it("deploys", async function () {
    const { batchAudit } = await deployBatchAudit();
    expect(await batchAudit.getAddress()).to.match(/^0x[a-fA-F0-9]{40}$/);
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
      "audit record already exists"
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
    await expect(recordBatch(batchAudit, validRecord({
      resultRowHash: ethers.ZeroHash
    }))).to.be.revertedWith("resultRowHash is required");
  });
});
