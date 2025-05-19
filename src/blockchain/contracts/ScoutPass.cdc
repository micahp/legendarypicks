// src/blockchain/contracts/ScoutPass.cdc

import NonFungibleToken from 0xNonFungibleTokenPlaceholder

pub contract ScoutPass: NonFungibleToken {

    pub var totalSupply: UInt64

    // Paths
    pub let CollectionStoragePath: StoragePath
    pub let CollectionPublicPath: PublicPath
    pub let MinterStoragePath: StoragePath
    // MinterPublicPath is optional; if minter is admin-only, no public path needed.
    // For this example, let's assume admin (contract deployer) uses the Minter from storage.

    // Events
    pub event ContractInitialized()
    pub event Withdraw(id: UInt64, from: Address?)
    pub event Deposit(id: UInt64, to: Address?)
    pub event Minted(id: UInt64, recipient: Address, bonusType: String, bonusValue: UFix64, referredByUserID: String?)

    pub struct ScoutPassMetadata {
        pub let name: String
        pub let description: String
        pub let thumbnail: String // URL
        pub let issuer: Address
        pub let issueDate: UFix64 // Timestamp
        pub let referredByUserID: String?
        pub let bonusType: String
        pub let bonusValue: UFix64 // e.g., 2.0 for 2%

        init(name: String, description: String, thumbnail: String, issuer: Address, issueDate: UFix64, referredByUserID: String?, bonusType: String, bonusValue: UFix64) {
            self.name = name
            self.description = description
            self.thumbnail = thumbnail
            self.issuer = issuer
            self.issueDate = issueDate
            self.referredByUserID = referredByUserID
            self.bonusType = bonusType
            self.bonusValue = bonusValue
        }
    }

    pub resource NFT: NonFungibleToken.INFT, NonFungibleToken.Resolver {
        pub let id: UInt64
        pub let metadata: ScoutPassMetadata

        init(id: UInt64, metadata: ScoutPassMetadata) {
            self.id = id
            self.metadata = metadata
        }

        pub fun getViews(): [Type] {
            return [Type<ScoutPassMetadata>()]
        }

        pub fun resolveView(_ view: Type): AnyStruct? {
            if view == Type<ScoutPassMetadata>() {
                return self.metadata
            }
            return nil
        }

        // If you need a destructor for the NFT resource (e.g., to log or manage external resources)
        // destroy() {
        //     log("NFT ".concat(self.id.toString()).concat(" destroyed"))
        // }
    }

    pub resource Collection: NonFungibleToken.Provider, NonFungibleToken.Receiver, NonFungibleToken.CollectionPublic {
        // dictionary of NFT conforming resources that stores the NFTs in this collection
        pub var ownedNFTs: @{UInt64: NonFungibleToken.NFT}

        init () {
            self.ownedNFTs <- {}
        }

        // withdraw removes an NFT from the collection and moves it to the caller
        pub fun withdraw(withdrawID: UInt64): @NonFungibleToken.NFT {
            let token <- self.ownedNFTs.remove(key: withdrawID) ?? panic("missing NFT")
            emit Withdraw(id: token.id, from: self.owner?.address)
            return <-token
        }

        // deposit takes a NFT and adds it to the collections dictionary
        // and adds the ID to the id array
        pub fun deposit(token: @NonFungibleToken.NFT) {
            let nft <- token as! @ScoutPass.NFT // Cast to the specific NFT type
            let id = nft.id
            // add the new NFT to the dictionary which removes the old one and destroys it
            let oldToken <- self.ownedNFTs[id] <- nft
            emit Deposit(id: id, to: self.owner?.address)
            destroy oldToken // Destroy the old token if one was replaced
        }

        // getIDs returns an array of the IDs that are in the collection
        pub fun getIDs(): [UInt64] {
            return self.ownedNFTs.keys
        }

        // borrowNFT returns a borrowed reference to an NFT in the collection
        // so that the caller can read its metadata and call its methods
        pub fun borrowNFT(id: UInt64): &NonFungibleToken.NFT {
            return (&self.ownedNFTs[id] as &NonFungibleToken.NFT?)!
        }
        
        // borrowViewResolver returns a reference to a view resolver for a specific NFT
        // so that the caller can resolve public views of the NFT.
        // The method needs to be an INFTViewResolver to be able to resolve views.
        pub fun borrowViewResolver(id: UInt64): &AnyResource{NonFungibleToken.ViewResolver} {
            let nft = (&self.ownedNFTs[id] as auth &NonFungibleToken.NFT?)!
            return nft as &AnyResource{NonFungibleToken.ViewResolver}
        }

        // Custom function to borrow a ScoutPass.NFT reference
        pub fun borrowScoutPass(id: UInt64): &ScoutPass.NFT? {
            if self.ownedNFTs[id] != nil {
                let ref = (&self.ownedNFTs[id] as auth &NonFungibleToken.NFT?)!
                return ref as &ScoutPass.NFT?
            }
            return nil
        }

        destroy() {
            destroy self.ownedNFTs
        }
    }

    // public function that anyone can call to create a new empty collection
    pub fun createEmptyCollection(): @NonFungibleToken.Collection {
        return <- create Collection()
    }

    pub resource NFTMinter {
        // Mints a new ScoutPass NFT and deposits it into the recipient's collection.
        pub fun mintNFT(
            recipient: &{NonFungibleToken.CollectionPublic}, // Recipient's collection capability
            referredByUserID: String?,
            bonusType: String,
            bonusValue: UFix64,
            // Optional: allow overriding default name, description, thumbnail per mint if needed
            name: String?,
            description: String?,
            thumbnail: String?
        ) {
            let newID = ScoutPass.totalSupply
            
            // Use provided metadata or defaults
            let finalName = name ?? "Scout Pass"
            let finalDescription = description ?? "Grants a special bonus in Legendary Picks fantasy contests."
            let finalThumbnail = thumbnail ?? "ipfs://YOUR_SCOUT_PASS_DEFAULT_IMAGE_HASH_HERE" // Placeholder

            let metadata = ScoutPassMetadata(
                name: finalName,
                description: finalDescription,
                thumbnail: finalThumbnail,
                issuer: self.account.address, // The Minter's account address (contract deployer)
                issueDate: getCurrentBlock().timestamp,
                referredByUserID: referredByUserID,
                bonusType: bonusType,
                bonusValue: bonusValue
            )

            // Create the new NFT
            let newNFT <- create NFT(id: newID, metadata: metadata)

            // Deposit the NFT in the recipient's collection
            recipient.deposit(token: <-newNFT)

            ScoutPass.totalSupply = ScoutPass.totalSupply + 1
            
            emit Minted(id: newID, recipient: recipient.owner!.address, bonusType: bonusType, bonusValue: bonusValue, referredByUserID: referredByUserID)
        }
    }

    init() {
        self.totalSupply = 0

        // Set up the storage paths
        self.CollectionStoragePath = /storage/ScoutPassCollection
        self.CollectionPublicPath = /public/ScoutPassCollection
        self.MinterStoragePath = /storage/ScoutPassMinter
        // No MinterPublicPath means only account that deployed contract can access minter from storage path.

        // Save the NFTMinter resource to the contract deployer's account storage.
        // This resource can then be used by the deployer to mint NFTs.
        self.account.storage.save(<-create NFTMinter(), to: self.MinterStoragePath)
        
        // The contract deployer should also have a collection.
        // This is standard practice, though not strictly required for the contract to function for others.
        // It's good for the deployer to be able to hold its own NFTs.
        if self.account.storage.borrow<&Collection>(from: self.CollectionStoragePath) == nil {
            self.account.storage.save(<-createEmptyCollection(), to: self.CollectionStoragePath)
            
            // Publish a public capability to the Collection.
            // This allows others to check the deployer's collection or deposit NFTs to it (if they somehow got one meant for the deployer).
            self.account.capabilities.publish(
                self.account.capabilities.storageCapability<&Collection{NonFungibleToken.CollectionPublic, NonFungibleToken.Receiver}>(self.CollectionStoragePath)!,
                at: self.CollectionPublicPath
            )
        }
        
        emit ContractInitialized()
        log("ScoutPass Contract Initialized and Minter created.")
    }
}
