import * as fcl from "@onflow/fcl"
import { ec as EC } from 'elliptic'
import { SHA3 } from "sha3"

const ec = new EC('secp256k1')

export const KeyGenerationService = {
  generateKeyPair: async () => {
    // Generate a new key pair
    const keyPair = ec.genKeyPair()
    
    // Get the public key in compressed format
    const publicKey = keyPair.getPublic(true, 'hex')
    
    // Get the private key
    const privateKey = keyPair.getPrivate('hex')
    
    // Hash the public key
    const hash = new SHA3(256)
    hash.update(Buffer.from(publicKey, 'hex'))
    const publicKeyHash = hash.digest('hex')

    return {
      privateKey,
      publicKey,
      publicKeyHash
    }
  },

  formatPublicKey: (publicKey: string) => {
    // Format the public key according to Flow requirements
    // Add padding and curve parameters
    return `${publicKey}000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000`
  }
} 