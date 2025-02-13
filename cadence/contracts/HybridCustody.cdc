pub contract HybridCustody {
    pub event ContractInitialized()
    pub event ChildAccountCreated(parent: Address, child: Address)
    pub event AccountsLinked(parent: Address, child: Address)

    // Mapping of parent addresses to their child accounts
    access(self) var childAccounts: {Address: [Address]}

    pub fun createChildAccount(parent: AuthAccount, child: AuthAccount, publicKey: String) {
        // Store the relationship
        if self.childAccounts[parent.address] == nil {
            self.childAccounts[parent.address] = []
        }
        self.childAccounts[parent.address]!.append(child.address)

        emit ChildAccountCreated(parent: parent.address, child: child.address)
    }

    pub fun linkAccounts(parent: AuthAccount, childAddress: Address) {
        // Store the relationship
        if self.childAccounts[parent.address] == nil {
            self.childAccounts[parent.address] = []
        }
        self.childAccounts[parent.address]!.append(childAddress)

        emit AccountsLinked(parent: parent.address, child: childAddress)
    }

    pub fun getChildAccounts(parent: Address): [Address] {
        return self.childAccounts[parent] ?? []
    }

    init() {
        self.childAccounts = {}
        emit ContractInitialized()
    }
} 