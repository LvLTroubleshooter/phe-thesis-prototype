require("@nomicfoundation/hardhat-toolbox");

const CHAIN_ID = 31337;
const RPC_URL = "http://127.0.0.1:8545";
const BLOCK_CREATION_TIME_MS = 2000;
const BLOCK_GAS_LIMIT = 30_000_000;


module.exports = {
  solidity: {
    version: "0.8.28",
    settings: {
      viaIR: true,
      optimizer: {
        enabled: true,
        runs: 200
      }
    }
  },
  networks: {
    hardhat: {
      chainId: CHAIN_ID,
      blockGasLimit: BLOCK_GAS_LIMIT,
      mining: {
        auto: false,
        interval: [BLOCK_CREATION_TIME_MS, BLOCK_CREATION_TIME_MS]
      }
    },
    localhost: {
      url: RPC_URL,
      chainId: CHAIN_ID,
      timeout: 120000
    }
  },
  paths: {
    sources: "./contracts",
    tests: "./test",
    cache: "./cache",
    artifacts: "./artifacts"
  }
};

module.exports.prototypeBlockchainConfig = {
  chainId: CHAIN_ID,
  rpcUrl: RPC_URL,
  blockCreationTimeMs: BLOCK_CREATION_TIME_MS,
  miningMode: "interval",
  blockGasLimit: BLOCK_GAS_LIMIT
};
