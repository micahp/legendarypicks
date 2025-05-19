// src/blockchain/contracts/LineupRegistry.cdc

pub contract LineupRegistry {

    // --- Data Structures ---
    pub struct RegisteredNftInfo {
        pub let nftContractAddress: Address
        pub let nftID: UInt64
        pub let ownerAddress: Address // User who registered this NFT for the lineup

        init(nftContractAddress: Address, nftID: UInt64, ownerAddress: Address) {
            self.nftContractAddress = nftContractAddress
            self.nftID = nftID
            self.ownerAddress = ownerAddress
        }
    }

    pub struct LineupEntry {
        pub let lineupEntryID: UInt64
        pub let contestID: String
        pub let userAddress: Address // The user who submitted this lineup
        pub let registeredNfts: [RegisteredNftInfo]
        pub let registrationTime: UFix64 // Timestamp

        init(lineupEntryID: UInt64, contestID: String, userAddress: Address, registeredNfts: [RegisteredNftInfo], registrationTime: UFix64) {
            self.lineupEntryID = lineupEntryID
            self.contestID = contestID
            self.userAddress = userAddress
            self.registeredNfts = registeredNfts
            self.registrationTime = registrationTime
        }
    }

    // --- Events ---
    pub event ContractInitialized()
    // Updated event to include more details as per conceptual snippet
    pub event LineupRegistered(lineupEntryID: UInt64, contestID: String, userAddress: Address, nftCount: Int, registeredNftDetails: [String])
    // Changed LineupError to LineupRegistrationFailed to match conceptual snippet
    pub event LineupRegistrationFailed(userAddress: Address, contestID: String, reason: String)
    pub event ContestEntriesCleaned(contestID: String, unlockedNftCount: Int, unlockedUserLimitCount: Int)


    // --- Storage Variables ---
    pub var lineupEntries: {UInt64: LineupEntry}
    access(self) var nextLineupEntryID: UInt64

    // Tracks NFT usage per contest: contestID -> (nftKey -> lineupEntryID)
    // nftKey is "<contractAddress>-<nftID>"
    pub var nftUsageTracker: {String: {String: UInt64}}
    
    // Optional: Tracks if a user already submitted a lineup for a specific contest: contestID -> (userAddress -> lineupEntryID)
    pub var userContestLineupLimit: {String: {Address: UInt64}}

    // Admin control: Resource and Capability
    // The capability to this resource can be given to authorized accounts.
    pub let AdminStoragePath: StoragePath
    pub let AdminPublicPath: PublicPath // Optional: if admin capabilities need to be public for other contracts/scripts

    pub resource AdminResource {
        // This resource existing implies admin privileges for the functions that require it.
        // It could also hold admin-specific functions in the future.
        pub fun helloAdmin() {
            log("AdminResource access granted.")
        }
    }

    // --- Helper Functions ---
    access(self) fun getCompositeNftKey(contractAddress: Address, nftID: UInt64): String {
        return contractAddress.toString().concat("-").concat(nftID.toString())
    }

    // --- Initialization ---
    init() {
        self.lineupEntries = {}
        self.nextLineupEntryID = 1
        self.nftUsageTracker = {}
        self.userContestLineupLimit = {} // Initialize the optional limit tracker

        self.AdminStoragePath = /storage/LineupRegistryAdminResource
        self.AdminPublicPath = /public/LineupRegistryAdmin // Example public path

        // Save an AdminResource to the contract deployer's account storage.
        // This resource is used to authorize admin-only functions.
        self.account.storage.save(<-create AdminResource(), to: self.AdminStoragePath)
        
        // Optionally, publish a capability if external entities need to acquire it.
        // For internal checks (signer is admin), direct borrow from storage path is fine.
        // The prompt's conceptual snippet used `self.adminProxy = self.account.capabilities.storage.issue...`
        // which creates a storable capability. This is useful if the contract itself needs to hold
        // a capability to its own admin resource, or if it's to be passed around.
        // For functions requiring `auth adminRef: &AdminResource`, the caller (transaction)
        // will borrow this reference from the AdminStoragePath.
        // So, no need for `adminProxy` field in the contract itself for this pattern.

        emit ContractInitialized()
        log("LineupRegistry Contract Initialized. AdminResource created at ".concat(self.AdminStoragePath.toString()))
    }
    
    // --- Public Functions ---
    pub fun getLineupEntry(lineupEntryID: UInt64): LineupEntry? {
        return self.lineupEntries[lineupEntryID]
    }

    pub fun isNftInUse(contestID: String, nftContractAddress: Address, nftID: UInt64): Bool {
        let compositeKey = self.getCompositeNftKey(contractAddress: nftContractAddress, nftID: nftID)
        if let contestTracker = self.nftUsageTracker[contestID] {
            return contestTracker[compositeKey] != nil
        }
        return false
    }
    
    // --- Restricted Functions ---
    // This function needs to be called from a transaction signed by an account
    // that has the AdminResource in its storage at AdminStoragePath, or has a capability to it.
    // The `auth adminRef: &AdminResource` ensures only authorized callers can execute this.
    pub fun registerLineup(
        contestID: String,
        userAddress: Address, // The end-user whose lineup this is
        nftsToRegisterInput: [{nftContractAddress: Address, nftID: UInt64}],
        auth adminRef: &AdminResource // Authorization mechanism
    ): UInt64? {
        adminRef.helloAdmin() // Example usage of adminRef to confirm access

        // 1. Check user-per-contest limit (optional rule)
        if let contestUserTracker = self.userContestLineupLimit[contestID] {
            if contestUserTracker[userAddress] != nil {
                let reason = "User ".concat(userAddress.toString()).concat(" already has a lineup registered for contest ").concat(contestID)
                emit LineupRegistrationFailed(userAddress: userAddress, contestID: contestID, reason: reason)
                return nil
            }
        }

        // 2. Prepare NFT usage tracker for this contest if it's the first entry
        if self.nftUsageTracker[contestID] == nil {
            self.nftUsageTracker[contestID] = {}
        }
        // Get a mutable reference to the inner dictionary.
        // This requires `nftUsageTracker`'s value type to be a resource or use specific dict operations.
        // For simple dictionaries of structs/primitives, direct modification after getting a reference works.
        // Let's assume `self.nftUsageTracker[contestID]!` gives a reference we can insert into.
        // More safely:
        let contestNftTracker = self.nftUsageTracker[contestID]! // This is a copy if value is struct, ref if resource.
                                                              // For {String: UInt64} this is fine.

        var lineupNftDetailsForEvent: [String] = []
        var nftsForEntry: [RegisteredNftInfo] = []

        // 3. Check NFT availability for this contest
        for nftInput in nftsToRegisterInput {
            let compositeKey = self.getCompositeNftKey(contractAddress: nftInput.nftContractAddress, nftID: nftInput.nftID)
            if contestNftTracker[compositeKey] != nil {
                let reason = "NFT ".concat(compositeKey).concat(" is already in use for contest ").concat(contestID)
                emit LineupRegistrationFailed(userAddress: userAddress, contestID: contestID, reason: reason)
                // Consider if panic is better to revert the transaction fully if any NFT is invalid.
                // Returning nil allows partial processing if not careful, but here it's an early exit.
                return nil 
            }
            // Create RegisteredNftInfo with the userAddress who is submitting the lineup
            nftsForEntry.append(RegisteredNftInfo(nftContractAddress: nftInput.nftContractAddress, nftID: nftInput.nftID, ownerAddress: userAddress))
            lineupNftDetailsForEvent.append(compositeKey)
        }

        // 4. All checks passed, proceed with registration
        let newID = self.nextLineupEntryID
        
        let newEntry = LineupEntry(
            lineupEntryID: newID,
            contestID: contestID,
            userAddress: userAddress,
            registeredNfts: nftsForEntry,
            registrationTime: getCurrentBlock().timestamp
        )
        self.lineupEntries[newID] = newEntry
        self.nextLineupEntryID = self.nextLineupEntryID + 1

        // 5. Update trackers
        // Update nftUsageTracker
        for nftInfo in nftsForEntry {
            let compositeKey = self.getCompositeNftKey(contractAddress: nftInfo.nftContractAddress, nftID: nftInfo.nftID)
            // We need to update the dictionary in storage, not just the local `contestNftTracker` copy.
            self.nftUsageTracker[contestID]![compositeKey] = newID
        }
        
        // Update userContestLineupLimit
        if self.userContestLineupLimit[contestID] == nil {
            self.userContestLineupLimit[contestID] = {}
        }
        self.userContestLineupLimit[contestID]![userAddress] = newID

        emit LineupRegistered(
            lineupEntryID: newID,
            contestID: contestID,
            userAddress: userAddress,
            nftCount: nftsForEntry.length,
            registeredNftDetails: lineupNftDetailsForEvent
        )
        return newID
    }

    // Restricted function to clean up trackers for a contest
    pub fun cleanupContest(contestID: String, auth adminRef: &AdminResource) {
        adminRef.helloAdmin() // Example usage
        
        var unlockedNfts = 0
        if self.nftUsageTracker.containsKey(contestID) {
            unlockedNfts = self.nftUsageTracker[contestID]!.keys.length
            self.nftUsageTracker.remove(key: contestID)
        }
        
        var unlockedUserLimits = 0
        if self.userContestLineupLimit.containsKey(contestID) {
            unlockedUserLimits = self.userContestLineupLimit[contestID]!.keys.length
            self.userContestLineupLimit.remove(key: contestID)
        }

        // Note: This does not remove the LineupEntry from self.lineupEntries, preserving historical data.
        // If LineupEntry structs should also be removed, that logic would be added here.

        emit ContestEntriesCleaned(contestID: contestID, unlockedNftCount: unlockedNfts, unlockedUserLimitCount: unlockedUserLimits)
        log("Cleaned up trackers for contest: ".concat(contestID))
    }

    // Helper to create an AdminResource instance. Should only be callable during contract init.
    // Or, if an admin needs to explicitly create one for another authorized account (more complex setup).
    // For this contract, it's created and stored at init for the contract deployer.
    // pub fun createAdminResource(): @AdminResource {
    //     return <-create AdminResource()
    // }
}
