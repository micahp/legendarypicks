from pydantic import BaseModel, Field
from typing import Optional, List, Any, Dict
from uuid import UUID
from datetime import datetime

class ContestBase(BaseModel):
    name: str
    description: Optional[str] = None
    sport: str = "NBA"
    start_time: datetime
    end_time: datetime
    salary_cap: int
    max_entries_per_user: int = 1
    status: str = Field(default="upcoming", description="e.g., upcoming, locked, scoring, completed, cancelled")
    entry_fee: float = 0.0
    prize_pool: Optional[Dict[str, Any]] = None

class ContestCreate(ContestBase):
    pass

class ContestUpdate(BaseModel):
    name: Optional[str] = None
    description: Optional[str] = None
    sport: Optional[str] = None
    start_time: Optional[datetime] = None
    end_time: Optional[datetime] = None
    salary_cap: Optional[int] = None
    max_entries_per_user: Optional[int] = None
    status: Optional[str] = None
    entry_fee: Optional[float] = None
    prize_pool: Optional[Dict[str, Any]] = None

class ContestResponse(ContestBase):
    id: UUID
    created_at: datetime
    updated_at: datetime

    class Config:
        orm_mode = True # For SQLAlchemy or other ORMs, good practice

class User(BaseModel):
    id: UUID
    email: str
    # Add other fields as necessary, like username (this is the existing User model from previous step)
    # For user creation and response, we'll define more specific models below.

# --- User Authentication and Profile Models ---

class UserCreate(BaseModel):
    email: str
    password: str # In a real app, this would be processed and hashed, not stored directly
    referral_code: Optional[str] = None
    flow_address: Optional[str] = None # For simulation: user provides their Flow address during sign-up

class UserAuthResponse(BaseModel): # For returning after signup/login, typically with a token
    id: UUID
    email: str
    flow_address: Optional[str] = None
    scout_pass_nft_id: Optional[str] = None # ID of the minted Scout Pass NFT
    # referred_by_user_id: Optional[UUID] = None # Might not be needed in auth response, but in UserInDB
    access_token: Optional[str] = None # Example if returning a token
    token_type: Optional[str] = "bearer" # Example

class UserInDB(User): # Extends the basic User model if it exists and is suitable
    # Or define from scratch:
    # id: UUID
    # email: str
    hashed_password: str
    flow_address: Optional[str] = None
    referred_by_user_id: Optional[UUID] = None
    scout_pass_nft_id: Optional[str] = None # This could be UInt64 if from Flow, using str for flexibility
    created_at: datetime
    updated_at: datetime
    # Add other fields like is_active, is_superuser etc. if needed

# New model for identifying selected NFTs
class OwnedNftIdentifier(BaseModel):
    contract_address: str # Address of the NFT contract (e.g., TopShot contract)
    nft_id: str       # The specific ID of the NFT moment
    # Optional: player_id: str # Could be useful to pre-associate for salary calculation
    # Optional: position: str # Could be useful

# Old PlayerSelection - to be replaced or removed
# class PlayerSelection(BaseModel):
#     player_id: str 
#     salary: int = Field(default=0, description="Player's salary for the contest")

class LineupBase(BaseModel):
    name: Optional[str] = None
    
# Updated LineupCreate
class LineupCreate(LineupBase): 
    selected_nft_ids: List[OwnedNftIdentifier] # New way
    # name: Optional[str] is inherited from LineupBase

# Old LineupPlayerDetail - to be replaced or removed
# class LineupPlayerDetail(PlayerSelection): 
#     name: Optional[str] = "Unknown Player" 
#     position: Optional[str] = "N/A"     

# New model for displaying selected NFT details in a lineup
class LineupNftDetail(OwnedNftIdentifier):
    player_name: Optional[str] = "Unknown Player" # To be enriched by backend
    player_team: Optional[str] = "N/A"
    player_position: Optional[str] = "N/A"
    # Salary might be derived from the player associated with the NFT for this contest
    salary_at_draft: Optional[int] = 0 

# Updated LineupResponse
class LineupResponse(LineupBase):
    id: UUID
    user_id: UUID # From the authenticated user
    contest_id: UUID
    # players_data: List[LineupPlayerDetail] # Old
    selected_nfts_data: List[LineupNftDetail] # New
    total_salary_used: float # Ensure this remains float, will be calculated from salary_at_draft of selected_nfts_data
    nft_id: Optional[str] = None # This would be the ID from a future LineupRegistry contract
    created_at: datetime
    updated_at: datetime
    total_score: float = 0.0 # Ensured present and default

    class Config:
        orm_mode = True

class LeaderboardEntry(BaseModel):
    user_id: UUID
    username: str # Or user_display_name
    lineup_id: UUID
    lineup_name: Optional[str] = None
    total_score: float
    rank: int

class ContestLeaderboard(BaseModel):
    contest_id: UUID
    contest_name: str
    last_updated: datetime
    entries: List[LeaderboardEntry]
