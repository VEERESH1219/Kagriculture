from kaggle_environments import make
from main import agent

env = make('kaggriculture')
def debug_agent(obs):
    result = agent(obs)
    step = obs.get('step', 0)
    day = step // 24
    hour = step % 24
    player = obs['player']
    me = obs['farms'][player]
    money = me.get('money', 0)
    private = obs.get('private', {})
    seeds = private.get('seeds', {})
    hands = me.get('hands', [])
    tiles = me['tiles']
    
    plants = sum(1 for row in tiles for t in row if isinstance(t, dict) and t.get('kind') == 'PLANT')
    locked = sum(1 for row in tiles for t in row if t == 'LOCKED')
    
    if hour == 0:
        print(f'D{day:2d} H00: ${money:>5,.0f} | p={plants:2d} h={len(hands)} L={locked} | sds={seeds}')
        if result['market']:
            print(f"  mkt: {result['market']}")
    return result

env.run([debug_agent, 'random'])
print('Final:', env.steps[-1][0].reward)
