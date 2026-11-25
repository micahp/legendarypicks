#!/bin/bash
for pid in $(pgrep -f "batch20.sh"); do kill $pid; done
for pid in $(pgrep -f "run_arm.py --out out/batch"); do kill $pid; done
sleep 3
echo "remaining: $(pgrep -fc 'run_arm.py --out out/batch')"
mv /root/v2-ablation/out/batch /root/v2-ablation/out/batch-invalid-state-leak-$(date -u +%H%M)
echo "STOPPED $(date -u +%FT%T): cached pack leaked state between games (IND_HOU 0/20 vs frozen)" >> /root/v2-ablation/out/batch.status
