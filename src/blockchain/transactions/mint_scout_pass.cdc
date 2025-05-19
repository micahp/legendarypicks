// src/blockchain/transactions/mint_scout_pass.cdc

import NonFungibleToken from 0xNonFungibleTokenPlaceholder
// Import ScoutPass using a relative path for local dev, or a placeholder for deployed address
import ScoutPass from "../contracts/ScoutPass.cdc" 
// If using a placeholder for deployment scripts:
// import ScoutPass from 0xScoutPassContractPlaceholder 

transaction(
    recipientAddress: Address,
    referredByUserID: String?,
    bonusType: String,
    bonusValue: UFix64,
    name: String?,
    description: String?,
    thumbnail: String?
) {

    let minterRef: &ScoutPass.NFTMinter
    let receiverCapability: &ScoutPass.Collection{NonFungibleToken.Receiver}

    prepare(signer: AuthAccount) {
        // Borrow a reference to the NFTMinter resource from the signer's account.
        // This path is defined in the ScoutPass contract.
        self.minterRef = signer.storage.borrow<&ScoutPass.NFTMinter>(from: ScoutPass.MinterStoragePath)
            ?? panic("Signer does not have the ScoutPass minter resource or path is incorrect. Ensure signer is the contract admin.")

        // Get the recipient's public account object
        let recipientAccount = getAccount(recipientAddress)

        // Get a public capability to the recipient's ScoutPass collection.
        // This path is defined in the ScoutPass contract.
        // The capability must conform to NonFungibleToken.Receiver to accept the deposit.
        self.receiverCapability = recipientAccount.capabilities.borrow<&ScoutPass.Collection{NonFungibleToken.Receiver}>(ScoutPass.CollectionPublicPath)
            ?? panic("Failed to borrow receiver capability from the recipient's ScoutPass collection. Ensure the collection has been set up at ".concat(ScoutPass.CollectionPublicPath.toString()))
    }

    execute {
        // Call the mintNFT function on the minter resource.
        // The ScoutPass contract's mintNFT function is designed to handle optional 'name', 'description', 
        // and 'thumbnail' parameters, using defaults if they are nil.
        self.minterRef.mintNFT(
            recipient: self.receiverCapability,
            referredByUserID: referredByUserID,
            bonusType: bonusType,
            bonusValue: bonusValue,
            name: name,
            description: description,
            thumbnail: thumbnail
        )
        
        log("ScoutPass NFT minted successfully and deposited to the recipient's collection.")
    }
}
