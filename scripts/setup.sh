#!/bin/bash

# Create Python virtual environment
echo "Creating Python virtual environment..."
python3 -m venv venv
source venv/bin/activate

# Install Python dependencies
echo "Installing Python dependencies..."
pip install -r backend/requirements.txt

# Create keys directory and generate keys
echo "Setting up Flow keys..."
mkdir -p keys
printf "ba68d45a5acaa52f3cacf4ad3a64d9523e0ce0ae3addb1ee6805385b380b7646" > keys/community.pkey
printf "ba68d45a5acaa52f3cacf4ad3a64d9523e0ce0ae3addb1ee6805385b380b7646" > keys/default.pkey
printf "1a05ba433be5af2988e814d1e4fa08f1574140e6cb5649a861cc6377718c51be" > keys/emulator-account.pkey
printf "ba68d45a5acaa52f3cacf4ad3a64d9523e0ce0ae3addb1ee6805385b380b7646" > keys/escrow.pkey
printf "ba68d45a5acaa52f3cacf4ad3a64d9523e0ce0ae3addb1ee6805385b380b7646" > keys/standard.pkey

echo "Setup complete!"