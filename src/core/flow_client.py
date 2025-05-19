# src/core/flow_client.py
import os
from pathlib import Path
from typing import Dict, Optional
import warnings 
import re # For more robust placeholder replacement

# Assuming flow_py_sdk is installed.
# The example used `from flow_py_sdk import flow_client` and then `flow_client(...)`
# This implies `flow_client` might be a factory or an alias.
# For clarity with typical SDK structure, one might do:
# from flow_py_sdk.client import FlowClient as ActualFlowClient
# and then use ActualFlowClient. However, sticking to the prompt's snippet structure:
from flow_py_sdk import flow_client # This is the module, the class is FlowClient inside it.
# So, it should be from flow_py_sdk.client import FlowClient
# I will correct this based on common usage of the SDK.
from flow_py_sdk.client import FlowClient
from flow_py_sdk.signer import InMemorySigner, SignAlgo, HashAlgo

from src.core import flow_config as cfg

# --- Global Caching for Client and Signer ---
_flow_client_instance: Optional[FlowClient] = None
_admin_signer_instance: Optional[InMemorySigner] = None

# Base path for Cadence files (src/blockchain/)
CADENCE_BASE_PATH = Path(__file__).resolve().parent.parent / "blockchain"

def init_flow_client(force_reinit: bool = False) -> FlowClient:
    """
    Initializes and returns a FlowClient instance.
    Caches the instance globally to avoid re-initialization.
    """
    global _flow_client_instance
    if _flow_client_instance is None or force_reinit:
        try:
            # FLOW_ACCESS_NODE_URL_GRPC is expected to be "host:port"
            host, port_str = cfg.FLOW_ACCESS_NODE_URL_GRPC.split(':')
            port = int(port_str)
            # Use the imported FlowClient class
            _flow_client_instance = FlowClient(host=host, port=port)
            print(f"Flow client initialized for {cfg.FLOW_ACCESS_NODE_URL_GRPC}")
        except ValueError as e:
            raise ValueError(
                f"Invalid FLOW_ACCESS_NODE_URL_GRPC format: '{cfg.FLOW_ACCESS_NODE_URL_GRPC}'. Expected 'host:port'. Error: {e}"
            )
        except Exception as e:
            # Catch any other exception during client initialization
            raise RuntimeError(f"Failed to initialize Flow client: {e}")
            
    return _flow_client_instance

def get_admin_signer(force_reinit: bool = False) -> InMemorySigner:
    """
    Initializes and returns an InMemorySigner for the admin account.
    Caches the instance globally.
    Raises ValueError if the admin private key is the placeholder.
    """
    global _admin_signer_instance
    if _admin_signer_instance is None or force_reinit:
        if cfg.ADMIN_ACCOUNT_PRIVATE_KEY_HEX == "YOUR_EMULATOR_ADMIN_PRIVATE_KEY_HEX_MUST_BE_SET":
            error_msg = (
                "CRITICAL: Admin private key (ADMIN_ACCOUNT_PRIVATE_KEY_HEX) is the placeholder value "
                "in src/core/flow_config.py. Cannot create a functional admin signer. "
                "Update it with a valid private key."
            )
            # warnings.warn(error_msg, UserWarning, stacklevel=2) # The config already warns
            raise ValueError(error_msg)

        try:
            _admin_signer_instance = InMemorySigner(
                sign_algo=SignAlgo.ECDSA_P256, # Standard for Flow emulator keys
                hash_algo=HashAlgo.SHA3_256,   # Standard for Flow emulator keys
                private_key_hex=cfg.ADMIN_ACCOUNT_PRIVATE_KEY_HEX
            )
            print(f"Admin signer loaded for account {cfg.ADMIN_ACCOUNT_ADDRESS}.")
        except Exception as e:
            # Catch potential errors from InMemorySigner, e.g., invalid key format or length
            raise ValueError(f"Failed to initialize admin signer: {e}")
            
    return _admin_signer_instance

