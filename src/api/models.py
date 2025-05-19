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
    # Add other fields as necessary, like username

class PlayerSelection(BaseModel):
    player_id: str # Or int, depending on how player IDs are sourced
    # Salary might be fetched server-side based on player_id and contest rules
    # For now, client might send it, or it's validated/calculated by backend.
    # Let's add salary here for simplicity in this step, assuming client sends it or we mock it.
    salary: int = Field(default=0, description="Player's salary for the contest")


class LineupBase(BaseModel):
    name: Optional[str] = None
    # player_selections will be used for creation, players_data for response
    
class LineupCreate(LineupBase):
    player_selections: List[PlayerSelection]

class LineupPlayerDetail(PlayerSelection): # For response, potentially more player details
    name: Optional[str] = "Unknown Player" # Example, would be enriched
    position: Optional[str] = "N/A"      # Example

class LineupResponse(LineupBase):
    id: UUID
    user_id: UUID # From the authenticated user
    contest_id: UUID
    players_data: List[LineupPlayerDetail] # Enriched player data
    total_salary_used: int
    total_score: float = 0.0 # Added for leaderboard, default to 0.0
    nft_id: Optional[str] = None # Will be populated after minting
    created_at: datetime
    updated_at: datetime

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
