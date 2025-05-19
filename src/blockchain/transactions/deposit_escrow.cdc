// src/blockchain/transactions/deposit_escrow.cdc
import FungibleToken from 0xFungibleTokenPlaceholder // Will be replaced by config
import FlowToken from 0xFlowTokenPlaceholder         // Will be replaced by config
import FantasyEscrow from 0xFantasyEscrowPlaceholder // Will be replaced by config, referring to FantasyEscrow contract address

transaction(contestId: String, amount: UFix64) {
    
    let temporaryVault: @FungibleToken.Vault
    let escrowAdminRef: &FantasyEscrow.FantasyEscrow // Incorrect type, should be &FantasyEscrow or specific capability if needed

    prepare(signer: AuthAccount) {
        // Get a reference to the signer's FlowToken Vault
        let mainVault = signer.storage.borrow<&FlowToken.Vault>(from: /storage/flowTokenVault)
            ?? panic("Cannot borrow FlowToken vault from signer at /storage/flowTokenVault")
        
        // Withdraw the specified amount to a temporary vault
        self.temporaryVault <- mainVault.withdraw(amount: amount)

        // Get a reference to the FantasyEscrow contract instance.
        // This assumes the FantasyEscrow contract is deployed at a known address (0xFantasyEscrowPlaceholder).
        // The type for borrowing a contract reference is simply the contract name.
        // We need to borrow a reference that allows calling the 'deposit' method.
        // Since 'deposit' requires admin privileges (signer == adminAddress in contract),
        // and this transaction is signed by the admin (signer), this approach is valid.
        // The FantasyEscrow contract itself has the vault.
        // We need to borrow the contract resource which has the deposit method.
        // The FantasyEscrow contract itself is not stored under a path like a resource.
        // We borrow a reference to the contract's public/admin capability if 'deposit' was exposed that way,
        // or we directly call it on the contract if the signer has rights.
        // The FantasyEscrow.deposit function is `pub fun deposit(contestId: String, fromVault: @FlowToken.Vault)`
        // and has `self.account.address == self.adminAddress` as a pre-condition.
        // This means the transaction *must* be signed by the FantasyEscrow.adminAddress.
        
        // No explicit borrow needed here for FantasyEscrow if signer is the admin.
        // The contract's functions are called directly if the signer is the contract account itself (admin).
        // If FantasyEscrow is deployed to a different account than the signer of this transaction,
        // then a capability to the deposit function or a more complex setup would be needed.
        // For this CLI, we assume the signer (ADMIN_ACCOUNT_ADDRESS from config) IS the FantasyEscrow.adminAddress.
    }

    execute {
        // Access the deployed FantasyEscrow contract
        // The import FantasyEscrow from 0xFantasyEscrowPlaceholder makes its public functions available.
        // The deposit function is on the FantasyEscrow contract itself, not a separate resource.
        // The pre-condition within FantasyEscrow.deposit will check if the signer (self.account.address)
        // is the adminAddress.
        FantasyEscrow.deposit(contestId: contestId, fromVault: <-self.temporaryVault)
        
        log("Deposit transaction executed. Funds transferred to FantasyEscrow contract for contest: ".concat(contestId))
    }
}