def read_cadence_template(relative_filepath: str) -> str:
    """
    Reads a Cadence template file from the `src/blockchain/` directory.
    Args:
        relative_filepath: Path relative to `src/blockchain/`, 
                           e.g., "scripts/get_escrow_balance.cdc" or "contracts/ScoutPass.cdc".
    Returns:
        The content of the Cadence file as a string.
    Raises:
        FileNotFoundError: If the file does not exist.
        IOError: If there's an error reading the file.
    """
    # Ensure CADENCE_BASE_PATH is correctly resolved
    if not CADENCE_BASE_PATH.is_dir():
        # This case should ideally not happen if the directory structure is correct
        raise FileNotFoundError(f"Cadence base path not found or not a directory: {CADENCE_BASE_PATH}")

    full_path = (CADENCE_BASE_PATH / relative_filepath).resolve()

    # Security check: ensure the resolved path is still within the CADENCE_BASE_PATH
    if not full_path.is_relative_to(CADENCE_BASE_PATH.resolve()):
         raise ValueError(f"Attempted to read Cadence file outside of the allowed base directory: {relative_filepath}")


    if not full_path.is_file():
        raise FileNotFoundError(f"Cadence template not found at: {full_path} (resolved from relative: {relative_filepath})")
    
    try:
        with open(full_path, 'r', encoding='utf-8') as f:
            return f.read()
    except Exception as e:
        raise IOError(f"Error reading Cadence template {full_path}: {e}")

def replace_address_placeholders(code: str, addresses_map: Dict[str, str]) -> str:
    """
    Replaces placeholders in Cadence code with actual addresses.
    Handles two types of placeholders:
    1. Direct address placeholders: e.g., `0xNonFungibleTokenPlaceholder`, `0xScoutPass`
    2. Relative import path placeholders: e.g., `import ScoutPass from "../contracts/ScoutPass.cdc"`

    Args:
        code: The Cadence code string.
        addresses_map: A dictionary mapping contract names (or logical names like "NonFungibleToken")
                       to their actual hex addresses (e.g., {"ScoutPass": "0x123..."}).
                       The addresses in this map should be 0x-prefixed.

    Returns:
        The Cadence code string with placeholders replaced.
    """
    processed_code = code

    # Replace direct address placeholders (e.g., 0xContractName, 0xContractNamePlaceholder)
    for name, address in addresses_map.items():
        if not address.startswith("0x"):
            # Ensure addresses in the map are 0x prefixed for consistency, though Flow addresses in Cadence always are.
            # This is more of a safeguard for the input `addresses_map`.
            actual_address = f"0x{address.lower().replace('0x', '')}" 
        else:
            actual_address = address

        # Placeholder style: 0xContractNamePlaceholder or 0xContractName
        # Using regex to be more precise and avoid accidental replacements if ContractName is a substring.
        # Matches "0x" followed by the contract name, optionally followed by "Placeholder".
        # Word boundaries (\b) ensure "ContractName" is not part of a larger word.
        placeholder_pattern = r"0x" + re.escape(name) + r"(Placeholder)?\b"
        processed_code = re.sub(placeholder_pattern, actual_address, processed_code)
        
        # Placeholder style for imports: import ContractName from "..."
        # e.g., import ScoutPass from "../contracts/ScoutPass.cdc"
        # e.g., import ScoutPass from "ScoutPass.cdc" (if in same dir in template, though less common for our structure)
        # Using regex to capture the contract name being imported and the path string.
        # This pattern looks for `import ContractName from "` followed by any path in quotes.
        # It's made specific to replacing paths for the *current contract name* in the loop.
        # Pattern: import ContractName from "../contracts/ContractName.cdc"
        # Pattern: import ContractName from "./ContractName.cdc"
        # Pattern: import ContractName from "ContractName.cdc" (less likely for cross-contract)
        
        # Regex to find imports like `import Name from "path/to/Name.cdc"`
        # or `import Name from "0xPlaceholderName"`
        # We need to be careful to only replace paths for the *current* contract_name in the loop.
        # Example: `import ScoutPass from "../contracts/ScoutPass.cdc"`
        #          `import ScoutPass from "0xScoutPassPlaceholder"`
        
        # More specific regex for relative paths:
        # Looks for `import ActualContractName from "` followed by a quoted string containing `ActualContractName.cdc`
        # This is quite specific to a convention where the imported name matches the .cdc filename.
        relative_import_pattern = r'import\s+' + re.escape(name) + r'\s+from\s+"(?:(?:\.\./contracts/|\./|\.\./scripts/)?' + re.escape(name) + r'\.cdc)"'
        processed_code = re.sub(relative_import_pattern, f'import {name} from {actual_address}', processed_code)

    return processed_code


async def execute_script(
    script_code: str, 
    script_args: Optional[list] = None # List of flow_py_sdk.cadence.Value
) -> Any: # Returns the native Python value from CadenceValue
    client = init_flow_client()
    script_args = script_args or []
    
    print(f"Executing script:\n{script_code[:200]}...\nArgs: {[str(arg) for arg in script_args]}") # Log args as strings
    
    try:
        # The flow-py-sdk's execute_script expects script as bytes
        # and arguments as a list of CadenceValue objects.
        result_cadence_value = await client.execute_script(
            script=script_code.encode('utf-8'),
            arguments=script_args
        )
        # Convert CadenceValue to Python native value
        # Assuming result_cadence_value is a flow_py_sdk.cadence.Value object
        native_result = result_cadence_value.value 
        print(f"Script executed successfully. Native Result: {native_result}")
        return native_result
    except Exception as e: # Catching a broader exception, can be refined with FlowException if available
        print(f"Script execution failed: {e}")
        # Propagate the error for the caller to handle
        raise


