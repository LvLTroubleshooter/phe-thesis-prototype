const fs = require("fs");
const path = require("path");
const hre = require("hardhat");

const {
  prototypeBlockchainConfig
} = require("../hardhat.config");

async function main() {
  const [deployer] = await hre.ethers.getSigners();
  const network = await hre.ethers.provider.getNetwork();

  const batchAudit = await hre.ethers.deployContract("BatchAudit");
  await batchAudit.waitForDeployment();

  const address = await batchAudit.getAddress();
  const deploymentTransaction = batchAudit.deploymentTransaction();
  const deploymentReceipt = deploymentTransaction
    ? await deploymentTransaction.wait()
    : null;
  const artifact = await hre.artifacts.readArtifact("BatchAudit");
  const deployment = {
    contractName: "BatchAudit",
    address,
    deploymentTransactionHash: deploymentReceipt?.hash || deploymentTransaction?.hash || "",
    deploymentBlockNumber: deploymentReceipt?.blockNumber || null,
    deployer: deployer.address,
    network: hre.network.name,
    chainId: Number(network.chainId),
    rpcUrl: prototypeBlockchainConfig.rpcUrl,
    miningMode: prototypeBlockchainConfig.miningMode,
    blockCreationTimeSeconds: prototypeBlockchainConfig.blockCreationTimeMs / 1000,
    blockGasLimit: prototypeBlockchainConfig.blockGasLimit,
    deployedAt: new Date().toISOString(),
    abi: artifact.abi,
    notes: [
      "Reusable Stage 6A local private blockchain foundation.",
      "Stores batch-level audit records, hashes, and metadata only.",
      "CLOB matching, full orders, trade logs, and unmatched orders remain off-chain."
    ]
  };

  const deploymentsDir = path.join(__dirname, "..", "deployments");
  fs.mkdirSync(deploymentsDir, { recursive: true });

  const outputPath = path.join(deploymentsDir, "BatchAudit.localhost.json");
  fs.writeFileSync(outputPath, `${JSON.stringify(deployment, null, 2)}\n`);

  const frontendDeploymentsDir = path.join(__dirname, "..", "..", "frontend", "public", "deployments");
  fs.mkdirSync(frontendDeploymentsDir, { recursive: true });
  const frontendOutputPath = path.join(frontendDeploymentsDir, "BatchAudit.localhost.json");
  fs.writeFileSync(frontendOutputPath, `${JSON.stringify(deployment, null, 2)}\n`);

  console.log(`BatchAudit deployed to ${address}`);
  console.log(`Network: ${hre.network.name}`);
  console.log(`Chain ID: ${Number(network.chainId)}`);
  console.log(`RPC URL: ${prototypeBlockchainConfig.rpcUrl}`);
  console.log(`Deployment details written to ${outputPath}`);
  console.log(`Frontend deployment details written to ${frontendOutputPath}`);
}

main().catch((error) => {
  console.error(error);
  process.exitCode = 1;
});
