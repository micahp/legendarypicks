// src/blockchain/scripts/mint_lineup_nft.cdc

import NonFungibleToken from 0xNonFungibleToken // Standard address placeholder
import LineupNFT from "../contracts/LineupNFT.cdc"     // Relative path to the contract

transaction(
    recipientAddress: Address,
    name: String,
    description: String,
    image_url: String,
    external_url: String,
    contest_id: String,
    user_id: String,
    players: [{String: String}],
    total_salary: Int
) {

    let minterRef: &LineupNFT.NFTMinter
    let receiverCapability: &{NonFungibleToken.CollectionPublic} // Using the public type, as mintNFT expects this

    prepare(signer: AuthAccount) {
        // Attempt to borrow a reference to the NFTMinter resource.
        // Assumes the Minter is stored at the standard path in the signer's account (contract deployer/minter account)
        self.minterRef = signer.storage.borrow<&LineupNFT.NFTMinter>(from: LineupNFT.MinterStoragePath)
            ?? panic("Signer is not the LineupNFT minter or minter not found at ".concat(LineupNFT.MinterStoragePath.toString()))

        // Get the recipient's public account object
        let recipientAccount = getAccount(recipientAddress)

        // Get a public capability to the recipient's LineupNFT collection
        // Assumes the collection is published at the standard public path defined in the LineupNFT contract
        self.receiverCapability = recipientAccount.capabilities.borrow<&{NonFungibleToken.CollectionPublic}>(LineupNFT.CollectionPublicPath)
            ?? panic("Failed to borrow receiver capability from recipient's account at ".concat(LineupNFT.CollectionPublicPath.toString()))
    }

    execute {
        self.minterRef.mintNFT(
            recipient: self.receiverCapability,
            name: name,
            description: description,
            image_url: image_url,
            external_url: external_url,
            contest_id: contest_id,
            user_id: user_id,
            players: players,
            total_salary: total_salary
        )
        log("LineupNFT minted successfully and deposited to recipient's collection")
    }
}