async def execute_transaction(
    transaction_code: str,
    transaction_args: Optional[list], # List of flow_py_sdk.cadence.Value
    # Proposer, Payer, Signer will be the admin account from cfg by default
    # For more complex scenarios, these could be parameters.
    # For this implementation, we use admin account from flow_config.
    proposer_key_index: int = 0 # Default to key index 0 for the admin account
) -> Dict[str, Any]:
    client = init_flow_client()
    admin_signer = get_admin_signer() # This will raise ValueError if key is placeholder
    
    proposer_address_str = cfg.ADMIN_ACCOUNT_ADDRESS
    payer_address_str = cfg.ADMIN_ACCOUNT_ADDRESS # Admin pays for its own transactions

    transaction_args = transaction_args or []
    
    print(f"Preparing transaction:\n{transaction_code[:300]}...\nArgs: {[str(arg) for arg in transaction_args]}")
    print(f"Proposer/Payer: {proposer_address_str}, Proposer Key Index: {proposer_key_index}")

    tx_id_hex: Optional[str] = None # To store tx_id for error reporting if it becomes available

    try:
        # 1. Get the latest sealed block ID
        latest_block = await client.get_latest_block(sealed=True)
        reference_block_id_bytes = latest_block.id
        print(f"Reference Block ID: {reference_block_id_bytes.hex()}")

        # 2. Get the proposer's account and key sequence number
        proposer_cadence_address = CadenceAddress.from_hex(proposer_address_str)
        proposer_account = await client.get_account(address=proposer_cadence_address.bytes)
        
        if not proposer_account.keys or proposer_key_index >= len(proposer_account.keys):
            raise ValueError(f"Proposer key at index {proposer_key_index} not found on account {proposer_address_str}.")
        
        proposer_key = proposer_account.keys[proposer_key_index]
        if proposer_key.revoked:
            raise ValueError(f"Proposer key at index {proposer_key_index} for account {proposer_address_str} is revoked.")
        
        sequence_number = proposer_key.sequence_number
        print(f"Proposer ({proposer_address_str}) Key Index {proposer_key_index} Sequence Number: {sequence_number}")

        # 3. Build the transaction object
        tx = (
            Transaction(
                script=transaction_code.encode('utf-8'), # Script must be bytes
                reference_block_id=reference_block_id_bytes,
                gas_limit=9999, # Default gas limit, adjust as needed per transaction type
                proposer=ProposalKey(
                    key_address=proposer_cadence_address.bytes, # Proposer's address bytes
                    key_id=proposer_key_index,
                    key_sequence_number=sequence_number
                ),
                payer=CadenceAddress.from_hex(payer_address_str).bytes, # Payer's address bytes
            )
            .add_arguments(*transaction_args) # Add CadenceValue arguments
        )

        # Add authorizers - for admin transactions, typically just the admin/proposer.
        tx.add_authorizers(proposer_cadence_address.bytes)
        print(f"Transaction built. Authorizers: {[auth.hex() for auth in tx.authorizers]}")

        # 4. Sign the transaction
        # Sign the payload (intended state change)
        # The admin_signer is already configured for the admin account's key.
        # The sign method of InMemorySigner takes the bytes to sign.
        # The Transaction object has methods to get these bytes.
        # tx.sign_payload(admin_signer) # This might be an old or helper method.
        # The SDK typically requires signing the `payload_message`
        await admin_signer.sign(tx, account_address=proposer_cadence_address) # Signs the payload
        print(f"Transaction payload signed by {proposer_address_str} (Key Index {proposer_key_index})")
        
        # Sign the envelope (authorizes the payer to pay for the transaction)
        # If payer is the same as proposer, use the same signer.
        await admin_signer.sign(tx, account_address=CadenceAddress.from_hex(payer_address_str)) # Signs the envelope
        print(f"Transaction envelope signed by payer {payer_address_str}")
        
        # The SDK might have a more direct way like:
        # tx.sign_payload(proposer_address_bytes, proposer_key_index, admin_signer)
        # tx.sign_envelope(payer_address_bytes, payer_key_index_if_different, payer_signer_if_different)
        # The `admin_signer.sign(tx, address)` is a newer pattern in some SDKs that handles both.
        # For flow-py-sdk, after setting signers on the transaction object, it handles it.
        # Let's adjust to the common flow-py-sdk pattern where signers are added to the tx.
        # The above `admin_signer.sign(tx, ...)` is conceptual.
        # The actual flow-py-sdk way:
        # tx.add_payload_signature(address_bytes, key_id, signer_object)
        # tx.add_envelope_signature(address_bytes, key_id, signer_object)

        # Clear previous conceptual signing
        tx._payload_signatures = {} # Assuming internal structure or use clear methods if available
        tx._envelope_signatures = {}
        
        # Correct signing for flow-py-sdk (v1.x style)
        tx.add_payload_signature(
            address=proposer_cadence_address.bytes,
            key_id=proposer_key_index,
            signer=admin_signer
        )
        print(f"Transaction payload signed by {proposer_address_str} (Key Index {proposer_key_index}) using add_payload_signature.")

        tx.add_envelope_signature(
            address=CadenceAddress.from_hex(payer_address_str).bytes, # Payer's address bytes
            key_id=proposer_key_index, # Assuming payer uses same key index if same account
            signer=admin_signer # Assuming payer uses same signer if same account
        )
        print(f"Transaction envelope signed by payer {payer_address_str} using add_envelope_signature.")


        # 5. Send the transaction and wait for it to be sealed
        print(f"Sending transaction to Flow network...")
        tx_response = await client.send_transaction(transaction=tx.to_signed_grpc_dict()) # send_transaction expects gRPC dict
        tx_id_hex = tx_response.id.hex()
        print(f"Transaction submitted with ID: {tx_id_hex}. Waiting for seal...")
        
        # Wait for the transaction to be sealed
        # The result from wait_for_transaction_seal is a TransactionResult object
        tx_result = await client.get_transaction_result(id=tx_response.id, timeout=120.0) # Polls until sealed or timeout
        
        print(f"Transaction {tx_id_hex} sealed. Status: {tx_result.status.name}")

        # Prepare the return dictionary
        # event.to_dict() might not exist; event.payload_as_json_string() or similar is common
        events_list = []
        for event in tx_result.events:
            try:
                # Attempt to get a dictionary representation of the event.
                # This depends on the SDK's event object structure.
                # A common pattern is event.payload (raw) or a method to get JSON/dict.
                # event.payload is often bytes; event.payload_as_json_string() is a guess.
                # Let's assume event objects have a 'type' and a 'payload_as_json_string' or similar.
                # For now, just storing the string representation of the event type.
                # A more robust solution would inspect the event object from the SDK.
                events_list.append({
                    "type": event.type,
                    "payload": event.payload_as_json_string() if hasattr(event, 'payload_as_json_string') else str(event.payload)
                })
            except Exception as e_event:
                print(f"Warning: Could not serialize event {event.type}: {e_event}")
                events_list.append({"type": event.type, "payload": "Error serializing payload"})


        return {
            "tx_id": tx_id_hex,
            "status": tx_result.status.name, # e.g., "SEALED", "EXPIRED", "REVERTED"
            "error_message": tx_result.error_message or None, # Ensure None if empty string
            "events": events_list,
            "block_id": tx_result.block_id.hex()
        }

    except ValueError as ve: # Catch config/signer errors specifically
        print(f"ValueError during transaction execution: {ve}")
        return {"tx_id": tx_id_hex, "status": "ERROR_SETUP", "error_message": str(ve), "events": [], "block_id": None}
    except Exception as e: # Catch Flow specific exceptions and other general errors
        # FlowException might be a base for more specific errors in the SDK
        # from flow_py_sdk.exceptions import FlowException
        # if isinstance(e, FlowException): ...
        print(f"Transaction execution failed: {type(e).__name__} - {e}")
        error_status = "ERROR_EXECUTION"
        if "TransactionStatus.EXPIRED" in str(e): # Basic check for expiration if not caught by specific exception
            error_status = "EXPIRED"
        
        return {
            "tx_id": tx_id_hex, # Include tx_id if available (e.g., if it failed after submission)
            "status": error_status, 
            "error_message": str(e), 
            "events": [], 
            "block_id": None
        }

