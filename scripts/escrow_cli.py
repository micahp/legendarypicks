# scripts/escrow_cli.py
import argparse
import asyncio
from pathlib import Path
import os
import re

# Attempt to import flow_py_sdk components. These are conceptual placeholders.
# Actual imports might vary based on the SDK's structure.
try:
    from flow_py_sdk.client import FlowClient
    from flow_py_sdk.signer import InMemorySigner, SignAlgo, HashAlgo
    from flow_py_sdk.cadence import Address as CadenceAddress, UFix64 as CadenceUFix64, String as CadenceString, Array as CadenceArray, Dictionary as CadenceDictionary, Struct as CadenceStruct, Event as CadenceEvent
    from flow_py_sdk.script import Script
    from flow_py_sdk.transaction import Transaction, TransactionResult
    from flow_py_sdk.account_key import AccountKey
except ImportError:
    print("WARNING: flow-py-sdk not installed or accessible. CLI will be non-functional.")
    # Define dummy classes for type hinting if SDK is not present
    class FlowClient: pass
    class InMemorySigner: pass
    class CadenceAddress: pass
    class CadenceUFix64: pass
    class CadenceString: pass
    class CadenceArray: pass
    class CadenceStruct: pass # Simplified
    class Script: pass
    class Transaction: pass
    class TransactionResult:
        def __init__(self):
            self.status = "SDK_NOT_FOUND"
            self.error_message = "flow-py-sdk not found"
            self.events = []
            self.id = b"unknown_tx_id"


# Assuming flow_cli_config.py is in the same directory
# If run as a script, __package__ might be None, so handle relative import carefully
if __package__ is None or __package__ == '':
    import flow_cli_config as cfg
else:
    from . import flow_cli_config as cfg


# --- Helper function to read Cadence code ---
def read_cadence_file(filepath_relative_to_src: str, contract_addresses: dict = None) -> str:
    """
    Reads a Cadence file from the src/blockchain directory and replaces placeholders.
    filepath_relative_to_src: e.g., "transactions/deposit_escrow.cdc" or "scripts/get_escrow_balance.cdc"
    contract_addresses: A dictionary for replacements, e.g., 
                        {"0xNonFungibleTokenPlaceholder": "0xActualNFTAddress"}
    """
    base_path = Path(__file__).parent.parent / "src" / "blockchain"
    full_path = base_path / filepath_relative_to_src

    if not full_path.exists():
        raise FileNotFoundError(f"Cadence file not found: {full_path}")

    with open(full_path, 'r') as f:
        code = f.read()

    # Default replacements based on config
    replacements = {
        "0xFungibleTokenPlaceholder": cfg.FUNGIBLE_TOKEN_CONTRACT_ADDRESS,
        "0xFlowTokenPlaceholder": cfg.FLOW_TOKEN_CONTRACT_ADDRESS,
        "0xLineupNFTPlaceholder": cfg.LINEUP_NFT_ADDRESS, # Assuming LineupNFT might be imported
        "0xFantasyEscrowPlaceholder": cfg.FANTASY_ESCROW_ADDRESS,
        # Handle relative imports for contracts if transactions/scripts are in subdirs
        # e.g. "../contracts/FantasyEscrow.cdc" -> actual address
        # This regex looks for "import ContractName from " followed by a relative path.
        r"import\s+(\w+)\s+from\s+\"(\.\./contracts/\w+\.cdc)\"": \
            lambda m: f"import {m.group(1)} from {contract_addresses.get(m.group(1), cfg.FANTASY_ESCROW_ADDRESS)}", # Default to FantasyEscrow address if specific contract not in map
        # A more specific replacement if needed for FantasyEscrow by its name
        r"import FantasyEscrow from \"\.\./contracts/FantasyEscrow\.cdc\"": f"import FantasyEscrow from {cfg.FANTASY_ESCROW_ADDRESS}",
        r"import LineupNFT from \"\.\./contracts/LineupNFT\.cdc\"": f"import LineupNFT from {cfg.LINEUP_NFT_ADDRESS}",
    }
    
    if contract_addresses: # Allow overriding default replacements
        replacements.update(contract_addresses)

    for placeholder, actual_value in replacements.items():
        if callable(actual_value): # For regex replacements
             code = re.sub(placeholder, actual_value, code)
        else:
            code = code.replace(placeholder, actual_value)
            
    # A common issue: flow-py-sdk expects addresses without "0x" for some parameters,
    # but Cadence code requires "0x". Ensure addresses in replacements HAVE "0x".
    # The cfg file now stores them with "0x".

    # print(f"--- Processed Cadence Code for {filepath_relative_to_src} ---")
    # print(code)
    # print("--- End Processed Cadence Code ---")
    return code

