# Admin Guide - MintLot Operations & Monitoring

## Overview

This guide covers operational tasks for MintLot administrators.

## Daily Operations

### System Health Check

```
curl http://localhost:5000/readyz
```

It answers `{"status": "ok", "checks": {"database": "ok"}}` (and `"redis"` when `REDIS_URL` is set), or HTTP 503 with
the failing check named. `/healthz` only says the process is up. The blockchain connection is not part of the check:
a slow RPC provider must not take the whole site out of service. See [DEPLOYMENT.md](DEPLOYMENT.md).

### Monitor Logs

The app writes its log to standard output, so read it where it runs: the terminal for `python run.py`,
`docker compose logs -f web worker` for the Docker stack, or the hosting platform's log view. Each request is one
line ending in its request id, which a user can find in the `X-Request-ID` response header if something went wrong.

### Responding to Alerts

**Error Rate > 5%**: Check logs for patterns
**RPC Unavailable**: Check Alchemy status, switch failover
**Database Issue**: Check disk space, run ANALYZE

## Key Metrics

**Transaction Metrics**
- Success rate: > 95%
- Confirmation time: < 5 minutes
- Failed transactions: < 5%

**RPC Metrics**
- Latency: < 1000ms
- Error rate: < 1%
- Availability: > 99.9%

**Application Metrics**
- Response time: < 500ms
- Error rate: < 1%

## Managing Auctions

### Approving Cards

1. Admin → Card Management
2. Review pending cards
3. Approve or reject with feedback

### Handling Disputes

- Check blockchain history (immutable truth)
- Transaction hash is proof
- Follow dispute resolution policy

## Maintenance

### Database Backup

Daily automated at 2 AM. Manual backup:
```bash
mysqldump -u root -p auction_db > backup_$(date +%Y%m%d).sql
```

### Log Rotation

Auto-rotates at size limits:
- transactions.log: 10 MB
- blockchain_errors.log: 10 MB
- app.log: 20 MB

### Monthly Optimization

```sql
ANALYZE TABLE User, Product, Auction;
OPTIMIZE TABLE Payment, Transaction;
```

## Incident Response

### High Error Rate

1. Check error logs
2. Alert team
3. Investigate root cause
4. Mitigate (scale, switch RPC, etc.)
5. Monitor recovery

### Database Recovery

```bash
mysql -u root -p auction_db < backup_20261007.sql
```

### Code Rollback

```bash
git log --oneline
git revert <commit-hash>
git push
```

---

**Last Updated**: 2026-10-07