# Remove the old __main__ block if it exists, or update it for new functions
if __name__ == '__main__':
    import asyncio
    from flow_py_sdk.cadence import String as CadenceString, Address as CadenceAddress

    # This __main__ block is for basic testing of execute_script and execute_transaction.
    # It requires a running Flow Emulator and ADMIN_ACCOUNT_PRIVATE_KEY_HEX to be correctly set in flow_config.py.

    async def test_flow_client_operations():
        print("--- Testing flow_client.py (execute_script & execute_transaction) ---")

        # --- Test execute_script ---
        print("\n--- Testing execute_script ---")
        # A simple script to get the current block timestamp
        test_script_code = """
        import FlowServiceAccount from 0xf8d6e0586b0a20c7 // Emulator service account
        pub fun main(): UFix64 {
            return FlowServiceAccount.getBlock(at: getCurrentBlock().height)!.timestamp
        }
        """
        # Replace placeholder if flow_config uses a different address for FlowServiceAccount or a generic one
        # For this test, assuming 0xf8d6e0586b0a20c7 is directly usable as it's often the service account.
        # If your config has a different address for FlowServiceAccount, use replace_address_placeholders.
        
        # Example of using replace_address_placeholders if needed:
        # address_map = {"FlowServiceAccount": cfg.ADMIN_ACCOUNT_ADDRESS} # Assuming admin is service account
        # final_script_code = replace_address_placeholders(test_script_code_template, address_map)
        
        try:
            # No arguments needed for this script
            script_result = await execute_script(script_code=test_script_code) 
            print(f"execute_script result (timestamp): {script_result}")
        except ValueError as e: # Catch config errors
            print(f"Skipping execute_script test due to config error: {e}")
        except ImportError:
            print("flow_py_sdk not installed. Skipping execute_script test.")
        except Exception as e:
            print(f"Error during execute_script test: {e}")

        # --- Test execute_transaction ---
        print("\n--- Testing execute_transaction (conceptual - requires setup) ---")
        # This transaction is conceptual and might not run successfully without
        # the "HelloWorld" contract deployed by the admin account.
        # It's for testing the transaction sending mechanism.
        
        # Ensure ADMIN_ACCOUNT_PRIVATE_KEY_HEX is set before running this part
        if cfg.ADMIN_ACCOUNT_PRIVATE_KEY_HEX == "YOUR_EMULATOR_ADMIN_PRIVATE_KEY_HEX_MUST_BE_SET":
            print("SKIPPING execute_transaction test: ADMIN_ACCOUNT_PRIVATE_KEY_HEX is not set.")
            print("--- flow_client.py testing finished ---")
            return

        # Example: A simple transaction to log a message (requires no specific contract)
        # Or, use a transaction that interacts with a contract known to be on the emulator, like FlowToken.
        # For this example, let's use a transaction that tries to call a non-existent function
        # on the admin account, which should still go through signing and submission.
        # A better test would be to deploy a simple contract and interact with it.
        
        # Let's use a transaction that should succeed if the account is set up:
        # This transaction creates a new public capability for the FlowToken vault.
        # It's relatively safe and standard.
        setup_flow_token_receiver_tx = """
        import FungibleToken from 0xFungibleToken
        import FlowToken from 0xFlowToken

        transaction {
            prepare(signer: AuthAccount) {
                // Check if a receiver is already set up
                if signer.capabilities.get<&FlowToken.Vault{FungibleToken.Receiver}>(/public/flowTokenReceiver).borrow() == nil {
                    // Create a new FlowToken receiver capability and link it
                    signer.capabilities.unlink(/public/flowTokenReceiver) // Unlink if exists but broken
                    signer.capabilities.publish(
                        signer.capabilities.storageCapability<&FlowToken.Vault{FungibleToken.Receiver}>(/storage/flowTokenVault)!,
                        at: /public/flowTokenReceiver
                    )
                    log("FlowToken receiver published at /public/flowTokenReceiver")
                } else {
                    log("FlowToken receiver already exists at /public/flowTokenReceiver")
                }
            }
            execute {
                log("Transaction to ensure FlowToken receiver executed.")
            }
        }
        """
        
        # Prepare addresses map for placeholder replacement
        tx_address_map = {
            "FungibleToken": cfg.FUNGIBLE_TOKEN_CONTRACT_ADDRESS,
            "FlowToken": cfg.FLOW_TOKEN_CONTRACT_ADDRESS
        }
        final_tx_code = replace_address_placeholders(setup_flow_token_receiver_tx, tx_address_map)
        
        try:
            print("Attempting to execute a sample transaction (ensure FlowToken receiver).")
            # This transaction takes no arguments.
            tx_result_dict = await execute_transaction(
                transaction_code=final_tx_code,
                transaction_args=[] 
                # Proposer key index defaults to 0
            )
            print(f"execute_transaction result:\n{tx_result_dict}")
            
            if tx_result_dict["status"] == "SEALED":
                print("Sample transaction successful!")
            else:
                print(f"Sample transaction failed: {tx_result_dict.get('error_message', 'No error message')}")

        except ValueError as e: # Catch config errors
            print(f"Skipping execute_transaction test due to config error: {e}")
        except ImportError:
            print("flow_py_sdk not installed. Skipping execute_transaction test.")
        except Exception as e:
            print(f"Error during execute_transaction test: {type(e).__name__} - {e}")

        print("\n--- flow_client.py testing finished ---")

    # Run the async test function
    try:
        asyncio.run(test_flow_client_operations())
    except ImportError:
        print("asyncio or flow_py_sdk not available. Skipping test run.")
    except Exception as e:
        print(f"Error in test_flow_client_operations: {e}")

