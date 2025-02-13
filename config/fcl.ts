import { config } from '@onflow/fcl'
import { ACCESS_NODE_URLS } from '../constants'
import flowJSON from '../flow.json'

const flowNetwork = process.env.NEXT_PUBLIC_FLOW_NETWORK

console.log('Dapp running on network:', flowNetwork)

config({
  'flow.network': flowNetwork,
  'accessNode.api': process.env.NEXT_PUBLIC_FLOW_NETWORK === "local" 
    ? "http://localhost:8888" 
    : process.env.NEXT_PUBLIC_FLOW_NETWORK === "testnet"
    ? "https://rest-testnet.onflow.org"
    : "https://rest-mainnet.onflow.org",
  'discovery.wallet': process.env.NEXT_PUBLIC_FLOW_NETWORK === "local"
    ? "http://localhost:8701/fcl/authn"
    : process.env.NEXT_PUBLIC_FLOW_NETWORK === "testnet"
    ? "https://fcl-discovery.onflow.org/testnet/authn"
    : "https://fcl-discovery.onflow.org/authn",
  'app.detail.icon': 'https://placekitten.com/g/200/200',
  'app.detail.title': 'Legendary Picks',
  '0xLEGENDARYPICKS': process.env.NEXT_PUBLIC_FLOW_NETWORK === "local"
    ? "0xf8d6e0586b0a20c7"  // This should match your emulator account address
    : process.env.NEXT_PUBLIC_FLOW_NETWORK === "testnet"
    ? "0xYOUR_TESTNET_ADDRESS"
    : "0xYOUR_MAINNET_ADDRESS"
}).load({ flowJSON })