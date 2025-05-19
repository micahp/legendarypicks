from fastapi import FastAPI, HTTPException, status, Depends
from pydantic import BaseModel, Field
from typing import List, Optional, Dict, Any
from uuid import UUID, uuid4
from datetime import datetime
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from jose import JWTError, jwt # Placeholder
from fastapi import WebSocket, WebSocketDisconnect # Added for WebSockets
import json # Added for WebSockets

app = FastAPI(title="Fantasy Platform API")

# Updated model imports
from .models import (
    ContestCreate, ContestUpdate, ContestResponse, User, # Basic User model for Depends(get_current_user)
    LineupCreate, LineupResponse, 
    OwnedNftIdentifier, LineupNftDetail, 
    ContestLeaderboard, LeaderboardEntry,
    UserCreate, UserAuthResponse, UserInDB # Added for user signup
)

# This is a very simplified placeholder. Real implementation needs Supabase JWT handling.
oauth2_scheme = HTTPBearer()

async def get_current_user(token: HTTPAuthorizationCredentials = Depends(oauth2_scheme)) -> User:
    # In a real app, you'd decode token.credentials (the JWT string)
    # and verify it against Supabase's public key.
    # For now, let's assume any token starting with "fake-token-" is valid
    # and decodes to a mock user.
    if not token.credentials or not token.credentials.startswith("fake-token-"):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid authentication credentials",
            headers={"WWW-Authenticate": "Bearer"},
        )
    # Mock user data based on a fake token
    try:
        user_id_str = token.credentials.split("-")[-1]
        # Attempt to create a UUID from the user_id_str if it's a valid UUID string
        # Otherwise, generate a new UUID. This handles cases where user_id_str might not be a UUID.
        try:
            user_uuid = UUID(user_id_str)
        except ValueError:
            # If user_id_str is not a valid UUID, we might want to either raise an error
            # or assign a new UUID. For this placeholder, let's try to make it somewhat consistent
            # if the string part is the same, but this part is highly dependent on real requirements.
            # For simplicity, let's just use a new uuid if it's not a valid UUID string.
            # A more robust mock might hash user_id_str to generate a consistent UUID.
            user_uuid = uuid4() # Fallback to a new UUID if parsing fails
    except IndexError: # If split doesn't produce enough parts
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid token format",
            headers={"WWW-Authenticate": "Bearer"},
        )

    return User(id=user_uuid, email=f"user_{user_id_str}@example.com")


# In-memory storage
db_contests: Dict[UUID, ContestResponse] = {}
db_lineups: Dict[UUID, LineupResponse] = {} 
db_users: Dict[UUID, UserInDB] = {} # In-memory user database


@app.get("/")
async def root():
    return {"message": "Welcome to the Fantasy Platform API"}

# --- Contest Endpoints ---
@app.post("/contests/", response_model=ContestResponse, status_code=status.HTTP_201_CREATED)
async def create_contest(contest_input: ContestCreate, current_user: User = Depends(get_current_user)): # Changed variable name
    print(f"Contest creation attempt by user: {current_user.email}")
    contest_id = uuid4()
    now = datetime.utcnow()
    
    new_contest_obj = ContestResponse( # Changed variable name
        id=contest_id,
        created_at=now,
        updated_at=now,
        name=contest_input.name,
        description=contest_input.description,
        sport=contest_input.sport,
        start_time=contest_input.start_time,
        end_time=contest_input.end_time,
        salary_cap=contest_input.salary_cap,
        max_entries_per_user=contest_input.max_entries_per_user,
        status=contest_input.status,
        entry_fee=contest_input.entry_fee,
        prize_pool=contest_input.prize_pool,
    )
    db_contests[contest_id] = new_contest_obj
    print(f"Contest '{new_contest_obj.name}' created successfully by user: {current_user.email}")
    return new_contest_obj

@app.get("/contests/", response_model=List[ContestResponse])
async def list_contests():
    return list(db_contests.values())

@app.get("/contests/{contest_id}", response_model=ContestResponse)
async def get_contest(contest_id: UUID):
    contest = db_contests.get(contest_id)
    if not contest:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Contest not found")
    return contest

@app.put("/contests/{contest_id}", response_model=ContestResponse)
async def update_contest(contest_id: UUID, contest_update: ContestUpdate):
    existing_contest = db_contests.get(contest_id)
    if not existing_contest:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Contest not found")

    update_data = contest_update.model_dump(exclude_unset=True)
    updated_contest = existing_contest.model_copy(update=update_data)
    updated_contest.updated_at = datetime.utcnow()
    db_contests[contest_id] = updated_contest
    db_contests[contest_id] = updated_contest
    return updated_contest

