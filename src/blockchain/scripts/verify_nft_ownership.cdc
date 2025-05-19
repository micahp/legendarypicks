// src/blockchain/scripts/verify_nft_ownership.cdc
import NonFungibleToken from 0xNonFungibleTokenPlaceholder // Standard NFT contract interface

// Input structure for each NFT to check
pub struct NftToCheck {
    // The address where the specific NFT contract (e.g., TopShot) is deployed.
    // While not used directly to borrow collection in this script if path is unique,
    // it's good for context and future use (e.g. verifying the collection's type).
    pub let contractAddress: Address 
    
    // The string identifier for the public path of the collection.
    // Examples: "MomentCollection", "AllDayNFLCollection", "ScoutPassCollection"
    // The script will prepend "/public/" to this string.
    pub let collectionPublicPathIdentifier: String 
    
    pub let nftID: UInt64

    init(contractAddress: Address, collectionPublicPathIdentifier: String, nftID: UInt64) {
        self.contractAddress = contractAddress
        self.collectionPublicPathIdentifier = collectionPublicPathIdentifier
        self.nftID = nftID
    }
}

pub fun main(userAddress: Address, nftsToVerify: [NftToCheck]): [Bool] {
    let results: [Bool] = []
    let account = getAccount(userAddress)

    for checkableNft in nftsToVerify {
        var ownsNft = false
        
        // Construct the PublicPath from the string identifier.
        // Example: if collectionPublicPathIdentifier is "MomentCollection", path becomes /public/MomentCollection
        let constructedPathString = "/public/".concat(checkableNft.collectionPublicPathIdentifier)
        
        // Attempt to create a PublicPath object from the string.
        // Note: Cadence does not allow direct string-to-PublicPath conversion like this.
        // The path needs to be known and valid at compile time or passed as a Path type.
        // This conceptual script assumes the *identifier string* itself is what's used to form a valid Path.
        // For a real FCL interaction, the path string from `collectionPublicPathIdentifier`
        // would be used by the client (e.g. FCL JS) to specify the capability.
        // In a pure Cadence script execution (e.g. via flow-cli or Go SDK),
        // you'd typically pass the path string, and the SDK helps form the actual Path object.
        //
        // Let's assume for this script execution context that PublicPath can be derived this way,
        // or more practically, the path string itself is the key for capability lookup.
        // The `getCapability` function takes a `PublicPath`.
        // The most robust way if paths are dynamic is if the collection itself is registered somewhere
        // or if we try a common pattern, but the prompt asked for `collectionPublicPathIdentifier`.
        //
        // Revisiting: The example from the prompt was:
        // `let collectionPath = PublicPath(identifier: checkableNft.collectionPublicPathString)`
        // This is the correct way to construct a path if `checkableNft.collectionPublicPathString`
        // is a valid *identifier* known to the system (like "flowTokenReceiver").
        // It might not work for arbitrary strings like "MyCustomCollectionPath".
        //
        // For maximum flexibility and to align with how capabilities are typically used with paths
        // that are not globally registered identifiers like "flowTokenReceiver", we should use
        // the string directly to form the path struct if the environment supports it,
        // or rely on the fact that `getCapability` often takes a string path in SDKs.
        //
        // Given the prompt's example `PublicPath(identifier: checkableNft.collectionPublicPathString)`,
        // this implies `collectionPublicPathString` must be a registered path identifier.
        // This is usually for standard, well-known paths.
        // For user-defined collection paths, they are usually `/public/ContractNameCollection`.
        //
        // Let's use the prompt's specific example:
        let collectionPath = PublicPath(identifier: checkableNft.collectionPublicPathIdentifier)
        // If `collectionPath` is nil here, it means the identifier string was not valid.
        // We should handle this.

        if collectionPath == nil {
            results.append(false)
            log("Invalid public path identifier provided: ".concat(checkableNft.collectionPublicPathIdentifier))
            continue // to the next NFT in the loop
        }

        // Attempt to borrow a reference to the user's collection for that NFT type
        // We are borrowing the most generic CollectionPublic interface
        let collectionCap = account.capabilities.get<&{NonFungibleToken.CollectionPublic}>(collectionPath!) // Use path! as we checked for nil
        // Note: Using capabilities.get() and then borrow() is safer than getCapability().borrow() directly for newer Cadence versions.
        
        if collectionCap.borrow() != nil { // Checks if capability is linked and borrows successfully
            let collectionRef = collectionCap.borrow()! // Safe to force unwrap due to check
            
            // Check if the NFT exists in that collection by trying to borrow it
            // borrowNFT returns an optional resource; non-nil means it exists.
            if collectionRef.borrowNFT(id: checkableNft.nftID) != nil {
                ownsNft = true
            } else {
                // NFT not found in this specific collection
                log("NFT ID ".concat(checkableNft.nftID.toString()).concat(" not found in collection at path /public/").concat(checkableNft.collectionPublicPathIdentifier))
            }
        } else {
            // Capability doesn't exist, isn't linked, or doesn't provide the required interface
            log("Could not borrow collection capability for path /public/".concat(checkableNft.collectionPublicPathIdentifier).concat(" for user ").concat(userAddress.toString()))
        }
        
        results.append(ownsNft)
    }
    return results
}
