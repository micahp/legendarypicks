// src/blockchain/contracts/LineupNFT.cdc

import NonFungibleToken from 0xNonFungibleToken // Standard address placeholder

pub contract LineupNFT: NonFungibleToken {

    pub var totalSupply: UInt64

    pub let CollectionStoragePath: StoragePath
    pub let CollectionPublicPath: PublicPath
    pub let MinterStoragePath: StoragePath
    pub let MinterPublicPath: PublicPath

    pub event ContractInitialized()
    pub event Withdraw(id: UInt64, from: Address?)
    pub event Deposit(id: UInt64, to: Address?)
    pub event Minted(id: UInt64, name: String, contestId: String, userId: String)
    pub event MetadataUpdated(id: UInt64, fantasy_points: UFix64, rank: Int?)

    // Struct for public metadata
    pub struct LineupNFTMetadata {
        pub let id: UInt64
        pub let name: String
        pub let description: String
        pub let image_url: String
        pub let external_url: String
        pub let contest_id: String
        pub let user_id: String // Could be Address, using String for now for simplicity
        pub let players: [{String: String}] // Simplified player representation
        pub let total_salary: Int
        pub var fantasy_points: UFix64
        pub var rank: Int?
        pub var last_updated: UFix64

        init(id: UInt64, name: String, description: String, image_url: String, external_url: String, contest_id: String, user_id: String, players: [{String: String}], total_salary: Int, fantasy_points: UFix64, rank: Int?, last_updated: UFix64) {
            self.id = id
            self.name = name
            self.description = description
            self.image_url = image_url
            self.external_url = external_url
            self.contest_id = contest_id
            self.user_id = user_id
            self.players = players
            self.total_salary = total_salary
            self.fantasy_points = fantasy_points
            self.rank = rank
            self.last_updated = last_updated
        }
    }

    pub resource NFT: NonFungibleToken.INFT {
        pub let id: UInt64
        access(self) var metadata: LineupNFTMetadata // Keep metadata private to the resource for controlled updates

        init(id: UInt64, name: String, description: String, image_url: String, external_url: String, contest_id: String, user_id: String, players: [{String: String}], total_salary: Int) {
            self.id = id
            self.metadata = LineupNFTMetadata(
                id: id,
                name: name,
                description: description,
                image_url: image_url,
                external_url: external_url,
                contest_id: contest_id,
                user_id: user_id,
                players: players,
                total_salary: total_salary,
                fantasy_points: 0.0,
                rank: nil,
                last_updated: getCurrentBlock().timestamp
            )
        }

        pub fun getViews(): [Type] {
            return [Type<LineupNFTMetadata>()]
        }

        pub fun resolveView(_ view: Type): AnyStruct? {
            if view == Type<LineupNFTMetadata>() {
                return self.metadata
            }
            return nil
        }

        // Function to update dynamic metadata, only callable internally or via authorized capability
        access(contract) fun updateMetadata(fantasy_points: UFix64, rank: Int?) {
            self.metadata.fantasy_points = fantasy_points
            self.metadata.rank = rank
            self.metadata.last_updated = getCurrentBlock().timestamp
            emit MetadataUpdated(id: self.id, fantasy_points: fantasy_points, rank: rank)
        }
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
            let nft <- token as! @LineupNFT.NFT
            let id = nft.id
            let oldToken <- self.ownedNFTs[id] <- nft
            emit Deposit(id: id, to: self.owner?.address)
            destroy oldToken
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

        // Returns a borrowed reference to an NFT in the collection
        // so that the caller can read its metadata and call its methods
        pub fun borrowLineupNFT(id: UInt64): &LineupNFT.NFT? {
            if self.ownedNFTs[id] != nil {
                // Create an authorized reference to allow downcasting
                let ref = (&self.ownedNFTs[id] as auth &NonFungibleToken.NFT?)!
                return ref as &LineupNFT.NFT?
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
        pub fun mintNFT(
            recipient: &{NonFungibleToken.CollectionPublic},
            name: String,
            description: String,
            image_url: String,
            external_url: String,
            contest_id: String,
            user_id: String, // Could be Address
            players: [{String: String}],
            total_salary: Int
        ) {
            let newID = LineupNFT.totalSupply
            
            // create the new NFT
            let newNFT <- create NFT(
                id: newID,
                name: name,
                description: description,
                image_url: image_url,
                external_url: external_url,
                contest_id: contest_id,
                user_id: user_id,
                players: players,
                total_salary: total_salary
            )

            // deposit the NFT in the recipient's collection
            recipient.deposit(token: <-newNFT)

            LineupNFT.totalSupply = LineupNFT.totalSupply + 1
            emit Minted(id: newID, name: name, contestId: contest_id, userId: user_id)
        }
    }

    // Function to update metadata - should be access controlled.
    // This version assumes the caller has a capability to the specific NFT or the admin has direct access.
    // A more robust implementation might involve storing NFTs in the contract or using capabilities.
    pub fun updateNFTMetadata(ownerAddress: Address, id: UInt64, fantasy_points: UFix64, rank: Int?) {
        let collectionCap = getAccount(ownerAddress).capabilities.borrow<&{LineupNFT.CollectionPublic}>(LineupNFT.CollectionPublicPath)
            ?? panic("Could not borrow CollectionPublic capability")

        let lineupCollection = collectionCap as! &LineupNFT.Collection
        
        let nftRef = lineupCollection.borrowLineupNFT(id: id)
            ?? panic("NFT with given ID not found in the collection")

        // Call the internal update function on the NFT resource
        // This requires `updateMetadata` to be accessible from the contract scope.
        nftRef.updateMetadata(fantasy_points: fantasy_points, rank: rank)
        
        log("NFT metadata update attempted for ID: ".concat(id.toString()))
    }
    
    // Public function to read metadata by ID
    pub fun getNFTMetadata(id: UInt64): LineupNFTMetadata? {
        // This is a simplified way to get metadata. 
        // In a real scenario, you'd need to know which collection the NFT is in.
        // This function might iterate over all public collections or require an address.
        // For now, we'll assume we can access it if it exists, which is not realistic for a deployed contract.
        // A better approach for a public getter might be to query a specific user's collection if address is known
        // or if NFTs are stored/indexed globally in the contract (which has storage implications).

        // Attempt to borrow from the contract owner's collection as a fallback/example
        let contractOwnerCollection = self.account.borrow<&Collection>(from: self.CollectionStoragePath)
        if contractOwnerCollection != nil {
            if let nftRef = contractOwnerCollection!.borrowLineupNFT(id: id) {
                return nftRef.metadata
            }
        }
        // If not found in contract owner's collection, ideally you'd have a way to look up public collections.
        // This part is complex without knowing the collection's location.
        log("getNFTMetadata called for ID: ".concat(id.toString()) movimientos ". Could not find NFT without collection context.")
        return nil
    }

    init() {
        self.totalSupply = 0

        self.CollectionStoragePath = /storage/LineupNFTCollection
        self.CollectionPublicPath = /public/LineupNFTCollection
        self.MinterStoragePath = /storage/LineupNFTMinter
        self.MinterPublicPath = /public/LineupNFTMinter

        // Save the Minter resource to account storage so it can be accessed.
        self.account.storage.save(<-create NFTMinter(), to: self.MinterStoragePath)
        // Create a public capability for the minter.
        self.account.capabilities.publish(
            self.account.capabilities.storageCapability<&NFTMinter>(self.MinterStoragePath)!,
            at: self.MinterPublicPath
        )

        // Create an empty collection and save it to account storage
        self.account.storage.save(<-self.createEmptyCollection(), to: self.CollectionStoragePath)
        
        // Publish a capability to the collection in public storage
        // Anyone can get this public capability to deposit NFTs
        self.account.capabilities.publish(
            self.account.capabilities.storageCapability<&Collection{NonFungibleToken.CollectionPublic, NonFungibleToken.Receiver}>(self.CollectionStoragePath)!,
            at: self.CollectionPublicPath
        )

        emit ContractInitialized()
        log("LineupNFT Contract Initialized")
    }
}