@app.delete("/contests/{contest_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_contest(contest_id: UUID, current_user: User = Depends(get_current_user)): # Added auth for safety
    if contest_id not in db_contests:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Contest not found")
    
    # Basic check: maybe only admin or contest creator can delete
    # For now, any authenticated user can delete if we don't add more logic.
    # Consider adding ownership check: if db_contests[contest_id].creator_id != current_user.id:
    #   raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Not authorized to delete this contest")

    print(f"User {current_user.email} attempting to delete contest {contest_id}")
    del db_contests[contest_id]
    
    # Also delete associated lineups
    lineups_to_delete = [lid for lid, ldata in db_lineups.items() if ldata.contest_id == contest_id]
    for lid in lineups_to_delete:
        del db_lineups[lid]
    print(f"Contest {contest_id} and {len(lineups_to_delete)} associated lineups deleted.")
    return

# --- Lineup Endpoints ---

@app.post("/contests/{contest_id}/lineups", response_model=LineupResponse, status_code=status.HTTP_201_CREATED)
async def submit_lineup(
    contest_id: UUID,
    lineup_data: LineupCreate, # Will now contain selected_nft_ids
    current_user: User = Depends(get_current_user)
):
    contest = db_contests.get(contest_id)
    if not contest:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Contest not found")

    calculated_total_salary = 0.0 # Ensure float for consistency with model
    nft_details_for_response: List[LineupNftDetail] = []

    # TODO: In future steps:
    # 1. Verify ownership of each NFT in lineup_data.selected_nft_ids using a Cadence script.
    # 2. For each NFT, get its associated player_id and current contest salary.
    #    This might involve querying NFT metadata or an internal 'nft_player_mapping_db'.
    # For now, using placeholder salary and data:
    placeholder_salary_per_nft = 10000 
    for nft_identifier in lineup_data.selected_nft_ids:
        calculated_total_salary += placeholder_salary_per_nft
        nft_details_for_response.append(LineupNftDetail(
            contract_address=nft_identifier.contract_address,
            nft_id=nft_identifier.nft_id,
            player_name=f"Player for NFT {nft_identifier.nft_id}", # Placeholder
            player_team="TEAM", # Placeholder
            player_position="POS", # Placeholder
            salary_at_draft=placeholder_salary_per_nft # This is an int, matching LineupNftDetail
        ))

    # db_contests stores ContestResponse objects, so use attribute access
    if calculated_total_salary > contest.salary_cap: 
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Lineup exceeds salary cap of {contest.salary_cap}. Used: {calculated_total_salary}"
        )

    new_lineup_id = uuid4()
    now = datetime.utcnow()
        
    new_lineup_obj = LineupResponse(
        id=new_lineup_id,
        user_id=current_user.id,
        contest_id=contest_id,
        name=lineup_data.name,
        selected_nfts_data=nft_details_for_response, # Use new field
        total_salary_used=float(calculated_total_salary), # Ensure this is float
        nft_id=None, 
        created_at=now,
        updated_at=now,
        total_score=0.0 # Default initial score, already in model default
    )
    
    db_lineups[new_lineup_id] = new_lineup_obj # Store the Pydantic object
    
    print(f"Lineup {new_lineup_id} (Pydantic object) created by user {current_user.email} for contest {contest_id}.")
    # print(f"TODO: Verify NFT ownership and register lineup on-chain.")
    
    return new_lineup_obj

@app.get("/users/me/lineups", response_model=List[LineupResponse])
async def get_my_lineups(current_user: User = Depends(get_current_user)):
    # db_lineups now stores LineupResponse objects, so this should work directly.
    user_lineups = [lineup for lineup in db_lineups.values() if lineup.user_id == current_user.id]
    return user_lineups

@app.get("/contests/{contest_id}/lineups", response_model=List[LineupResponse])
async def get_contest_lineups(contest_id: UUID): 
    if contest_id not in db_contests: 
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Contest not found")
    # db_lineups stores LineupResponse objects
    contest_lineups = [lineup for lineup in db_lineups.values() if lineup.contest_id == contest_id]
    return contest_lineups

@app.get("/lineups/{lineup_id}", response_model=LineupResponse)
async def get_lineup(lineup_id: UUID): 
    # db_lineups stores LineupResponse objects
    lineup = db_lineups.get(lineup_id)
    if not lineup:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Lineup not found")
    return lineup


# --- Leaderboard Endpoints ---

@app.get("/contests/{contest_id}/leaderboard", response_model=ContestLeaderboard)
async def get_contest_leaderboard(contest_id: UUID):
    contest = db_contests.get(contest_id)
    if not contest:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Contest not found")

    # Fetch lineups for the contest
    contest_lineups = [
        lineup for lineup in db_lineups.values() if lineup.contest_id == contest_id
    ]

    leaderboard_entries_data = []
    # Sort by score (descending). LineupResponse objects have total_score.
    sorted_lineups = sorted(contest_lineups, key=lambda x: x.total_score, reverse=True)
    
    for idx, lineup_obj in enumerate(sorted_lineups):
        # Mock username - in real app, fetch from user DB based on lineup_obj.user_id
        # For now, use the mock email from get_current_user or a generic placeholder if user not found
        # This part is tricky as we don't have a user DB. We'll use user_id for now.
        username = f"User_{str(lineup_obj.user_id)[:8]}" 
        
        leaderboard_entries_data.append(
            LeaderboardEntry(
                user_id=lineup_obj.user_id,
                username=username, # This is a mock username
                lineup_id=lineup_obj.id,
                lineup_name=lineup_obj.name,
                total_score=lineup_obj.total_score, # Already a float
                rank=idx + 1 # Rank based on sort order
            )
        )
    
    return ContestLeaderboard(
        contest_id=contest_id,
        contest_name=contest.name, # Accessing attribute from ContestResponse object
        last_updated=datetime.utcnow(), # Or a more specific update time from contest status
        entries=leaderboard_entries_data
    )

