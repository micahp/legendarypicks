import TopShot from 0x877931736ee77cff

access(all) contract LegendaryPicksContest {
    access(all) event ContractInitialized()
    access(all) event ContestCreated(contestId: UInt64, gameIds: [String])
    access(all) event ContestEntrySubmitted(contestId: UInt64, participant: Address, momentIds: [UInt64])
    access(all) event ContestCompleted(contestId: UInt64, winners: [Address])
    access(all) event ScoreUpdated(contestId: UInt64, participant: Address, newScore: UFix64)
    access(all) event GameStatsUpdated(gameId: String, stats: {String: UFix64})

    access(all) struct LineupRequirements {
        access(all) let requiredPositions: {String: UInt8} // e.g., {"G": 2, "F": 2, "C": 1}
        access(all) let maxPlayersPerTeam: UInt8
        access(all) let totalPlayers: UInt8

        init(
            requiredPositions: {String: UInt8},
            maxPlayersPerTeam: UInt8,
            totalPlayers: UInt8
        ) {
            self.requiredPositions = requiredPositions
            self.maxPlayersPerTeam = maxPlayersPerTeam
            self.totalPlayers = totalPlayers
        }
    }

    access(all) struct Contest {
        access(all) let contestId: UInt64
        access(all) let gameIds: [String]
        access(all) let startTime: UFix64
        access(all) let endTime: UFix64
        access(all) let entryFee: UFix64
        access(all) let prizePool: UFix64
        access(all) let maxEntries: UInt64
        access(all) let requirements: LineupRequirements
        access(all) let entries: {Address: Entry}
        access(all) var isComplete: Bool
        access(all) var winners: [Address]

        init(
            contestId: UInt64,
            gameIds: [String],
            startTime: UFix64,
            endTime: UFix64,
            entryFee: UFix64,
            maxEntries: UInt64,
            requirements: LineupRequirements
        ) {
            self.contestId = contestId
            self.gameIds = gameIds
            self.startTime = startTime
            self.endTime = endTime
            self.entryFee = entryFee
            self.maxEntries = maxEntries
            self.prizePool = 0.0
            self.requirements = requirements
            self.entries = {}
            self.isComplete = false
            self.winners = []
        }
    }

    access(all) struct Entry {
        access(all) let owner: Address
        access(all) let momentIds: [UInt64]
        access(all) var score: UFix64
        access(all) let timestamp: UFix64
        access(all) let playerScores: {UInt64: UFix64} // momentId -> score

        init(owner: Address, momentIds: [UInt64]) {
            self.owner = owner
            self.momentIds = momentIds
            self.score = 0.0
            self.timestamp = getCurrentBlock().timestamp
            self.playerScores = {}
        }

        access(all) fun updateScore(gameStats: {String: GameStats}, moments: {UInt64: TopShot.MomentData}) {
            var totalScore: UFix64 = 0.0

            for momentId in self.momentIds {
                if let moment = moments[momentId] {
                    let playerId = moment.playerId
                    var playerScore: UFix64 = 0.0

                    for gameStats in gameStats.values {
                        if let stats = gameStats.playerStats[playerId] {
                            playerScore = playerScore + stats
                        }
                    }

                    let rarityMultiplier = self.calculateRarityMultiplier(moment.serialNumber)
                    let momentScore = playerScore * rarityMultiplier
                    
                    self.playerScores[momentId] = momentScore
                    totalScore = totalScore + momentScore
                }
            }

            self.score = totalScore
        }

        access(contract) fun calculateRarityMultiplier(_ serialNumber: UInt32): UFix64 {
            if serialNumber <= 10 {
                return 2.0
            } else if serialNumber <= 100 {
                return 1.5
            } else if serialNumber <= 1000 {
                return 1.2
            }
            return 1.0
        }
    }

    access(all) struct GameStats {
        access(all) let gameId: String
        access(all) let playerStats: {String: UFix64} // playerId -> score
        access(all) let timestamp: UFix64

        init(gameId: String, playerStats: {String: UFix64}) {
            self.gameId = gameId
            self.playerStats = playerStats
            self.timestamp = getCurrentBlock().timestamp
        }
    }

    access(all) resource ContestManager {
        access(self) var contests: @{UInt64: Contest}
        access(all) var nextContestId: UInt64
        access(self) var gameStats: {String: GameStats}

        access(all) fun createContest(
            gameIds: [String],
            startTime: UFix64,
            endTime: UFix64,
            entryFee: UFix64,
            maxEntries: UInt64
        ): UInt64 {
            let contestId = self.nextContestId
            let contest = Contest(
                contestId: contestId,
                gameIds: gameIds,
                startTime: startTime,
                endTime: endTime,
                entryFee: entryFee,
                maxEntries: maxEntries
            )
            self.contests[contestId] <-! contest
            self.nextContestId = self.nextContestId + 1

            emit ContestCreated(contestId: contestId, gameIds: gameIds)
            return contestId
        }

        access(all) fun submitEntry(contestId: UInt64, momentIds: [UInt64], participant: Address) {
            pre {
                self.contests[contestId]?.isComplete == false: "Contest is already complete"
                self.contests[contestId]?.startTime <= getCurrentBlock().timestamp: "Contest hasn't started"
                self.contests[contestId]?.endTime >= getCurrentBlock().timestamp: "Contest has ended"
            }

            let collection = getAccount(participant)
                .getCapability(/public/MomentCollection)
                .borrow<&{TopShot.MomentCollectionPublic}>()
                ?? panic("Could not borrow moment collection")

            for momentId in momentIds {
                let moment = collection.borrowMoment(id: momentId)
                    ?? panic("Moment not found in collection")
            }

            self.verifyLineup(momentIds: momentIds, requirements: self.contests[contestId]?.requirements)

            let entry = Entry(owner: participant, momentIds: momentIds)
            self.contests[contestId]?.entries[participant] = entry

            emit ContestEntrySubmitted(contestId: contestId, participant: participant, momentIds: momentIds)
        }

        access(contract) fun verifyLineup(momentIds: [UInt64], requirements: LineupRequirements) {
            // Implement lineup verification logic
            // - Check total players
            // - Check position requirements
            // - Check players per team limit
        }

        access(all) fun updateGameStats(gameId: String, playerStats: {String: UFix64}) {
            let stats = GameStats(gameId: gameId, playerStats: playerStats)
            self.gameStats[gameId] = stats

            for contest in self.contests.values {
                if contest.gameIds.contains(gameId) {
                    self.updateContestScores(contestId: contest.contestId)
                }
            }

            emit GameStatsUpdated(gameId: gameId, stats: playerStats)
        }

        access(all) fun updateContestScores(contestId: UInt64) {
            if let contest = &self.contests[contestId] as &Contest {
                let relevantStats: {String: GameStats} = {}
                for gameId in contest.gameIds {
                    if let stats = self.gameStats[gameId] {
                        relevantStats[gameId] = stats
                    }
                }

                for entry in contest.entries.values {
                    let oldScore = entry.score
                    entry.updateScore(gameStats: relevantStats, moments: self.getMomentsData(momentIds: entry.momentIds))
                    
                    if oldScore != entry.score {
                        emit ScoreUpdated(
                            contestId: contestId,
                            participant: entry.owner,
                            newScore: entry.score
                        )
                    }
                }

                self.updateContestRankings(contestId: contestId)
            }
        }

        access(all) fun getMomentsData(momentIds: [UInt64]): {UInt64: TopShot.MomentData} {
            let moments: {UInt64: TopShot.MomentData} = {}
            
            for momentId in momentIds {
                if let moment = TopShot.borrowMoment(id: momentId) {
                    moments[momentId] = moment.data
                }
            }
            
            return moments
        }

        access(all) fun updateContestRankings(contestId: UInt64) {
            if let contest = &self.contests[contestId] as &Contest {
                let sortedEntries = contest.entries.values.sort(by: fun (a: Entry, b: Entry): Bool {
                    return a.score > b.score
                })

                contest.winners = []
                var rank = 0
                for entry in sortedEntries {
                    if rank < 3 {
                        contest.winners.append(entry.owner)
                    }
                    rank = rank + 1
                }
            }
        }

        init() {
            self.contests <- {}
            self.nextContestId = 1
            self.gameStats = {}
        }
    }

    init() {
        self.account.save(<-create ContestManager(), to: /storage/LegendaryPicksContestManager)
    }
} 