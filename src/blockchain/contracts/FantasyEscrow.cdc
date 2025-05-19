// src/blockchain/contracts/FantasyEscrow.cdc

import FungibleToken from 0xFungibleTokenPlaceholder // e.g., 0x9a0766d93b6608b7 for testnet FlowToken FT interface via FungibleToken
import FlowToken from 0xFlowTokenPlaceholder         // e.g., 0x7e60df042a9c0868 for testnet FlowToken contract itself

// If using actual testnet/mainnet addresses, they would be:
// import FungibleToken from 0x9a0766d93b6608b7 // Testnet
// import FlowToken from 0x7e60df042a9c0868     // Testnet
// import FungibleToken from 0xf233dcee88fe0abe // Mainnet
// import FlowToken from 0x1654653399040a61     // Mainnet

pub contract FantasyEscrow {

    pub var vault: @FlowToken.Vault
    pub var contestPools: {String: UFix64}
    pub let adminAddress: Address // Simple admin check: contract deployer

    // Events
    pub event ContractInitialized()
    pub event EscrowDeposit(contestId: String, amount: UFix64, currentPoolTotal: UFix64)
    pub event EscrowPayout(contestId: String, winnerAddress: Address, amount: UFix64)
    pub event PayoutAttemptFailed(contestId: String, winnerAddress: Address, amount: UFix64, reason: String)
    pub event PayoutProcessFailed(contestId: String, reason: String)


    init() {
        // Create an empty FlowToken Vault and save it to contract storage
        self.vault <- FlowToken.createEmptyVault()
        self.contestPools = {}
        self.adminAddress = self.account.address // The account deploying the contract is the admin
        emit ContractInitialized()
        log("FantasyEscrow Contract Initialized")
    }

    // Allows admin to deposit funds into a contest pool
    // In a real scenario, this might be callable by a platform-owned account,
    // or users might deposit directly (requiring different access control and logic).
    pub fun deposit(contestId: String, fromVault: @FlowToken.Vault) {
        pre {
            // For this version, only the adminAddress (contract deployer) can deposit.
            // This simplifies entry fee collection as the platform would collect fees
            // and then deposit them into the escrow for a specific contest.
            self.account.address == self.adminAddress : "Only the contract admin can deposit funds into a contest pool."
            fromVault.balance > 0.0 : "Deposit vault cannot be empty."
        }
        
        let amountToDeposit = fromVault.balance
        
        // Deposit the incoming tokens into the contract's main vault
        self.vault.deposit(from: <-fromVault)
        
        // Update the contest pool balance
        let currentTotal = self.contestPools[contestId] ?? 0.0
        self.contestPools[contestId] = currentTotal + amountToDeposit
        
        emit EscrowDeposit(contestId: contestId, amount: amountToDeposit, currentPoolTotal: self.contestPools[contestId]!)
        log("Funds deposited into contest pool.".concat(contestId).concat(" Amount: ").concat(amountToDeposit.toString()))
    }

    // Struct for winner data, making it easy to pass around
    pub struct WinnerPayout {
        pub let address: Address
        pub let amount: UFix64

        init(address: Address, amount: UFix64) {
            pre {
                amount > 0.0 : "Payout amount must be positive."
            }
            self.address = address
            self.amount = amount
        }
    }

    // Distributes funds to winners based on the provided list
    pub fun payout(contestId: String, winners: [WinnerPayout]) {
        pre {
            self.account.address == self.adminAddress : "Only the contract admin can execute payouts."
            self.contestPools[contestId] != nil : "Contest pool does not exist for contestId: ".concat(contestId)
        }

        var totalPayoutAmount: UFix64 = 0.0
        for winner in winners {
            totalPayoutAmount = totalPayoutAmount + winner.amount
        }

        let currentPoolBalance = self.contestPools[contestId]!
        if currentPoolBalance < totalPayoutAmount {
            emit PayoutProcessFailed(contestId: contestId, reason: "Total payout amount exceeds available funds in the pool.")
            panic("Total payout amount (")
                .concat(totalPayoutAmount.toString())
                .concat(") exceeds available funds (")
                .concat(currentPoolBalance.toString())
                .concat(") in pool: ")
                .concat(contestId)
        }

        for winner in winners {
            if winner.amount == 0.0 { // Skip zero amounts, though pre-condition in struct helps
                log("Skipping zero amount payout for winner: ".concat(winner.address.toString()))
                continue 
            }

            // Get the recipient's public capability to receive FlowToken
            let recipientCapability = getAccount(winner.address)
                .capabilities.borrow<&{FungibleToken.Receiver}>(/public/flowTokenReceiver) // Standard public path for FlowToken receiver

            if recipientCapability == nil || !recipientCapability!.check() {
                emit PayoutAttemptFailed(
                    contestId: contestId, 
                    winnerAddress: winner.address, 
                    amount: winner.amount, 
                    reason: "Winner's FlowToken Receiver capability is invalid or not found at /public/flowTokenReceiver."
                )
                log("Payout failed for ".concat(winner.address.toString()).concat(": Receiver capability invalid or not found."))
                // In a real application, you might have a mechanism to handle failed payouts (e.g., retry, manual intervention).
                // For now, we log and continue to the next winner. This means this amount remains in the pool.
                // IMPORTANT: This choice has implications. If one payout fails, the totalPayoutAmount is not reduced,
                // so the pool might not be fully depleted as intended if subsequent payouts succeed.
                // A more robust solution might collect all successfully withdrawn vaults and only then update the pool,
                // or have a multi-stage payout. For this placeholder, we proceed with this simpler logic.
                continue 
            }
            
            // Withdraw the specified amount from the contract's vault
            let paymentVault <- self.vault.withdraw(amount: winner.amount)
            
            // Deposit the payment into the winner's vault
            recipientCapability!.deposit(from: <-paymentVault)
            
            emit EscrowPayout(contestId: contestId, winnerAddress: winner.address, amount: winner.amount)
            log("Payout successful to ".concat(winner.address.toString()).concat(" Amount: ").concat(winner.amount.toString()))
        }
        
        // Update the contest pool balance
        self.contestPools[contestId] = currentPoolBalance - totalPayoutAmount // Use original total for deduction
        
        // Optionally, remove the contest pool if it's now zero (or very close to zero due to UFix64 precision)
        if self.contestPools[contestId]! <= 0.00000001 { // Check against a very small number
            self.contestPools.remove(key: contestId)
            log("Contest pool ".concat(contestId).concat(" is now empty and has been removed."))
        } else {
            log("Contest pool ".concat(contestId).concat(" updated. New balance: ").concat(self.contestPools[contestId]!.toString()))
        }
    }

    // Public function to allow anyone to check a specific contest pool's balance
    pub fun getContestPoolBalance(contestId: String): UFix64? {
        return self.contestPools[contestId]
    }

    // Public function to check the contract's total vault balance (admin/debug purposes)
    pub fun getContractTotalBalance(): UFix64 {
        return self.vault.balance
    }
}
