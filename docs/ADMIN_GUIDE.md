# Admin Guide - ChainBid Operations & Monitoring

## Overview

This guide covers operational tasks for ChainBid administrators.

## Daily Operations

### System Health Check

```
curl http://localhost:5000/api/health/ready
```

Check:
- Database: healthy
- RPC: healthy
- Contract: healthy

### Monitor Logs

- transactions.log: All blockchain events
- blockchain_errors.log: All errors
- app.log: General application logs

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
