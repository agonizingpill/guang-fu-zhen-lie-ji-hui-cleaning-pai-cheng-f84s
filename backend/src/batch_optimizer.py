"""草稿任务组合优化：多班组工时背包 + 同阵列互斥。

candidates: [{'key','crew','minutes','benefit','group'}]，crew 为班组标识，group 为阵列标识。
capacities: {crew: 当日剩余分钟}（已扣除已签许可占用）。
目标：在每组至多一项、各班组总工时不超过剩余容量的约束下，最大化保守收益合计。
分支限界精确求解，不按单项损失贪心；收益相同先找到的组合优先，结果确定可复现。
"""
EPS=1e-9

def optimize(candidates,capacities,node_limit=200000):
    order=sorted(range(len(candidates)),key=lambda i:(-candidates[i]['benefit'],candidates[i]['key']))
    suffix=[0.0]*(len(order)+1)
    for k in range(len(order)-1,-1,-1):suffix[k]=suffix[k+1]+candidates[order[k]]['benefit']
    used={c:0 for c in capacities}
    groups=set();chosen=[];best=[0.0,()];state={'exhausted':True,'budget':node_limit}
    def dfs(pos,obj):
        if not state['exhausted']:return
        state['budget']-=1
        if state['budget']<0:
            state['exhausted']=False
            return
        if obj+suffix[pos]<=best[0]+EPS:return
        if pos==len(order):
            if obj>best[0]+EPS:
                best[0]=obj
                best[1]=tuple(sorted(chosen))
            return
        c=candidates[order[pos]]
        if used[c['crew']]+c['minutes']<=capacities.get(c['crew'],0) and c['group'] not in groups:
            used[c['crew']]+=c['minutes'];groups.add(c['group']);chosen.append(c['key'])
            dfs(pos+1,obj+c['benefit'])
            chosen.pop();groups.discard(c['group']);used[c['crew']]-=c['minutes']
        dfs(pos+1,obj)
    dfs(0,0.0)
    return set(best[1]),state['exhausted']
