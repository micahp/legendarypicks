# scripts/flow_cli_config.py
# Placeholder configuration for Flow client
# In a real application, use environment variables or a secure config file.

# For Flow Emulator:
EMULATOR_HOST = "127.0.0.1"
EMULATOR_PORT = 3569 # Default Flow emulator port
# For flow-py-sdk, gRPC typically does not use http:// prefix, just host:port
ACCESS_NODE_GRPC = f"{EMULATOR_HOST}:{EMULATOR_PORT}" 

# Account that deployed the contracts and will sign transactions (Admin Account)
# This address should have the LineupNFT and FantasyEscrow contracts deployed.
# For emulator, "f8d6e0586b0a20c7" is often the service account.
# The flow-py-sdk expects addresses often without "0x" for configuration,
# but Cadence code needs "0x" prefix. We'll manage this in read_cadence_file.
# For clarity in config, let's store them here as they appear in Cadence.
ADMIN_ACCOUNT_ADDRESS_HEX = "0xf8d6e0586b0a20c7" # Emulator default service account with 0x
# Corresponding private key (hex encoded) for the admin account.
# WARNING: Never hardcode private keys in production. Use env variables or secure key management.
# This is a COMMON emulator private key for the service account. REPLACE IF YOURS IS DIFFERENT.
ADMIN_ACCOUNT_KEY_HEX = "YOUR_EMULATOR_ADMIN_PRIVATE_KEY_HEX_HERE" # Placeholder - MUST BE REPLACED

# Addresses for standard contracts. These are placeholders and would be the actual
# addresses where these contracts are deployed on the network (emulator, testnet, mainnet).
# On emulator, these are typically deployed by the service account.
# The names "FungibleToken" and "FlowToken" are standard.
# The example in the prompt had specific different addresses, I'll use those.
FUNGIBLE_TOKEN_CONTRACT_ADDRESS = "0xee82856bf20e2aa6" # Placeholder for emulator FT address
FLOW_TOKEN_CONTRACT_ADDRESS = "0x0ae53cb6e3f42a79"      # Placeholder for emulator FlowToken address
# If these standards are deployed to the service account on your emulator, you might use:
# FUNGIBLE_TOKEN_CONTRACT_ADDRESS = ADMIN_ACCOUNT_ADDRESS_HEX
# FLOW_TOKEN_CONTRACT_ADDRESS = ADMIN_ACCOUNT_ADDRESS_HEX


# Deployed contract names and their addresses
# Assuming contracts are deployed to the ADMIN_ACCOUNT_ADDRESS for emulator scenarios
LINEUP_NFT_CONTRACT_NAME = "LineupNFT"
FANTASY_ESCROW_CONTRACT_NAME = "FantasyEscrow"

# Addresses where *your* contracts are deployed.
# For emulator, if deployed by service account, this would be ADMIN_ACCOUNT_ADDRESS_HEX.
LINEUP_NFT_ADDRESS = ADMIN_ACCOUNT_ADDRESS_HEX
FANTASY_ESCROW_ADDRESS = ADMIN_ACCOUNT_ADDRESS_HEX


# Standard paths (can be overridden if your setup differs)
FLOW_TOKEN_STORAGE_PATH = "/storage/flowTokenVault"
FLOW_TOKEN_RECEIVER_PUBLIC_PATH = "/public/flowTokenReceiver"
FLOW_TOKEN_BALANCE_PUBLIC_PATH = "/public/flowTokenBalance"

if __name__ == '__main__':
    print("Flow CLI Configuration:")
    print(f"  Access Node (gRPC): {ACCESS_NODE_GRPC}")
    print(f"  Admin Account Address (Hex): {ADMIN_ACCOUNT_ADDRESS_HEX}")
    print(f"  Admin Account Key (Placeholder): {ADMIN_ACCOUNT_KEY_HEX}")
    print(f"  FungibleToken Contract Address: {FUNGIBLE_TOKEN_CONTRACT_ADDRESS}")
    print(f"  FlowToken Contract Address: {FLOW_TOKEN_CONTRACT_ADDRESS}")
    print(f"  LineupNFT Contract Address: {LINEUP_NFT_ADDRESS}")
    print(f"  FantasyEscrow Contract Address: {FANTASY_ESCROW_ADDRESS}")
    print(f"  LineupNFT Contract Name: {LINEUP_NFT_CONTRACT_NAME}")
    print(f"  FantasyEscrow Contract Name: {FANTASY_ESCROW_CONTRACT_NAME}")
    print("\nNote: Replace 'YOUR_EMULATOR_ADMIN_PRIVATE_KEY_HEX_HERE' with your actual private key for the emulator service account.")
    print("Ensure contract addresses match your deployment, especially for FungibleToken and FlowToken.")