async def get_flow_client_and_signer():
    """
    Initializes and returns an async Flow client and a signer.
    """
    # Ensure ADMIN_ACCOUNT_KEY_HEX is not the placeholder
    if cfg.ADMIN_ACCOUNT_KEY_HEX == "YOUR_ADMIN_PRIVATE_KEY_HEX" or not cfg.ADMIN_ACCOUNT_KEY_HEX :
        print("ERROR: ADMIN_ACCOUNT_KEY_HEX is not set in flow_cli_config.py. Please replace the placeholder.")
        print("       You can generate emulator keys or use keys from flow.json if using Flow CLI.")
        print("       A common default emulator service account private key (if you haven't changed it) might be:")
        print("       'e50112281303bseparate0897689291f5793c90753a3f687autonomy4692e2796e94895169ea051f'")
        print("       (This is an example, verify your actual key for the emulator service account 0xf8d6e0586b0a20c7)")
        return None, None

    client = FlowClient(host=cfg.EMULATOR_HOST, port=cfg.EMULATOR_PORT) # Using separate host/port
    
    # The flow-py-sdk InMemorySigner expects the private_key_hex string directly.
    # SignAlgo and HashAlgo depend on the key type (e.g., ECDSA_P256, SHA3_256 for emulator keys)
    signer = InMemorySigner(
        hash_algo=HashAlgo.SHA3_256, # Common for emulator keys
        sign_algo=SignAlgo.ECDSA_P256, # Common for emulator keys
        private_key_hex=cfg.ADMIN_ACCOUNT_KEY_HEX
    )
    # The SDK handles fetching account details like sequence number when signing.
    print(f"Flow client configured for {cfg.ACCESS_NODE_GRPC}")
    print(f"Admin account for signing: {cfg.ADMIN_ACCOUNT_ADDRESS_HEX}")
    return client, signer

