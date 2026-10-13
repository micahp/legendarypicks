import { nflHomepageCampaign } from './leagueReadiness'

const row = (phase: string) => ({ phase } as any)

describe('nflHomepageCampaign', () => {
  it('retires draft copy once the regular season starts', () => {
    const campaign = nflHomepageCampaign(row('regular_season'))
    expect(campaign.title).toBe('NFL Season')
    expect(campaign.description.toLowerCase()).not.toContain('draft')
  })

  it('uses phase-specific preseason and postseason copy', () => {
    expect(nflHomepageCampaign(row('preseason')).title).toBe('NFL Preseason')
    expect(nflHomepageCampaign(row('postseason')).title).toBe('NFL Playoffs')
  })

  it('fails to evergreen NFL copy when readiness is unavailable', () => {
    const campaign = nflHomepageCampaign(null)
    expect(campaign.title).toBe('NFL')
    expect(campaign.description.toLowerCase()).not.toContain('draft')
  })
})
