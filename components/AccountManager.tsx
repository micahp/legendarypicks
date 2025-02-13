import { useState } from 'react'
import { AccountLinkingService } from '../services/accountLinking'
import { KeyGenerationService } from '../services/keyGeneration'

export default function AccountManager() {
  const [isCreating, setIsCreating] = useState(false)
  const [isLinking, setIsLinking] = useState(false)
  const [childAddress, setChildAddress] = useState('')
  const [error, setError] = useState<string | null>(null)
  const [success, setSuccess] = useState<string | null>(null)

  const handleCreateAccount = async () => {
    try {
      setIsCreating(true)
      setError(null)
      
      // Generate a new key pair
      const { publicKey, privateKey } = await KeyGenerationService.generateKeyPair()
      
      // Format the public key for Flow
      const formattedPublicKey = KeyGenerationService.formatPublicKey(publicKey)
      
      // Create the child account
      const result = await AccountLinkingService.createChildAccount(formattedPublicKey)
      
      // Store the private key securely (you'll need to implement this)
      // For example, you might encrypt it and store it in localStorage
      localStorage.setItem('childAccountKey', privateKey)
      
      setSuccess('Account created successfully!')
    } catch (error) {
      console.error("Error creating account:", error)
      setError('Failed to create account. Please try again.')
    } finally {
      setIsCreating(false)
    }
  }

  const handleLinkAccount = async () => {
    try {
      setIsLinking(true)
      setError(null)
      
      await AccountLinkingService.linkAccounts(childAddress)
      setChildAddress('')
      setSuccess('Account linked successfully!')
    } catch (error) {
      console.error("Error linking account:", error)
      setError('Failed to link account. Please try again.')
    } finally {
      setIsLinking(false)
    }
  }

  return (
    <div className="space-y-4 p-6 bg-white rounded-lg shadow">
      {error && (
        <div className="bg-red-50 text-red-600 p-3 rounded-lg mb-4">
          {error}
        </div>
      )}
      
      {success && (
        <div className="bg-green-50 text-green-600 p-3 rounded-lg mb-4">
          {success}
        </div>
      )}

      <div>
        <h3 className="text-lg font-semibold mb-2">Create New Account</h3>
        <p className="text-sm text-gray-600 mb-4">
          Create a new account that will be linked to your main account.
        </p>
        <button
          className="bg-blue-500 text-white px-4 py-2 rounded-lg disabled:opacity-50
            hover:bg-blue-600 transition-colors"
          onClick={handleCreateAccount}
          disabled={isCreating}
        >
          {isCreating ? 'Creating...' : 'Create Account'}
        </button>
      </div>

      <div className="border-t pt-4 mt-4">
        <h3 className="text-lg font-semibold mb-2">Link Existing Account</h3>
        <p className="text-sm text-gray-600 mb-4">
          Link an existing Flow account to your main account.
        </p>
        <div className="flex gap-2">
          <input
            type="text"
            className="border rounded-lg px-4 py-2 flex-1 focus:ring-2 
              focus:ring-blue-500 focus:border-blue-500"
            placeholder="Enter account address"
            value={childAddress}
            onChange={(e) => setChildAddress(e.target.value)}
          />
          <button
            className="bg-blue-500 text-white px-4 py-2 rounded-lg disabled:opacity-50
              hover:bg-blue-600 transition-colors"
            onClick={handleLinkAccount}
            disabled={isLinking || !childAddress}
          >
            {isLinking ? 'Linking...' : 'Link Account'}
          </button>
        </div>
      </div>
    </div>
  )
} 