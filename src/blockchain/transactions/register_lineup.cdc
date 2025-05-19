// src/blockchain/transactions/register_lineup.cdc

// Import LineupRegistry using a relative path for local dev convenience.
// A deployment/execution script would replace this with the actual contract address
// or use a placeholder like 0xLineupRegistryPlaceholder that gets replaced.
import LineupRegistry from "../contracts/LineupRegistry.cdc"

// The transaction arguments match the signature of LineupRegistry.registerLineup,
// plus the admin resource which is handled in the prepare phase.
// The type [{nftContractAddress: Address, nftID: UInt64}] is an array of structs.
// Cadence SDKs handle the conversion from client-side objects to this structure.
transaction(
    contestID: String,
    userAddress: Address, // The fantasy platform user whose lineup this is
    nftsToRegisterInput: [{nftContractAddress: Address, nftID: UInt64}]
) {

    // This reference will point to the deployed LineupRegistry contract.
    // It's not strictly needed as a field if LineupRegistry is imported directly
    // and its functions are called like LineupRegistry.registerLineup(...),
    // but the conceptual example used a borrowed reference.
    // Let's stick to direct calls via import for simplicity if AdminResource is the auth mechanism.
    // However, the conceptual snippet's `registerLineup` was `pub fun registerLineup(... auth adminRef: &AdminResource)`.
    // This function is part of the contract, not the AdminResource.
    // So, a reference to the contract *instance* is needed if we want to call its methods.

    let adminResourceRef: &LineupRegistry.AdminResource
    let lineupRegistry: &LineupRegistry // Reference to the contract instance

    prepare(signer: AuthAccount) {
        // 1. Borrow AdminResource from the signer
        // This ensures the transaction is being run by an account authorized to manage the LineupRegistry.
        // LineupRegistry.AdminStoragePath is defined in the LineupRegistry contract.
        self.adminResourceRef = signer.storage.borrow<&LineupRegistry.AdminResource>(from: LineupRegistry.AdminStoragePath)
            ?? panic("Could not borrow reference to LineupRegistry AdminResource. Signer must be an admin.")

        // 2. Borrow a reference to the LineupRegistry contract itself.
        // This is necessary to call its instance methods like registerLineup.
        // The contract is expected to be deployed at the address associated with the import.
        // If LineupRegistry was imported from an address (e.g. 0xDeployedRegistry),
        // then `LineupRegistry` itself is the contract type, and its functions can be called directly
        // assuming they are public.
        // For contract instance methods, we need a reference to the deployed contract.
        // The typical way is `getAccount(Address).contracts.borrow<&ContractType>(name: "ContractName")`
        // The import `import LineupRegistry from "..."` makes `LineupRegistry` a type.
        // To call its functions, we need an instance.
        // If the import is `import LineupRegistry from 0xActualAddress`, then LineupRegistry.registerLineup should be callable.
        // Let's assume the import handles getting us the "contract instance" or its type correctly.
        // The conceptual snippet's `self.lineupRegistryRef = getAccount(0xPlaceholder).contracts.borrow...`
        // is the most explicit way if we have the address.
        // If using relative import, the execution context (emulator, testnet) resolves it.
        // For now, let's assume the functions are callable via the import.
        // The `registerLineup` function is a public function on the contract, not a resource.
        // The conceptual snippet's approach of borrowing the contract is good.
        // The address for `getAccount` would be the address where LineupRegistry is deployed.
        // This address comes from the import statement after replacement.
        
        // The import `import LineupRegistry from "..."` provides the type and the location.
        // We don't need to borrow the contract again if we call `LineupRegistry.registerLineup`.
        // Let's simplify and remove `self.lineupRegistry` if direct calls are made.
        // The function signature `pub fun registerLineup(... auth adminRef: &AdminResource)` is on the contract `LineupRegistry`.
        // So, we call `LineupRegistry.registerLineup(...)`.

        // No explicit borrow of LineupRegistry contract needed here if calling static-like via imported name.
        // The authorization is through adminResourceRef.
    }

    execute {
        // Call the registerLineup function on the LineupRegistry contract.
        // The import `import LineupRegistry from "..."` (after path/placeholder resolution)
        // makes the contract's public functions directly callable.
        let lineupEntryID = LineupRegistry.registerLineup(
            contestID: contestID,
            userAddress: userAddress,
            nftsToRegisterInput: nftsToRegisterInput,
            auth: self.adminResourceRef // Pass the borrowed admin resource reference
        )

        if lineupEntryID != nil {
            log("Lineup successfully registered with ID: ".concat(lineupEntryID!.toString()))
        } else {
            // The LineupRegistry.registerLineup function emits LineupRegistrationFailed with a reason.
            log("Failed to register lineup. Check contract events (LineupRegistrationFailed) for details.")
        }
    }
}