# --- WebSocket Connection Manager ---
class ConnectionManager:
    def __init__(self):
        self.active_connections: Dict[UUID, List[WebSocket]] = {}

    async def connect(self, websocket: WebSocket, contest_id: UUID):
        await websocket.accept()
        if contest_id not in self.active_connections:
            self.active_connections[contest_id] = []
        self.active_connections[contest_id].append(websocket)
        print(f"Client connected to contest {contest_id} leaderboard WebSocket.")

    def disconnect(self, websocket: WebSocket, contest_id: UUID):
        if contest_id in self.active_connections:
            self.active_connections[contest_id].remove(websocket)
            if not self.active_connections[contest_id]: # If list is empty
                del self.active_connections[contest_id]
        print(f"Client disconnected from contest {contest_id} leaderboard WebSocket.")

    async def broadcast_to_contest(self, contest_id: UUID, message: str):
        if contest_id in self.active_connections:
            for connection in self.active_connections[contest_id]:
                await connection.send_text(message)

manager = ConnectionManager()

# Function to be called by scoring engine or other update mechanisms
async def broadcast_leaderboard_update(contest_id: UUID):
    print(f"Broadcasting leaderboard update for contest {contest_id}")
    try:
        # This uses the existing HTTP endpoint logic to get current leaderboard
        leaderboard_data = await get_contest_leaderboard(contest_id) 
        await manager.broadcast_to_contest(contest_id, leaderboard_data.model_dump_json()) # Use model_dump_json for Pydantic models
    except HTTPException as http_exc: # Contest not found, etc.
        print(f"Could not get leaderboard for broadcast (HTTPException): {http_exc.detail}")
    except Exception as e:
        print(f"Error broadcasting leaderboard for {contest_id}: {e}")


@app.websocket("/ws/contests/{contest_id}/leaderboard")
async def websocket_leaderboard_endpoint(websocket: WebSocket, contest_id: UUID):
    await manager.connect(websocket, contest_id)
    # Send initial state
    try:
        initial_leaderboard = await get_contest_leaderboard(contest_id)
        await websocket.send_text(initial_leaderboard.model_dump_json()) # Use model_dump_json
    except HTTPException as e: # Catch errors from get_contest_leaderboard (e.g. contest not found)
        await websocket.send_text(json.dumps({"error": f"Failed to get initial leaderboard: {e.detail}"}))
    except Exception as e: # Catch other errors
         await websocket.send_text(json.dumps({"error": f"An unexpected error occurred: {str(e)}"}))


    try:
        while True:
            # Keep connection alive. In a real app, might handle pings or other messages.
            # For now, this primarily serves to keep the connection open for server-sent updates.
            data = await websocket.receive_text()
            # Echoing back or simple ack for testing client-sent messages
            # print(f"Received from client for contest {contest_id}: {data}")
            # await websocket.send_text(f"Message received (not processed): {data}") 
            # For this leaderboard, we don't expect client messages to trigger actions other than keeping alive
            # If client sends "ping", server could send "pong"
            if data.lower() == "ping":
                await websocket.send_text("pong")

    except WebSocketDisconnect:
        manager.disconnect(websocket, contest_id)
    except Exception as e: # Catch other errors during the loop
        print(f"WebSocket error for contest {contest_id} during receive loop: {e}")
        manager.disconnect(websocket, contest_id)
        # Consider closing with a specific code if not already closed by WebSocketDisconnect
        # await websocket.close(code=status.WS_1011_INTERNAL_ERROR)


# Example test trigger endpoint (usually not part of a production API like this)
@app.post("/contests/{contest_id}/trigger_leaderboard_broadcast", include_in_schema=False)
async def trigger_broadcast(contest_id: UUID):
    # This is a test endpoint. In a real app, this call comes from the scoring engine.
    # Simulate a score update for a lineup in this contest for testing
    if db_lineups:
        for lineup_id, lineup_data in db_lineups.items():
            if lineup_data.contest_id == contest_id:
                # Simulate a score update - in reality, this comes from scoring engine
                import random
                db_lineups[lineup_id].total_score = round(random.uniform(50.0, 300.0), 2)
                db_lineups[lineup_id].updated_at = datetime.utcnow()
                print(f"Simulated score update for lineup {lineup_id}: {db_lineups[lineup_id].total_score}")
                break # Just update one for testing broadcast
    
    print(f"Manually triggering leaderboard broadcast for contest {contest_id}")
    await broadcast_leaderboard_update(contest_id)
    return {"message": "Leaderboard broadcast triggered."}