# --- Main async function for CLI ---
async def main():
    parser = argparse.ArgumentParser(description="CLI for interacting with the FantasyEscrow Cadence contract.")
    subparsers = parser.add_subparsers(dest="command", required=True, help="Sub-command help")

    # Deposit sub-command
    deposit_parser = subparsers.add_parser("deposit", help="Deposit funds into a contest's escrow pool.")
    deposit_parser.add_argument("contest_id", type=str, help="The ID of the contest.")
    deposit_parser.add_argument("amount", type=str, help="The amount of FlowToken to deposit (e.g., '10.0').")

    # Payout sub-command
    payout_parser = subparsers.add_parser("payout", help="Distribute funds from a contest pool to winners.")
    payout_parser.add_argument("contest_id", type=str, help="The ID of the contest.")
    payout_parser.add_argument("winners", type=str, help="Comma-separated list of winner_address:amount (e.g., '0xAddress1:5.0,0xAddress2:3.0').")

    # Balance sub-command
    balance_parser = subparsers.add_parser("balance", help="Check the balance of a specific contest pool.")
    balance_parser.add_argument("contest_id", type=str, help="The ID of the contest.")

    args = parser.parse_args()

    if cfg.ADMIN_ACCOUNT_KEY_HEX == "YOUR_ADMIN_PRIVATE_KEY_HEX" or not cfg.ADMIN_ACCOUNT_KEY_HEX:
         print("CRITICAL: Admin private key not configured in scripts/flow_cli_config.py. Exiting.")
         return

    # Initialize Flow client and signer
    # Note: In a real SDK, client setup might be async or require more parameters.
    # This is a conceptual representation.
    try:
        flow, signer = await get_flow_client_and_signer()
        if not flow or not signer:
            print("Failed to initialize Flow client or signer. Exiting.")
            return
        
        # Get admin account details for transactions (proposer key sequence number)
        # This is often handled by the SDK internally or needs to be fetched.
        # For flow-py-sdk, the signer usually handles this if it has access to the client or account state.
        # The SDK's Transaction object might require an account object or sequence number.
        # Let's assume for now the SDK's send_transaction takes care of this.
        admin_address_bytes = bytes.fromhex(cfg.ADMIN_ACCOUNT_ADDRESS_HEX.replace("0x", ""))

    except NameError: # If flow-py-sdk is not installed
        print("Skipping command execution as flow-py-sdk is not available.")
        if args.command == "deposit":
            print(f"Conceptual: Depositing {args.amount} FLOW for contest {args.contest_id}")
        elif args.command == "payout":
            print(f"Conceptual: Paying out for contest {args.contest_id} to {args.winners}")
        elif args.command == "balance":
            print(f"Conceptual: Checking balance for contest {args.contest_id}")
        return
    except Exception as e:
        print(f"Error during Flow client initialization: {e}")
        return


    # Define contract addresses for placeholder replacement
    contract_addr_map = {
        "0xFungibleTokenPlaceholder": cfg.FUNGIBLE_TOKEN_CONTRACT_ADDRESS,
        "0xFlowTokenPlaceholder": cfg.FLOW_TOKEN_CONTRACT_ADDRESS,
        "0xFantasyEscrowPlaceholder": cfg.FANTASY_ESCROW_ADDRESS,
        # For relative paths if needed by specific transactions/scripts
        "../contracts/FantasyEscrow.cdc": cfg.FANTASY_ESCROW_ADDRESS,
        "../contracts/LineupNFT.cdc": cfg.LINEUP_NFT_ADDRESS,
    }

    if args.command == "deposit":
        print(f"Attempting to deposit {args.amount} FLOW for contest '{args.contest_id}'...")
        try:
            tx_code = read_cadence_file("transactions/deposit_escrow.cdc", contract_addr_map)
            
            # Arguments for the transaction
            cadence_args = [
                CadenceString(args.contest_id),
                CadenceUFix64(args.amount) # Make sure amount is formatted correctly for UFix64 e.g. "10.0"
            ]

            tx = Transaction(
                code=tx_code,
                authorizers=[CadenceAddress.from_hex(cfg.ADMIN_ACCOUNT_ADDRESS_HEX)],
                payer=CadenceAddress.from_hex(cfg.ADMIN_ACCOUNT_ADDRESS_HEX),
                proposer=CadenceAddress.from_hex(cfg.ADMIN_ACCOUNT_ADDRESS_HEX) # Proposer is usually an account object or address with key ID and sequence no.
            ).add_arguments(*cadence_args)
            
            # Sign the transaction
            # The InMemorySigner typically needs to know the account's key sequence number.
            # This might be fetched via client.get_account_at_latest_block(address=...).
            # For simplicity, let's assume the SDK handles this or we set a placeholder key_id.
            # tx.add_payload_signature(CadenceAddress.from_hex(cfg.ADMIN_ACCOUNT_ADDRESS_HEX), 0, signer) # key_id 0
            # Or, the sign method might be part of the signer object itself applied to the tx
            # tx.sign(signer, account_address=cfg.ADMIN_ACCOUNT_ADDRESS_HEX, key_id=0) # Conceptual
            
            # The flow-py-sdk send_transaction typically expects a signed transaction.
            # The signing process might be more involved, e.g. by getting proposer seq_num.
            # Placeholder for full signing process:
            # latest_block = await flow.get_latest_block()
            # proposer_account = await flow.get_account(address=CadenceAddress.from_hex(cfg.ADMIN_ACCOUNT_ADDRESS_HEX))
            # proposer_key = proposer_account.keys[0] # Assuming first key is used

            # tx.proposer = Transaction.ProposalKey(
            #     address=CadenceAddress.from_hex(cfg.ADMIN_ACCOUNT_ADDRESS_HEX),
            #     key_id=proposer_key.id, # or 0 if default/managed by signer
            #     sequence_number=proposer_key.sequence_number # Needs to be up-to-date
            # )
            # tx.payer = CadenceAddress.from_hex(cfg.ADMIN_ACCOUNT_ADDRESS_HEX)
            # tx.authorizers = [CadenceAddress.from_hex(cfg.ADMIN_ACCOUNT_ADDRESS_HEX)]

            # tx = await signer.sign_transaction(tx, address=CadenceAddress.from_hex(cfg.ADMIN_ACCOUNT_ADDRESS_HEX)) # Conceptual SDK usage
            # For now, let's assume a simpler path if the SDK allows it or this is a placeholder.
            
            # Simplified for placeholder - actual signing is critical and specific to SDK usage
            # The InMemorySigner needs to be used correctly with the Transaction object.
            # Often, you prepare the transaction, then sign it, then send it.
            # The Tx object in flow-py-sdk has a sign method or is passed to a signer.
            # This is highly conceptual without running code:
            tx.add_envelope_signature(CadenceAddress.from_hex(cfg.ADMIN_ACCOUNT_ADDRESS_HEX), 0, signer) # key_id 0 for envelope

            print("Sending deposit transaction...")
            result: TransactionResult = await flow.execute_transaction(tx) # Or send_transaction, wait_for_seal

            if result.status == "SEALED" and not result.error_message:
                print(f"Deposit transaction {result.id.hex()} successful (Sealed).")
                for event in result.events:
                    print(f"  Event: {event.type} - {event.payload_as_json()}")
            else:
                print(f"Deposit transaction failed. Status: {result.status}, Error: {result.error_message}")

        except FileNotFoundError as e:
            print(f"Error: {e}")
        except NameError: # SDK not found
             print("Conceptual: Transaction would be built and sent here for deposit.")
        except Exception as e:
            print(f"An error occurred during deposit: {e}")


    elif args.command == "payout":
        print(f"Attempting to payout for contest '{args.contest_id}' to winners: {args.winners}")
        try:
            tx_code = read_cadence_file("transactions/payout_escrow.cdc", contract_addr_map)
            
            winner_data_str = args.winners.split(',')
            winner_addresses_cadence = []
            winner_amounts_cadence = []

            for item in winner_data_str:
                addr_str, amt_str = item.split(':')
                winner_addresses_cadence.append(CadenceAddress.from_hex(addr_str))
                winner_amounts_cadence.append(CadenceUFix64(amt_str))
            
            # Arguments for the transaction
            cadence_args = [
                CadenceString(args.contest_id),
                CadenceArray(winner_addresses_cadence),
                CadenceArray(winner_amounts_cadence)
            ]

            tx = Transaction(
                code=tx_code,
                authorizers=[CadenceAddress.from_hex(cfg.ADMIN_ACCOUNT_ADDRESS_HEX)],
                payer=CadenceAddress.from_hex(cfg.ADMIN_ACCOUNT_ADDRESS_HEX)],
                proposer=CadenceAddress.from_hex(cfg.ADMIN_ACCOUNT_ADDRESS_HEX)
            ).add_arguments(*cadence_args)
            
            # Conceptual signing (replace with actual SDK mechanism)
            tx.add_envelope_signature(CadenceAddress.from_hex(cfg.ADMIN_ACCOUNT_ADDRESS_HEX), 0, signer)

            print("Sending payout transaction...")
            result: TransactionResult = await flow.execute_transaction(tx)

            if result.status == "SEALED" and not result.error_message:
                print(f"Payout transaction {result.id.hex()} successful (Sealed).")
                for event in result.events:
                    print(f"  Event: {event.type} - {event.payload_as_json()}")
            else:
                print(f"Payout transaction failed. Status: {result.status}, Error: {result.error_message}")

        except FileNotFoundError as e:
            print(f"Error: {e}")
        except NameError: # SDK not found
             print("Conceptual: Transaction would be built and sent here for payout.")
        except Exception as e:
            print(f"An error occurred during payout: {e}")


    elif args.command == "balance":
        print(f"Checking balance for contest '{args.contest_id}'...")
        try:
            script_code = read_cadence_file("scripts/get_escrow_balance.cdc", contract_addr_map)
            
            # Argument for the script
            cadence_args = [CadenceString(args.contest_id)]
            
            script = Script(code=script_code).add_arguments(*cadence_args)
            
            print("Executing balance script...")
            result = await flow.execute_script(script=script.code, arguments=script.arguments) # SDKs vary: script object or code+args

            # Assuming result is a Cadence Optional type containing UFix64 or nil
            if result is not None : # Check if result is not Cadence.Optional(None)
                if hasattr(result, 'value') and result.value is not None: # For Cadence.Optional
                     print(f"Balance for contest {args.contest_id}: {result.value}")
                elif isinstance(result, (float, int, str)): # Direct value from some SDKs
                     print(f"Balance for contest {args.contest_id}: {result}")
                else: # Potentially a complex Cadence object, try to print its value if simple
                     print(f"Balance for contest {args.contest_id}: {result} (raw)")
            else: # result is None or Cadence.Optional(None)
                print(f"Contest pool '{args.contest_id}' not found or empty.")

        except FileNotFoundError as e:
            print(f"Error: {e}")
        except NameError: # SDK not found
             print("Conceptual: Script would be executed here for balance check.")
        except Exception as e:
            print(f"An error occurred during balance check: {e}")
            
    else:
        parser.print_help()

if __name__ == "__main__":
    # Check if ADMIN_ACCOUNT_KEY_HEX is still the placeholder at the very start
    if cfg.ADMIN_ACCOUNT_KEY_HEX == "YOUR_ADMIN_PRIVATE_KEY_HEX" or not cfg.ADMIN_ACCOUNT_KEY_HEX :
        print("CRITICAL ERROR: Admin private key (ADMIN_ACCOUNT_KEY_HEX) is not configured in scripts/flow_cli_config.py.")
        print("Please set it to a valid hex private key for the emulator admin account (e.g., 0xf8d6e0586b0a20c7).")
        print("The CLI will not be able to sign transactions without it.")
        print("Exiting CLI script.")
    else:
        try:
            asyncio.run(main())
        except NameError: # SDK not installed
            print("escrow_cli.py executed with conceptual printouts due to missing flow-py-sdk.")
        except Exception as e:
            print(f"CLI execution failed: {e}")

    print("\nCLI script finished. Requires flow-py-sdk, a configured private key, and a running Flow emulator/testnet to execute blockchain interactions.")