# --- High-Level Wrapper Functions ---

async def verify_nft_ownership_on_flow(
    user_flow_address: str, 
    nfts_to_check: List[Dict[str, str]]
) -> Optional[List[bool]]:
    """
    Verifies NFT ownership for a user on the Flow blockchain.

    Args:
        user_flow_address: The user's Flow address string (e.g., "0xabcdef1234567890").
        nfts_to_check: A list of dictionaries, each specifying an NFT:
                       {"contract_address": "0x...", 
                        "collection_public_path_identifier": "MomentCollection", 
                        "nft_id": "123"}
    Returns:
        A list of booleans indicating ownership for each NFT, or None on error.
    """
    print(f"Verifying NFT ownership for user {user_flow_address} for {len(nfts_to_check)} NFTs.")
    try:
        script_template = read_cadence_template("scripts/verify_nft_ownership.cdc")
        
        # Prepare addresses map for placeholder replacement (mainly for NonFungibleToken)
        # The verify_nft_ownership.cdc script also uses 0xNonFungibleTokenPlaceholder
        addresses_map = {
            "NonFungibleToken": cfg.NON_FUNGIBLE_TOKEN_CONTRACT_ADDRESS
            # Add other global placeholders if the script might use them, though it's simple.
        }
        processed_script_code = replace_address_placeholders(script_template, addresses_map)

        # Prepare arguments for Cadence script
        cadence_user_address = CadenceAddress.from_hex(user_flow_address)
        
        cadence_nfts_array = []
        for nft_info in nfts_to_check:
            # The Cadence script expects an array of NftToCheck structs.
            # We construct dictionaries that match the struct's field names and types.
            # flow-py-sdk can convert a list of Python dicts to a Cadence Array of Structs/Dictionaries
            # if the struct is defined in Cadence and fields match.
            # The NftToCheck struct in Cadence script has:
            # contractAddress: Address, collectionPublicPathIdentifier: String, nftID: UInt64
            cadence_nfts_array.append(
                CadenceDictionary([ # Using Dictionary as it's simpler to construct than Struct without pre-defining struct type
                    {"key": CadenceString("contractAddress"), "value": CadenceAddress.from_hex(nft_info["contract_address"])},
                    {"key": CadenceString("collectionPublicPathIdentifier"), "value": CadenceString(nft_info["collection_public_path_identifier"])},
                    {"key": CadenceString("nftID"), "value": CadenceUInt64(int(nft_info["nft_id"]))}
                ])
            )
        
        script_args = [
            cadence_user_address,
            CadenceArray(cadence_nfts_array)
        ]
        
        result = await execute_script(processed_script_code, script_args)
        
        # Result should be a Python list of booleans
        if isinstance(result, list) and all(isinstance(item, bool) for item in result):
            print(f"NFT ownership verification successful. Result: {result}")
            return result
        else:
            print(f"Unexpected result type from verify_nft_ownership script: {type(result)}, value: {result}")
            return None

    except ValueError as ve: # Catch config errors or address conversion errors
        print(f"Configuration or argument error in verify_nft_ownership_on_flow: {ve}")
        return None
    except FileNotFoundError as fnfe:
        print(f"Cadence script file not found for verify_nft_ownership: {fnfe}")
        return None
    except Exception as e:
        print(f"Error during verify_nft_ownership_on_flow: {type(e).__name__} - {e}")
        return None


