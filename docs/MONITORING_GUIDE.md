# Monitoring Guide - ChainBid

## Health Checks

### Readiness Endpoint

```bash
curl http://localhost:5000/api/health/ready
```

Returns 200 when ready, 503 when degraded.

Check all components:
- Database: Can connect and query
- RPC: Can get current block
- Contract: Can load contract

### Liveness Endpoint

```bash
curl http://localhost:5000/api/health/live
```

Returns 200 if app is running (lightweight check).

---

## Metrics Collection

### Viewing Metrics

Via API:
```bash
curl http://localhost:5000/api/health/metrics/summary | jq
```

Via Logs:
```bash
tail -f logs/transactions.log
```

### Key Metrics

**Transaction Metrics** (hourly)
- Success: Number of successful transactions
- Failure: Number of failed transactions
- Success Rate: success / (success + failure)

**RPC Metrics**
- Latency: Time to get response
- Errors: Failed RPC calls
- Availability: 99.9% target

**Blockchain Metrics**
- Confirmation Time: Time to 2 confirmations
- Gas Usage: Wei spent per transaction
- Error Rate: Failed transactions

---

## Alerting

### Alert Thresholds

**WARNING Level**
- Transaction error rate > 5%
- RPC latency > 5 seconds
- Confirmation time > 5 minutes

**CRITICAL Level**
- RPC unavailable
- Database connection failed
- Transaction error rate > 10%

### Receiving Alerts

1. **Console Logs**
```bash
grep ERROR logs/blockchain_errors.log
```

2. **Email** (configure in .env)
```
ALERT_EMAIL=admin@example.com
```

3. **Slack Integration** (optional)
```
SLACK_WEBHOOK=https://hooks.slack.com/...
```

---

## Dashboards

### Local Metrics Dashboard

Open in browser:
```
http://localhost:5000/admin/metrics
```

Shows:
- System health
- Transaction trends
- Error rates
- Performance stats

### Grafana Integration (Optional)

If using Grafana:
1. Add data source: `http://localhost:5000/api/metrics`
2. Import dashboards from `dashboards/`
3. Set alerts in Grafana

---

## Troubleshooting

### High Error Rate

1. Check error logs
```bash
tail -100 logs/blockchain_errors.log | grep ERROR
```

2. Identify error type
- RPC errors: Network issue
- Validation errors: Bad input
- Contract errors: Transaction would fail

3. Check RPC status
```bash
curl https://status.alchemy.com
```

### Database Issues

1. Check connection
```bash
sqlite3 auction.db "SELECT COUNT(*) FROM user;"
```

2. Check size
```bash
du -h auction.db
```

3. Optimize if large
```bash
sqlite3 auction.db "VACUUM; ANALYZE;"
```

### Slow Transactions

1. Check confirmation time
```bash
grep "confirmation_time" logs/transactions.log | tail -20
```

2. Check RPC latency
```bash
curl -w "@curl-format.txt" -o /dev/null -s http://localhost:5000/api/health/ready
```

3. Check gas price
```bash
curl https://etherscan.io/api?module=gastracker
```

---

## Maintenance

### Daily

- [ ] Check health endpoint
- [ ] Review error logs
- [ ] Monitor RPC status

### Weekly

- [ ] Review transaction trends
- [ ] Check database size
- [ ] Verify backup completed

### Monthly

- [ ] Analyze slow queries
- [ ] Review security logs
- [ ] Test disaster recovery

---

**Last Updated**: 2026-10-07
