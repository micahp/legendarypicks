# scripts/flow_cli_config.py
# This file will be moved to src/core/flow_config.py

# --- Flow Network Configuration ---
# For local emulator:
FLOW_ACCESS_NODE_URL_GRPC = "127.0.0.1:3569"
# For Testnet:
# FLOW_ACCESS_NODE_URL_GRPC = "access.testnet.nodes.onflow.org:9000"
# For Mainnet:
# FLOW_ACCESS_NODE_URL_GRPC = "access.mainnet.nodes.onflow.org:9000"


# --- Admin Account Configuration ---
# WARNING: CRITICAL SECURITY RISK!
# Never hardcode private keys directly in production code or commit them to version control.
# Use environment variables, a secure secrets management system, or a dedicated key management service.
# This admin account is assumed to have deployed the project's contracts (ScoutPass, LineupRegistry, FantasyEscrow).
ADMIN_ACCOUNT_ADDRESS = "0xf8d6e0586b0a20c7"  # Emulator default service account
ADMIN_ACCOUNT_PRIVATE_KEY_HEX = "YOUR_EMULATOR_ADMIN_PRIVATE_KEY_HEX_MUST_BE_SET" # Replace this immediately!

# --- Standard Contract Addresses (Emulator/Testnet - verify these) ---
# These might differ based on your Flow environment (emulator, testnet, mainnet).
# For emulator, if the service account (ADMIN_ACCOUNT_ADDRESS) deployed them or they are pre-deployed:
NON_FUNGIBLE_TOKEN_CONTRACT_ADDRESS = "0xf8d6e0586b0a20c7" # Often deployed by/to service account on emulator
FUNGIBLE_TOKEN_CONTRACT_ADDRESS = "0xf8d6e0586b0a20c7"     # Often deployed by/to service account on emulator
FLOW_TOKEN_CONTRACT_ADDRESS = "0xf8d6e0586b0a20c7"         # Often deployed by/to service account on emulator
# For actual testnet/mainnet, these would be specific addresses like:
# NON_FUNGIBLE_TOKEN_CONTRACT_ADDRESS = "0x1d7e57aa55817448" # Mainnet & Testnet NFT Standard
# FUNGIBLE_TOKEN_CONTRACT_ADDRESS = "0xf233dcee88fe0abe" # Mainnet FT Standard
# FLOW_TOKEN_CONTRACT_ADDRESS = "0x1654653399040a61"     # Mainnet FlowToken


# --- Project-Specific Contract Configuration ---
# These addresses are determined after deploying your contracts.
# For emulator, if deployed by ADMIN_ACCOUNT_ADDRESS, they will be the same as ADMIN_ACCOUNT_ADDRESS.
PROJECT_CONTRACT_DEPLOYER_ADDRESS = ADMIN_ACCOUNT_ADDRESS 

# Contract Names (used as identifiers in `flow.json` and potentially for contract references)
SCOUTPASS_CONTRACT_NAME = "ScoutPass"
LINEUPREGISTRY_CONTRACT_NAME = "LineupRegistry" # Corrected from any potential "LinupRegistry" typo
FANTASYESCROW_CONTRACT_NAME = "FantasyEscrow"

# Contract Addresses (replace with actual deployed addresses if not on emulator or if different)
# Assuming these project contracts are deployed by the ADMIN_ACCOUNT_ADDRESS on the emulator.
SCOUTPASS_CONTRACT_ADDRESS = PROJECT_CONTRACT_DEPLOYER_ADDRESS 
LINEUPREGISTRY_CONTRACT_ADDRESS = PROJECT_CONTRACT_DEPLOYER_ADDRESS 
FANTASYESCROW_CONTRACT_ADDRESS = PROJECT_CONTRACT_DEPLOYER_ADDRESS 


# --- Public Path Identifiers (as strings, matching those in Cadence contracts) ---
# These are the string identifiers for PublicPath as defined in the respective contracts
# Example: `ScoutPass.cdc` defines `self.CollectionPublicPath = /public/ScoutPassCollection`
# The identifier is "ScoutPassCollection".
SCOUTPASS_COLLECTION_PUBLIC_PATH_IDENTIFIER = "ScoutPassCollection" 

# For verifying ownership of third-party NFTs (example):
NBA_TOP_SHOT_CONTRACT_ADDRESS = "0x0b2a3299cc857e29" # Actual TopShot Mainnet address (example for reference)
# NBA_TOP_SHOT_CONTRACT_ADDRESS = "0x87ca73a41bb50Ad5" # Actual TopShot Testnet address (example for reference)
NBA_TOP_SHOT_COLLECTION_PUBLIC_PATH_IDENTIFIER = "MomentCollection" # Standard for Top Shot collections

# --- Storage Paths (as strings, matching those in Cadence contracts) ---
# These are useful if scripts/transactions need to refer to storage paths directly.
# Example from LineupRegistry.cdc: self.AdminStoragePath = /storage/LineupRegistryAdminResource
LINEUP_REGISTRY_ADMIN_STORAGE_PATH_IDENTIFIER = "LineupRegistryAdminResource" # Identifier for AdminStoragePath

# --- General Flow Standard Path Identifiers ---
# These are the string identifiers for common public/storage paths.
FLOW_TOKEN_RECEIVER_PUBLIC_PATH_IDENTIFIER = "flowTokenReceiver" 
FLOW_TOKEN_VAULT_STORAGE_PATH_IDENTIFIER = "flowTokenVault" 
FLOW_TOKEN_BALANCE_PUBLIC_PATH_IDENTIFIER = "flowTokenBalance" 


# --- Security Check and Warning for Admin Private Key ---
# This check runs when the module is imported.
if ADMIN_ACCOUNT_PRIVATE_KEY_HEX == "YOUR_EMULATOR_ADMIN_PRIVATE_KEY_HEX_MUST_BE_SET":
    import warnings
    warnings.warn(
        "\n" + "="*70 + "\n" +
        "CRITICAL SECURITY WARNING: ADMIN_ACCOUNT_PRIVATE_KEY_HEX is not set \n"
        "or is still the placeholder value in src/core/flow_config.py. \n"
        "This application will NOT be able to sign transactions for admin operations. \n"
        "Please replace it with a valid private key for the admin account "
        f"({ADMIN_ACCOUNT_ADDRESS}) \nand ensure it is managed securely (e.g., via environment "
        "variables in production)." + "\n" + "="*70,
        UserWarning, # Changed to UserWarning for less aggressive runtime interruption by default
        stacklevel=2 # Ensures the warning points to where flow_config is imported
    )