async def mint_scout_pass_on_flow(
    recipient_flow_address: str, 
    referred_by_user_id: Optional[str], 
    bonus_type: str, 
    bonus_value: float
) -> Optional[str]: # Returns minted NFT ID as string
    """
    Mints a Scout Pass NFT on the Flow blockchain.

    Args:
        recipient_flow_address: The Flow address of the recipient.
        referred_by_user_id: Optional string ID of the referring user.
        bonus_type: String describing the bonus type (e.g., "salary_cap_boost_percentage").
        bonus_value: Float value of the bonus (e.g., 2.0 for 2%).

    Returns:
        The ID of the minted Scout Pass NFT as a string, or None on failure.
    """
    print(f"Attempting to mint Scout Pass for recipient {recipient_flow_address}.")
    try:
        tx_template = read_cadence_template("transactions/mint_scout_pass.cdc")
        
        addresses_map = {
            "NonFungibleToken": cfg.NON_FUNGIBLE_TOKEN_CONTRACT_ADDRESS,
            "ScoutPass": cfg.SCOUTPASS_CONTRACT_ADDRESS # Address of deployed ScoutPass contract
        }
        processed_tx_code = replace_address_placeholders(tx_template, addresses_map)

        # Prepare arguments for Cadence transaction
        cadence_recipient_address = CadenceAddress.from_hex(recipient_flow_address)
        
        if referred_by_user_id is not None:
            cadence_referred_by = CadenceOptional(CadenceString(referred_by_user_id))
        else:
            cadence_referred_by = CadenceOptional(None) # Cadence String? can be None

        cadence_bonus_type = CadenceString(bonus_type)
        # Ensure UFix64 format, e.g., "2.0"
        cadence_bonus_value = CadenceUFix64(f"{bonus_value:.1f}") 

        # For optional metadata (name, description, thumbnail), pass None to use contract defaults
        cadence_name_optional = CadenceOptional(None)
        cadence_description_optional = CadenceOptional(None)
        cadence_thumbnail_optional = CadenceOptional(None)

        transaction_args = [
            cadence_recipient_address,
            cadence_referred_by,
            cadence_bonus_type,
            cadence_bonus_value,
            cadence_name_optional,
            cadence_description_optional,
            cadence_thumbnail_optional
        ]

        tx_result = await execute_transaction(processed_tx_code, transaction_args)

        if tx_result and tx_result.get("status") == "SEALED" and not tx_result.get("error_message"):
            # Construct the expected event name using configured address and contract name
            # Remove "0x" prefix for address in event name construction if SDK does that.
            # The SDK usually provides event type as "A.ContractAddress.ContractName.EventName"
            scout_pass_address_no_prefix = cfg.SCOUTPASS_CONTRACT_ADDRESS.replace("0x", "")
            expected_event_name = f"A.{scout_pass_address_no_prefix}.{cfg.SCOUTPASS_CONTRACT_NAME}.Minted"
            
            print(f"Scout Pass mint transaction {tx_result['tx_id']} SEALED. Searching for event: {expected_event_name}")

            for event in tx_result.get("events", []):
                if event.get("type") == expected_event_name:
                    # Event payload parsing depends on SDK's structure.
                    # event["payload"] string from previous implementation, or event["value"].fields list
                    # Assuming event["payload"] is a JSON string of the event's CadenceValue (often a Struct)
                    try:
                        # If payload is a JSON string representing Cadence fields:
                        # event_payload_dict = json.loads(event.get("payload", "{}")) 
                        # scout_pass_id = event_payload_dict.get("id")
                        # Or, if event.get("payload") is already a dict from SDK:
                        # payload_fields = event.get("payload", {}).get("value", {}).get("fields", [])
                        
                        # Let's assume the structure from previous execute_transaction:
                        # event = {"type": "...", "payload": "JSON string of Cadence event"}
                        # And the JSON string represents a struct with fields.
                        event_payload_data = json.loads(event.get("payload","{}"))
                        if event_payload_data and "fields" in event_payload_data.get("value", {}):
                            for field in event_payload_data["value"]["fields"]:
                                if field.get("name") == "id":
                                    minted_id = field.get("value", {}).get("value") # e.g. "1" for UInt64
                                    if minted_id is not None:
                                        print(f"Found ScoutPass.Minted event. Minted NFT ID: {minted_id}")
                                        return str(minted_id)
                    except json.JSONDecodeError:
                        print(f"Failed to parse JSON from event payload: {event.get('payload')}")
                    except Exception as e_parse:
                         print(f"Error parsing Minted event payload: {e_parse}")
            print(f"ScoutPass.Minted event not found or ID missing in transaction {tx_result['tx_id']}.")
            return None
        else:
            err_msg = tx_result.get('error_message', 'Unknown error') if tx_result else 'Transaction execution failed to return result.'
            print(f"Scout Pass mint transaction failed or not sealed. Status: {tx_result.get('status') if tx_result else 'N/A'}. Error: {err_msg}")
            return None

    except ValueError as ve:
        print(f"Configuration or argument error in mint_scout_pass_on_flow: {ve}")
        return None
    except FileNotFoundError as fnfe:
        print(f"Cadence transaction file not found for mint_scout_pass: {fnfe}")
        return None
    except Exception as e:
        print(f"Error during mint_scout_pass_on_flow: {type(e).__name__} - {e}")
        return None


