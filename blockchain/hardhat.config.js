require("@nomicfoundation/hardhat-toolbox");

const CHAIN_ID = 31337;
const RPC_URL = "http://127.0.0.1:8545";
const BLOCK_CREATION_TIME_MS = 12_000;
const BLOCK_GAS_LIMIT = 60_000_000;
const INITIAL_BASE_FEE_PER_GAS = 1_000_000_000;


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
      initialBaseFeePerGas: INITIAL_BASE_FEE_PER_GAS,
      mining: {
        auto: false,
        interval: [BLOCK_CREATION_TIME_MS, BLOCK_CREATION_TIME_MS],
        mempool: {
          order: "priority"
        }
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
  blockGasLimit: BLOCK_GAS_LIMIT,
  initialBaseFeePerGas: INITIAL_BASE_FEE_PER_GAS
};