async def register_lineup_on_flow(
    contest_id_str: str, 
    user_flow_address: str, 
    nfts_to_register: List[Dict[str, str]] # Each dict: {"nftContractAddress": "0x...", "nftID": "123"}
) -> Optional[str]: # Returns on-chain lineupEntryID as string
    """
    Registers a user's lineup on the Flow blockchain via the LineupRegistry contract.

    Args:
        contest_id_str: The ID of the contest (string).
        user_flow_address: The user's Flow address string.
        nfts_to_register: List of dicts, each with "nftContractAddress" and "nftID".

    Returns:
        The on-chain lineupEntryID as a string, or None on failure.
    """
    print(f"Attempting to register lineup for contest {contest_id_str}, user {user_flow_address}.")
    try:
        tx_template = read_cadence_template("transactions/register_lineup.cdc")
        
        addresses_map = {
            "LineupRegistry": cfg.LINEUPREGISTRY_CONTRACT_ADDRESS
            # Add other global placeholders if the register_lineup.cdc script might use them.
            # e.g. NonFungibleToken, if it were imported directly in register_lineup.cdc (it's not)
        }
        processed_tx_code = replace_address_placeholders(tx_template, addresses_map)

        # Prepare arguments for Cadence transaction
        cadence_contest_id = CadenceString(contest_id_str)
        cadence_user_address = CadenceAddress.from_hex(user_flow_address)
        
        cadence_nfts_input_array = []
        for nft_info in nfts_to_register:
            # The Cadence script expects an array of structs: [{nftContractAddress: Address, nftID: UInt64}]
            # Constructing as an array of Dictionaries.
            cadence_nfts_input_array.append(
                CadenceDictionary([
                    {"key": CadenceString("nftContractAddress"), "value": CadenceAddress.from_hex(nft_info["nftContractAddress"])},
                    {"key": CadenceString("nftID"), "value": CadenceUInt64(int(nft_info["nftID"]))}
                ])
            )
        
        transaction_args = [
            cadence_contest_id,
            cadence_user_address,
            CadenceArray(cadence_nfts_input_array)
        ]

        tx_result = await execute_transaction(processed_tx_code, transaction_args)

        if tx_result and tx_result.get("status") == "SEALED" and not tx_result.get("error_message"):
            lineup_registry_addr_no_prefix = cfg.LINEUPREGISTRY_CONTRACT_ADDRESS.replace("0x", "")
            expected_event_name = f"A.{lineup_registry_addr_no_prefix}.{cfg.LINEUPREGISTRY_CONTRACT_NAME}.LineupRegistered"
            
            print(f"Lineup registration transaction {tx_result['tx_id']} SEALED. Searching for event: {expected_event_name}")

            for event in tx_result.get("events", []):
                if event.get("type") == expected_event_name:
                    try:
                        event_payload_data = json.loads(event.get("payload","{}"))
                        if event_payload_data and "fields" in event_payload_data.get("value", {}):
                            for field in event_payload_data["value"]["fields"]:
                                if field.get("name") == "lineupEntryID":
                                    lineup_entry_id = field.get("value", {}).get("value")
                                    if lineup_entry_id is not None:
                                        print(f"Found LineupRegistered event. LineupEntryID: {lineup_entry_id}")
                                        return str(lineup_entry_id)
                    except json.JSONDecodeError:
                        print(f"Failed to parse JSON from event payload: {event.get('payload')}")
                    except Exception as e_parse:
                         print(f"Error parsing LineupRegistered event payload: {e_parse}")
            print(f"LineupRegistered event not found or lineupEntryID missing in transaction {tx_result['tx_id']}.")
            return None
        else:
            err_msg = tx_result.get('error_message', 'Unknown error') if tx_result else 'Transaction execution failed to return result.'
            print(f"Lineup registration transaction failed or not sealed. Status: {tx_result.get('status') if tx_result else 'N/A'}. Error: {err_msg}")
            return None

    except ValueError as ve:
        print(f"Configuration or argument error in register_lineup_on_flow: {ve}")
        return None
    except FileNotFoundError as fnfe:
        print(f"Cadence transaction file not found for register_lineup: {fnfe}")
        return None
    except Exception as e:
        print(f"Error during register_lineup_on_flow: {type(e).__name__} - {e}")
        return None
